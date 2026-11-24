"""メモリに置く保存先（MODE=mock 用。再起動で消える）。"""

from collections.abc import Callable
from datetime import datetime
from threading import Lock

from app.models.api import Patient
from app.store.base import (
    Document,
    RecordUpdate,
    ensure_linked_task,
    is_rule_task_to_move,
    request_fields_from_task,
    updated_linked_requests,
)


class MemoryStore:
    """名簿・記録・タスクをこのプロセスのメモリにだけ置く（ほかのインスタンスとは共有しない）。"""

    def __init__(self, patients: list[Patient], tasks: list[Document] | None = None):
        """名簿と、最初から入れておくタスク（モックの見本）で作る。"""
        self._patients = {p.id: p for p in patients}
        self._records: dict[str, Document] = {}
        self._tasks: dict[str, Document] = {t["id"]: t for t in tasks or []}
        self._record_task_lock = Lock()

    def list_patients(self) -> list[Patient]:
        """名簿の全員（部屋番号の順）。"""
        return sorted(self._patients.values(), key=lambda p: (p.room, p.bed))

    def get_patient(self, patient_id: str) -> Patient | None:
        """名簿の1人。いなければ None。"""
        return self._patients.get(patient_id)

    def save_record(
        self, record_id: str, record: Document, tasks: list[Document]
    ) -> Document | None:
        """確定した記録とタスクを保存する。修正済みなら現在の記録を返す。"""
        with self._record_task_lock:
            current = self._records.get(record_id)
            if current and current.get("revision", 0) > 0:
                return {"id": record_id, **current}
            self._records[record_id] = record
            self._tasks = {k: t for k, t in self._tasks.items() if t.get("record_id") != record_id}
            self._tasks.update({t["id"]: t for t in tasks})
            return None

    def amend_record(
        self, record_id: str, prepare: Callable[[Document], RecordUpdate]
    ) -> Document | None:
        """記録を読み、検証と記録・タスクの変更を同じロック内で行う。"""
        with self._record_task_lock:
            saved = self._records.get(record_id)
            if saved is None:
                return None
            record = {"id": record_id, **saved}
            update = prepare(record)
            for task_id in update.linked_task_ids:
                ensure_linked_task(record, self._tasks.get(task_id), update.now)
            patient = self._patients.get(record["patient_id"])
            for task_id, changes in update.task_changes.items():
                if changes is None:
                    del self._tasks[task_id]
                else:
                    self._tasks[task_id].update(changes)
            for task in update.new_tasks:
                if patient is not None:
                    task["assigned_to"] = patient.assigned_to
                self._tasks[task["id"]] = task
            saved.update(update.fields)
            return {**record, **update.fields}

    def list_records(self, patient_id: str | None, now: datetime) -> list[Document]:
        """記録の一覧（期限切れは除く）。"""
        with self._record_task_lock:
            return [
                {"id": record_id, **r}
                for record_id, r in self._records.items()
                if r["expires_at"] > now and (patient_id is None or r["patient_id"] == patient_id)
            ]

    def get_record(self, record_id: str, now: datetime) -> Document | None:
        """記録の1件（期限切れなら None）。"""
        with self._record_task_lock:
            record = self._records.get(record_id)
            if record is None or record["expires_at"] <= now:
                return None
            return {"id": record_id, **record}

    def set_patient_assignee(
        self, patient_id: str, nurse_id: str, reported_by: str | None
    ) -> Patient | None:
        """患者の受け持ちを変える。"""
        patient = self._patients.get(patient_id)
        if patient is None:
            return None
        change = {"assigned_to": nurse_id, "assigned_reported_by": reported_by}
        self._patients[patient_id] = patient.model_copy(update=change)
        return self._patients[patient_id]

    def move_rule_tasks(self, patient_id: str, nurse_id: str, now: datetime) -> list[str]:
        """受け持ちから写しただけの未完了のタスクを、新しい受け持ちに移す。"""
        with self._record_task_lock:
            moved = [
                t
                for t in self._tasks.values()
                if t["patient_id"] == patient_id and is_rule_task_to_move(t, now)
            ]
            for task in moved:
                task["assigned_to"] = nurse_id
            return [t["id"] for t in moved]

    def add_task(self, task: Document) -> None:
        """タスクを1件保存する。"""
        with self._record_task_lock:
            self._tasks[task["id"]] = task

    def list_tasks(self, status: str | None, now: datetime) -> list[Document]:
        """タスクの一覧（期限切れは除く）。"""
        with self._record_task_lock:
            return [
                dict(t)
                for t in self._tasks.values()
                if t["expires_at"] > now and (status is None or t["status"] == status)
            ]

    def update_task(self, task_id: str, fields: Document, now: datetime) -> Document | None:
        """タスクと、ひも付いた依頼の共通項目をまとめて更新する。"""
        with self._record_task_lock:
            task = self._tasks.get(task_id)
            if task is None or task["expires_at"] <= now:
                return None

            changes = request_fields_from_task(fields)
            record_id = task.get("record_id")
            record = self._records.get(record_id) if record_id and changes else None
            if record is not None:
                requests = updated_linked_requests(record, task_id, changes, now)
                if requests is not None:
                    record["requests"] = requests
                    record["revision"] = record.get("revision", 0) + 1
            task.update(fields)
            return dict(task)
