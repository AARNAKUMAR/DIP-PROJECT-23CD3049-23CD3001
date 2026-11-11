"""CP-0 configuration and API smoke tests."""

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from datagard.config import Settings
from datagard.main import app


def test_settings_load_defaults_and_validate_port() -> None:
    settings = Settings()

    assert settings.app_name == "DataGuard AI"
    assert 1 <= settings.api_port <= 65535

    with pytest.raises(ValidationError):
        Settings(api_port=0)


def test_health_endpoint_reports_liveness() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "development"}
