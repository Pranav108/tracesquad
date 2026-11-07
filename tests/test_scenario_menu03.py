COHORT = "ios-18.5-BLR-G1-none"
MENU_CALLS = [("set_address", {"city": "BLR", "area": "Indiranagar"}), ("set_group", {"group": "G1"})]


def OPEN(rid):
    return [{"screen": "restaurant", "action": "open", "params": {"restaurant_id": rid}}]


def test_menu03_small_screen(setup_user, run):
    mu = setup_user(COHORT, MENU_CALLS)
    r = run("RPT-103", mu, "ios-18.5", "iphone-se-2", OPEN("R-5520"))
    assert r["result"] == "reproduced" and "overlaps" in r["observed"]


def test_menu03_regular_screen(setup_user, run):
    mu = setup_user(COHORT, MENU_CALLS)
    assert run("RPT-103", mu, "ios-18.5", "iphone-15", OPEN("R-5520"))["result"] == "not_reproduced"


def test_menu03_short_name(setup_user, run):
    mu = setup_user(COHORT, MENU_CALLS)
    assert run("RPT-103", mu, "ios-18.5", "iphone-se-2", OPEN("R-2210"))["result"] == "not_reproduced"


def test_menu03_release_candidate_still_broken(setup_user, run):
    mu = setup_user(COHORT, MENU_CALLS)
    assert run("RPT-103", mu, "ios-18.6-rc1", "iphone-se-2", OPEN("R-5520"))["result"] == "reproduced"


def test_menu03_logs_clean(client):
    logs = client.get("/logs", params={"user_id": "U-23017"}).json()
    assert logs and all(l["level"] == "info" and l["status"] == 200 for l in logs)
    assert client.get("/users/U-23017").json()["device_id"] == "iphone-se-2"
