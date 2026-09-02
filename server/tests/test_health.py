from fastapi.testclient import TestClient

from app.core.config import settings


def test_health_check_status_code(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/health")
    assert response.status_code == 200


def test_health_check_payload_structure(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["environment"] == settings.ENVIRONMENT
    assert data["version"] == settings.VERSION
