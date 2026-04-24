from fastapi.testclient import TestClient

from app.main import app


def _cid(headers: dict) -> str | None:
    return headers.get("x-correlation-id") or headers.get("X-Correlation-ID")


def test_correlation_id_echoed_on_response():
    client = TestClient(app)
    r = client.get("/", headers={"X-Correlation-ID": "trace-test-abc"})
    assert r.status_code == 200
    assert _cid(r.headers) == "trace-test-abc"


def test_correlation_id_generated_when_missing():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    cid = _cid(r.headers)
    assert cid and len(cid) >= 8
