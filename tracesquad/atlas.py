"""Atlas fix submissions. A right and a wrong fix look identical; only verification tells them apart.

A fix is right only when it changes the right layer and target, comes from the right culprit change,
and (for the app) is built for a platform the bug affects. Frontend fixes are built on the next app
release's candidate build, because that is the build that will ship. Backend fixes deploy to a
pre-prod env of their own, so one attempt (or one bug) never overwrites another. A bug gets at most
LIMITS["fix_attempts"] attempts.
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from tracesquad.errors import ApiError
from tracesquad.models import Build, Release
from tracesquad.sandbox import DynamicBuild, PreviewEnv, Sandbox, base_version
from tracesquad.store import Store


class FixRequest(BaseModel):
    bug_ref: str
    layer: Literal["frontend", "backend"]
    target: str
    # every platform the bug affects; required for frontend, ignored for backend
    platforms: list[Literal["android", "ios"]] = []
    culprit_change_id: str
    summary: str


def next_app_release(store: Store) -> Release | None:
    """The app release a frontend fix lands in: the one in QA, else the next planned one."""
    for status in ("in_qa", "planned"):
        candidates = [r for r in store.releases.values() if r.kind == "app" and r.status == status]
        if candidates:
            return min(candidates, key=lambda r: r.release_date or date.max)
    return None


def release_candidate(store: Store, platform: str, version: str) -> Build | None:
    """The newest build of `version` for a platform: the release itself or its latest -rc<n>."""
    builds = [
        b for b in store.builds.values()
        if b.platform == platform and (b.app_version == version or b.app_version.startswith(f"{version}-rc"))
    ]
    return max(builds, key=lambda b: b.build_id) if builds else None


def submit_fix(req: FixRequest, store: Store, sandbox: Sandbox) -> dict[str, Any]:
    report = sandbox.report(req.bug_ref)
    if report is None:
        raise ApiError(404, f"report '{req.bug_ref}' not found")
    if req.culprit_change_id not in store.changes:
        raise ApiError(404, f"change '{req.culprit_change_id}' not found; see GET /changes")
    platforms = list(dict.fromkeys(req.platforms)) if req.layer == "frontend" else []
    if req.layer == "frontend" and not platforms:
        raise ApiError(422, "a frontend fix needs platforms: every affected platform, from android and ios")
    if req.layer == "frontend":
        screens = sorted({s for t in store.teams.values() if t.kind == "frontend" for s in t.owns})
        if req.target not in screens:
            raise ApiError(422, f"unknown app screen '{req.target}'; use one of: {', '.join(screens)}")
    if req.layer == "backend" and req.target not in sandbox.services:
        raise ApiError(404, f"service '{req.target}' not found in pre-prod; see GET /sandbox/services")

    release, base_builds = None, {}
    if req.layer == "frontend":
        release = next_app_release(store)
        if release is None:
            raise ApiError(422, "no open app release to ship a frontend fix in; see GET /releases")
        for platform in platforms:
            build = release_candidate(store, platform, release.version)
            if build is None:
                raise ApiError(422, f"no {platform} build for release {release.version} yet; see GET /builds")
            base_builds[platform] = build

    sandbox.check_budget(req.bug_ref, "fix_attempts")
    scenario = store.scenarios[report.scenario_id]
    fix = store.fixes.get(scenario.fix_id) if scenario.fix_id else None
    right_change = (
        fix is not None
        and req.layer == fix.layer
        and req.target == fix.target
        and (fix.culprit_change_id is None or req.culprit_change_id == fix.culprit_change_id)
    )

    n = sandbox.next_attempt_no()
    attempt_id = f"ATL-{n:04d}"
    repo = req.target if req.layer == "backend" else "consumer-app"
    attempt: dict[str, Any] = {
        "attempt_id": attempt_id,
        "bug_ref": req.bug_ref,
        "layer": req.layer,
        "target": req.target,
        "platforms": platforms,
        "pr_url": f"https://git.example.invalid/{repo}/pull/{7000 + n}",
        "status": "pr_opened",
        "culprit_change_id": req.culprit_change_id,
        "summary": req.summary,
    }

    if release is not None:
        attempt["release"] = release.release_id
        attempt["builds"] = []
        for platform, base_build in base_builds.items():
            build_id = f"{base_build.build_id}-atlas-{n}"
            extension = "apk" if platform == "android" else "ipa"
            fixes_it = right_change and platform in fix.platforms
            sandbox.dynamic_builds[build_id] = DynamicBuild(
                build_id=build_id,
                platform=base_build.platform,
                app_version=base_build.app_version,
                source="atlas",
                branch=f"atlas/{attempt_id.lower()}",
                download_url=f"https://builds.example.invalid/{build_id}.{extension}",
                ready_in_minutes=10,
                base_build_id=base_build.build_id,
                fixes_scenario=scenario.scenario_id if fixes_it else None,
            )
            attempt["builds"].append({"platform": platform, "build_id": build_id, "built_on": base_build.build_id})
    else:
        env = f"preprod-{attempt_id.lower()}"
        version = f"{base_version(sandbox.services[req.target])}-atlas-{n}"
        sandbox.preview_envs[env] = PreviewEnv(
            env=env,
            attempt_id=attempt_id,
            bug_ref=req.bug_ref,
            service=req.target,
            version=version,
            fixes_scenario=scenario.scenario_id if right_change else None,
        )
        attempt["preprod"] = {"env": env, "service": req.target, "version": version}

    sandbox.spend(req.bug_ref, "fix_attempts")
    sandbox.attempts.append(attempt)
    return attempt
