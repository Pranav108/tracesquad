COHORT = "android-18.2-PNQ-G3-gold_monthly"
CART_CALLS = [("set_address", {"city": "PNQ", "area": "Baner"}), ("set_group", {"group": "G3"}),
              ("activate_plan", {"plan": "gold_monthly"}),
              ("fill_cart", {"restaurant_id": "R-3391", "items": [{"item_id": "I-88", "qty": 1}, {"item_id": "I-91", "qty": 2}]}),
              ("apply_coupon", {"code": "SAVE50"})]
STEPS = [{"screen": "cart", "action": "open"}, {"screen": "checkout", "action": "open"}]


def test_cart02_expected_path(client, setup_user, run):
    assert client.get("/builds/android-18.2").json()["ready_in_minutes"] == 18
    mu = setup_user(COHORT, CART_CALLS)
    r = run("RPT-102", mu, "android-18.2", "redmi-note-10", STEPS)
    assert r["result"] == "reproduced" and "Something went wrong" in r["observed"]
    # the next release candidate still has the bug until Atlas fixes it
    assert run("RPT-102", mu, "android-18.6-rc1", "redmi-note-10", STEPS)["result"] == "reproduced"


def test_cart02_coupon_only_in_journey(client):
    assert "SAVE50" not in client.get("/reports/RPT-102").json()["text"]
    events = client.get("/users/U-77105/journey").json()["events"]
    assert any(e["action"] == "apply_coupon" and e["params"]["code"] == "SAVE50" for e in events)


def test_cart02_without_coupon(client, setup_user, run):
    mu = setup_user(COHORT, CART_CALLS[:4])
    assert run("RPT-102", mu, "android-18.2", "redmi-note-10", STEPS)["result"] == "not_reproduced"


def test_cart02_client_logs(client):
    logs = client.get("/logs", params={"user_id": "U-77105", "source": "client"}).json()
    assert len(logs) == 2 and {l["error_signature"] for l in logs} == {"app.checkout.discount_row_crash"}


def test_cart02_ios_build_with_android_user_422(client, setup_user):
    mu = setup_user(COHORT, CART_CALLS)
    r = client.post("/repro/runs", json={"bug_ref": "RPT-102", "build_id": "ios-18.5", "mock_user_id": mu, "device_id": "iphone-15", "steps": STEPS})
    assert r.status_code == 422
