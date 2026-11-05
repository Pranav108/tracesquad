"""Pydantic models for every record type in the mock dataset."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

Platform = Literal["android", "ios"]
Level = Literal["info", "warn", "error"]
Source = Literal["backend", "client"]


class CohortDimensions(BaseModel):
    platforms: list[str]
    app_versions: list[str]
    cities: dict[str, str]
    groups: dict[str, str]
    plans: list[str]


class Device(BaseModel):
    device_id: str
    model: str
    platform: Platform
    os_version: str
    screen: Literal["small", "regular", "large"]


class Build(BaseModel):
    build_id: str
    platform: Platform
    app_version: str
    source: Literal["s3", "play", "github_actions", "atlas"]
    branch: str
    download_url: str
    ready_in_minutes: int


class SetupApi(BaseModel):
    name: str
    path: str
    params: dict[str, str]
    requires: list[str]
    adds_tags: list[str]


class Team(BaseModel):
    team_id: str
    name: str
    kind: Literal["frontend", "backend"]
    owns: list[str]
    channel: str


class KnownBug(BaseModel):
    bug_id: str
    title: str
    status: Literal["open", "fixed", "wont_fix"]
    layer: Literal["frontend", "backend", "both"]
    affected_platforms: list[str]
    affected_versions: list[str]
    affected_os: list[str] | None = None
    fixed_in: str | None = None
    thread_url: str
    summary: str
    error_signature: str | None = None


class Report(BaseModel):
    report_id: str
    scenario_id: str
    channel: str
    posted_at: datetime
    reporter: str
    user_id: str
    text: str
    attachments: list[str] = []


class User(BaseModel):
    user_id: str
    name: str
    phone: str
    platform: Platform
    app_version: str
    device_id: str
    city: str
    area: str
    group: str
    plan: str
    plan_status: Literal["active", "expired", "none"]
    cohort_id: str
    signup_date: date
    flags: dict[str, str] = {}


class JourneyEvent(BaseModel):
    ts: datetime
    screen: str
    action: str
    params: dict[str, Any] = {}


class Journey(BaseModel):
    user_id: str
    events: list[JourneyEvent]


class LogEntry(BaseModel):
    log_id: str
    ts: datetime
    env: Literal["prod", "sandbox"]
    source: Source
    service: str
    endpoint: str | None = None
    method: str | None = None
    status: int | None = None
    level: Level
    trace_id: str
    user_id: str
    app_version: str | None = None
    message: str
    error_signature: str | None = None
    response_excerpt: dict[str, Any] | None = None


class LogTemplate(BaseModel):
    source: Source
    service: str
    endpoint: str | None = None
    method: str | None = None
    status: int | None = None
    level: Level
    message: str
    error_signature: str | None = None
    response_excerpt: dict[str, Any] | None = None


class Deploy(BaseModel):
    deploy_id: str
    service: str
    version: str
    deployed_at: datetime
    change: str


class Impact(BaseModel):
    error_signature: str
    first_seen: datetime
    affected_users: int
    by_app_version: dict[str, int]
    note: str


class Trigger(BaseModel):
    screen: str
    action: str
    params: dict[str, Any] = {}


class BackendCondition(BaseModel):
    service: str
    versions: list[str]


class ReproRule(BaseModel):
    rule_id: str
    scenario_id: str
    trigger: Trigger
    requires_tags: list[str] = []
    affected_builds: list[str]
    devices: list[str] | None = None
    backend: BackendCondition | None = None
    observed: str
    artifacts: dict[str, str] = {}
    network: list[dict[str, Any]] = []
    sandbox_logs: list[LogTemplate] = []
    sandbox_logs_ok: list[LogTemplate] = []


class Fix(BaseModel):
    fix_id: str
    bug_ref: str
    team_id: str
    layer: Literal["frontend", "backend"]
    title: str
    pr_url: str
    ships_in: str
    # service name (backend) or app screen (frontend) the fix changes
    target: str
    # platforms a frontend fix applies to
    platforms: list[str] = []
    # True for fixes that already shipped before the scenario (visible from the start)
    published: bool = False


class Scenario(BaseModel):
    scenario_id: str
    title: str
    report_id: str
    expected_class: Literal["backend", "frontend", "ui", "duplicate", "both"]
    duplicate_of: str | None = None
    fix_id: str | None = None
    expected_path: list[str]
    unexpected_paths: list[str] = []


class Change(BaseModel):
    change_id: str
    repo: str
    area: str
    platforms: list[str] | None = None
    title: str
    summary: str
    pr_url: str
    team_id: str
    merged_at: datetime
    released_in: str


class ApiResponse(BaseModel):
    status: int
    body: dict[str, Any]


class BuggyWhen(BaseModel):
    versions: list[str]
    app_versions: list[str] | None = None
    tags: list[str] = []


class ApiCheckDef(BaseModel):
    check_def_id: str
    scenario_id: str
    service: str
    method: str
    endpoint: str
    requires_tags: list[str] = []
    missing_response: ApiResponse
    buggy_when: BuggyWhen
    buggy_response: ApiResponse
    ok_response: ApiResponse


class PrdSection(BaseModel):
    heading: str
    body: str


class ChangelogEntry(BaseModel):
    date: date
    change: str
    reason: str
    bug_ref: str | None = None


class Prd(BaseModel):
    prd_id: str
    title: str
    feature: str
    owner_team: str
    status: Literal["live", "in_progress"]
    target_release: str
    summary: str
    sections: list[PrdSection] = []
    known_issues: list[str] = []
    changelog: list[ChangelogEntry] = []


class Release(BaseModel):
    release_id: str
    kind: Literal["app", "backend"]
    version: str
    status: Literal["released", "in_qa", "planned"]
    code_cutoff: date | None = None
    release_date: date | None = None
    notes: list[str] = []


class ThreadMessage(BaseModel):
    author: str
    ts: datetime
    text: str


class Thread(BaseModel):
    thread_id: str
    channel: str
    title: str
    started_at: datetime
    prd_id: str | None = None
    messages: list[ThreadMessage] = []


class Dataset(BaseModel):
    cohort_dimensions: CohortDimensions
    sandbox_defaults: dict[str, str]
    devices: list[Device] = []
    builds: list[Build] = []
    setup_apis: list[SetupApi] = []
    teams: list[Team] = []
    known_bugs: list[KnownBug] = []
    reports: list[Report] = []
    users: list[User] = []
    journeys: list[Journey] = []
    logs: list[LogEntry] = []
    deploys: list[Deploy] = []
    impacts: list[Impact] = []
    repro_rules: list[ReproRule] = []
    fixes: list[Fix] = []
    scenarios: list[Scenario] = []
    changes: list[Change] = []
    api_checks: list[ApiCheckDef] = []
    prds: list[Prd] = []
    releases: list[Release] = []
    threads: list[Thread] = []
    # filled by the loader: scenario_id -> known bug ids defined in that scenario's file
    scenario_known_bugs: dict[str, list[str]] = {}
