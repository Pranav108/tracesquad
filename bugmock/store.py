"""Load, merge, validate and index the JSON mock data (read-only)."""

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from bugmock.models import CohortDimensions, Dataset

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SINGLE_KEYS = ("cohort_dimensions", "sandbox_defaults")

# collection name -> the field that identifies a record in it
ID_FIELDS = {
    "devices": "device_id",
    "builds": "build_id",
    "setup_apis": "name",
    "teams": "team_id",
    "known_bugs": "bug_id",
    "reports": "report_id",
    "users": "user_id",
    "journeys": "user_id",
    "logs": "log_id",
    "deploys": "deploy_id",
    "impacts": "error_signature",
    "repro_rules": "rule_id",
    "fixes": "fix_id",
    "scenarios": "scenario_id",
    "changes": "change_id",
    "api_checks": "check_def_id",
    "prds": "prd_id",
    "releases": "release_id",
    "threads": "thread_id",
}


class DataError(Exception):
    """The JSON data is malformed or internally inconsistent."""


def parse_cohort_id(cohort_id: str, dims: CohortDimensions) -> dict[str, str]:
    parts = cohort_id.split("-")
    if len(parts) != 5:
        raise DataError(f"cohort_id '{cohort_id}' must have 5 parts: platform-app_version-city-group-plan")
    platform, app_version, city, group, plan = parts
    checks = [
        ("platform", platform, dims.platforms),
        ("app_version", app_version, dims.app_versions),
        ("city", city, dims.cities),
        ("group", group, dims.groups),
        ("plan", plan, dims.plans),
    ]
    for name, value, allowed in checks:
        if value not in allowed:
            raise DataError(f"cohort_id '{cohort_id}': unknown {name} '{value}'")
    return {"platform": platform, "app_version": app_version, "city": city, "group": group, "plan": plan}


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise DataError(f"{path.name}: invalid JSON ({exc})") from exc


def load_dataset(data_dir: Path) -> Dataset:
    files = [data_dir / "shared.json"]
    scenario_dir = data_dir / "scenarios"
    if scenario_dir.is_dir():
        files += sorted(scenario_dir.glob("*.json"))

    merged: dict[str, Any] = {key: [] for key in ID_FIELDS}
    scenario_known_bugs: dict[str, list[str]] = {}
    for path in files:
        content = _read(path)
        for key, value in content.items():
            if key in SINGLE_KEYS:
                if key in merged:
                    raise DataError(f"{key} defined more than once (again in {path.name})")
                merged[key] = value
            elif key in ID_FIELDS:
                merged[key].extend(value)
            else:
                raise DataError(f"{path.name}: unknown top-level key '{key}'")
        for scenario in content.get("scenarios", []):
            scenario_known_bugs[scenario["scenario_id"]] = [b["bug_id"] for b in content.get("known_bugs", [])]
    for key in SINGLE_KEYS:
        if key not in merged:
            raise DataError(f"{key} missing from shared.json")
    merged["scenario_known_bugs"] = scenario_known_bugs

    try:
        dataset = Dataset.model_validate(merged)
    except ValidationError as exc:
        raise DataError(str(exc)) from exc
    _check_integrity(dataset)
    return dataset


def _check_integrity(ds: Dataset) -> None:
    for key, id_field in ID_FIELDS.items():
        seen: set[str] = set()
        for record in getattr(ds, key):
            record_id = getattr(record, id_field)
            if record_id in seen:
                raise DataError(f"duplicate {id_field} '{record_id}' in {key}")
            seen.add(record_id)

    devices = {d.device_id: d for d in ds.devices}
    users = {u.user_id for u in ds.users}
    reports = {r.report_id for r in ds.reports}
    known_bugs = {b.bug_id for b in ds.known_bugs}
    fixes = {f.fix_id for f in ds.fixes}
    teams = {t.team_id for t in ds.teams}
    builds = {b.build_id for b in ds.builds}

    for u in ds.users:
        expected = f"{u.platform}-{u.app_version}-{u.city}-{u.group}-{u.plan}"
        if u.cohort_id != expected:
            raise DataError(f"user {u.user_id}: cohort_id '{u.cohort_id}' does not match profile ('{expected}')")
        try:
            parse_cohort_id(u.cohort_id, ds.cohort_dimensions)
        except DataError as exc:
            raise DataError(f"user {u.user_id}: {exc}") from exc
        device = devices.get(u.device_id)
        if device is None:
            raise DataError(f"user {u.user_id}: unknown device_id '{u.device_id}'")
        if device.platform != u.platform:
            raise DataError(f"user {u.user_id}: device '{u.device_id}' is {device.platform}, user is {u.platform}")

    def need(value: str | None, pool: set[str], what: str) -> None:
        if value is not None and value not in pool:
            raise DataError(f"{what} refers to unknown id '{value}'")

    for r in ds.reports:
        need(r.user_id, users, f"report {r.report_id}")
    for j in ds.journeys:
        need(j.user_id, users, f"journey of {j.user_id}")
    for log in ds.logs:
        if log.env == "prod":
            need(log.user_id, users, f"log {log.log_id}")
    for s in ds.scenarios:
        need(s.report_id, reports, f"scenario {s.scenario_id} report_id")
        need(s.fix_id, fixes, f"scenario {s.scenario_id} fix_id")
        need(s.duplicate_of, known_bugs, f"scenario {s.scenario_id} duplicate_of")
    for f in ds.fixes:
        need(f.team_id, teams, f"fix {f.fix_id} team_id")
        need(f.bug_ref, known_bugs | reports, f"fix {f.fix_id} bug_ref")
    services = set(ds.sandbox_defaults)
    scenarios = {s.scenario_id for s in ds.scenarios}
    prds = {p.prd_id for p in ds.prds}
    for f in ds.fixes:
        if f.layer == "backend":
            need(f.target, services, f"fix {f.fix_id} target")
    for c in ds.changes:
        need(c.team_id, teams, f"change {c.change_id} team_id")
    for chk in ds.api_checks:
        need(chk.service, services, f"api check {chk.check_def_id} service")
        need(chk.scenario_id, scenarios, f"api check {chk.check_def_id} scenario_id")
    for prd in ds.prds:
        need(prd.owner_team, teams, f"prd {prd.prd_id} owner_team")
    for t in ds.threads:
        need(t.prd_id, prds, f"thread {t.thread_id} prd_id")
    for rule in ds.repro_rules:
        for build_id in rule.affected_builds:
            if build_id != "*":
                need(build_id, builds, f"repro rule {rule.rule_id} affected_builds")
        for device_id in rule.devices or []:
            need(device_id, set(devices), f"repro rule {rule.rule_id} devices")


class Store:
    """Read-only indexes over a validated Dataset."""

    def __init__(self, dataset: Dataset):
        self.dataset = dataset
        self.users = {u.user_id: u for u in dataset.users}
        self.reports = {r.report_id: r for r in dataset.reports}
        self.known_bugs = {b.bug_id: b for b in dataset.known_bugs}
        self.journeys = {j.user_id: j for j in dataset.journeys}
        self.builds = {b.build_id: b for b in dataset.builds}
        self.devices = {d.device_id: d for d in dataset.devices}
        self.setup_apis = {a.name: a for a in dataset.setup_apis}
        self.teams = {t.team_id: t for t in dataset.teams}
        self.fixes = {f.fix_id: f for f in dataset.fixes}
        self.scenarios = {s.scenario_id: s for s in dataset.scenarios}
        self.impacts = {i.error_signature: i for i in dataset.impacts}
        self.logs = list(dataset.logs)
        self.deploys = list(dataset.deploys)
        self.repro_rules = list(dataset.repro_rules)
        self.changes = {c.change_id: c for c in dataset.changes}
        self.api_checks = {(c.method.upper(), c.endpoint): c for c in dataset.api_checks}
        self.prds = {p.prd_id: p for p in dataset.prds}
        self.releases = {r.release_id: r for r in dataset.releases}
        self.threads = {t.thread_id: t for t in dataset.threads}
