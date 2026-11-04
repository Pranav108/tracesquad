import pytest
from fastapi.testclient import TestClient

from bugmock.api import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        c.post("/sandbox/reset")
        yield c


@pytest.fixture
def setup_user(client):
    """Create a mock user for a cohort, apply setup calls in order, return its mock_user_id."""

    def _setup(cohort: str, calls: list[tuple[str, dict]]) -> str:
        r = client.post("/sandbox/users", json={"cohort_id": cohort})
        assert r.status_code == 200, r.text
        mu = r.json()["mock_user_id"]
        for api, params in calls:
            r = client.post(f"/sandbox/users/{mu}/setup/{api}", json=params)
            assert r.status_code == 200, f"{api}: {r.text}"
        return mu

    return _setup


@pytest.fixture
def run(client):
    """Post a repro run and return the JSON body."""

    def _run(mock_user_id: str, build_id: str, device_id: str, steps: list[dict]) -> dict:
        body = {"build_id": build_id, "mock_user_id": mock_user_id, "device_id": device_id, "steps": steps}
        return client.post("/repro/runs", json=body).json()

    return _run
