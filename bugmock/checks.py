"""Pre-prod API checks: Kinetics calls a backend endpoint as a mock user to verify a backend fix."""

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel

from bugmock.errors import ApiError
from bugmock.models import LogEntry
from bugmock.sandbox import Sandbox, base_version, has_tag
from bugmock.store import Store

IST = timezone(timedelta(hours=5, minutes=30))


class CheckRequest(BaseModel):
    env: Literal["preprod"]
    mock_user_id: str
    method: str
    endpoint: str


def run_api_check(req: CheckRequest, store: Store, sandbox: Sandbox) -> dict[str, Any]:
    user = sandbox.get(req.mock_user_id)
    method = req.method.upper()
    definition = store.api_checks.get((method, req.endpoint))
    if definition is None:
        raise ApiError(404, f"no such endpoint on preprod: {method} {req.endpoint}")

    version = sandbox.services[definition.service]
    when = definition.buggy_when
    if not all(has_tag(user.tags, tag) for tag in definition.requires_tags):
        response = definition.missing_response
    elif (
        base_version(version) in when.versions
        and sandbox.fixed_by_deploy.get(definition.service) != definition.scenario_id
        and (when.app_versions is None or user.app_version in when.app_versions)
        and all(has_tag(user.tags, tag) for tag in when.tags)
    ):
        response = definition.buggy_response
    else:
        response = definition.ok_response

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
            message="preprod api check",
            response_excerpt=response.body,
        )
    )
    return {
        "check_id": check_id,
        "status": response.status,
        "body": response.body,
        "served_by": f"{definition.service}@{version}",
        "app_version": user.app_version,
    }
