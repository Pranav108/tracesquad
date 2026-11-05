"""Atlas fix submissions. A right and a wrong fix look identical; only verification tells them apart."""

from typing import Any, Literal

from pydantic import BaseModel

from bugmock.errors import ApiError
from bugmock.sandbox import DynamicBuild, Sandbox, base_version
from bugmock.store import Store


class FixRequest(BaseModel):
    bug_ref: str
    layer: Literal["frontend", "backend"]
    target: str
    platform: Literal["android", "ios"] | None = None
    culprit_change_id: str
    summary: str


def submit_fix(req: FixRequest, store: Store, sandbox: Sandbox) -> dict[str, Any]:
    report = store.reports.get(req.bug_ref)
    if report is None:
        raise ApiError(404, f"report '{req.bug_ref}' not found")
    if req.culprit_change_id not in store.changes:
        raise ApiError(404, f"change '{req.culprit_change_id}' not found; see GET /changes")
    if req.layer == "frontend" and req.platform is None:
        raise ApiError(422, "a frontend fix needs a platform: android or ios")
    if req.layer == "backend" and req.target not in sandbox.services:
        raise ApiError(404, f"service '{req.target}' not found in pre-prod; see GET /sandbox/services")

    user = store.users[report.user_id]
    base_build = None
    if req.layer == "frontend":
        base_build = store.builds.get(f"{req.platform}-{user.app_version}")
        if base_build is None:
            raise ApiError(
                422,
                f"no {req.platform} build for app version {user.app_version}; the reporter is on {user.platform}",
            )

    scenario = store.scenarios[report.scenario_id]
    fix = store.fixes.get(scenario.fix_id) if scenario.fix_id else None
    right = (
        fix is not None
        and req.layer == fix.layer
        and req.target == fix.target
        and (req.layer == "backend" or req.platform in fix.platforms)
    )

    n = sandbox.next_attempt_no()
    attempt_id = f"ATL-{n:04d}"
    repo = req.target if req.layer == "backend" else "consumer-app"
    attempt: dict[str, Any] = {
        "attempt_id": attempt_id,
        "bug_ref": req.bug_ref,
        "layer": req.layer,
        "target": req.target,
        "platform": req.platform,
        "pr_url": f"https://git.example.invalid/{repo}/pull/{7000 + n}",
        "status": "pr_opened",
        "culprit_change_id": req.culprit_change_id,
        "summary": req.summary,
    }

    if base_build is not None:
        build_id = f"{base_build.build_id}-atlas-{n}"
        extension = "apk" if req.platform == "android" else "ipa"
        sandbox.dynamic_builds[build_id] = DynamicBuild(
            build_id=build_id,
            platform=base_build.platform,
            app_version=base_build.app_version,
            source="atlas",
            branch=f"atlas/{attempt_id.lower()}",
            download_url=f"https://builds.example.invalid/{build_id}.{extension}",
            ready_in_minutes=10,
            base_build_id=base_build.build_id,
            fixes_scenario=scenario.scenario_id if right else None,
        )
        attempt["build_id"] = build_id
    else:
        version = f"{base_version(sandbox.services[req.target])}-atlas-{n}"
        sandbox.services[req.target] = version
        sandbox.fixed_by_deploy[req.target] = scenario.scenario_id if right else None
        attempt["preprod"] = {"service": req.target, "version": version}

    sandbox.attempts.append(attempt)
    return attempt
