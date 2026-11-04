COHORT = "android-18.3-BOM-G2-none"
PAY_CALLS = [("set_address", {"city": "BOM", "area": "Andheri"}), ("set_group", {"group": "G2"}),
             ("add_payment_method", {"type": "upi"}),
             ("fill_cart", {"restaurant_id": "R-1200", "items": [{"item_id": "I-12", "qty": 1}]})]
STEPS = [{"screen": "checkout", "action": "open"}, {"screen": "payment", "action": "pay_upi"}]


def test_pay04_known_bug_matches_user(client):
    bug, user = client.get("/known-bugs/BUG-1152").json(), client.get("/users/U-61540").json()
    device = next(d for d in client.get("/devices").json() if d["device_id"] == user["device_id"])
    assert bug["fixed_in"] == "18.4" and user["app_version"] in bug["affected_versions"] and device["os_version"] in bug["affected_os"]
    assert client.get("/admin/scenarios/PAY-04").json()["scenario"]["duplicate_of"] == "BUG-1152"


def test_pay04_repro_matrix(setup_user, run):
    mu = setup_user(COHORT, PAY_CALLS)
    assert run(mu, "android-18.3", "galaxy-m32", STEPS)["result"] == "reproduced"
    assert run(mu, "android-18.4", "galaxy-m32", STEPS)["result"] == "not_reproduced"
    assert run(mu, "android-18.3", "redmi-note-10", STEPS)["result"] == "not_reproduced"


def test_pay04_fix_record(client):
    assert [f["ships_in"] for f in client.get("/fixes", params={"bug_ref": "BUG-1152"}).json()] == ["android-18.4"]


def test_pay04_signature_in_logs(client):
    sigs = {l["error_signature"] for l in client.get("/logs", params={"user_id": "U-61540"}).json()}
    assert "app.payment.upi_intent_timeout" in sigs
