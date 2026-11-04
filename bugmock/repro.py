"""Repro runs: decide whether a Kinetics run reproduces a bug, from hand-written repro rules."""

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel

from bugmock.errors import ApiError
from bugmock.models import Build, LogEntry, LogTemplate, Trigger
from bugmock.sandbox import MockUser, Sandbox, has_tag
from bugmock.store import Store

IST = timezone(timedelta(hours=5, minutes=30))


class ReproStep(BaseModel):
    screen: str
    action: str
    params: dict[str, Any] = {}


class ReproRequest(BaseModel):
    build_id: str
    mock_user_id: str
    device_id: str
    steps: list[ReproStep]


class ReproResult(BaseModel):
    run_id: str
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


def _write_logs(sandbox: Sandbox, templates: list[LogTemplate], run_id: str, user: MockUser, build: Build) -> None:
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
            )
        )


def run_repro(req: ReproRequest, store: Store, sandbox: Sandbox) -> ReproResult:
    if req.build_id not in store.builds:
        raise ApiError(404, f"build '{req.build_id}' not found; see GET /builds")
    if req.device_id not in store.devices:
        raise ApiError(404, f"device '{req.device_id}' not found; see GET /devices")
    build, device = store.builds[req.build_id], store.devices[req.device_id]
    user = sandbox.get(req.mock_user_id)
    if not build.platform == device.platform == user.platform:
        raise ApiError(
            422,
            f"platform mismatch: build {build.platform}, device {device.platform}, mock user {user.platform}",
        )

    run_id = sandbox.next_run_id()
    for rule in store.repro_rules:
        if not any(step_matches(step, rule.trigger) for step in req.steps):
            continue
        state_ok = all(has_tag(user.tags, tag) for tag in rule.requires_tags)
        if not state_ok:
            # The user never reached the state this flow needs, so we can't say what the backend did.
            continue
        backend_buggy = rule.backend is not None and sandbox.services.get(rule.backend.service) in rule.backend.versions
        reproduces = (
            ("*" in rule.affected_builds or build.build_id in rule.affected_builds)
            and (rule.devices is None or device.device_id in rule.devices)
            and (rule.backend is None or backend_buggy)
        )
        if reproduces:
            _write_logs(sandbox, rule.sandbox_logs, run_id, user, build)
            return ReproResult(
                run_id=run_id,
                result="reproduced",
                observed=rule.observed,
                artifacts=rule.artifacts,
                network=rule.network,
            )
        if backend_buggy:
            # The client copes, but the backend still behaves as before: log only its side.
            backend_side = [t for t in rule.sandbox_logs if t.source == "backend"]
            _write_logs(sandbox, backend_side, run_id, user, build)
        else:
            _write_logs(sandbox, rule.sandbox_logs_ok, run_id, user, build)

    return ReproResult(
        run_id=run_id,
        result="not_reproduced",
        observed="Completed all steps; no problem seen.",
        artifacts={"video_url": f"https://artifacts.example.invalid/{run_id}.mp4"},
        network=[],
    )
