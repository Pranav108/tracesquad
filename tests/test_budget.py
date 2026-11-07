"""The API enforces each bug's budget: fix attempts, app runs per platform, API checks."""

from test_scenario_cart02 import CART_CALLS, COHORT as CART, STEPS as CART_STEPS
from test_scenario_gold01 import GOLD, GOLD_CALLS

CART_IOS = "ios-18.5-PNQ-G3-gold_monthly"


def fix(client, **body):
    return client.post("/atlas/fixes", json={"summary": "fix", **body})


def test_third_fix_attempt_is_refused(client):
    bad_target = fix(client, bug_ref="RPT-102", layer="frontend", target="nope", platforms=["android"], culprit_change_id="CHG-411")
    assert bad_target.status_code == 422  # a rejected call costs nothing
    for culprit in ("CHG-412", "CHG-411"):
        assert fix(client, bug_ref="RPT-102", layer="frontend", target="checkout", platforms=["android"], culprit_change_id=culprit).status_code == 200
    third = fix(client, bug_ref="RPT-102", layer="frontend", target="checkout", platforms=["android"], culprit_change_id="CHG-411")
    assert third.status_code == 429 and "Triage" in third.json()["detail"] and "2 fix attempts" in third.json()["detail"]
    assert len(client.get("/fixes", params={"bug_ref": "RPT-102"}).json()) == 2
    assert client.get("/budget/RPT-102").json()["fix_attempts"] == {"used": 2, "limit": 2, "left": 0}
    # another bug has its own budget
    assert fix(client, bug_ref="RPT-101", layer="backend", target="membership-service", culprit_change_id="CHG-401").status_code == 200


def test_runs_are_capped_per_platform(client, setup_user):
    android, ios = setup_user(CART, CART_CALLS), setup_user(CART_IOS, CART_CALLS)

    def post(mu, build, device, bug="RPT-102"):
        return client.post("/repro/runs", json={"bug_ref": bug, "build_id": build, "mock_user_id": mu,
                                                "device_id": device, "steps": CART_STEPS})

    for _ in range(7):
        assert post(android, "android-18.2", "redmi-note-10").status_code == 200
    over = post(android, "android-18.2", "redmi-note-10")
    assert over.status_code == 429 and "7 app runs on android" in over.json()["detail"]
    assert post(ios, "ios-18.5", "iphone-15").status_code == 200
    assert post(android, "android-18.2", "redmi-note-10", bug="RPT-104").status_code == 200
    budget = client.get("/budget/RPT-102").json()
    assert budget["runs"] == {"android": {"used": 7, "limit": 7, "left": 0}, "ios": {"used": 1, "limit": 7, "left": 6}}
    # the refused run never happened: no run id was used up
    assert post(ios, "ios-18.5", "iphone-15").json()["run_id"] == "RUN-0010"


def test_api_checks_are_capped(client, setup_user):
    mu = setup_user(GOLD, GOLD_CALLS)
    body = {"bug_ref": "RPT-101", "env": "preprod", "mock_user_id": mu, "method": "GET", "endpoint": "/v2/membership/status"}
    for _ in range(4):
        assert client.post("/api-checks", json=body).status_code == 200
    over = client.post("/api-checks", json=body)
    assert over.status_code == 429 and "4 API checks" in over.json()["detail"]


def test_budget_route_and_reset(client):
    assert client.get("/budget/RPT-999").status_code == 404
    fresh = client.get("/budget/RPT-101").json()
    assert fresh == {"bug_ref": "RPT-101", "fix_attempts": {"used": 0, "limit": 2, "left": 2},
                     "runs": {"android": {"used": 0, "limit": 7, "left": 7}, "ios": {"used": 0, "limit": 7, "left": 7}},
                     "api_checks": {"used": 0, "limit": 4, "left": 4}}
    fix(client, bug_ref="RPT-101", layer="backend", target="membership-service", culprit_change_id="CHG-401")
    client.post("/sandbox/reset")
    assert client.get("/budget/RPT-101").json() == fresh
    assert "/budget/{bug_ref}" in client.get("/openapi.json").json()["paths"]
