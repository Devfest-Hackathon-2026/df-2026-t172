"""Firestore の保存先（MODE=live 用）。

データベースは `(default)`、場所は `asia-northeast1`。認証は Cloud Run の
サービスアカウント（鍵ファイルは使わない）。records と tasks は `expires_at` を
TTL の対象にして、作った日の翌日0時以降に自動で消す。
"""

from datetime import datetime
from typing import Any

from app.models.api import Patient
from app.store.base import Document, is_rule_task_to_move

PATIENTS, RECORDS, TASKS = "patients", "records", "tasks"


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
            fields = p.model_dump(exclude={"id"})
            kept = saved.get(p.id, {})
            if kept.get("assigned_to") is not None:
                fields["assigned_to"] = kept["assigned_to"]
                fields["assigned_reported_by"] = kept.get("assigned_reported_by")
            batch.set(self._db.collection(PATIENTS).document(p.id), fields)
        batch.commit()

    def list_patients(self) -> list[Patient]:
        """名簿の全員（部屋番号の順）。"""
        patients = [
            Patient(id=doc.id, **doc.to_dict()) for doc in self._db.collection(PATIENTS).stream()
        ]
        return sorted(patients, key=lambda p: (p.room, p.bed))

    def get_patient(self, patient_id: str) -> Patient | None:
        """名簿の1人。いなければ None。"""
        doc = self._db.collection(PATIENTS).document(patient_id).get()
        return Patient(id=doc.id, **doc.to_dict()) if doc.exists else None

    def save_record(self, record_id: str, record: Document, tasks: list[Document]) -> None:
        """記録とタスクを1回の書き込み（batch）で保存する（同じ記録の前のタスクは消す）。"""
        old_tasks = self._db.collection(TASKS).where("record_id", "==", record_id).stream()
        batch = self._db.batch()
        for doc in old_tasks:
            batch.delete(doc.reference)
        batch.set(self._db.collection(RECORDS).document(record_id), record)
        for task in tasks:
            fields = {k: v for k, v in task.items() if k != "id"}
            batch.set(self._db.collection(TASKS).document(task["id"]), fields)
        batch.commit()

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
        return Patient(id=patient_id, **{**doc.to_dict(), **change})

    def move_rule_tasks(self, patient_id: str, nurse_id: str, now: datetime) -> list[str]:
        """受け持ちから写しただけの未完了のタスクを移す（1人分の1日の依頼なので数件）。"""
        docs = self._db.collection(TASKS).where("patient_id", "==", patient_id).stream()
        moved = [doc.id for doc in docs if is_rule_task_to_move(doc.to_dict(), now)]
        for task_id in moved:
            self._db.collection(TASKS).document(task_id).update({"assigned_to": nurse_id})
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
        """タスクを書き換える。"""
        ref = self._db.collection(TASKS).document(task_id)
        doc = ref.get()
        if not doc.exists or doc.to_dict()["expires_at"] <= now:
            return None
        ref.update(fields)
        return {"id": task_id, **doc.to_dict(), **fields}
