COHORT = "android-18.3-HYD-G4-gold_trial"
TRACK_CALLS = [("set_address", {"city": "HYD", "area": "Madhapur"}), ("set_group", {"group": "G4"}),
               ("activate_plan", {"plan": "gold_trial"}), ("add_payment_method", {"type": "upi"}),
               ("place_order", {"restaurant_id": "R-7781", "items": [{"item_id": "I-301", "qty": 1}]})]
STEPS = [{"screen": "order_tracking", "action": "open"}]


def test_track05_order_needs_payment_409(client, setup_user):
    mu = setup_user(COHORT, TRACK_CALLS[:3])
    r = client.post(f"/sandbox/users/{mu}/setup/place_order", json=TRACK_CALLS[4][1])
    assert r.status_code == 409 and "payment_method" in r.json()["detail"] and "add_payment_method" in r.json()["detail"]


def test_track05_expected_path(client, setup_user, run):
    mu = setup_user(COHORT, TRACK_CALLS)
    first = run(mu, "android-18.3", "oneplus-nord", STEPS)
    assert first["result"] == "reproduced" and "blank" in first["observed"]
    client.post("/sandbox/deploy", json={"service": "order-tracking-service", "version": "5.3.1"})
    assert run(mu, "android-18.3", "oneplus-nord", STEPS)["result"] == "not_reproduced"
    logs = client.get("/logs", params={"env": "sandbox", "user_id": mu}).json()
    assert logs[-1]["response_excerpt"]["schema_version"] == 1


def test_track05_newer_app_copes(setup_user, run):
    mu = setup_user(COHORT, TRACK_CALLS)
    assert run(mu, "android-18.4", "oneplus-nord", STEPS)["result"] == "not_reproduced"


def test_track05_evidence(client):
    assert any(d["deploy_id"] == "DEP-205" and d["version"] == "5.3.0"
               for d in client.get("/deploys", params={"service": "order-tracking-service"}).json())
    assert set(client.get("/impact/app.tracking.eta_type_error").json()["by_app_version"]) == {"18.2", "18.3"}
