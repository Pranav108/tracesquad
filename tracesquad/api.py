"""FastAPI app serving the mock data, with routes grouped by the agent that uses them."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Body, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tracesquad.atlas import FixRequest, submit_fix
from tracesquad.checks import CheckRequest, run_api_check
from tracesquad.errors import ApiError
from tracesquad.models import LogEntry
from tracesquad.repro import ReproRequest, run_repro
from tracesquad.sandbox import Sandbox
from tracesquad.store import DATA_DIR, DataError, Store, load_dataset, parse_cohort_id


def _store(request: Request) -> Store:
    return request.app.state.store


def _get(index: dict, key: str, what: str):
    if key not in index:
        raise ApiError(404, f"{what} '{key}' not found")
    return index[key]


def _parse_time(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    # An unencoded "+05:30" in a query string arrives as " 05:30"; put the plus back.
    text = value.strip().replace(" ", "+")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ApiError(422, f"'{name}' is not an ISO 8601 time: '{value}'") from exc
    if parsed.tzinfo is None:
        raise ApiError(422, f"'{name}' needs a timezone offset, e.g. 2026-11-04T04:00:00Z or +05:30")
    return parsed


def _sandbox_logs(request: Request) -> list[LogEntry]:
    sandbox = getattr(request.app.state, "sandbox", None)
    return list(sandbox.logs) if sandbox is not None else []


triage = APIRouter(tags=["Triage: reports, known bugs, users, journeys, cohorts"])
espida = APIRouter(tags=["Espida: logs, traces, deploys, impact"])
telios = APIRouter(tags=["Telios: builds and setup API catalog"])
teams = APIRouter(tags=["Teams: owners and fixes"])
admin = APIRouter(
    prefix="/admin", tags=["Admin: scenarios with expected answers (not for agents)"], include_in_schema=False
)


@triage.get("/reports/{report_id}", summary="A Slack bug report")
def get_report(report_id: str, request: Request) -> dict[str, Any]:
    report = _get(_store(request).reports, report_id, "report")
    return report.model_dump(mode="json", exclude={"scenario_id"})


@triage.get("/known-bugs", summary="All bugs already in the bug database")
def list_known_bugs(request: Request) -> list[dict[str, Any]]:
    return [b.model_dump(mode="json") for b in _store(request).known_bugs.values()]


@triage.get("/known-bugs/{bug_id}", summary="One known bug")
def get_known_bug(bug_id: str, request: Request) -> dict[str, Any]:
    return _get(_store(request).known_bugs, bug_id, "known bug").model_dump(mode="json")


@triage.get("/users/{user_id}", summary="A real user's profile: platform, app version, device, city, group, plan, cohort")
def get_user(user_id: str, request: Request) -> dict[str, Any]:
    return _get(_store(request).users, user_id, "user").model_dump(mode="json")


@triage.get("/users/{user_id}/journey", summary="What the user did in the app, in order")
def get_journey(user_id: str, request: Request) -> dict[str, Any]:
    store = _store(request)
    _get(store.users, user_id, "user")
    return _get(store.journeys, user_id, "journey for user").model_dump(mode="json")


@triage.get("/cohorts/{cohort_id}", summary="Break a cohort id into its labelled parts")
def get_cohort(cohort_id: str, request: Request) -> dict[str, Any]:
    dims = _store(request).dataset.cohort_dimensions
    try:
        parts = parse_cohort_id(cohort_id, dims)
    except DataError as exc:
        raise ApiError(422, str(exc)) from exc
    return {
        "cohort_id": cohort_id,
        "platform": parts["platform"],
        "app_version": parts["app_version"],
        "city": {"code": parts["city"], "name": dims.cities[parts["city"]]},
        "group": {"id": parts["group"], "label": dims.groups[parts["group"]]},
        "plan": parts["plan"],
    }


@espida.get("/logs", summary="Backend and client logs, filtered; env=prod (default) or env=sandbox")
def get_logs(
    request: Request,
    user_id: str | None = None,
    env: Literal["prod", "sandbox"] = "prod",
    source: Literal["backend", "client"] | None = None,
    service: str | None = None,
    from_raw: str | None = Query(None, alias="from", description="ISO 8601 with offset, e.g. 2026-11-04T04:00:00Z"),
    to_raw: str | None = Query(None, alias="to", description="ISO 8601 with offset, e.g. 2026-11-04T05:00:00Z"),
) -> list[dict[str, Any]]:
    from_, to = _parse_time(from_raw, "from"), _parse_time(to_raw, "to")
    entries = _store(request).logs if env == "prod" else _sandbox_logs(request)
    selected = [
        e for e in entries
        if e.env == env
        and (user_id is None or e.user_id == user_id)
        and (source is None or e.source == source)
        and (service is None or e.service == service)
        and (from_ is None or e.ts >= from_)
        and (to is None or e.ts <= to)
    ]
    return [e.model_dump(mode="json") for e in sorted(selected, key=lambda e: e.ts)]


@espida.get("/traces/{trace_id}", summary="Every log line (prod and sandbox) for one trace")
def get_trace(trace_id: str, request: Request) -> list[dict[str, Any]]:
    entries = [e for e in _store(request).logs + _sandbox_logs(request) if e.trace_id == trace_id]
    if not entries:
        raise ApiError(404, f"trace '{trace_id}' not found")
    return [e.model_dump(mode="json") for e in sorted(entries, key=lambda e: e.ts)]


@espida.get("/deploys", summary="Prod deploys, optionally for one service")
def get_deploys(request: Request, service: str | None = None) -> list[dict[str, Any]]:
    deploys = [d for d in _store(request).deploys if service is None or d.service == service]
    return [d.model_dump(mode="json") for d in sorted(deploys, key=lambda d: d.deployed_at)]


@espida.get("/impact/{error_signature}", summary="How many users hit an error signature, by app version")
def get_impact(error_signature: str, request: Request) -> dict[str, Any]:
    return _get(_store(request).impacts, error_signature, "error signature").model_dump(mode="json")


@telios.get("/builds", summary="Every app build that can be fetched")
def list_builds(request: Request) -> list[dict[str, Any]]:
    static = [b.model_dump(mode="json") for b in _store(request).builds.values()]
    return static + [_dynamic_build_view(b) for b in _sandbox(request).dynamic_builds.values()]


@telios.get("/builds/{build_id}", summary="One build, e.g. android-18.2: where it comes from and its download URL")
def get_build(build_id: str, request: Request) -> dict[str, Any]:
    dynamic = _sandbox(request).dynamic_builds.get(build_id)
    if dynamic is not None:
        return _dynamic_build_view(dynamic)
    return _get(_store(request).builds, build_id, "build").model_dump(mode="json")


def _dynamic_build_view(build) -> dict[str, Any]:
    # never reveal which scenario (if any) an Atlas build fixes
    return build.model_dump(mode="json", exclude={"base_build_id", "fixes_scenario"})


@telios.get("/setup-apis", summary="Catalog of sandbox setup APIs: params, prerequisites, tags they add")
def list_setup_apis(request: Request) -> list[dict[str, Any]]:
    return [a.model_dump(mode="json") for a in _store(request).setup_apis.values()]


@teams.get("/teams", summary="Teams and what each one owns")
def list_teams(request: Request) -> list[dict[str, Any]]:
    return [t.model_dump(mode="json") for t in _store(request).teams.values()]


def _published(request: Request) -> set[str]:
    return request.app.state.sandbox.published_fixes


_HIDDEN_FIX_FIELDS = {"published", "target", "platforms", "culprit_change_id"}


@teams.get("/fixes", summary="Atlas fix attempts and already-published fixes, optionally for one bug (known bug id or report id)")
def list_fixes(request: Request, bug_ref: str | None = None) -> list[dict[str, Any]]:
    published = _published(request)
    fixes = [
        f.model_dump(mode="json", exclude=_HIDDEN_FIX_FIELDS) for f in _store(request).fixes.values()
        if f.fix_id in published and (bug_ref is None or f.bug_ref == bug_ref)
    ]
    attempts = [dict(a) for a in _sandbox(request).attempts if bug_ref is None or a["bug_ref"] == bug_ref]
    return fixes + attempts


@teams.get("/fixes/{fix_id}", summary="One fix: an Atlas attempt (ATL-…) or a published fix")
def get_fix(fix_id: str, request: Request) -> dict[str, Any]:
    for attempt in _sandbox(request).attempts:
        if attempt["attempt_id"] == fix_id:
            return dict(attempt)
    if fix_id not in _published(request):
        raise ApiError(404, f"fix '{fix_id}' not found (or not published yet)")
    return _store(request).fixes[fix_id].model_dump(mode="json", exclude=_HIDDEN_FIX_FIELDS)


@teams.post("/fixes/{fix_id}/publish", summary="Operator: announce a fix so agents can see it", include_in_schema=False)
def publish_fix(fix_id: str, request: Request) -> dict[str, Any]:
    fix = _get(_store(request).fixes, fix_id, "fix")
    _published(request).add(fix_id)
    return fix.model_dump(mode="json", exclude={"published"})


sandbox_routes = APIRouter(prefix="/sandbox", tags=["Telios: sandbox mock users; Teams: sandbox deploys"])


class CreateMockUser(BaseModel):
    cohort_id: str


class DeployRequest(BaseModel):
    service: str
    version: str


def _sandbox(request: Request) -> Sandbox:
    return request.app.state.sandbox


@sandbox_routes.post("/users", summary="Create a mock user for a cohort (setup api create_user)")
def create_mock_user(body: CreateMockUser, request: Request) -> dict[str, Any]:
    return _sandbox(request).create_user(body.cohort_id).model_dump()


@sandbox_routes.post(
    "/users/{mock_user_id}/setup/{api_name}",
    summary="Run one setup api on a mock user; body is that api's params (see GET /setup-apis)",
)
def apply_setup(mock_user_id: str, api_name: str, request: Request, params: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return _sandbox(request).apply(mock_user_id, api_name, params).model_dump()


@sandbox_routes.get("/users/{mock_user_id}", summary="A mock user: login, tags (its state) and the setup calls made")
def get_mock_user(mock_user_id: str, request: Request) -> dict[str, Any]:
    return _sandbox(request).get(mock_user_id).model_dump()


@sandbox_routes.post(
    "/deploy", summary="Operator: deploy a service version to shared pre-prod", include_in_schema=False
)
def deploy(body: DeployRequest, request: Request) -> dict[str, str]:
    return _sandbox(request).deploy(body.service, body.version)


@sandbox_routes.get(
    "/services",
    summary="Service versions in pre-prod: shared (env=preprod, the default) or one backend fix attempt's env",
)
def get_services(request: Request, env: str = "preprod") -> dict[str, str]:
    return _sandbox(request).services_in(env)


@sandbox_routes.post(
    "/reset",
    summary="Admin: clear mock users, sandbox logs, service versions, pre-prod envs and budgets",
    include_in_schema=False,
)
def reset_sandbox(request: Request) -> dict[str, bool]:
    _sandbox(request).reset()
    return {"reset": True}


atlas_routes = APIRouter(tags=["Atlas: recent changes and fixes"])
gremlin = APIRouter(tags=["Gremlin: PRDs, releases, threads, RCA"])


@atlas_routes.get("/changes", summary="Recently merged PRs, newest first; filter by repo, area or since (YYYY-MM-DD)")
def list_changes(
    request: Request, repo: str | None = None, area: str | None = None, since: date | None = None
) -> list[dict[str, Any]]:
    changes = [
        c for c in _store(request).changes.values()
        if (repo is None or c.repo == repo)
        and (area is None or c.area == area)
        and (since is None or c.merged_at.date() >= since)
    ]
    return [c.model_dump(mode="json") for c in sorted(changes, key=lambda c: c.merged_at, reverse=True)]


@atlas_routes.post("/atlas/fixes", summary="Submit a fix: opens a PR and returns new builds on the next release candidate, one per platform (frontend), or a deploy to its own pre-prod env (backend). At most 2 per bug")
def post_atlas_fix(body: FixRequest, request: Request) -> dict[str, Any]:
    return submit_fix(body, _store(request), _sandbox(request))


@gremlin.get("/prds", summary="All PRDs")
def list_prds(request: Request) -> list[dict[str, Any]]:
    return [_prd_view(request, p) for p in _store(request).prds.values()]


@gremlin.get("/prds/{prd_id}", summary="One PRD with its sections, known issues and changelog")
def get_prd(prd_id: str, request: Request) -> dict[str, Any]:
    return _prd_view(request, _get(_store(request).prds, prd_id, "prd"))


@gremlin.get("/releases", summary="App releases and the backend hotfix train")
def list_releases(request: Request) -> list[dict[str, Any]]:
    return [_release_view(request, r) for r in _store(request).releases.values()]


@gremlin.get("/threads", summary="Threads in other channels; q searches titles and messages")
def list_threads(request: Request, q: str | None = None) -> list[dict[str, Any]]:
    views = [_thread_view(request, t) for t in _store(request).threads.values()]
    if q:
        needle = q.lower()
        views = [v for v in views if needle in v["title"].lower() or any(needle in m["text"].lower() for m in v["messages"])]
    return views


@gremlin.get("/threads/{thread_id}", summary="One thread with all its messages")
def get_thread(thread_id: str, request: Request) -> dict[str, Any]:
    return _thread_view(request, _get(_store(request).threads, thread_id, "thread"))


def _prd_view(request: Request, prd) -> dict[str, Any]:
    view = prd.model_dump(mode="json")
    sandbox = _sandbox(request)
    view["changelog"] += sandbox.prd_changelog.get(prd.prd_id, [])
    view["known_issues"] += sandbox.prd_known_issues.get(prd.prd_id, [])
    return view


def _release_view(request: Request, release) -> dict[str, Any]:
    view = release.model_dump(mode="json")
    view["notes"] += _sandbox(request).release_notes.get(release.release_id, [])
    return view


def _thread_view(request: Request, thread) -> dict[str, Any]:
    view = thread.model_dump(mode="json")
    view["messages"] += _sandbox(request).thread_replies.get(thread.thread_id, [])
    return view


class PrdUpdate(BaseModel):
    change: str
    reason: str
    bug_ref: str
    known_issue: str | None = None


class ReleaseNote(BaseModel):
    bug_ref: str
    note: str


class ThreadReply(BaseModel):
    bug_ref: str
    text: str


class Rca(BaseModel):
    bug_ref: str
    title: str
    what_happened: str
    root_cause: str
    culprit_change_id: str
    fix: dict[str, Any]
    verification: dict[str, Any]
    impact: str
    follow_ups: list[str] = []


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


@gremlin.post("/prds/{prd_id}/updates", summary="Add a changelog entry (and optionally a known issue) to a PRD")
def post_prd_update(prd_id: str, body: PrdUpdate, request: Request) -> dict[str, Any]:
    prd = _get(_store(request).prds, prd_id, "prd")
    sandbox = _sandbox(request)
    entry = {"date": _now_ist().date().isoformat(), "change": body.change, "reason": body.reason, "bug_ref": body.bug_ref}
    sandbox.prd_changelog.setdefault(prd_id, []).append(entry)
    if body.known_issue:
        sandbox.prd_known_issues.setdefault(prd_id, []).append(body.known_issue)
    return _prd_view(request, prd)


@gremlin.post("/releases/{release_id}/notes", summary="Add a note to a release (e.g. which fix it carries)")
def post_release_note(release_id: str, body: ReleaseNote, request: Request) -> dict[str, Any]:
    release = _get(_store(request).releases, release_id, "release")
    _sandbox(request).release_notes.setdefault(release_id, []).append(body.note)
    return _release_view(request, release)


@gremlin.post("/threads/{thread_id}/replies", summary="Reply in a thread in another channel")
def post_thread_reply(thread_id: str, body: ThreadReply, request: Request) -> dict[str, Any]:
    thread = _get(_store(request).threads, thread_id, "thread")
    reply = {"author": "Gremlin", "ts": _now_ist().isoformat(), "text": body.text}
    _sandbox(request).thread_replies.setdefault(thread_id, []).append(reply)
    return _thread_view(request, thread)


@gremlin.post("/rca", summary="Store the final RCA for a bug (report id)")
def post_rca(body: Rca, request: Request) -> dict[str, Any]:
    _get(_store(request).reports, body.bug_ref, "report")
    rca = body.model_dump(mode="json")
    _sandbox(request).rcas[body.bug_ref] = rca
    return rca


@gremlin.get("/rca/{bug_ref}", summary="The final RCA for a bug, once Gremlin has written it")
def get_rca(bug_ref: str, request: Request) -> dict[str, Any]:
    return dict(_get(_sandbox(request).rcas, bug_ref, "rca for report"))


kinetics = APIRouter(tags=["Kinetics: devices, repro runs and API checks"])


@kinetics.get("/devices", summary="Devices Kinetics can run builds on")
def list_devices(request: Request) -> list[dict[str, Any]]:
    return [d.model_dump(mode="json") for d in _store(request).devices.values()]


@kinetics.post("/repro/runs", summary="For one bug: install a build on a device, log in as a mock user, follow the steps")
def post_repro_run(body: ReproRequest, request: Request) -> dict[str, Any]:
    return run_repro(body, _store(request), _sandbox(request)).model_dump()


@kinetics.post("/api-checks", summary="For one bug: call a backend endpoint on a pre-prod env as a mock user (to verify a backend fix)")
def post_api_check(body: CheckRequest, request: Request) -> dict[str, Any]:
    return run_api_check(body, _store(request), _sandbox(request))


budget = APIRouter(tags=["Everyone: per-bug budgets"])


@budget.get("/budget/{bug_ref}", summary="What one bug has used of its budget: fix attempts, app runs per platform, API checks")
def get_budget(bug_ref: str, request: Request) -> dict[str, Any]:
    _get(_store(request).reports, bug_ref, "report")
    return _sandbox(request).budget(bug_ref)


@admin.get("/scenarios", summary="All scenarios with expected class and path")
def list_scenarios(request: Request) -> list[dict[str, Any]]:
    return [s.model_dump(mode="json") for s in _store(request).scenarios.values()]


@admin.get("/scenarios/{scenario_id}", summary="One scenario with every record it uses, including repro rules")
def get_scenario(scenario_id: str, request: Request) -> dict[str, Any]:
    store = _store(request)
    scenario = _get(store.scenarios, scenario_id, "scenario")
    report = store.reports[scenario.report_id]
    fix_refs = {report.report_id, scenario.duplicate_of}
    fixes = [f for f in store.fixes.values() if f.fix_id == scenario.fix_id or f.bug_ref in fix_refs]
    known = store.dataset.scenario_known_bugs.get(scenario_id, [])
    return {
        "scenario": scenario.model_dump(mode="json"),
        "report": report.model_dump(mode="json"),
        "user": store.users[report.user_id].model_dump(mode="json"),
        "logs": [e.model_dump(mode="json") for e in store.logs if e.user_id == report.user_id],
        "repro_rules": [r.model_dump(mode="json") for r in store.repro_rules if r.scenario_id == scenario_id],
        "fixes": [f.model_dump(mode="json") for f in fixes],
        "known_bugs": [store.known_bugs[b].model_dump(mode="json") for b in known],
    }


SERVICE = "tracesquad-api"


def create_app(data_dir: Path = DATA_DIR) -> FastAPI:
    app = FastAPI(
        title="TraceSquad API",
        description="Mock world for the TraceSquad bug agents: Triage, Telios, Kinetics, Espida, Atlas and Gremlin.",
        version="0.1.0",
    )
    app.state.store = Store(load_dataset(data_dir))
    app.state.sandbox = Sandbox(app.state.store)

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    # The client (bin/tsq) probes this to tell the TraceSquad API apart from whatever else answers on a URL.
    @app.get("/health", summary="Liveness: which service this is", tags=["Everyone: health"])
    def health() -> dict[str, str]:
        return {"service": SERVICE, "status": "ok"}

    for router in (triage, espida, telios, sandbox_routes, kinetics, atlas_routes, gremlin, teams, budget, admin):
        app.include_router(router)
    return app


app = create_app()
