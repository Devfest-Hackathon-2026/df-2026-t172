"""ルートが共通で使う取り出し口。"""

from fastapi import Request

from app.config import Settings
from app.container import Services
from app.errors import ApiError
from app.models.api import Patient


def services(request: Request) -> Services:
    """アプリに組み込んだ部品一式。"""
    return request.app.state.services


def settings(request: Request) -> Settings:
    """アプリの設定。"""
    return request.app.state.settings


def client_key(request: Request) -> str:
    """1日の上限を数える接続元（IP）。

    Cloud Run では `X-Forwarded-For` の先頭が接続元。先頭は送る側が書き換えられるが、
    全体の上限（C-04）は別に効くので、費用が膨らむことはない。
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


def ensure_known_nurse(svc: Services, nurse_id: str) -> None:
    """担当・受け持ち・自己申告の「自分」が、看護師の一覧にいるかを確かめる（S-08）。

    Raises:
        ApiError: 一覧にない id の場合（422）
    """
    if all(n.id != nurse_id for n in svc.nurses):
        raise ApiError(422, "unknown_nurse", "看護師の一覧にない人です。選び直してください")


def ensure_reported_by(svc: Services, reported_by: str | None) -> None:
    """自己申告の「自分」は送らなくてもよい（今の画面のため）。送ったら一覧にいる人だけ。"""
    if reported_by is not None:
        ensure_known_nurse(svc, reported_by)


def with_current_assignee(svc: Services, patient: Patient) -> Patient:
    """受け持ちを、保存先の今の値にする（名簿は起動時に読んだもので、受け持ちは画面で変わる）。"""
    saved = svc.store.get_patient(patient.id)
    if saved is None:
        return patient
    return patient.model_copy(update={"assigned_to": saved.assigned_to})


def find_patient(svc: Services, patient_id: str) -> Patient:
    """名簿（起動時に読んでメモリに置いたもの）から1人を引く。

    Raises:
        ApiError: 名簿にいない場合（404）
    """
    patient = next((p for p in svc.roster if p.id == patient_id), None)
    if patient is None:
        raise ApiError(404, "patient_not_found", "名簿にない患者です。選び直してください")
    return patient
