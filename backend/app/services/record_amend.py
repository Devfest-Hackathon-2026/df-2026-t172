"""保存済みの記録を手動で訂正し、同じ依頼から作ったタスクの変更を組み立てる。"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from app.errors import ApiError
from app.models.api import Patient
from app.models.draft import Draft
from app.models.record_amend import RecordAmend, RequestEdit, SentenceEdit, TextEdit, VitalEdit
from app.models.task_create import TaskCreate
from app.services.care_plan import ensure_known_care_plans
from app.services.manual_task import manual_task_document
from app.services.record_documents import evidence_ids
from app.store.base import Document, RecordUpdate

# Firestore の文書上限 1 MiB に対し、文書のキーや型などの分を見込む。
MAX_RECORD_BYTES = 900 * 1024


@dataclass
class _Metadata:
    original: Document
    paths: set[str] = field(default_factory=set)
    unchanged: dict[str, str] = field(default_factory=dict)

    def keep(self, old: str, new: str) -> None:
        self.unchanged[old] = new

    def apply(self, changed_lists: set[str]) -> Document:
        def retained_path(path: str) -> str | None:
            parent = path.split("[", 1)[0]
            return self.unchanged.get(path) if parent in changed_lists else path

        for original in self.original.get("amended_paths", []):
            if (new := retained_path(original)) is not None:
                self.paths.add(new)
        return {
            "amended_paths": sorted(self.paths),
            "kept_after_check": [
                {**check, "path": new}
                for check in self.original.get("kept_after_check", [])
                if (new := retained_path(check["path"])) is not None
            ],
        }


def _edit_rows(
    original: list[Document],
    rows: list[SentenceEdit] | list[TextEdit] | list[VitalEdit],
    group: str,
    meta: _Metadata,
) -> list[Document]:
    result: list[Document] = []
    used: set[int] = set()
    for pos, row in enumerate(rows):
        index = row.index
        if index is not None and (index in used or index >= len(original)):
            raise ApiError(422, "invalid_record_row", "記録の項目を特定できません")
        old = original[index] if index is not None else {}
        if index is not None:
            used.add(index)
        path = f"{group}[{pos}]"
        values = row.model_dump(exclude={"index"})
        content_keys = ("item", "value") if isinstance(row, VitalEdit) else ("text",)
        if old and all(old[key] == values[key] for key in content_keys):
            meta.keep(f"{group}[{index}]", path)
            result.append({**old, **values})
        else:
            value = values["value"] if isinstance(row, VitalEdit) else values["text"]
            if not value.strip():
                raise ApiError(
                    422, "empty_record_row", "空の項目に入力するか、その項目を削除してください"
                )
            origin = {"source": "manual"} if isinstance(row, VitalEdit) else {"added_by": "nurse"}
            result.append({**values, **origin, "evidence": []})
            meta.paths.add(path)
    return result


def _edit_requests(
    record: Document,
    rows: list[RequestEdit],
    patient: Patient,
    update: RecordUpdate,
    meta: _Metadata,
) -> list[Document]:
    original = record["requests"]
    by_id = {row.get("task_id"): (index, row) for index, row in enumerate(original)}
    if None in by_id or len(by_id) != len(original):
        raise ApiError(
            422, "unlinked_requests", "タスクとの対応がない旧記録では、依頼欄は変更できません"
        )
    update.linked_task_ids = set(by_id)
    remaining = set(by_id)
    result = []
    for pos, row in enumerate(rows):
        task_id = row.task_id
        values = row.model_dump(exclude={"task_id"})
        path = f"requests[{pos}]"
        if task_id is None:
            if not row.text.strip():
                raise ApiError(
                    422, "empty_record_row", "依頼内容を入力するか、その項目を削除してください"
                )
            new_task = manual_task_document(
                patient, TaskCreate(patient_id=patient.id, **values), update.now
            )
            new_task.update(
                id=f"t_edit_{uuid4().hex}",
                record_id=record["id"],
                text=row.text,
                expires_at=record["expires_at"],
            )
            update.new_tasks.append(new_task)
            result.append(
                {
                    **values,
                    "task_id": new_task["id"],
                    "evidence": [],
                    "cue": None,
                    "added_by": "nurse",
                }
            )
            meta.paths.add(path)
            continue
        if task_id not in remaining:
            raise ApiError(422, "invalid_record_task", "この記録に対応するタスクを特定できません")
        remaining.remove(task_id)
        index, old = by_id[task_id]
        changed = {key: value for key, value in values.items() if old.get(key, "その他") != value}
        task_fields = dict(changed)
        for key in ("urgency", "category", "role"):
            if key in changed:
                task_fields[f"{key}_set_by"] = "nurse"
        if "text" in changed:
            if not row.text.strip():
                raise ApiError(
                    422, "empty_record_row", "依頼内容を入力するか、その項目を削除してください"
                )
            changed.update(evidence=[], cue=None, added_by="nurse")
            task_fields.update(patient_words=[], cue=None, urgency_set_by="nurse")
            meta.paths.add(path)
        else:
            meta.keep(f"requests[{index}]", path)
            meta.keep(f"requests[{index}].cue", f"{path}.cue")
        if task_fields:
            update.task_changes[task_id] = task_fields
        result.append({**old, **changed})
    for task_id in remaining:
        update.task_changes[task_id] = None
    return result


def prepare_amendment(
    record: Document, body: RecordAmend, patient: Patient, now: datetime
) -> RecordUpdate:
    """変更を検証して、記録とタスクを一緒に書き込むための差分を返す。"""
    if record["expires_at"] <= now:
        raise ApiError(
            404, "record_not_found", "記録が見つかりません（期限切れで消えた可能性があります）"
        )
    if body.revision != record.get("revision", 0):
        raise ApiError(
            409, "record_changed", "別の変更が保存されています。最新の記録を開き直してください"
        )

    update = RecordUpdate(now)
    changes = body.changes
    meta = _Metadata(record)
    changed_lists: set[str] = set()
    soap = dict(record["soap"])
    plans_to_check: Document = {}
    if changes.soap is not None:
        for part in ("S", "O"):
            rows = getattr(changes.soap, part)
            if rows is None:
                continue
            group = f"soap.{part}"
            changed_lists.add(group)
            soap[part] = _edit_rows(record["soap"][part], rows, group, meta)
            # 名簿が変わる前から付いていた計画はそのまま読める。新しく指定した計画だけを確かめる。
            plans_to_check[part] = [
                row
                if incoming.index is None
                or row.get("plan_id") != record["soap"][part][incoming.index].get("plan_id")
                else {**row, "plan_id": None}
                for incoming, row in zip(rows, soap[part], strict=True)
            ]
        for part in ("A", "P"):
            value = getattr(changes.soap, part)
            if value is not None and value != soap[part]:
                soap[part] = value
                meta.paths.add(f"soap.{part}")
    ensure_known_care_plans(Draft.model_validate({"soap": plans_to_check}), patient.care_plans)

    candidates = {"soap": soap}
    for group in ("vitals", "manual_needed", "doctor_questions"):
        rows = getattr(changes, group)
        if rows is not None:
            changed_lists.add(group)
            candidates[group] = _edit_rows(record[group], rows, group, meta)
    if changes.requests is not None:
        changed_lists.add("requests")
        candidates["requests"] = _edit_requests(record, changes.requests, patient, update, meta)
    update.fields = {key: value for key, value in candidates.items() if value != record[key]}
    if not update.fields:
        return update

    draft = Draft.model_validate({**record, **update.fields})
    used = evidence_ids(draft)
    update.fields.update(
        meta.apply(changed_lists),
        evidence_utterances=[u for u in record["evidence_utterances"] if u["id"] in used],
        revision=body.revision + 1,
    )
    encoded = json.dumps(
        {**record, **update.fields}, ensure_ascii=False, default=str, separators=(",", ":")
    )
    if len(encoded.encode()) > MAX_RECORD_BYTES:
        raise ApiError(422, "record_too_large", "記録が長すぎます。入力内容を短くしてください")
    return update
