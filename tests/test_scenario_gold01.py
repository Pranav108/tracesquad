GOLD = "android-18.5-DEL-G7-gold_annual"
GOLD_CALLS = [("set_address", {"city": "DEL", "area": "Saket"}), ("set_group", {"group": "G7"}),
              ("activate_plan", {"plan": "gold_annual"}), ("renew_plan", {"plan": "gold_annual"})]
HOME = [{"screen": "home", "action": "open"}]


def test_gold01_expected_path(client, setup_user, run):
    mu = setup_user(GOLD, GOLD_CALLS)
    first = run(mu, "android-18.5", "pixel-7", HOME)
    assert first["result"] == "reproduced" and "Join Gold" in first["observed"]
    client.post("/sandbox/deploy", json={"service": "membership-service", "version": "3.12.1"})
    assert run(mu, "android-18.5", "pixel-7", HOME)["result"] == "not_reproduced"
    logs = client.get("/logs", params={"env": "sandbox", "user_id": mu}).json()
    assert logs[-1]["response_excerpt"]["status"] == "active"


def test_gold01_without_renewal(client, setup_user, run):
    mu = setup_user(GOLD, GOLD_CALLS[:3])
    assert run(mu, "android-18.5", "pixel-7", HOME)["result"] == "not_reproduced"
