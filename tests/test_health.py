from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_200(test_env):
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200


def test_health_body_is_exact(test_env):
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.json() == {"status": "ok"}
