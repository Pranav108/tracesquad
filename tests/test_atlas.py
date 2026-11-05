from test_scenario_cart02 import CART_CALLS, COHORT as CART, STEPS as CART_STEPS
from test_scenario_gold01 import GOLD, GOLD_CALLS, HOME


def fix(client, **body):
    return client.post("/atlas/fixes", json={"summary": "fix", **body})


def test_frontend_fix_right_and_wrong_look_alike(client, setup_user, run):
    mu = setup_user(CART, CART_CALLS)
    right = fix(client, bug_ref="RPT-102", layer="frontend", target="checkout", platform="android", culprit_change_id="CHG-411")
    assert right.status_code == 200 and right.json()["build_id"] == "android-18.2-atlas-1"
    assert run(mu, right.json()["build_id"], "redmi-note-10", CART_STEPS)["result"] == "not_reproduced"
    wrong = fix(client, bug_ref="RPT-102", layer="frontend", target="cart", platform="android", culprit_change_id="CHG-411")
    assert wrong.json()["build_id"] == "android-18.2-atlas-2"
    assert run(mu, wrong.json()["build_id"], "redmi-note-10", CART_STEPS)["result"] == "reproduced"
    assert set(right.json()) == set(wrong.json())
    assert "fixes_scenario" not in right.text
    build = client.get("/builds/android-18.2-atlas-1")
    assert build.status_code == 200 and "fixes_scenario" not in build.text and "base_build_id" not in build.text


def test_backend_fix_and_latest_deploy_wins(client, setup_user, run):
    mu = setup_user(GOLD, GOLD_CALLS)
    wrong = fix(client, bug_ref="RPT-101", layer="backend", target="payment-service", culprit_change_id="CHG-402")
    assert wrong.json()["preprod"] == {"service": "payment-service", "version": "9.0.3-atlas-1"}
    assert run(mu, "android-18.5", "pixel-7", HOME)["result"] == "reproduced"
    right = fix(client, bug_ref="RPT-101", layer="backend", target="membership-service", culprit_change_id="CHG-401")
    assert right.json()["preprod"] == {"service": "membership-service", "version": "3.12.0-atlas-2"}
    assert run(mu, "android-18.5", "pixel-7", HOME)["result"] == "not_reproduced"
    client.post("/sandbox/deploy", json={"service": "membership-service", "version": "3.12.0"})
    assert run(mu, "android-18.5", "pixel-7", HOME)["result"] == "reproduced"


def test_fix_errors(client):
    def body(**over):
        base = {"bug_ref": "RPT-101", "layer": "backend", "target": "membership-service", "culprit_change_id": "CHG-401"}
        return {**base, **over}

    assert fix(client, **body(culprit_change_id="CHG-999")).status_code == 404
    assert fix(client, **body(bug_ref="RPT-999")).status_code == 404
    assert fix(client, **body(target="nope-service")).status_code == 404
    r = fix(client, **body(bug_ref="RPT-105", layer="frontend", target="order_tracking", platform="ios", culprit_change_id="CHG-432"))
    assert r.status_code == 422 and "ios" in r.json()["detail"] and "18.3" in r.json()["detail"]
    assert fix(client, **body(bug_ref="RPT-102", layer="frontend", target="checkout", culprit_change_id="CHG-411")).status_code == 422


def test_fixes_lists_attempts(client):
    fix(client, bug_ref="RPT-102", layer="frontend", target="checkout", platform="android", culprit_change_id="CHG-411")
    items = client.get("/fixes", params={"bug_ref": "RPT-102"}).json()
    assert len(items) == 1 and items[0]["attempt_id"] == "ATL-0001"
    assert "fixes_scenario" not in str(items) and "ships_in" not in items[0]
    assert client.get("/fixes/ATL-0001").json()["build_id"] == "android-18.2-atlas-1"


def test_frontend_target_must_be_a_known_screen(client):
    for bad in ("Checkout", "restaurant_page"):
        r = fix(client, bug_ref="RPT-102", layer="frontend", target=bad, platform="android", culprit_change_id="CHG-411")
        assert r.status_code == 422 and bad in r.json()["detail"] and "checkout" in r.json()["detail"]
    assert client.get("/fixes", params={"bug_ref": "RPT-102"}).json() == []
