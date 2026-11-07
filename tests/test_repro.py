from tracesquad.models import Trigger
from tracesquad.repro import ReproStep, step_matches


def test_step_matches_param_subset():
    t = Trigger(screen="restaurant", action="open", params={"restaurant_id": "R-5520"})
    assert step_matches(ReproStep(screen="restaurant", action="open", params={"restaurant_id": "R-5520", "x": 1}), t)
    assert not step_matches(ReproStep(screen="restaurant", action="open", params={"restaurant_id": "R-2210"}), t)
    assert not step_matches(ReproStep(screen="restaurant", action="scroll", params={"restaurant_id": "R-5520"}), t)


def test_platform_mismatch_422(client, setup_user):
    mu = setup_user("android-18.5-DEL-G7-gold_annual", [])
    r = client.post("/repro/runs", json={"bug_ref": "RPT-101", "build_id": "ios-18.5", "mock_user_id": mu, "device_id": "iphone-15",
                                         "steps": [{"screen": "home", "action": "open"}]})
    assert r.status_code == 422 and "android" in r.json()["detail"] and "ios" in r.json()["detail"]


def test_unknown_build_404(client, setup_user):
    mu = setup_user("android-18.5-DEL-G7-gold_annual", [])
    r = client.post("/repro/runs", json={"bug_ref": "RPT-101", "build_id": "android-17.9", "mock_user_id": mu, "device_id": "pixel-7", "steps": []})
    assert r.status_code == 404 and "android-17.9" in r.json()["detail"]


def test_run_ids_and_default_result(client, setup_user, run):
    mu = setup_user("android-18.5-DEL-G7-gold_annual", [])
    first = run("RPT-101", mu, "android-18.5", "pixel-7", [{"screen": "search", "action": "open"}])
    assert first["run_id"] == "RUN-0001" and first["result"] == "not_reproduced"
    assert first["artifacts"]["video_url"].endswith("RUN-0001.mp4") and first["network"] == []


# A run that doesn't reproduce still says what the screen showed, and why.
from test_scenario_cart02 import CART_CALLS, COHORT as CART, STEPS as CART_STEPS  # noqa: E402
from test_scenario_track05 import COHORT as TRACK, STEPS as TRACK_STEPS, TRACK_CALLS  # noqa: E402


def test_missing_state_shows_on_screen(setup_user, run):
    no_coupon = run("RPT-102", setup_user(CART, CART_CALLS[:4]), "android-18.2", "redmi-note-10", CART_STEPS)
    assert no_coupon["result"] == "not_reproduced" and "no coupon is applied" in no_coupon["observed"]
    # the first missing piece is reported: an empty cart, before the coupon that needs it
    empty = run("RPT-102", setup_user(CART, CART_CALLS[:3]), "android-18.2", "redmi-note-10", CART_STEPS)
    assert "Your cart is empty" in empty["observed"] and empty["network"] == []
    no_order = run("RPT-105", setup_user(TRACK, TRACK_CALLS[:4]), "android-18.3", "oneplus-nord", TRACK_STEPS)
    assert no_order["observed"] == "Order tracking shows 'No active orders'"


def test_healthy_screen_is_described(setup_user, run):
    mu = setup_user("ios-18.5-BLR-G1-none", [("set_address", {"city": "BLR", "area": "Indiranagar"})])
    other_device = run("RPT-103", mu, "ios-18.5", "iphone-15", [{"screen": "restaurant", "action": "open", "params": {"restaurant_id": "R-5520"}}])
    assert other_device["result"] == "not_reproduced" and "two lines" in other_device["observed"]
    assert other_device["network"][0]["endpoint"] == "/restaurants/R-5520"


def test_newer_app_copes_and_network_shows_why(setup_user, run):
    mu = setup_user(TRACK, TRACK_CALLS)
    rc = run("RPT-105", mu, "android-18.6-rc1", "oneplus-nord", TRACK_STEPS)
    assert rc["result"] == "not_reproduced" and "ETA" in rc["observed"]
    # the backend still sends the new format; this app version just handles it
    assert rc["network"][0]["response"]["schema_version"] == 2


def test_trigger_never_reached(setup_user, run):
    mu = setup_user(CART, CART_CALLS)
    one = run("RPT-102", mu, "android-18.2", "redmi-note-10", [{"screen": "cart", "action": "open"}])
    assert one["observed"] == "Completed the one step, ending on cart (open). No problem seen."
    two = run("RPT-102", mu, "android-18.2", "redmi-note-10", [{"screen": "home", "action": "open"}, {"screen": "cart", "action": "open"}])
    assert two["observed"].startswith("Completed all 2 steps, ending on cart (open)")


def test_run_only_judges_its_own_bug(setup_user, run):
    mu = setup_user(CART, CART_CALLS)
    # CART-02's crash happens on this run, but the run is about TRACK-05
    other = run("RPT-105", mu, "android-18.2", "redmi-note-10", CART_STEPS)
    assert other["result"] == "not_reproduced" and other["bug_ref"] == "RPT-105"
    assert run("RPT-102", mu, "android-18.2", "redmi-note-10", CART_STEPS)["result"] == "reproduced"


def test_run_needs_a_known_bug_and_env(client, setup_user):
    mu = setup_user(CART, CART_CALLS)
    body = {"bug_ref": "RPT-102", "build_id": "android-18.2", "mock_user_id": mu, "device_id": "redmi-note-10", "steps": CART_STEPS}
    r = client.post("/repro/runs", json={**body, "bug_ref": "BUG-1152"})
    assert r.status_code == 404 and "report id" in r.json()["detail"]
    r = client.post("/repro/runs", json={**body, "env": "preprod-atl-0001"})
    assert r.status_code == 404 and "preprod" in r.json()["detail"]
    assert client.post("/repro/runs", json={k: v for k, v in body.items() if k != "bug_ref"}).status_code == 422
    assert client.post("/repro/runs", json=body).json()["env"] == "preprod"
