"""Firestore の保存先（MODE=live 用）。

データベースは `(default)`、場所は `asia-northeast1`。認証は Cloud Run の
サービスアカウント（鍵ファイルは使わない）。records と tasks は `expires_at` を
TTL の対象にして、作った日の翌日0時以降に自動で消す。
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.models.api import Patient
from app.store.base import (
    Document,
    RecordUpdate,
    ensure_linked_task,
    is_rule_task_to_move,
    request_fields_from_task,
    updated_linked_requests,
)

PATIENTS, RECORDS, TASKS = "patients", "records", "tasks"
# 看護計画は起動時の名簿からだけ使う。Firestore には書かず、読んでも使わない
# （care-plan-soap の要件2の9。保存先に病状の情報を増やさない）
_ROSTER_ONLY_FIELDS = {"care_plans"}


def _stored_patient(patient_id: str, fields: dict[str, Any]) -> Patient:
    """Firestore の名簿の1人。看護計画の欄が入っていても捨てる（型の条件もかけない）。"""
    kept = {k: v for k, v in fields.items() if k not in _ROSTER_ONLY_FIELDS}
    return Patient(id=patient_id, **kept)


class FirestoreStore:
    """Firestore への読み書き。client はテストで差し替えられる。"""

    def __init__(self, client: Any):
        """`google.cloud.firestore.Client` か、同じ形の差し替えで作る。"""
        self._db = client

    @classmethod
    def connect(cls, project: str, database: str) -> "FirestoreStore":
        """本物の Firestore につなぐ（呼んだ時点では通信しない）。"""
        from google.cloud import firestore

        return cls(firestore.Client(project=project, database=database))

    def seed_patients(self, patients: list[Patient]) -> None:
        """起動時に、架空の名簿を入れる（同じ id は上書き）。

        受け持ち（assigned_to）と、変えた人の自己申告だけは、画面で変えた値が入って
        いればそれを残す（起動のたびに seed の受け持ちに戻さないため、S-08）。
        """
        saved = {doc.id: doc.to_dict() for doc in self._db.collection(PATIENTS).stream()}
        batch = self._db.batch()
        for p in patients:
            fields = p.model_dump(exclude={"id", *_ROSTER_ONLY_FIELDS})
            kept = saved.get(p.id, {})
            if kept.get("assigned_to") is not None:
                fields["assigned_to"] = kept["assigned_to"]
                fields["assigned_reported_by"] = kept.get("assigned_reported_by")
            batch.set(self._db.collection(PATIENTS).document(p.id), fields)
        batch.commit()

    def list_patients(self) -> list[Patient]:
        """名簿の全員（部屋番号の順）。"""
        patients = [
            _stored_patient(doc.id, doc.to_dict()) for doc in self._db.collection(PATIENTS).stream()
        ]
        return sorted(patients, key=lambda p: (p.room, p.bed))

    def get_patient(self, patient_id: str) -> Patient | None:
        """名簿の1人。いなければ None。"""
        doc = self._db.collection(PATIENTS).document(patient_id).get()
        return _stored_patient(doc.id, doc.to_dict()) if doc.exists else None

    def save_record(
        self, record_id: str, record: Document, tasks: list[Document]
    ) -> Document | None:
        """確定を一括保存する。修正済みかどうかも同じトランザクションで確認する。"""
        from google.cloud.firestore import transactional

        return transactional(self._save_record)(self._db.transaction(), record_id, record, tasks)

    def _save_record(
        self, transaction: Any, record_id: str, record: Document, tasks: list[Document]
    ) -> Document | None:
        ref = self._db.collection(RECORDS).document(record_id)
        snapshot = ref.get(transaction=transaction)
        task_collection = self._db.collection(TASKS)
        if snapshot.exists:
            current = snapshot.to_dict()
            if current.get("revision", 0) > 0:
                return {"id": record_id, **current}
            old_tasks = task_collection.where("record_id", "==", record_id).stream(
                transaction=transaction
            )
            new_ids = {task["id"] for task in tasks}
            removed = [doc.id for doc in old_tasks if doc.id not in new_ids]
            for task_id in removed:
                transaction.delete(task_collection.document(task_id))
        transaction.set(ref, record)
        for task in tasks:
            fields = {k: v for k, v in task.items() if k != "id"}
            transaction.set(task_collection.document(task["id"]), fields)
        return None

    def amend_record(
        self, record_id: str, prepare: Callable[[Document], RecordUpdate]
    ) -> Document | None:
        """記録とタスクを同じトランザクションで読み書きする。"""
        from google.cloud.firestore import transactional

        return transactional(self._amend_record)(self._db.transaction(), record_id, prepare)

    def _amend_record(
        self, transaction: Any, record_id: str, prepare: Callable[[Document], RecordUpdate]
    ) -> Document | None:
        ref = self._db.collection(RECORDS).document(record_id)
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            return None
        record = {"id": record_id, **snapshot.to_dict()}
        update = prepare(record)
        tasks = self._db.collection(TASKS)
        for task_id in sorted(update.linked_task_ids):
            doc = tasks.document(task_id).get(transaction=transaction)
            ensure_linked_task(record, doc.to_dict() if doc.exists else None, update.now)
        if update.new_tasks:
            patient_ref = self._db.collection(PATIENTS).document(record["patient_id"])
            patient = patient_ref.get(transaction=transaction)
            if patient.exists:
                assignee = patient.to_dict().get("assigned_to")
                for task in update.new_tasks:
                    task["assigned_to"] = assignee
        if update.fields:
            transaction.update(ref, update.fields)
        for task_id, fields in update.task_changes.items():
            task_ref = tasks.document(task_id)
            if fields is None:
                transaction.delete(task_ref)
            else:
                transaction.update(task_ref, fields)
        for task in update.new_tasks:
            fields = {k: v for k, v in task.items() if k != "id"}
            transaction.create(tasks.document(task["id"]), fields)
        return {**record, **update.fields}

    def list_records(self, patient_id: str | None, now: datetime) -> list[Document]:
        """記録の一覧（期限切れは除く）。

        複合インデックスを作らずに済むよう、条件は patient_id だけにし、期限は
        コードで扱う（TTL で翌日0時に消えるので、残るのはほぼ当日分）。
        """
        query = self._db.collection(RECORDS)
        if patient_id is not None:
            query = query.where("patient_id", "==", patient_id)
        records = [{"id": doc.id, **doc.to_dict()} for doc in query.stream()]
        return [r for r in records if r["expires_at"] > now]

    def get_record(self, record_id: str, now: datetime) -> Document | None:
        """記録の1件（期限切れなら None）。"""
        doc = self._db.collection(RECORDS).document(record_id).get()
        if not doc.exists or doc.to_dict()["expires_at"] <= now:
            return None
        return {"id": record_id, **doc.to_dict()}

    def set_patient_assignee(
        self, patient_id: str, nurse_id: str, reported_by: str | None
    ) -> Patient | None:
        """患者の受け持ちを変える。"""
        ref = self._db.collection(PATIENTS).document(patient_id)
        doc = ref.get()
        if not doc.exists:
            return None
        change = {"assigned_to": nurse_id, "assigned_reported_by": reported_by}
        ref.update(change)
        return _stored_patient(patient_id, {**doc.to_dict(), **change})

    def move_rule_tasks(self, patient_id: str, nurse_id: str, now: datetime) -> list[str]:
        """受け持ちから写しただけの未完了のタスクを移す（1人分の1日の依頼なので数件）。"""
        from google.cloud.firestore import transactional

        return transactional(self._move_rule_tasks)(
            self._db.transaction(), patient_id, nurse_id, now
        )

    def _move_rule_tasks(
        self, transaction: Any, patient_id: str, nurse_id: str, now: datetime
    ) -> list[str]:
        tasks = self._db.collection(TASKS)
        docs = tasks.where("patient_id", "==", patient_id).stream(transaction=transaction)
        moved = [doc.id for doc in docs if is_rule_task_to_move(doc.to_dict(), now)]
        for task_id in moved:
            transaction.update(tasks.document(task_id), {"assigned_to": nurse_id})
        return moved

    def add_task(self, task: Document) -> None:
        """タスクを1件保存する（id は文書の id にし、中身には入れない）。"""
        fields = {k: v for k, v in task.items() if k != "id"}
        self._db.collection(TASKS).document(task["id"]).set(fields)

    def list_tasks(self, status: str | None, now: datetime) -> list[Document]:
        """タスクの一覧（期限切れは除く）。

        複合インデックスを作らずに済むよう、条件は status だけにし、期限と並びは
        コードで扱う（件数は1日分の依頼なので少ない）。
        """
        query = self._db.collection(TASKS)
        if status is not None:
            query = query.where("status", "==", status)
        tasks = [{"id": doc.id, **doc.to_dict()} for doc in query.stream()]
        return [t for t in tasks if t["expires_at"] > now]

    def update_task(self, task_id: str, fields: Document, now: datetime) -> Document | None:
        """タスクを更新する。共通項目の変更は記録と同じトランザクションに入れる。"""
        from google.cloud.firestore import transactional

        return transactional(self._update_task)(self._db.transaction(), task_id, fields, now)

    def _update_task(
        self, transaction: Any, task_id: str, fields: Document, now: datetime
    ) -> Document | None:
        ref = self._db.collection(TASKS).document(task_id)
        doc = ref.get(transaction=transaction)
        task = doc.to_dict() if doc.exists else None
        if task is None or task["expires_at"] <= now:
            return None

        changes = request_fields_from_task(fields)
        record_id = task.get("record_id")
        if changes and record_id:
            record_ref = self._db.collection(RECORDS).document(record_id)
            record_doc = record_ref.get(transaction=transaction)
            if record_doc.exists:
                record = record_doc.to_dict()
                requests = updated_linked_requests(record, task_id, changes, now)
                if requests is not None:
                    transaction.update(
                        record_ref,
                        {"requests": requests, "revision": record.get("revision", 0) + 1},
                    )
        transaction.update(ref, fields)
        return {"id": task_id, **task, **fields}
