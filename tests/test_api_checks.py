from test_scenario_gold01 import GOLD, GOLD_CALLS
from test_scenario_track05 import COHORT as TRACK, TRACK_CALLS


def check(client, mu, method, endpoint, env="preprod"):
    return client.post("/api-checks", json={"env": env, "mock_user_id": mu, "method": method, "endpoint": endpoint})


def test_gold_check_before_and_after_atlas(client, setup_user):
    mu = setup_user(GOLD, GOLD_CALLS)
    before = check(client, mu, "GET", "/v2/membership/status").json()
    assert before["check_id"] == "CHK-0001" and before["body"]["status"] == "expired"
    client.post("/atlas/fixes", json={"bug_ref": "RPT-101", "layer": "backend", "target": "membership-service",
                                      "culprit_change_id": "CHG-401", "summary": "clear cache on renewal"})
    after = check(client, mu, "get", "/v2/membership/status").json()
    assert after["body"]["status"] == "active" and after["served_by"] == "membership-service@3.12.0-atlas-1"
    logs = client.get("/logs", params={"env": "sandbox", "user_id": mu}).json()
    assert [l["response_excerpt"]["status"] for l in logs] == ["expired", "active"]


def test_track_check_old_app(client, setup_user):
    mu = setup_user(TRACK, TRACK_CALLS)
    assert check(client, mu, "GET", "/orders/active/track").json()["body"]["schema_version"] == 2
    client.post("/atlas/fixes", json={"bug_ref": "RPT-105", "layer": "backend", "target": "order-tracking-service",
                                      "culprit_change_id": "CHG-431", "summary": "serve v1 to old apps"})
    after = check(client, mu, "GET", "/orders/active/track").json()
    assert after["body"]["schema_version"] == 1 and after["app_version"] == "18.3"


def test_check_missing_state(client, setup_user):
    no_plan = setup_user("android-18.5-DEL-G7-gold_annual", [])
    r = check(client, no_plan, "GET", "/v2/membership/status")
    assert r.status_code == 200 and r.json()["status"] == 200 and r.json()["body"] == {"status": "none"}
    no_order = setup_user(TRACK, [])
    r = check(client, no_order, "GET", "/orders/active/track")
    assert r.status_code == 200 and r.json()["status"] == 404 and r.json()["body"] == {"error": "no active order"}


def test_check_unknown_endpoint_and_env(client, setup_user):
    mu = setup_user(GOLD, [])
    r = check(client, mu, "GET", "/nope")
    assert r.status_code == 404 and "/nope" in r.json()["detail"]
    assert check(client, mu, "GET", "/v2/membership/status", env="prod").status_code == 422
    assert check(client, "MU-9999", "GET", "/v2/membership/status").status_code == 404
