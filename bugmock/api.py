"""FastAPI app serving the mock data, with routes grouped by the agent that uses them."""

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from bugmock.errors import ApiError
from bugmock.models import LogEntry
from bugmock.store import DATA_DIR, DataError, Store, load_dataset, parse_cohort_id


def _store(request: Request) -> Store:
    return request.app.state.store


def _get(index: dict, key: str, what: str):
    if key not in index:
        raise ApiError(404, f"{what} '{key}' not found")
    return index[key]


def _sandbox_logs(request: Request) -> list[LogEntry]:
    sandbox = getattr(request.app.state, "sandbox", None)
    return list(sandbox.logs) if sandbox is not None else []


triage = APIRouter(tags=["Triage: reports, known bugs, users, journeys, cohorts"])
espida = APIRouter(tags=["Espida: logs, traces, deploys, impact"])
telios = APIRouter(tags=["Telios: builds and setup API catalog"])
teams = APIRouter(tags=["Teams: owners and fixes"])
admin = APIRouter(prefix="/admin", tags=["Admin: scenarios with expected answers (not for agents)"])


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
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
) -> list[dict[str, Any]]:
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
    return [b.model_dump(mode="json") for b in _store(request).builds.values()]


@telios.get("/builds/{build_id}", summary="One build, e.g. android-18.2: where it comes from and its download URL")
def get_build(build_id: str, request: Request) -> dict[str, Any]:
    return _get(_store(request).builds, build_id, "build").model_dump(mode="json")


@telios.get("/setup-apis", summary="Catalog of sandbox setup APIs: params, prerequisites, tags they add")
def list_setup_apis(request: Request) -> list[dict[str, Any]]:
    return [a.model_dump(mode="json") for a in _store(request).setup_apis.values()]


@teams.get("/teams", summary="Teams and what each one owns")
def list_teams(request: Request) -> list[dict[str, Any]]:
    return [t.model_dump(mode="json") for t in _store(request).teams.values()]


@teams.get("/fixes", summary="Fixes, optionally for one bug (known bug id or report id)")
def list_fixes(request: Request, bug_ref: str | None = None) -> list[dict[str, Any]]:
    fixes = [f for f in _store(request).fixes.values() if bug_ref is None or f.bug_ref == bug_ref]
    return [f.model_dump(mode="json") for f in fixes]


@teams.get("/fixes/{fix_id}", summary="One fix: team, PR and where it ships")
def get_fix(fix_id: str, request: Request) -> dict[str, Any]:
    return _get(_store(request).fixes, fix_id, "fix").model_dump(mode="json")


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


def create_app(data_dir: Path = DATA_DIR) -> FastAPI:
    app = FastAPI(
        title="Bugmock",
        description="Mock data for the Triage, Telios, Kinetics and Espida bug agents.",
        version="0.1.0",
    )
    app.state.store = Store(load_dataset(data_dir))

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    for router in (triage, espida, telios, teams, admin):
        app.include_router(router)
    return app


app = create_app()
