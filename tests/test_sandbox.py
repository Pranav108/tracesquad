COHORT = "android-18.5-DEL-G7-gold_annual"


def create(client, cohort=COHORT):
    return client.post("/sandbox/users", json={"cohort_id": cohort})


def setup(client, mu, api, params):
    return client.post(f"/sandbox/users/{mu}/setup/{api}", json=params)


def test_sequential_ids_and_login(client):
    a, b = create(client).json(), create(client).json()
    assert (a["mock_user_id"], b["mock_user_id"]) == ("MU-0001", "MU-0002")
    assert a["login"] == {"phone": "+91-90000-00001", "otp": "000000"} and a["platform"] == "android"
    assert a["app_version"] == "18.5" and {"user", f"cohort:{COHORT}"} <= set(a["tags"])


def test_setup_in_order(client):
    mu = create(client).json()["mock_user_id"]
    assert setup(client, mu, "set_address", {"city": "DEL", "area": "Saket"}).status_code == 200
    assert setup(client, mu, "set_group", {"group": "G7"}).status_code == 200
    r = setup(client, mu, "activate_plan", {"plan": "gold_annual"})
    assert r.status_code == 200
    assert {"address:DEL", "group:G7", "plan:gold_annual", "plan_status:active"} <= set(r.json()["tags"])
    assert [c["api"] for c in client.get(f"/sandbox/users/{mu}").json()["calls"]] == ["create_user", "set_address", "set_group", "activate_plan"]


def test_wrong_order_409(client):
    mu = create(client).json()["mock_user_id"]
    r = setup(client, mu, "activate_plan", {"plan": "gold_annual"})
    assert r.status_code == 409 and "address" in r.json()["detail"] and "set_address" in r.json()["detail"]


def test_missing_param_422(client):
    mu = create(client).json()["mock_user_id"]
    r = setup(client, mu, "set_address", {"city": "DEL"})
    assert r.status_code == 422 and "area" in r.json()["detail"]


def test_unknown_mock_user_404(client):
    r = client.get("/sandbox/users/MU-9999")
    assert r.status_code == 404 and "MU-9999" in r.json()["detail"]
    r = setup(client, "MU-9999", "set_group", {"group": "G1"})
    assert r.status_code == 404 and "MU-9999" in r.json()["detail"]


def test_unknown_setup_api_404(client):
    mu = create(client).json()["mock_user_id"]
    assert setup(client, mu, "teleport", {}).status_code == 404


def test_bad_cohort_422(client):
    assert create(client, "android-18.5-XXX-G7-gold_annual").status_code == 422


def test_deploy_and_reset(client):
    client.post("/sandbox/deploy", json={"service": "membership-service", "version": "3.12.1"})
    assert client.get("/sandbox/services").json()["membership-service"] == "3.12.1"
    create(client)
    client.post("/sandbox/reset")
    assert client.get("/sandbox/services").json()["membership-service"] == "3.12.0"
    assert create(client).json()["mock_user_id"] == "MU-0001"
    assert client.get("/logs", params={"env": "sandbox"}).json() == []


def test_deploy_unknown_service_404(client):
    r = client.post("/sandbox/deploy", json={"service": "nope", "version": "1"})
    assert r.status_code == 404 and "nope" in r.json()["detail"]
