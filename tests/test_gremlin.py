from test_scenario_gold01 import GOLD, GOLD_CALLS

RCA = {"bug_ref": "RPT-101", "title": "Gold status stale after renewal", "what_happened": "Renewed members saw Join Gold.",
       "root_cause": "Status cache was not cleared on renewal.", "culprit_change_id": "CHG-401",
       "fix": {"pr_url": "https://git.example.invalid/membership-service/pull/7001", "preprod": {"env": "preprod-atl-0001", "service": "membership-service", "version": "3.12.0-atlas-1"}},
       "verification": {"check_id": "CHK-0002"}, "impact": "1284 users", "follow_ups": ["Alert on stale status"]}


def test_prd_update_and_known_issue(client):
    r = client.post("/prds/PRD-GOLD-RENEW/updates", json={"change": "Renewal clears the status cache", "reason": "Bug fix",
                                                          "bug_ref": "RPT-101", "known_issue": "Renewals between 2 and 5 Nov showed stale status"})
    assert r.status_code == 200
    prd = client.get("/prds/PRD-GOLD-RENEW").json()
    assert prd["changelog"][-1]["bug_ref"] == "RPT-101" and prd["changelog"][-1]["change"] == "Renewal clears the status cache"
    assert prd["known_issues"] == ["Renewals between 2 and 5 Nov showed stale status"]


def test_release_note_and_thread_reply(client):
    assert client.post("/releases/hotfix-2026-11-06/notes", json={"bug_ref": "RPT-101", "note": "Gold status fix"}).status_code == 200
    assert "Gold status fix" in next(r for r in client.get("/releases").json() if r["release_id"] == "hotfix-2026-11-06")["notes"]
    assert client.post("/threads/THR-101/replies", json={"bug_ref": "RPT-101", "text": "Fixed in pre-prod"}).status_code == 200
    last = client.get("/threads/THR-101").json()["messages"][-1]
    assert last["author"] == "Gremlin" and last["text"] == "Fixed in pre-prod"


def test_rca_roundtrip(client):
    assert client.post("/rca", json=RCA).status_code == 200
    got = client.get("/rca/RPT-101").json()
    assert {k: got[k] for k in RCA} == RCA


def test_gremlin_unknown_ids_404(client):
    for r, needle in [
        (client.post("/prds/PRD-NOPE/updates", json={"change": "x", "reason": "y", "bug_ref": "RPT-101"}), "PRD-NOPE"),
        (client.post("/releases/app-99/notes", json={"bug_ref": "RPT-101", "note": "x"}), "app-99"),
        (client.post("/threads/THR-999/replies", json={"bug_ref": "RPT-101", "text": "x"}), "THR-999"),
        (client.post("/rca", json={**RCA, "bug_ref": "RPT-999"}), "RPT-999"),
        (client.get("/rca/RPT-102"), "RPT-102"),
    ]:
        assert r.status_code == 404 and needle in r.json()["detail"]


def test_reset_clears_fix_loop_state(client, setup_user):
    mu = setup_user(GOLD, GOLD_CALLS)
    client.post("/atlas/fixes", json={"bug_ref": "RPT-101", "layer": "backend", "target": "membership-service",
                                      "culprit_change_id": "CHG-401", "summary": "x"})
    client.post("/api-checks", json={"bug_ref": "RPT-101", "env": "preprod", "mock_user_id": mu, "method": "GET", "endpoint": "/v2/membership/status"})
    client.post("/prds/PRD-GOLD-RENEW/updates", json={"change": "c", "reason": "r", "bug_ref": "RPT-101", "known_issue": "k"})
    client.post("/releases/hotfix-2026-11-06/notes", json={"bug_ref": "RPT-101", "note": "n"})
    client.post("/threads/THR-101/replies", json={"bug_ref": "RPT-101", "text": "t"})
    client.post("/rca", json=RCA)
    client.post("/sandbox/reset")
    assert client.get("/prds/PRD-GOLD-RENEW").json()["known_issues"] == []
    assert len(client.get("/threads/THR-101").json()["messages"]) == 3
    assert client.get("/rca/RPT-101").status_code == 404 and client.get("/fixes", params={"bug_ref": "RPT-101"}).json() == []
    assert client.get("/sandbox/services").json()["membership-service"] == "3.12.0"
    mu = setup_user(GOLD, GOLD_CALLS)
    attempt = client.post("/atlas/fixes", json={"bug_ref": "RPT-101", "layer": "backend", "target": "membership-service",
                                                "culprit_change_id": "CHG-401", "summary": "x"}).json()
    chk = client.post("/api-checks", json={"bug_ref": "RPT-101", "env": "preprod", "mock_user_id": mu, "method": "GET", "endpoint": "/v2/membership/status"}).json()
    assert attempt["attempt_id"] == "ATL-0001" and chk["check_id"] == "CHK-0001"
