"""保存先の形。モックはメモリ、本番は Firestore（docs/design/data-model.md の 4章）。

記録とタスクは Firestore の1件と同じ dict で受け渡す。日時は datetime のまま渡し、
API で返すときに文字列にする。**会話の文（発言の列）と音声は渡さない。**
"""

from datetime import datetime
from typing import Any, Protocol

from app.models.api import Patient

Document = dict[str, Any]


def is_rule_task_to_move(task: Document, now: datetime) -> bool:
    """受け持ちが替わったときに一緒に移すタスクか（未完了・期限内・担当を人が変えていない）。

    前からあるタスクには assigned_set_by がないので、rule とみなす。
    """
    return (
        task["status"] == "open"
        and task["expires_at"] > now
        and task.get("assigned_set_by", "rule") == "rule"
    )


class Store(Protocol):
    """名簿・記録・タスクの読み書き。"""

    def list_patients(self) -> list[Patient]:
        """名簿の全員（部屋番号の順）。"""
        ...

    def get_patient(self, patient_id: str) -> Patient | None:
        """名簿の1人。いなければ None。"""
        ...

    def save_record(self, record_id: str, record: Document, tasks: list[Document]) -> None:
        """確定した記録と、その依頼から作ったタスクをまとめて保存する。

        同じ record_id がすでにあれば上書きし、その記録から作った前のタスクは消す
        （二重の確定でタスクが重ならないように）。
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
        """タスクを書き換えて、書き換えた後の1件を返す。ない・期限切れなら None。"""
        ...
