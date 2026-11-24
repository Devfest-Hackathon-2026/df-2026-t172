"""保存先の形。モックはメモリ、本番は Firestore（docs/design/data-model.md の 4章）。

記録とタスクは Firestore の1件と同じ dict で受け渡す。日時は datetime のまま渡し、
API で返すときに文字列にする。**会話の文（発言の列）と音声は渡さない。**
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.errors import ApiError
from app.models.api import Patient

Document = dict[str, Any]


@dataclass
class RecordUpdate:
    """保存済み記録への変更と、同時に適用するタスクの変更。"""

    now: datetime
    fields: Document = field(default_factory=dict)
    linked_task_ids: set[str] = field(default_factory=set)
    task_changes: dict[str, Document | None] = field(default_factory=dict)
    new_tasks: list[Document] = field(default_factory=list)


def ensure_linked_task(record: Document, task: Document | None, now: datetime) -> None:
    """タスクが同じ記録と患者に属し、期限内であることを確かめる。"""
    if (
        task is None
        or task.get("record_id") != record["id"]
        or task["patient_id"] != record["patient_id"]
        or task["expires_at"] <= now
    ):
        raise ApiError(
            422, "unlinked_requests", "対応するタスクが見つからないため、依頼欄は変更できません"
        )


def is_rule_task_to_move(task: Document, now: datetime) -> bool:
    """受け持ちが替わったときに一緒に移すタスクか（未完了・期限内・担当を人が変えていない）。

    前からあるタスクには assigned_set_by がないので、rule とみなす。
    """
    return (
        task["status"] == "open"
        and task["expires_at"] > now
        and task.get("assigned_set_by", "rule") == "rule"
    )


def request_fields_from_task(fields: Document) -> Document:
    """タスクから記録の依頼に反映する共通項目だけを選ぶ。"""
    return {key: fields[key] for key in ("urgency", "category", "role") if key in fields}


def updated_linked_requests(
    record: Document, task_id: str, changes: Document, now: datetime
) -> list[Document] | None:
    """期限内の記録で、明示的にひも付く依頼が1件なら変更後の一覧を返す。"""
    if record["expires_at"] <= now:
        return None
    requests: list[Document] = record.get("requests", [])
    matches = [i for i, request in enumerate(requests) if request.get("task_id") == task_id]
    if len(matches) != 1:
        return None
    index = matches[0]
    original = requests[index]
    if all(original.get(key) == value for key, value in changes.items()):
        return None
    return [*requests[:index], {**original, **changes}, *requests[index + 1 :]]


class Store(Protocol):
    """名簿・記録・タスクの読み書き。"""

    def list_patients(self) -> list[Patient]:
        """名簿の全員（部屋番号の順）。"""
        ...

    def get_patient(self, patient_id: str) -> Patient | None:
        """名簿の1人。いなければ None。"""
        ...

    def save_record(
        self, record_id: str, record: Document, tasks: list[Document]
    ) -> Document | None:
        """確定した記録と、その依頼から作ったタスクをまとめて保存する。

        同じ record_id がすでにあれば上書きし、その記録から作った前のタスクは消す
        （二重の確定でタスクが重ならないように）。修正済みなら上書きせず、現在の記録を返す。
        """
        ...

    def amend_record(
        self, record_id: str, prepare: Callable[[Document], RecordUpdate]
    ) -> Document | None:
        """現在の記録を基に検証し、同じ処理で記録とタスクを更新する。

        存在しなければ None。検証に失敗したときは何も書き込まない。
        """
        ...

    def list_records(self, patient_id: str | None, now: datetime) -> list[Document]:
        """確定した記録の一覧（各件に "id" を入れる）。patient_id が None なら全員。

        期限切れ（expires_at <= now）は除く（TTL の削除は最大で1日ほど遅れるため）。
        並びと件数の上限は呼び出し側で扱う。
        """
        ...

    def get_record(self, record_id: str, now: datetime) -> Document | None:
        """確定した記録の1件（"id" を入れる）。ない・期限切れなら None。"""
        ...

    def set_patient_assignee(
        self, patient_id: str, nurse_id: str, reported_by: str | None
    ) -> Patient | None:
        """患者の基本の受け持ちを変えて、変えた後の1人を返す。いなければ None（S-08）。

        reported_by は変えたと申告した看護師（自己申告）。
        """
        ...

    def move_rule_tasks(self, patient_id: str, nurse_id: str, now: datetime) -> list[str]:
        """その患者の未完了のタスクのうち、担当を人が変えていない（rule）ものを移す。

        受け持ちが替わったら、受け持ちから写しただけの担当も一緒に替える（S-08）。
        看護師が回した・引き取ったタスク（nurse）は動かさない。移したタスクの id を返す。
        """
        ...

    def add_task(self, task: Document) -> None:
        """記録なしで作ったタスクを1件保存する（看護師が直接作ったもの、A-12）。"""
        ...

    def list_tasks(self, status: str | None, now: datetime) -> list[Document]:
        """タスクの一覧。status が None なら全部。期限切れ（expires_at <= now）は除く。

        Firestore の TTL は期限から削除まで最大で1日ほど遅れるので、読むときにも除く。
        """
        ...

    def update_task(self, task_id: str, fields: Document, now: datetime) -> Document | None:
        """タスクと、ひも付いた依頼の共通項目をまとめて更新する。

        更新後のタスクを返す。タスクがない場合や期限切れの場合は None。
        """
        ...
