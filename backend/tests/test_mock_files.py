"""モック JSON が、今の照合のコードで作り直したものと一致するか。

食い違ったら `python -m scripts.build_mocks` で作り直す（画面はモック JSON を使うため）。
"""

import json

import pytest

from app.models.api import DraftResponse
from app.services.mock_data import load_scenarios, mock_draft_path
from scripts.build_mocks import build_mock

SCENARIO_IDS = [sc["id"] for sc in load_scenarios()]


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_mock_file_is_up_to_date(scenario_id: str) -> None:
    on_disk = json.loads(mock_draft_path(scenario_id).read_text(encoding="utf-8"))
    assert on_disk == build_mock(scenario_id).model_dump(mode="json")


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_mock_file_matches_contract(scenario_id: str) -> None:
    data = json.loads(mock_draft_path(scenario_id).read_text(encoding="utf-8"))
    response = DraftResponse.model_validate(data)
    assert response.mode == "mock"
    assert response.draft.soap.A == "" and response.draft.soap.P == ""
    assert all(u.start is not None for u in response.utterances)


def test_scene3_shows_ai_added_sentence() -> None:
    data = json.loads(mock_draft_path("s3").read_text(encoding="utf-8"))
    first = data["checks"][0]
    assert (first["path"], first["code"]) == ("soap.S[2]", "entail_not_supported")
