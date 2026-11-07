"""The whole loop through the API only: Telios setup, Kinetics repro, Atlas fix, Kinetics verify, Gremlin close."""

from test_scenario_cart02 import CART_CALLS, COHORT as CART, STEPS as CART_STEPS
from test_scenario_gold01 import GOLD, GOLD_CALLS, HOME
from test_scenario_track05 import COHORT as TRACK, STEPS as TRACK_STEPS, TRACK_CALLS

CART_IOS = "ios-18.5-PNQ-G3-gold_monthly"


def atlas(client, **body):
    return client.post("/atlas/fixes", json={"summary": "fix", **body}).json()


def api_check(client, bug_ref, mu, endpoint, env="preprod"):
    body = {"bug_ref": bug_ref, "env": env, "mock_user_id": mu, "method": "GET", "endpoint": endpoint}
    return client.post("/api-checks", json=body).json()


def test_cart02_full_loop(client, setup_user, run):
    mu = setup_user(CART, CART_CALLS)
    ios = setup_user(CART_IOS, CART_CALLS)
    assert run("RPT-102", mu, "android-18.2", "redmi-note-10", CART_STEPS)["result"] == "reproduced"
    # baselines on the release candidate the fix will ship in, one per affected platform
    assert run("RPT-102", mu, "android-18.6-rc1", "redmi-note-10", CART_STEPS)["result"] == "reproduced"
    assert run("RPT-102", ios, "ios-18.6-rc1", "iphone-15", CART_STEPS)["result"] == "reproduced"
    attempt = atlas(client, bug_ref="RPT-102", layer="frontend", target="checkout", platforms=["android", "ios"], culprit_change_id="CHG-411")
    built = {b["platform"]: b["build_id"] for b in attempt["builds"]}
    passing = run("RPT-102", mu, built["android"], "redmi-note-10", CART_STEPS)
    assert passing["result"] == "not_reproduced"
    assert run("RPT-102", ios, built["ios"], "iphone-15", CART_STEPS)["result"] == "not_reproduced"
    client.post("/prds/PRD-CHECKOUT-V3/updates", json={"change": "DiscountRow shows the coupon code when label is missing",
                                                       "reason": "Crash on coupon rows", "bug_ref": "RPT-102",
                                                       "known_issue": "18.2-18.5 crash with Gold + coupon; fixed in 18.6"})
    client.post("/releases/app-18.6/notes", json={"bug_ref": "RPT-102", "note": "Checkout no longer crashes with Gold + coupon"})
    client.post("/threads/THR-111/replies", json={"bug_ref": "RPT-102", "text": "Root-caused and fixed; ships in 18.6."})
    rca = {"bug_ref": "RPT-102", "title": "Checkout crash with Gold + coupon", "what_happened": "Checkout showed an error dialog.",
           "root_cause": "DiscountRow assumed every discount has a label.", "culprit_change_id": "CHG-411",
           "fix": {"pr_url": attempt["pr_url"], "builds": built}, "verification": {"run_id": passing["run_id"]},
           "impact": "3410 users on 18.2-18.5", "follow_ups": ["Contract tests for optional fields"]}
    assert client.post("/rca", json=rca).status_code == 200
    got = client.get("/rca/RPT-102").json()
    assert got["fix"]["builds"] == built and got["verification"]["run_id"] == passing["run_id"]
    assert "DiscountRow shows the coupon code" in client.get("/prds/PRD-CHECKOUT-V3").json()["changelog"][-1]["change"]
    assert client.get("/threads/THR-111").json()["messages"][-1]["author"] == "Gremlin"


def test_gold01_full_loop(client, setup_user, run):
    mu = setup_user(GOLD, GOLD_CALLS)
    assert api_check(client, "RPT-101", mu, "/v2/membership/status")["body"]["status"] == "expired"
    attempt = atlas(client, bug_ref="RPT-101", layer="backend", target="membership-service", culprit_change_id="CHG-401")
    env = attempt["preprod"]["env"]
    verified = api_check(client, "RPT-101", mu, "/v2/membership/status", env=env)
    assert verified["body"]["status"] == "active"
    assert run("RPT-101", mu, "android-18.5", "pixel-7", HOME, env=env)["result"] == "not_reproduced"
    client.post("/releases/hotfix-2026-11-06/notes", json={"bug_ref": "RPT-101", "note": "Gold status refreshes on renewal"})
    rca = {"bug_ref": "RPT-101", "title": "Gold status stale after renewal", "what_happened": "Renewed members saw Join Gold.",
           "root_cause": "Cache not cleared on renewal (CHG-401).", "culprit_change_id": "CHG-401",
           "fix": {"pr_url": attempt["pr_url"], "preprod": attempt["preprod"]}, "verification": {"check_id": verified["check_id"]},
           "impact": "1284 users", "follow_ups": []}
    client.post("/rca", json=rca)
    assert client.get("/rca/RPT-101").json()["verification"] == {"check_id": verified["check_id"]}


def test_wrong_fix_then_retry(client, setup_user, run):
    mu = setup_user(TRACK, TRACK_CALLS)
    assert run("RPT-105", mu, "android-18.3", "oneplus-nord", TRACK_STEPS)["result"] == "reproduced"
    # The release candidate never shows the bug, so there is no baseline for an app fix: only old
    # apps break, and they can't be patched. An app fix "passes" without proving anything.
    assert run("RPT-105", mu, "android-18.6-rc1", "oneplus-nord", TRACK_STEPS)["result"] == "not_reproduced"
    wrong = atlas(client, bug_ref="RPT-105", layer="frontend", target="order_tracking", platforms=["android"], culprit_change_id="CHG-432")
    assert run("RPT-105", mu, wrong["builds"][0]["build_id"], "oneplus-nord", TRACK_STEPS)["result"] == "not_reproduced"
    assert run("RPT-105", mu, "android-18.3", "oneplus-nord", TRACK_STEPS)["result"] == "reproduced"
    right = atlas(client, bug_ref="RPT-105", layer="backend", target="order-tracking-service", culprit_change_id="CHG-431")
    assert right["attempt_id"] == "ATL-0002"
    env = right["preprod"]["env"]
    assert api_check(client, "RPT-105", mu, "/orders/active/track", env=env)["body"]["schema_version"] == 1
    assert run("RPT-105", mu, "android-18.3", "oneplus-nord", TRACK_STEPS, env=env)["result"] == "not_reproduced"
