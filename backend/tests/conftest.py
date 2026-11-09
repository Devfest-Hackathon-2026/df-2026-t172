"""pytest の共通の fixture。"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers import make_services, make_settings


@pytest.fixture
def mock_client() -> TestClient:
    """MODE=mock のアプリ。"""
    return TestClient(create_app(make_settings("mock"), make_services()))
