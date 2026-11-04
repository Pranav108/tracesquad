# Bugmock

Mock data service for the bug agents **Triage**, **Telios**, **Kinetics** and **Espida**.
Every answer comes from hand-written JSON in `data/`. The only state is a small in-memory
sandbox (mock users, sandbox service versions, sandbox logs) that resets on restart or on
`POST /sandbox/reset`.

## Run

```bash
uv sync
uv run uvicorn bugmock.api:app --port 8090
```

Interactive docs: http://localhost:8090/docs. OpenAPI JSON: http://localhost:8090/openapi.json
(handy for generating agent tools).

Tests: `uv run pytest`

## Endpoints

| Used by | Method & path | Returns |
|---|---|---|
| Triage | `GET /reports/{report_id}` | A Slack bug report |
| Triage | `GET /known-bugs`, `GET /known-bugs/{bug_id}` | Bugs already in the bug database |
| Triage | `GET /users/{user_id}` | Profile: platform, app version, device, city, group, plan, cohort |
| Triage | `GET /users/{user_id}/journey` | What the user did, in order |
| Triage | `GET /cohorts/{cohort_id}` | Cohort id broken into labelled parts |
| Espida | `GET /logs?user_id=&env=prod\|sandbox&source=backend\|client&service=&from=&to=` | Logs sorted by time; `env` defaults to `prod` |
| Espida | `GET /traces/{trace_id}` | Every log line for a trace |
| Espida | `GET /deploys?service=` | Prod deploys |
| Espida | `GET /impact/{error_signature}` | Users affected, by app version |
| Telios | `GET /builds`, `GET /builds/{build_id}` | App builds (`android-18.2`, `ios-18.6-rc1`, …): source, branch, download URL, ready time |
| Telios | `GET /setup-apis` | Setup API catalog: params, prerequisites, tags added |
| Telios | `POST /sandbox/users` `{cohort_id}` | New mock user with login |
| Telios | `POST /sandbox/users/{mock_user_id}/setup/{api_name}` body = params | Mock user after the call (409 if a prerequisite is missing) |
| Telios, Kinetics | `GET /sandbox/users/{mock_user_id}` | Mock user: login, tags, calls made |
| Kinetics | `GET /devices` | Devices to run on |
| Kinetics | `POST /repro/runs` `{build_id, mock_user_id, device_id, steps}` | `reproduced` / `not_reproduced`, what was seen, artifacts, network calls |
| Teams | `GET /teams` | Teams and what they own |
| Teams | `GET /fixes?bug_ref=`, `GET /fixes/{fix_id}` | Fixes: team, PR, where it ships |
| Teams | `POST /sandbox/deploy` `{service, version}`, `GET /sandbox/services` | Sandbox service versions |
| Admin | `GET /admin/scenarios`, `GET /admin/scenarios/{scenario_id}` | Scenarios with expected answers (do not give these to agents) |
| Admin | `POST /sandbox/reset` | Clears the sandbox |

Errors are `{"detail": "..."}`. 404 means an unknown id, 409 means a setup prerequisite is missing,
and 422 means bad params or a platform mismatch.

## Scenarios

| ID | Bug | Class | Report | User |
|---|---|---|---|---|
| GOLD-01 | Gold benefits missing after renewal | backend | RPT-101 | U-48213 |
| CART-02 | "Something went wrong" at checkout after a coupon | frontend | RPT-102 | U-77105 |
| MENU-03 | Restaurant name overlaps the rating badge | ui | RPT-103 | U-23017 |
| PAY-04 | UPI payment stuck on "Processing" | duplicate of BUG-1152 | RPT-104 | U-61540 |
| TRACK-05 | Order tracking screen blank after a backend change | both | RPT-105 | U-90877 |

Full detail, including expected and unexpected paths, is in
`docs/superpowers/plans/2026-11-05-bugmock-data.md` and at `GET /admin/scenarios/{id}`.

## Adding a scenario

1. Copy a file in `data/scenarios/` and give every record a new, unique id.
2. Add a walkthrough test in `tests/test_scenario_<id>.py`.
3. Run `uv run pytest`. The loader rejects duplicate ids, cohort ids that don't match a user's
   profile, and references to unknown users, devices, builds, teams or bugs.
