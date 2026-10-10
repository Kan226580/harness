from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_live_returns_ok() -> None:
    """检验 /health/live api 能否正确使用"""
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
