from fastapi.testclient import TestClient

from app.main import app


def test_prometheus_metrics_disabled_by_default():
    client = TestClient(app)
    r = client.get("/admin/metrics/prometheus")
    assert r.status_code == 404


def test_prometheus_metrics_when_enabled(monkeypatch):
    monkeypatch.setenv("METRICS_EXPORT_ENABLED", "1")
    client = TestClient(app)
    r = client.get("/admin/metrics/prometheus")
    assert r.status_code == 200
    assert "http_requests_total" in r.text or "smtp_send" in r.text or "TYPE" in r.text
