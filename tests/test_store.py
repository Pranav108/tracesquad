import json
from pathlib import Path

import pytest

from bugmock.store import DATA_DIR, DataError, Store, load_dataset, parse_cohort_id


def base_shared() -> dict:
    return json.loads((DATA_DIR / "shared.json").read_text())


def make_user(**overrides) -> dict:
    user = {
        "user_id": "U-00001",
        "name": "Test User 00001",
        "phone": "+91-90000-01234",
        "platform": "android",
        "app_version": "18.5",
        "device_id": "pixel-7",
        "city": "DEL",
        "area": "Saket",
        "group": "G7",
        "plan": "gold_annual",
        "plan_status": "active",
        "cohort_id": "android-18.5-DEL-G7-gold_annual",
        "signup_date": "2024-01-01",
        "flags": {},
    }
    user.update(overrides)
    return user


def write_dataset(tmp_path: Path, shared: dict, scenarios: dict[str, dict]) -> Path:
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "shared.json").write_text(json.dumps(shared))
    for name, content in scenarios.items():
        (tmp_path / "scenarios" / f"{name}.json").write_text(json.dumps(content))
    return tmp_path


def test_shared_data_loads():
    ds = load_dataset(DATA_DIR)
    assert len(ds.cohort_dimensions.groups) == 10
    assert set(ds.cohort_dimensions.cities) == {"DEL", "BOM", "BLR", "PNQ", "HYD"}
    assert len(ds.setup_apis) == 9 and len(ds.builds) == 8 and len(ds.devices) == 6 and len(ds.teams) == 7


def test_duplicate_id_rejected(tmp_path):
    d = write_dataset(tmp_path, base_shared(), {"A": {"users": [make_user()]}, "B": {"users": [make_user()]}})
    with pytest.raises(DataError, match="U-00001"):
        load_dataset(d)


def test_cohort_mismatch_rejected(tmp_path):
    d = write_dataset(tmp_path, base_shared(), {"A": {"users": [make_user(city="PNQ")]}})
    with pytest.raises(DataError, match="U-00001"):
        load_dataset(d)


def test_unknown_device_rejected(tmp_path):
    d = write_dataset(tmp_path, base_shared(), {"A": {"users": [make_user(device_id="nokia-1")]}})
    with pytest.raises(DataError, match="nokia-1"):
        load_dataset(d)


def test_parse_cohort_id():
    dims = load_dataset(DATA_DIR).cohort_dimensions
    assert parse_cohort_id("android-18.5-DEL-G7-gold_annual", dims) == {
        "platform": "android", "app_version": "18.5", "city": "DEL", "group": "G7", "plan": "gold_annual"}
    with pytest.raises(DataError):
        parse_cohort_id("android-18.5-XXX-G7-gold_annual", dims)


def test_store_indexes_shared_data():
    s = Store(load_dataset(DATA_DIR))
    assert s.builds["android-18.2"].source == "github_actions"
    assert s.setup_apis["place_order"].requires == ["address", "payment_method"]
    assert s.dataset.sandbox_defaults["membership-service"] == "3.12.0"


def test_gold01_records():
    s = Store(load_dataset(DATA_DIR))
    assert s.users["U-48213"].cohort_id == "android-18.5-DEL-G7-gold_annual"
    assert s.reports["RPT-101"].user_id == "U-48213"
    assert s.scenarios["GOLD-01"].expected_class == "backend"
    assert any(l.error_signature == "membership.stale_status_after_renewal" for l in s.logs)
    assert [d.version for d in s.deploys if d.deploy_id == "DEP-201"] == ["3.12.0"]
    assert s.fixes["FIX-GOLD-01"].ships_in == "membership-service@3.12.1"
    assert s.known_bugs["BUG-1180"].status == "fixed"


def test_releases_loaded():
    ds = load_dataset(DATA_DIR)
    assert {r.release_id for r in ds.releases} == {"app-18.5", "app-18.6", "app-18.7", "hotfix-2026-11-06"}


def test_fix_targets():
    s = Store(load_dataset(DATA_DIR))
    assert s.fixes["FIX-GOLD-01"].target == "membership-service"
    assert s.fixes["FIX-TRACK-05"].target == "order-tracking-service"
    assert (s.fixes["FIX-CART-02"].target, s.fixes["FIX-CART-02"].platforms) == ("checkout", ["android", "ios"])
    assert (s.fixes["FIX-MENU-03"].target, s.fixes["FIX-MENU-03"].platforms) == ("restaurant", ["ios"])
    assert (s.fixes["FIX-PAY-04"].target, s.fixes["FIX-PAY-04"].platforms) == ("payment", ["android"])


def test_api_check_service_must_exist(tmp_path):
    check = {
        "check_def_id": "API-X", "scenario_id": "X", "service": "ghost-service", "method": "GET", "endpoint": "/x",
        "requires_tags": [], "missing_response": {"status": 404, "body": {}},
        "buggy_when": {"versions": ["1.0"]}, "buggy_response": {"status": 200, "body": {}},
        "ok_response": {"status": 200, "body": {}},
    }
    d = write_dataset(tmp_path, base_shared(), {"A": {"api_checks": [check]}})
    with pytest.raises(DataError, match="ghost-service"):
        load_dataset(d)
