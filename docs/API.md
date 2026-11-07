# TraceSquad API reference

The TraceSquad API is the agents' whole world: the real user, the logs, the app builds, a pre-prod
sandbox, the code history and the product docs. It is all mock data, served from `data/` by a small
FastAPI app (`tracesquad/api.py`). Nothing in it is real.

- **Run it:** `scripts/serve.sh` (port 8095). Interactive docs are at `/docs`, OpenAPI JSON at `/openapi.json`.
- **Call it:** agents use `~/.tracesquad/bin/tsq GET /path` or `tsq POST /path '<json>'`, never a URL.
  See [SWITCH.md](../SWITCH.md#how-agents-find-the-api) for how `tsq` finds the API.
- **State:** the mock users, sandbox logs, Atlas's builds and pre-prod envs, API checks, budgets and
  Gremlin's writes live in memory. They reset on restart or on `POST /sandbox/reset`.

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
| Espida | `GET /impact/{error_signature}` | Users affected, by app version and by platform |
| Telios | `GET /builds`, `GET /builds/{build_id}` | App builds (`android-18.2`, `ios-18.6-rc1`, …): source, branch, download URL, ready time |
| Telios | `GET /setup-apis` | Setup API catalog: params, prerequisites, tags added |
| Telios | `POST /sandbox/users` `{cohort_id}` | New mock user with login |
| Telios | `POST /sandbox/users/{mock_user_id}/setup/{api_name}` body = params | Mock user after the call (409 if a prerequisite is missing) |
| Telios, Kinetics | `GET /sandbox/users/{mock_user_id}` | Mock user: login, tags, calls made |
| Kinetics | `GET /devices` | Devices to run on |
| Kinetics | `POST /repro/runs` `{bug_ref, build_id, mock_user_id, device_id, steps, env?}` | `reproduced` / `not_reproduced` for that bug only; what was seen (or, when it didn't happen, the healthy screen, the missing state, or where the run ended), artifacts, network calls |
| Kinetics | `POST /api-checks` `{bug_ref, env, mock_user_id, method, endpoint}` | A backend response for that mock user in `preprod` (shared, unfixed) or a fix's own env (`preprod-atl-<n>`) |
| Teams | `GET /teams` | Teams and what they own |
| Atlas | `GET /changes?repo=&area=&since=` | Recently merged PRs (culprits and distractors) |
| Atlas | `POST /atlas/fixes` `{bug_ref, layer, target, platforms?, culprit_change_id, summary}` | A PR plus one `-atlas-<n>` build per platform on the next release candidate (frontend), or a deploy to its own pre-prod env (backend); never says if it's right, a wrong culprit doesn't fix the bug, and a third attempt per bug gets a 429 |
| Everyone | `GET /fixes?bug_ref=`, `GET /fixes/{fix_id}` | Atlas's attempts, and fixes that shipped earlier |
| Gremlin | `GET /prds`, `GET /prds/{prd_id}`, `POST /prds/{prd_id}/updates` | PRDs; add a changelog entry or known issue |
| Gremlin | `GET /releases`, `POST /releases/{release_id}/notes` | Release calendar; add a release note |
| Gremlin | `GET /threads?q=`, `GET /threads/{thread_id}`, `POST /threads/{thread_id}/replies` | Threads in other channels; reply |
| Gremlin | `POST /rca`, `GET /rca/{bug_ref}` | The final RCA per bug |
| Operator | `POST /fixes/{fix_id}/publish`, `POST /sandbox/deploy` | Hidden from `/openapi.json`; only for manual demos |
| Everyone | `GET /sandbox/services?env=` | Service versions in shared pre-prod (`preprod`, the default) or in one backend fix's env |
| Everyone | `GET /health` | `{"service": "tracesquad-api", "status": "ok"}`; `tsq` uses it to find the API |
| Everyone | `GET /budget/{bug_ref}` | What the bug has used and has left: fix attempts (2), app runs per platform (7), API checks (4) |
| Admin | `GET /admin/scenarios`, `GET /admin/scenarios/{scenario_id}` | Scenarios with expected answers (do not give these to agents) |
| Admin | `POST /sandbox/reset` | Clears mock users, logs, Atlas's builds and pre-prod envs, API checks, budgets and Gremlin's writes |

Admin routes and `/sandbox/reset` are left out of `/openapi.json`, so tools generated from it never
reach the answers or wipe the sandbox.

Errors are `{"detail": "..."}`. 404 means an unknown id, 409 means a setup prerequisite is missing,
422 means bad params or a platform mismatch, and 429 means the bug's budget for that call is used up.

## Errors

Errors are `{"detail": "..."}`:

| Status | Meaning |
|---|---|
| 404 | An unknown id |
| 409 | A setup prerequisite is missing; the message names the setup API to call first |
| 422 | Bad params, or a platform mismatch |
| 429 | The bug's budget for that call is used up (see `GET /budget/{bug_ref}`) |

## What agents never see

- `/admin/*` holds each scenario's expected answer and its repro rules.
- `POST /sandbox/reset`, `POST /sandbox/deploy` and `POST /fixes/{fix_id}/publish` are for the operator.
- These routes are left out of `/openapi.json`, so tools generated from it can't reach them, and no
  prompt mentions them. They are still reachable by anyone who has the API's address, which is fine
  for fake data. Don't share a public tunnel URL widely.
- Whether an Atlas fix is right: a right and a wrong fix get the same kind of response. Only a repro
  run or an API check shows whether the bug is gone.
