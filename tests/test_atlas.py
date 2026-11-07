from test_scenario_cart02 import CART_CALLS, COHORT as CART, STEPS as CART_STEPS
from test_scenario_gold01 import GOLD, GOLD_CALLS, HOME

CART_IOS = "ios-18.5-PNQ-G3-gold_monthly"


def fix(client, **body):
    return client.post("/atlas/fixes", json={"summary": "fix", **body})


def builds(attempt) -> dict[str, str]:
    return {b["platform"]: b["build_id"] for b in attempt["builds"]}


def test_frontend_fix_right_and_wrong_look_alike(client, setup_user, run):
    mu = setup_user(CART, CART_CALLS)
    right = fix(client, bug_ref="RPT-102", layer="frontend", target="checkout", platforms=["android"], culprit_change_id="CHG-411")
    assert right.status_code == 200
    assert right.json()["release"] == "app-18.6"
    assert right.json()["builds"] == [{"platform": "android", "build_id": "android-18.6-rc1-atlas-1", "built_on": "android-18.6-rc1"}]
    assert run("RPT-102", mu, "android-18.6-rc1-atlas-1", "redmi-note-10", CART_STEPS)["result"] == "not_reproduced"
    wrong = fix(client, bug_ref="RPT-102", layer="frontend", target="cart", platforms=["android"], culprit_change_id="CHG-411")
    assert builds(wrong.json()) == {"android": "android-18.6-rc1-atlas-2"}
    assert run("RPT-102", mu, "android-18.6-rc1-atlas-2", "redmi-note-10", CART_STEPS)["result"] == "reproduced"
    assert set(right.json()) == set(wrong.json())
    assert "fixes_scenario" not in right.text
    build = client.get("/builds/android-18.6-rc1-atlas-1")
    assert build.status_code == 200 and "fixes_scenario" not in build.text and "base_build_id" not in build.text


def test_release_candidate_has_the_bug_until_fixed(setup_user, run):
    mu = setup_user(CART, CART_CALLS)
    assert run("RPT-102", mu, "android-18.6-rc1", "redmi-note-10", CART_STEPS)["result"] == "reproduced"


def test_wrong_culprit_does_not_fix(client, setup_user, run):
    mu = setup_user(CART, CART_CALLS)
    wrong = fix(client, bug_ref="RPT-102", layer="frontend", target="checkout", platforms=["android"], culprit_change_id="CHG-412")
    assert wrong.status_code == 200
    assert run("RPT-102", mu, builds(wrong.json())["android"], "redmi-note-10", CART_STEPS)["result"] == "reproduced"


def test_wrong_culprit_backend_does_not_fix(client, setup_user, run):
    mu = setup_user(GOLD, GOLD_CALLS)
    env = fix(client, bug_ref="RPT-101", layer="backend", target="membership-service", culprit_change_id="CHG-403").json()["preprod"]["env"]
    assert run("RPT-101", mu, "android-18.5", "pixel-7", HOME, env=env)["result"] == "reproduced"


def test_fix_covers_each_platform_it_names(client, setup_user, run):
    android = setup_user(CART, CART_CALLS)
    ios = setup_user(CART_IOS, CART_CALLS)
    assert run("RPT-102", ios, "ios-18.6-rc1", "iphone-15", CART_STEPS)["result"] == "reproduced"
    only_android = fix(client, bug_ref="RPT-102", layer="frontend", target="checkout", platforms=["android"], culprit_change_id="CHG-411")
    assert "ios" not in builds(only_android.json())
    both = fix(client, bug_ref="RPT-102", layer="frontend", target="checkout", platforms=["android", "ios", "ios"], culprit_change_id="CHG-411")
    assert both.json()["platforms"] == ["android", "ios"]
    assert builds(both.json()) == {"android": "android-18.6-rc1-atlas-2", "ios": "ios-18.6-rc1-atlas-2"}
    assert run("RPT-102", android, "android-18.6-rc1-atlas-2", "redmi-note-10", CART_STEPS)["result"] == "not_reproduced"
    assert run("RPT-102", ios, "ios-18.6-rc1-atlas-2", "iphone-15", CART_STEPS)["result"] == "not_reproduced"


def test_menu03_fix_on_the_release_candidate(client, setup_user, run):
    attempt = fix(client, bug_ref="RPT-103", layer="frontend", target="restaurant", platforms=["ios"], culprit_change_id="CHG-421")
    mu = setup_user("ios-18.5-BLR-G1-none", [("set_address", {"city": "BLR", "area": "Indiranagar"}), ("set_group", {"group": "G1"})])
    steps = [{"screen": "restaurant", "action": "open", "params": {"restaurant_id": "R-5520"}}]
    assert run("RPT-103", mu, "ios-18.6-rc1", "iphone-se-2", steps)["result"] == "reproduced"
    assert run("RPT-103", mu, builds(attempt.json())["ios"], "iphone-se-2", steps)["result"] == "not_reproduced"


def test_backend_fix_gets_its_own_preprod_env(client, setup_user, run):
    mu = setup_user(GOLD, GOLD_CALLS)
    wrong = fix(client, bug_ref="RPT-101", layer="backend", target="payment-service", culprit_change_id="CHG-402")
    assert wrong.json()["preprod"] == {"env": "preprod-atl-0001", "service": "payment-service", "version": "9.0.3-atlas-1"}
    assert wrong.json()["platforms"] == [] and "builds" not in wrong.json()
    assert run("RPT-101", mu, "android-18.5", "pixel-7", HOME, env="preprod-atl-0001")["result"] == "reproduced"
    right = fix(client, bug_ref="RPT-101", layer="backend", target="membership-service", culprit_change_id="CHG-401")
    assert right.json()["preprod"] == {"env": "preprod-atl-0002", "service": "membership-service", "version": "3.12.0-atlas-2"}
    fixed = run("RPT-101", mu, "android-18.5", "pixel-7", HOME, env="preprod-atl-0002")
    assert fixed["result"] == "not_reproduced" and fixed["env"] == "preprod-atl-0002"
    assert fixed["network"][0]["response"]["status"] == "active"
    # shared pre-prod is untouched: it stays the baseline
    assert run("RPT-101", mu, "android-18.5", "pixel-7", HOME)["result"] == "reproduced"
    services = client.get("/sandbox/services").json()
    assert services["membership-service"] == "3.12.0" and services["payment-service"] == "9.0.3"
    assert client.get("/sandbox/services", params={"env": "preprod-atl-0002"}).json()["membership-service"] == "3.12.0-atlas-2"
    assert client.get("/sandbox/services", params={"env": "preprod-atl-0009"}).status_code == 404
    assert "fixes_scenario" not in right.text


def test_attempts_and_bugs_dont_overwrite_each_other(client, setup_user, run):
    """The old shared pre-prod let a later wrong attempt (or another bug's deploy) undo a verified fix."""
    gold = setup_user(GOLD, GOLD_CALLS)
    right = fix(client, bug_ref="RPT-101", layer="backend", target="membership-service", culprit_change_id="CHG-401").json()
    # another bug's backend fix, and then a wrong attempt on the same service, both land later
    fix(client, bug_ref="RPT-105", layer="backend", target="order-tracking-service", culprit_change_id="CHG-431")
    fix(client, bug_ref="RPT-101", layer="backend", target="membership-service", culprit_change_id="CHG-403")
    assert run("RPT-101", gold, "android-18.5", "pixel-7", HOME, env=right["preprod"]["env"])["result"] == "not_reproduced"


def test_fix_errors(client):
    def body(**over):
        base = {"bug_ref": "RPT-101", "layer": "backend", "target": "membership-service", "culprit_change_id": "CHG-401"}
        return {**base, **over}

    assert fix(client, **body(culprit_change_id="CHG-999")).status_code == 404
    assert fix(client, **body(bug_ref="RPT-999")).status_code == 404
    assert fix(client, **body(target="nope-service")).status_code == 404
    no_platforms = fix(client, **body(bug_ref="RPT-102", layer="frontend", target="checkout", culprit_change_id="CHG-411"))
    assert no_platforms.status_code == 422 and "platforms" in no_platforms.json()["detail"]
    assert fix(client, **body(bug_ref="RPT-102", layer="frontend", target="checkout", platforms=["web"])).status_code == 422


def test_fixes_lists_attempts(client):
    fix(client, bug_ref="RPT-102", layer="frontend", target="checkout", platforms=["android"], culprit_change_id="CHG-411")
    items = client.get("/fixes", params={"bug_ref": "RPT-102"}).json()
    assert len(items) == 1 and items[0]["attempt_id"] == "ATL-0001"
    assert "fixes_scenario" not in str(items) and "ships_in" not in items[0]
    assert builds(client.get("/fixes/ATL-0001").json()) == {"android": "android-18.6-rc1-atlas-1"}


def test_published_fix_hides_its_culprit(client):
    published = client.get("/fixes", params={"bug_ref": "BUG-1152"}).json()
    assert published and all("culprit_change_id" not in f for f in published)


def test_frontend_target_must_be_a_known_screen(client):
    for bad in ("Checkout", "restaurant_page"):
        r = fix(client, bug_ref="RPT-102", layer="frontend", target=bad, platforms=["android"], culprit_change_id="CHG-411")
        assert r.status_code == 422 and bad in r.json()["detail"] and "checkout" in r.json()["detail"]
    assert client.get("/fixes", params={"bug_ref": "RPT-102"}).json() == []


def test_impact_splits_by_platform(client):
    impact = client.get("/impact/app.checkout.discount_row_crash").json()
    assert impact["by_platform"] == {"android": 3000, "ios": 410}
    assert sum(impact["by_platform"].values()) == impact["affected_users"]
