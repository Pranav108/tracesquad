def test_get_user(client):
    r = client.get("/users/U-48213")
    assert r.status_code == 200 and r.json()["cohort_id"] == "android-18.5-DEL-G7-gold_annual"


def test_unknown_user_404(client):
    r = client.get("/users/U-00000")
    assert r.status_code == 404 and "U-00000" in r.json()["detail"]


def test_report_hides_scenario(client):
    r = client.get("/reports/RPT-101")
    assert r.status_code == 200 and "scenario_id" not in r.json()


def test_cohort_breakdown(client):
    c = client.get("/cohorts/android-18.5-DEL-G7-gold_annual").json()
    assert c["city"] == {"code": "DEL", "name": "Delhi NCR"} and c["group"] == {"id": "G7", "label": "Gold loyalist"}


def test_bad_cohort_422(client):
    assert client.get("/cohorts/android-18.5-XXX-G7-gold_annual").status_code == 422


def test_logs_window_timezones(client):
    z = client.get("/logs", params={"user_id": "U-48213", "from": "2026-11-04T04:00:00Z", "to": "2026-11-04T05:00:00Z"}).json()
    ist = client.get("/logs", params={"user_id": "U-48213", "from": "2026-11-04T09:30:00+05:30", "to": "2026-11-04T10:30:00+05:30"}).json()
    assert z == ist and any(l["error_signature"] == "membership.stale_status_after_renewal" for l in z)


def test_trace(client):
    assert {l["service"] for l in client.get("/traces/tr-gold01-1").json()} == {"payment-service", "membership-service"}


def test_unknown_trace_404(client):
    assert client.get("/traces/tr-nope").status_code == 404


def test_build_lookup(client):
    assert client.get("/builds/android-18.2").json()["source"] == "github_actions"
    assert client.get("/builds/android-17.9").status_code == 404


def test_admin_scenario_has_rules(client):
    assert client.get("/admin/scenarios/GOLD-01").json()["repro_rules"][0]["rule_id"] == "R-GOLD01"


def test_journey(client):
    events = client.get("/users/U-48213/journey").json()["events"]
    assert any(e["action"] == "tap_renew" for e in events)


def test_impact_and_deploys(client):
    assert client.get("/impact/membership.stale_status_after_renewal").json()["affected_users"] == 1284
    assert [d["deploy_id"] for d in client.get("/deploys", params={"service": "membership-service"}).json()] == ["DEP-201"]
    assert client.get("/impact/nope").status_code == 404


def test_known_bug_and_fix(client):
    assert client.get("/known-bugs/BUG-1180").json()["fixed_in"] == "18.4"
    client.post("/fixes/FIX-GOLD-01/publish")
    assert [f["fix_id"] for f in client.get("/fixes", params={"bug_ref": "RPT-101"}).json()] == ["FIX-GOLD-01"]
    assert client.get("/fixes/FIX-NOPE").status_code == 404


def test_changes_filter(client):
    ids = [c["change_id"] for c in client.get("/changes", params={"repo": "membership-service"}).json()]
    assert ids[0] == "CHG-401"
    ids = [c["change_id"] for c in client.get("/changes", params={"area": "checkout", "since": "2026-10-01"}).json()]
    assert "CHG-411" in ids and "CHG-412" not in ids


def test_threads_search(client):
    found = client.get("/threads", params={"q": "join gold"}).json()
    assert any(t["channel"] == "#gold-support" for t in found)
    assert client.get("/threads", params={"q": "zzz"}).json() == []


def test_prd_and_unknown_404(client):
    assert client.get("/prds/PRD-GOLD-RENEW").json()["owner_team"] == "membership-be"
    r = client.get("/prds/PRD-NOPE")
    assert r.status_code == 404 and "PRD-NOPE" in r.json()["detail"]
    assert {r["release_id"] for r in client.get("/releases").json()} >= {"app-18.6", "hotfix-2026-11-06"}
    assert client.get("/threads/THR-121").json()["channel"] == "#design-reviews"


def test_operator_routes_hidden(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/sandbox/deploy" not in paths and "/fixes/{fix_id}/publish" not in paths
