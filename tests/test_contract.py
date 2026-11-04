import pytest


def test_all_five_scenarios(client):
    got = {s["scenario_id"]: s["expected_class"] for s in client.get("/admin/scenarios").json()}
    assert got == {"GOLD-01": "backend", "CART-02": "frontend", "MENU-03": "ui", "PAY-04": "duplicate", "TRACK-05": "both"}


AGENT_PATHS = ["/reports/RPT-101", "/reports/RPT-105", "/users/U-90877", "/users/U-77105/journey", "/known-bugs",
               "/logs?user_id=U-77105", "/deploys", "/builds", "/setup-apis", "/teams", "/fixes", "/devices"]


@pytest.mark.parametrize("path", AGENT_PATHS)
def test_agent_routes_do_not_leak(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "scenario_id" not in r.text and "expected_" not in r.text and "rule_id" not in r.text
