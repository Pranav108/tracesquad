"""Regression tests for the final-review findings."""

GOLD = "android-18.5-DEL-G7-gold_annual"
TRACK = "android-18.3-HYD-G4-gold_trial"
TRACK_CALLS = [("set_address", {"city": "HYD", "area": "Madhapur"}), ("set_group", {"group": "G4"}),
               ("activate_plan", {"plan": "gold_trial"}), ("add_payment_method", {"type": "upi"}),
               ("place_order", {"restaurant_id": "R-7781", "items": [{"item_id": "I-301", "qty": 1}]})]


def sandbox_logs(client, mu):
    return client.get("/logs", params={"env": "sandbox", "user_id": mu}).json()


# Finding 1: /logs with a time that has no offset
def test_logs_naive_time_422(client):
    r = client.get("/logs", params={"user_id": "U-48213", "from": "2026-11-04T09:30:00"})
    assert r.status_code == 422 and "offset" in r.json()["detail"]


def test_logs_unencoded_plus_offset_works(client):
    r = client.get("/logs?user_id=U-48213&from=2026-11-04T09:30:00+05:30&to=2026-11-04T10:30:00+05:30")
    assert r.status_code == 200
    assert any(l["error_signature"] == "membership.stale_status_after_renewal" for l in r.json())


# Finding 2: OpenAPI must not hand agents the answers or the reset button
def test_openapi_hides_admin_and_reset(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert not any(p.startswith("/admin") for p in paths) and "/sandbox/reset" not in paths


# Finding 3: fixes stay hidden until a team publishes them
def test_unpublished_fix_hidden(client):
    assert client.get("/fixes", params={"bug_ref": "RPT-102"}).json() == []
    assert client.get("/fixes/FIX-CART-02").status_code == 404


def test_publish_fix_then_reset_hides_it(client):
    assert client.post("/fixes/FIX-CART-02/publish").status_code == 200
    assert [f["fix_id"] for f in client.get("/fixes", params={"bug_ref": "RPT-102"}).json()] == ["FIX-CART-02"]
    client.post("/sandbox/reset")
    assert client.get("/fixes", params={"bug_ref": "RPT-102"}).json() == []


def test_publish_unknown_fix_404(client):
    r = client.post("/fixes/FIX-NOPE/publish")
    assert r.status_code == 404 and "FIX-NOPE" in r.json()["detail"]


# Finding 4: sandbox logs must not contradict the scenario on off-path runs
def test_track05_newer_app_still_sees_schema_v2(client, setup_user, run):
    mu = setup_user(TRACK, TRACK_CALLS)
    run(mu, "android-18.4", "oneplus-nord", [{"screen": "order_tracking", "action": "open"}])
    logs = sandbox_logs(client, mu)
    assert [l["response_excerpt"]["schema_version"] for l in logs if l["source"] == "backend"] == [2]
    assert not any(l["level"] == "error" for l in logs)


def test_no_sandbox_logs_when_state_missing(client, setup_user, run):
    mu = setup_user("android-18.5-DEL-G1-none", [])
    steps = [{"screen": s, "action": a} for s, a in
             [("home", "open"), ("checkout", "open"), ("payment", "pay_upi"), ("order_tracking", "open")]]
    assert run(mu, "android-18.5", "pixel-7", steps)["result"] == "not_reproduced"
    assert sandbox_logs(client, mu) == []


# Finding 5: the data must hold everything Telios needs (area, items)
def test_profiles_have_area(client):
    expected = {"U-48213": "Saket", "U-77105": "Baner", "U-23017": "Indiranagar", "U-61540": "Andheri", "U-90877": "Madhapur"}
    assert {uid: client.get(f"/users/{uid}").json()["area"] for uid in expected} == expected


def test_journeys_have_items(client):
    track = client.get("/users/U-90877/journey").json()["events"]
    pay = client.get("/users/U-61540/journey").json()["events"]
    assert next(e for e in track if e["action"] == "place_order")["params"]["items"] == [{"item_id": "I-301", "qty": 1}]
    assert next(e for e in pay if e["screen"] == "cart")["params"]["items"] == [{"item_id": "I-12", "qty": 1}]


# Finding 6: setup param values are validated
def test_setup_rejects_unknown_values(client):
    mu = client.post("/sandbox/users", json={"cohort_id": GOLD}).json()["mock_user_id"]

    def setup(api, params):
        return client.post(f"/sandbox/users/{mu}/setup/{api}", json=params)

    r = setup("set_address", {"city": "Delhi", "area": "Saket"})
    assert r.status_code == 422 and "Delhi" in r.json()["detail"]
    assert setup("set_address", {"city": "DEL", "area": "Saket"}).status_code == 200
    r = setup("activate_plan", {"plan": "gold_anual"})
    assert r.status_code == 422 and "gold_anual" in r.json()["detail"]
    assert setup("activate_plan", {"plan": "none"}).status_code == 422
    assert setup("add_payment_method", {"type": "wallet"}).status_code == 422
    r = setup("fill_cart", {"restaurant_id": "R-1", "items": "two biryanis"})
    assert r.status_code == 422 and "items" in r.json()["detail"]
    assert setup("fill_cart", {"restaurant_id": "R-1", "items": [{"item_id": "I-1", "qty": 1}]}).status_code == 200
    assert setup("apply_coupon", {"code": {"x": 1}}).status_code == 422
