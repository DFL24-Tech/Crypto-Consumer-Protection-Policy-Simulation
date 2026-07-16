"""The plain-HTTP side of the app: a healthcheck for compose and load balancers."""
from starlette.testclient import TestClient

from dfl24sim_server.app import create_app


def test_health_returns_200():
    with TestClient(create_app()) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
