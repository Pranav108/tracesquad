"""Pre-prod API checks: Kinetics calls a backend endpoint as a mock user to verify a backend fix.

`env` is shared pre-prod ("preprod", the unfixed baseline) or one backend fix attempt's own env
("preprod-atl-0002"). Each check counts against the bug's budget.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

from tracesquad.errors import ApiError
from tracesquad.models import LogEntry
from tracesquad.sandbox import Sandbox, has_tag
from tracesquad.store import Store

IST = timezone(timedelta(hours=5, minutes=30))


class CheckRequest(BaseModel):
    bug_ref: str
    env: str
    mock_user_id: str
    method: str
    endpoint: str


def run_api_check(req: CheckRequest, store: Store, sandbox: Sandbox) -> dict[str, Any]:
    if req.bug_ref not in store.reports:
        raise ApiError(404, f"report '{req.bug_ref}' not found; bug_ref is the report id, e.g. RPT-101")
    user = sandbox.get(req.mock_user_id)
    method = req.method.upper()
    version = sandbox.services_in(req.env)  # 404 for an unknown env
    definition = store.api_checks.get((method, req.endpoint))
    if definition is None:
        raise ApiError(404, f"no such endpoint on pre-prod: {method} {req.endpoint}")
    sandbox.check_budget(req.bug_ref, "api_checks")

    version = version[definition.service]
    when = definition.buggy_when
    if not all(has_tag(user.tags, tag) for tag in definition.requires_tags):
        response = definition.missing_response
    elif (
        sandbox.backend_buggy(req.env, definition.service, when.versions, definition.scenario_id)
        and (when.app_versions is None or user.app_version in when.app_versions)
        and all(has_tag(user.tags, tag) for tag in when.tags)
    ):
        response = definition.buggy_response
    else:
        response = definition.ok_response

    sandbox.spend(req.bug_ref, "api_checks")
    check_id = sandbox.next_check_id()
    sandbox.logs.append(
        LogEntry(
            log_id=f"SBX-{check_id}",
            ts=datetime.now(IST),
            env="sandbox",
            source="backend",
            service=definition.service,
            endpoint=req.endpoint,
            method=method,
            status=response.status,
            level="info",
            trace_id=f"tr-{check_id}",
            user_id=user.mock_user_id,
            app_version=user.app_version,
            message="pre-prod api check",
            response_excerpt=response.body,
            preprod_env=req.env,
        )
    )
    return {
        "check_id": check_id,
        "bug_ref": req.bug_ref,
        "env": req.env,
        "status": response.status,
        "body": response.body,
        "served_by": f"{definition.service}@{version}",
        "app_version": user.app_version,
    }
