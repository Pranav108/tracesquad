"""The whole loop through the API only: Telios setup, Kinetics repro, Atlas fix, Kinetics verify, Gremlin close."""

from test_scenario_cart02 import CART_CALLS, COHORT as CART, STEPS as CART_STEPS
from test_scenario_gold01 import GOLD, GOLD_CALLS, HOME
from test_scenario_track05 import COHORT as TRACK, STEPS as TRACK_STEPS, TRACK_CALLS


def atlas(client, **body):
    return client.post("/atlas/fixes", json={"summary": "fix", **body}).json()


def api_check(client, mu, endpoint):
    return client.post("/api-checks", json={"env": "preprod", "mock_user_id": mu, "method": "GET", "endpoint": endpoint}).json()


def test_cart02_full_loop(client, setup_user, run):
    mu = setup_user(CART, CART_CALLS)
    assert run(mu, "android-18.2", "redmi-note-10", CART_STEPS)["result"] == "reproduced"
    attempt = atlas(client, bug_ref="RPT-102", layer="frontend", target="checkout", platform="android", culprit_change_id="CHG-411")
    passing = run(mu, attempt["build_id"], "redmi-note-10", CART_STEPS)
    assert passing["result"] == "not_reproduced"
    client.post("/prds/PRD-CHECKOUT-V3/updates", json={"change": "DiscountRow shows the coupon code when label is missing",
                                                       "reason": "Crash on coupon rows", "bug_ref": "RPT-102",
                                                       "known_issue": "18.2-18.5 crash with Gold + coupon; fixed in 18.6"})
    client.post("/releases/app-18.6/notes", json={"bug_ref": "RPT-102", "note": "Checkout no longer crashes with Gold + coupon"})
    client.post("/threads/THR-111/replies", json={"bug_ref": "RPT-102", "text": "Root-caused and fixed; ships in 18.6."})
    rca = {"bug_ref": "RPT-102", "title": "Checkout crash with Gold + coupon", "what_happened": "Checkout showed an error dialog.",
           "root_cause": "DiscountRow assumed every discount has a label.", "culprit_change_id": "CHG-411",
           "fix": {"pr_url": attempt["pr_url"], "build_id": attempt["build_id"]}, "verification": {"run_id": passing["run_id"]},
           "impact": "3410 users on 18.2-18.5", "follow_ups": ["Contract tests for optional fields"]}
    assert client.post("/rca", json=rca).status_code == 200
    got = client.get("/rca/RPT-102").json()
    assert got["fix"]["build_id"] == attempt["build_id"] and got["verification"]["run_id"] == passing["run_id"]
    assert "DiscountRow shows the coupon code" in client.get("/prds/PRD-CHECKOUT-V3").json()["changelog"][-1]["change"]
    assert client.get("/threads/THR-111").json()["messages"][-1]["author"] == "Gremlin"


def test_gold01_full_loop(client, setup_user, run):
    mu = setup_user(GOLD, GOLD_CALLS)
    assert api_check(client, mu, "/v2/membership/status")["body"]["status"] == "expired"
    attempt = atlas(client, bug_ref="RPT-101", layer="backend", target="membership-service", culprit_change_id="CHG-401")
    verified = api_check(client, mu, "/v2/membership/status")
    assert verified["body"]["status"] == "active"
    assert run(mu, "android-18.5", "pixel-7", HOME)["result"] == "not_reproduced"
    client.post("/releases/hotfix-2026-11-06/notes", json={"bug_ref": "RPT-101", "note": "Gold status refreshes on renewal"})
    rca = {"bug_ref": "RPT-101", "title": "Gold status stale after renewal", "what_happened": "Renewed members saw Join Gold.",
           "root_cause": "Cache not cleared on renewal (CHG-401).", "culprit_change_id": "CHG-401",
           "fix": {"pr_url": attempt["pr_url"], "preprod": attempt["preprod"]}, "verification": {"check_id": verified["check_id"]},
           "impact": "1284 users", "follow_ups": []}
    client.post("/rca", json=rca)
    assert client.get("/rca/RPT-101").json()["verification"] == {"check_id": verified["check_id"]}


def test_wrong_fix_then_retry(client, setup_user, run):
    mu = setup_user(TRACK, TRACK_CALLS)
    wrong = atlas(client, bug_ref="RPT-105", layer="frontend", target="order_tracking", platform="android", culprit_change_id="CHG-432")
    assert run(mu, wrong["build_id"], "oneplus-nord", TRACK_STEPS)["result"] == "reproduced"
    right = atlas(client, bug_ref="RPT-105", layer="backend", target="order-tracking-service", culprit_change_id="CHG-431")
    assert right["attempt_id"] == "ATL-0002"
    assert api_check(client, mu, "/orders/active/track")["body"]["schema_version"] == 1
    assert run(mu, "android-18.3", "oneplus-nord", TRACK_STEPS)["result"] == "not_reproduced"
