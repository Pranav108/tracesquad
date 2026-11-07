"""POST /reports: Triage files a community post under the id the herald gave it, so the squad can work it."""

from tests.test_scenario_cart02 import CART_CALLS, COHORT, STEPS

POST = {
    "report_id": "FB-a1b2c3",
    "user_id": "U-77105",
    "text": "Checkout says 'Something went wrong' when I use a coupon",
    "reporter": "priya",
}


def test_a_filed_report_reads_like_any_other(client):
    r = client.post("/reports", json=POST)
    assert r.status_code == 201, r.text
    filed = client.get("/reports/FB-a1b2c3").json()
    assert filed == r.json()
    assert filed["channel"] == "#community" and filed["reporter"] == "priya" and filed["user_id"] == "U-77105"
    assert "scenario_id" not in filed


def test_a_filed_report_reproduces_what_is_wrong_with_the_users_account(client, setup_user, run):
    client.post("/reports", json=POST)
    mu = setup_user(COHORT, CART_CALLS)
    r = run("FB-a1b2c3", mu, "android-18.2", "redmi-note-10", STEPS)
    assert r["result"] == "reproduced" and "Something went wrong" in r["observed"]
    budget = client.get("/budget/FB-a1b2c3").json()
    assert budget["runs"]["android"]["used"] == 1
    assert client.get("/budget/RPT-102").json()["runs"]["android"]["used"] == 0, "each report has its own budget"


def test_filing_refuses_bad_ids_unknown_users_and_repeats(client):
    assert client.post("/reports", json={**POST, "report_id": "RPT-101"}).status_code == 409
    assert client.post("/reports", json={**POST, "report_id": "FB a/b"}).status_code == 422
    assert client.post("/reports", json={**POST, "user_id": "U-00000"}).status_code == 404
    assert client.post("/reports", json=POST).status_code == 201
    assert client.post("/reports", json=POST).status_code == 409


def test_a_reset_forgets_filed_reports(client):
    client.post("/reports", json=POST)
    client.post("/sandbox/reset")
    assert client.get("/reports/FB-a1b2c3").status_code == 404
