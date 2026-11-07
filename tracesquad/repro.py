"""Repro runs: decide whether a Kinetics run reproduces a bug, from hand-written repro rules.

A run is about one bug (`bug_ref`): only that bug's rules count. When the bug doesn't show, the run
still says what the screen showed instead: the healthy screen, or the state the user is missing.
Each run counts against the bug's per-platform budget.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel

from tracesquad.errors import ApiError
from tracesquad.models import Build, LogEntry, LogTemplate, Trigger
from tracesquad.sandbox import SHARED_PREPROD, MockUser, Sandbox, has_tag
from tracesquad.store import Store

IST = timezone(timedelta(hours=5, minutes=30))


class ReproStep(BaseModel):
    screen: str
    action: str
    params: dict[str, Any] = {}


class ReproRequest(BaseModel):
    bug_ref: str
    build_id: str
    mock_user_id: str
    device_id: str
    steps: list[ReproStep]
    # which pre-prod the app talks to: shared "preprod", or a backend fix attempt's own env
    env: str = SHARED_PREPROD


class ReproResult(BaseModel):
    run_id: str
    bug_ref: str
    env: str
    result: Literal["reproduced", "not_reproduced"]
    observed: str
    artifacts: dict[str, str]
    network: list[dict[str, Any]]


def step_matches(step: ReproStep, trigger: Trigger) -> bool:
    return (
        step.screen == trigger.screen
        and step.action == trigger.action
        and all(step.params.get(k) == v for k, v in trigger.params.items())
    )


def _write_logs(
    sandbox: Sandbox, templates: list[LogTemplate], run_id: str, user: MockUser, build: Build, env: str
) -> None:
    now = datetime.now(IST)
    for template in templates:
        sandbox.logs.append(
            LogEntry(
                **template.model_dump(),
                log_id=f"SBX-{run_id}-{len(sandbox.logs) + 1}",
                ts=now,
                env="sandbox",
                user_id=user.mock_user_id,
                trace_id=f"tr-{run_id}",
                app_version=build.app_version,
                preprod_env=env,
            )
        )


def _nothing_seen(steps: list[ReproStep]) -> str:
    if not steps:
        return "No steps to follow: the app opened on home. No problem seen."
    last = steps[-1]
    done = "Completed the one step" if len(steps) == 1 else f"Completed all {len(steps)} steps"
    return f"{done}, ending on {last.screen} ({last.action}). No problem seen."


def run_repro(req: ReproRequest, store: Store, sandbox: Sandbox) -> ReproResult:
    report = sandbox.report(req.bug_ref)
    if report is None:
        raise ApiError(404, f"report '{req.bug_ref}' not found; bug_ref is the report id, e.g. RPT-102")
    dynamic = sandbox.dynamic_builds.get(req.build_id)
    if req.build_id not in store.builds and dynamic is None:
        raise ApiError(404, f"build '{req.build_id}' not found; see GET /builds")
    if req.device_id not in store.devices:
        raise ApiError(404, f"device '{req.device_id}' not found; see GET /devices")
    build, device = store.builds.get(req.build_id) or dynamic, store.devices[req.device_id]
    # an Atlas build behaves like its base build, unless it carries the fix for the rule's scenario
    effective_build_id = dynamic.base_build_id if dynamic else build.build_id
    user = sandbox.get(req.mock_user_id)
    if not build.platform == device.platform == user.platform:
        raise ApiError(
            422,
            f"platform mismatch: build {build.platform}, device {device.platform}, mock user {user.platform}",
        )
    sandbox.preview(req.env)  # 404 for an unknown env
    sandbox.check_budget(req.bug_ref, "runs", build.platform)
    sandbox.spend(req.bug_ref, "runs", build.platform)

    run_id = sandbox.next_run_id()

    def result(outcome: str, observed: str, network: list[dict[str, Any]], artifacts: dict[str, str] | None = None):
        return ReproResult(
            run_id=run_id,
            bug_ref=req.bug_ref,
            env=req.env,
            result=outcome,
            observed=observed,
            artifacts=artifacts or {"video_url": f"https://artifacts.example.invalid/{run_id}.mp4"},
            network=network,
        )

    # Only this bug's rules count: a run never "reproduces" a different bug.
    for rule in (r for r in store.repro_rules if r.scenario_id == report.scenario_id):
        if not any(step_matches(step, rule.trigger) for step in req.steps):
            continue
        missing = [tag for tag in rule.missing_state if not has_tag(user.tags, tag)]
        if missing:
            # The screen shows the user isn't in the state this flow needs; the backend is never asked.
            return result("not_reproduced", rule.missing_state[missing[0]], [])
        backend_buggy = rule.backend is not None and sandbox.backend_buggy(
            req.env, rule.backend.service, rule.backend.versions, rule.scenario_id
        )
        build_fixed = dynamic is not None and dynamic.fixes_scenario == rule.scenario_id
        reproduces = (
            not build_fixed
            and ("*" in rule.affected_builds or effective_build_id in rule.affected_builds)
            and (rule.devices is None or device.device_id in rule.devices)
            and (rule.backend is None or backend_buggy)
        )
        if reproduces:
            _write_logs(sandbox, rule.sandbox_logs, run_id, user, build, req.env)
            return result("reproduced", rule.observed, rule.network, rule.artifacts)
        if backend_buggy:
            # The client copes, but the backend still behaves as before: log only its side.
            backend_side = [t for t in rule.sandbox_logs if t.source == "backend"]
            _write_logs(sandbox, backend_side, run_id, user, build, req.env)
            return result("not_reproduced", rule.observed_ok, rule.network)
        _write_logs(sandbox, rule.sandbox_logs_ok, run_id, user, build, req.env)
        network = rule.network_ok if rule.backend is not None and rule.network_ok is not None else rule.network
        return result("not_reproduced", rule.observed_ok, network)

    return result("not_reproduced", _nothing_seen(req.steps), [])
