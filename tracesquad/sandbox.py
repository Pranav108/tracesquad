"""In-memory sandbox: mock users built by setup calls, sandbox service versions, sandbox logs.

This is the only mutable state in the service. It lives in memory and resets on restart
or on POST /sandbox/reset.
"""

import re
from collections import Counter
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from tracesquad.errors import ApiError
from tracesquad.models import Build, LogEntry, Report
from tracesquad.store import DataError, Store, parse_cohort_id


class MockUser(BaseModel):
    mock_user_id: str
    cohort_id: str
    platform: str
    app_version: str
    login: dict[str, str]
    tags: list[str]
    calls: list[dict[str, Any]]


_ATLAS_SUFFIX = re.compile(r"-atlas-\d+$")
# A report id: RPT-123 from the bug tracker, or FB-1a2b3c, which the herald gives a community post.
REPORT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,9}-[A-Za-z0-9]{1,32}$")


def base_version(version: str) -> str:
    """'3.12.0-atlas-2' -> '3.12.0'; other versions unchanged."""
    return _ATLAS_SUFFIX.sub("", version)


class DynamicBuild(Build):
    """A build Atlas produced. Never serialize base_build_id/fixes_scenario to agents."""

    base_build_id: str
    fixes_scenario: str | None = None


def has_tag(tags: list[str], requirement: str) -> bool:
    return any(tag == requirement or tag.startswith(requirement + ":") for tag in tags)


SHARED_PREPROD = "preprod"

# Per-bug limits the API enforces. The prompts break them down (3 runs to reproduce, then a baseline
# and a check for each of 2 fix attempts); the API only holds the totals.
LIMITS = {"fix_attempts": 2, "runs_per_platform": 7, "api_checks": 4}


class PreviewEnv(BaseModel):
    """Pre-prod as one backend fix attempt sees it: shared pre-prod plus that attempt's deploy.

    Each attempt gets its own, like a per-PR preview environment, so attempts and bugs never
    overwrite each other. Never serialize fixes_scenario to agents.
    """

    env: str
    attempt_id: str
    bug_ref: str
    service: str
    version: str
    fixes_scenario: str | None = None


class Sandbox:
    def __init__(self, store: Store):
        self.store = store
        self.reset()

    def reset(self) -> None:
        # reports Triage filed from the community room (POST /reports), next to the prepared ones
        self.filed_reports: dict[str, Report] = {}
        self.users: dict[str, MockUser] = {}
        self.logs: list[LogEntry] = []
        # shared pre-prod: the unfixed baseline; only the operator deploys to it
        self.services: dict[str, str] = dict(self.store.dataset.sandbox_defaults)
        self.preview_envs: dict[str, PreviewEnv] = {}
        # bug_ref -> what it has used: "fix_attempts", "api_checks", "runs:<platform>"
        self.usage: dict[str, Counter] = {}
        self.published_fixes: set[str] = {f.fix_id for f in self.store.dataset.fixes if f.published}
        self.attempts: list[dict[str, Any]] = []
        self.dynamic_builds: dict[str, DynamicBuild] = {}
        self._user_seq = 0
        self._run_seq = 0
        self._attempt_seq = 0
        # Gremlin's writes, keyed by prd / release / thread id and by report id for RCAs
        self.prd_changelog: dict[str, list[dict[str, Any]]] = {}
        self.prd_known_issues: dict[str, list[str]] = {}
        self.release_notes: dict[str, list[str]] = {}
        self.thread_replies: dict[str, list[dict[str, Any]]] = {}
        self.rcas: dict[str, dict[str, Any]] = {}
        self._check_seq = 0

    def report(self, report_id: str) -> Report | None:
        """A prepared report, or one Triage filed from the community room."""
        return self.store.reports.get(report_id) or self.filed_reports.get(report_id)

    def file_report(self, report_id: str, user_id: str, text: str, reporter: str, channel: str, posted_at: datetime) -> Report:
        """File a report posted in the community room, under the id the herald gave it.

        The sandbox replays the user's own account, so the report reproduces whatever is wrong there.
        """
        if not REPORT_ID.match(report_id):
            raise ApiError(422, f"'{report_id}' is not a report id: use the bug= id from the thread, e.g. FB-1a2b3c or RPT-123")
        if self.report(report_id) is not None:
            raise ApiError(409, f"report '{report_id}' is already filed; GET /reports/{report_id}")
        if user_id not in self.store.users:
            raise ApiError(404, f"user '{user_id}' not found")
        scenario_id = next((r.scenario_id for r in self.store.reports.values() if r.user_id == user_id), None)
        if scenario_id is None:
            raise ApiError(422, f"user '{user_id}' has no account history in this sandbox to reproduce against")
        report = Report(
            report_id=report_id, scenario_id=scenario_id, channel=channel, posted_at=posted_at,
            reporter=reporter, user_id=user_id, text=text,
        )
        self.filed_reports[report_id] = report
        return report

    def create_user(self, cohort_id: str) -> MockUser:
        try:
            parts = parse_cohort_id(cohort_id, self.store.dataset.cohort_dimensions)
        except DataError as exc:
            raise ApiError(422, str(exc)) from exc
        self._user_seq += 1
        n = self._user_seq
        params = {"cohort_id": cohort_id}
        user = MockUser(
            mock_user_id=f"MU-{n:04d}",
            cohort_id=cohort_id,
            platform=parts["platform"],
            app_version=parts["app_version"],
            login={"phone": f"+91-90000-0{n:04d}", "otp": "000000"},
            tags=[t.format(**params) for t in self.store.setup_apis["create_user"].adds_tags],
            calls=[{"api": "create_user", "params": params}],
        )
        self.users[user.mock_user_id] = user
        return user

    def get(self, mock_user_id: str) -> MockUser:
        if mock_user_id not in self.users:
            raise ApiError(404, f"mock user '{mock_user_id}' not found")
        return self.users[mock_user_id]

    def apply(self, mock_user_id: str, api_name: str, params: dict[str, Any]) -> MockUser:
        user = self.get(mock_user_id)
        api = self.store.setup_apis.get(api_name)
        if api is None or api_name == "create_user":
            raise ApiError(404, f"setup api '{api_name}' not found; see GET /setup-apis")
        missing = [p for p in api.params if p not in params]
        if missing:
            raise ApiError(422, f"setup api '{api_name}' is missing params: {', '.join(missing)}")
        self._check_values(api_name, list(api.params), params)
        for requirement in api.requires:
            if not has_tag(user.tags, requirement):
                raise ApiError(
                    409, f"missing prerequisite '{requirement}': call {self._provider_of(requirement)} first"
                )
        for tag in (t.format(**params) for t in api.adds_tags):
            if tag not in user.tags:
                user.tags.append(tag)
        user.calls.append({"api": api_name, "params": params})
        return user

    def _check_values(self, api_name: str, names: list[str], params: dict[str, Any]) -> None:
        dims = self.store.dataset.cohort_dimensions
        allowed = {
            "city": list(dims.cities),
            "group": list(dims.groups),
            "plan": [p for p in dims.plans if p != "none"],
            "type": ["upi", "card"],
        }
        for name in names:
            value = params[name]
            if name == "items":
                if not (isinstance(value, list) and value and all(isinstance(i, dict) and "item_id" in i for i in value)):
                    raise ApiError(422, f"setup api '{api_name}': param 'items' must be a non-empty list of {{item_id, qty}}")
            elif not isinstance(value, str) or not value:
                raise ApiError(422, f"setup api '{api_name}': param '{name}' must be a non-empty string")
            elif name in allowed and value not in allowed[name]:
                raise ApiError(
                    422, f"setup api '{api_name}': {name} '{value}' is not one of {', '.join(allowed[name])}"
                )

    def _provider_of(self, requirement: str) -> str:
        for api in self.store.setup_apis.values():
            if any(t.split(":")[0] == requirement for t in api.adds_tags):
                return api.name
        return "the setup api that provides it"

    def deploy(self, service: str, version: str) -> dict[str, str]:
        if service not in self.services:
            raise ApiError(404, f"service '{service}' not found in sandbox; see GET /sandbox/services")
        self.services[service] = version
        return dict(self.services)

    def preview(self, env: str) -> PreviewEnv | None:
        """None for shared pre-prod; 404 for an env that doesn't exist."""
        if env == SHARED_PREPROD:
            return None
        if env not in self.preview_envs:
            known = ", ".join([SHARED_PREPROD, *self.preview_envs]) or SHARED_PREPROD
            raise ApiError(404, f"pre-prod env '{env}' not found; use one of: {known}")
        return self.preview_envs[env]

    def services_in(self, env: str) -> dict[str, str]:
        preview = self.preview(env)
        services = dict(self.services)
        if preview is not None:
            services[preview.service] = preview.version
        return services

    def backend_buggy(self, env: str, service: str, versions: list[str], scenario_id: str) -> bool:
        """Does `service` in `env` still have the scenario's bug? An Atlas deploy keeps the base version
        number (3.12.0-atlas-2), so it fixes the bug only if it is the right fix for that scenario."""
        preview = self.preview(env)
        if preview is not None and preview.service == service:
            return base_version(preview.version) in versions and preview.fixes_scenario != scenario_id
        # shared pre-prod changes only by operator deploys, judged by version alone
        return base_version(self.services.get(service, "")) in versions

    def check_budget(self, bug_ref: str, kind: str, platform: str | None = None) -> None:
        """429 if the bug has used up this budget. Call after validating, before doing the work."""
        key, limit = (f"runs:{platform}", LIMITS["runs_per_platform"]) if kind == "runs" else (kind, LIMITS[kind])
        used = self.usage.get(bug_ref, Counter())[key]
        if used >= limit:
            what = {
                "fix_attempts": f"{limit} fix attempts",
                "api_checks": f"{limit} API checks",
                "runs": f"{limit} app runs on {platform}",
            }[kind]
            raise ApiError(
                429,
                f"budget used up: {bug_ref} has had {what}, the most one bug gets. "
                f"Stop and [REPORT] to Triage with what is known; see GET /budget/{bug_ref}",
            )

    def spend(self, bug_ref: str, kind: str, platform: str | None = None) -> None:
        key = f"runs:{platform}" if kind == "runs" else kind
        self.usage.setdefault(bug_ref, Counter())[key] += 1

    def budget(self, bug_ref: str) -> dict[str, Any]:
        used = self.usage.get(bug_ref, Counter())

        def line(key: str, limit: int) -> dict[str, int]:
            return {"used": used[key], "limit": limit, "left": max(limit - used[key], 0)}

        return {
            "bug_ref": bug_ref,
            "fix_attempts": line("fix_attempts", LIMITS["fix_attempts"]),
            "runs": {p: line(f"runs:{p}", LIMITS["runs_per_platform"]) for p in ("android", "ios")},
            "api_checks": line("api_checks", LIMITS["api_checks"]),
        }

    def next_attempt_no(self) -> int:
        self._attempt_seq += 1
        return self._attempt_seq

    def next_check_id(self) -> str:
        self._check_seq += 1
        return f"CHK-{self._check_seq:04d}"

    def next_run_id(self) -> str:
        self._run_seq += 1
        return f"RUN-{self._run_seq:04d}"
