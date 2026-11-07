from test_scenario_gold01 import GOLD, GOLD_CALLS
from test_scenario_track05 import COHORT as TRACK, TRACK_CALLS


def check(client, mu, method, endpoint, env="preprod", bug_ref="RPT-101"):
    body = {"bug_ref": bug_ref, "env": env, "mock_user_id": mu, "method": method, "endpoint": endpoint}
    return client.post("/api-checks", json=body)


def test_gold_check_before_and_after_atlas(client, setup_user):
    mu = setup_user(GOLD, GOLD_CALLS)
    before = check(client, mu, "GET", "/v2/membership/status").json()
    assert before["check_id"] == "CHK-0001" and before["body"]["status"] == "expired" and before["env"] == "preprod"
    attempt = client.post("/atlas/fixes", json={"bug_ref": "RPT-101", "layer": "backend", "target": "membership-service",
                                                "culprit_change_id": "CHG-401", "summary": "clear cache on renewal"}).json()
    env = attempt["preprod"]["env"]
    assert env == "preprod-atl-0001"
    after = check(client, mu, "get", "/v2/membership/status", env=env).json()
    assert after["body"]["status"] == "active" and after["served_by"] == "membership-service@3.12.0-atlas-1"
    # shared pre-prod is the unfixed baseline: the fix lives only in its own env
    assert check(client, mu, "GET", "/v2/membership/status").json()["body"]["status"] == "expired"
    logs = client.get("/logs", params={"env": "sandbox", "user_id": mu}).json()
    assert [(l["preprod_env"], l["response_excerpt"]["status"]) for l in logs] == [
        ("preprod", "expired"), (env, "active"), ("preprod", "expired")]


def test_track_check_old_app(client, setup_user):
    mu = setup_user(TRACK, TRACK_CALLS)
    assert check(client, mu, "GET", "/orders/active/track", bug_ref="RPT-105").json()["body"]["schema_version"] == 2
    attempt = client.post("/atlas/fixes", json={"bug_ref": "RPT-105", "layer": "backend", "target": "order-tracking-service",
                                                "culprit_change_id": "CHG-431", "summary": "serve v1 to old apps"}).json()
    after = check(client, mu, "GET", "/orders/active/track", env=attempt["preprod"]["env"], bug_ref="RPT-105").json()
    assert after["body"]["schema_version"] == 1 and after["app_version"] == "18.3"


def test_check_missing_state(client, setup_user):
    no_plan = setup_user("android-18.5-DEL-G7-gold_annual", [])
    r = check(client, no_plan, "GET", "/v2/membership/status")
    assert r.status_code == 200 and r.json()["status"] == 200 and r.json()["body"] == {"status": "none"}
    no_order = setup_user(TRACK, [])
    r = check(client, no_order, "GET", "/orders/active/track", bug_ref="RPT-105")
    assert r.status_code == 200 and r.json()["status"] == 404 and r.json()["body"] == {"error": "no active order"}


def test_check_unknown_endpoint_env_and_bug(client, setup_user):
    mu = setup_user(GOLD, [])
    r = check(client, mu, "GET", "/nope")
    assert r.status_code == 404 and "/nope" in r.json()["detail"]
    for env in ("prod", "preprod-atl-0009"):
        r = check(client, mu, "GET", "/v2/membership/status", env=env)
        assert r.status_code == 404 and env in r.json()["detail"] and "preprod" in r.json()["detail"]
    assert check(client, "MU-9999", "GET", "/v2/membership/status").status_code == 404
    r = check(client, mu, "GET", "/v2/membership/status", bug_ref="BUG-1152")
    assert r.status_code == 404 and "report id" in r.json()["detail"]
    # failed calls don't use up the budget
    assert client.get("/budget/RPT-101").json()["api_checks"]["used"] == 0
