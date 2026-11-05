# Bugmock

Mock data service for the bug agents **Triage**, **Telios**, **Kinetics** and **Espida**.
For how the whole system works (agents, prompts, protocol, data, decisions and flow diagrams), see
[docs/SYSTEM.md](docs/SYSTEM.md).
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

### Public URL for hosted agents (demo)

```bash
brew install cloudflared      # once
scripts/tunnel.sh             # prints ">>> BUGMOCK_URL=https://<random>.trycloudflare.com"
```

This runs the API on this laptop (port 8095, or set `PORT=…`) and exposes it through a Cloudflare
quick tunnel. You don't need an account. Set the printed URL as `BUGMOCK_URL` for the hosted agents.

- **The URL is temporary.** It changes every time the script starts, and it stops working when the
  script stops or the laptop sleeps. The script rewrites the base URL in `prompts/*.md` to the new
  one, so re-paste the prompts into your agents after a restart.
- **The script won't start on a busy port.** If something else already owns the port, it exits
  instead of exposing that service.
- **The API is open to anyone who has the URL**, including `/admin`, which is hidden from
  `/openapi.json` but still reachable. That's fine for fake demo data. Don't share the URL widely.

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
| Kinetics | `POST /api-checks` `{env: "preprod", mock_user_id, method, endpoint}` | A pre-prod backend response for that mock user (verifies backend fixes) |
| Teams | `GET /teams` | Teams and what they own |
| Atlas | `GET /changes?repo=&area=&since=` | Recently merged PRs (culprits and distractors) |
| Atlas | `POST /atlas/fixes` `{bug_ref, layer, target, platform?, culprit_change_id, summary}` | A PR plus a new `-atlas-<n>` build (frontend) or pre-prod version (backend); never says if it's right |
| Everyone | `GET /fixes?bug_ref=`, `GET /fixes/{fix_id}` | Atlas's attempts, and fixes that shipped earlier |
| Gremlin | `GET /prds`, `GET /prds/{prd_id}`, `POST /prds/{prd_id}/updates` | PRDs; add a changelog entry or known issue |
| Gremlin | `GET /releases`, `POST /releases/{release_id}/notes` | Release calendar; add a release note |
| Gremlin | `GET /threads?q=`, `GET /threads/{thread_id}`, `POST /threads/{thread_id}/replies` | Threads in other channels; reply |
| Gremlin | `POST /rca`, `GET /rca/{bug_ref}` | The final RCA per bug |
| Operator | `POST /fixes/{fix_id}/publish`, `POST /sandbox/deploy` | Hidden from `/openapi.json`; only for manual demos |
| Everyone | `GET /sandbox/services` | Service versions running in pre-prod (the sandbox), including Atlas's deploys |
| Admin | `GET /admin/scenarios`, `GET /admin/scenarios/{scenario_id}` | Scenarios with expected answers (do not give these to agents) |
| Admin | `POST /sandbox/reset` | Clears mock users, logs, Atlas's builds and deploys, API checks and Gremlin's writes |

Admin routes and `/sandbox/reset` are left out of `/openapi.json`, so tools generated from it never
reach the answers or wipe the sandbox.

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

## Agent prompts

System prompts for the six agents are in `prompts/`: `triage.md`, `telios.md`, `kinetics.md`,
`espida.md`, `atlas.md` and `gremlin.md`. Each one is self-contained. It covers the agent's role, the team directory (who owns
what), the Bugmock endpoints it should call, how it works, and the shared message protocol
(`[ASK]`, `[ANSWER]`, `[NOT MINE]`, `[CLAIM]`, `[REPORT]`) the agents use in a bug's thread.

To use one:
1. Paste the file into the agent's system prompt.
2. Give the agent an HTTP tool, or generate tools from `/openapi.json`.
3. Set `BUGMOCK_URL`, and connect the agent to the bug channel.

`tests/test_prompts.py` fails if a prompt names an endpoint that doesn't exist, or mentions `/admin`.

## Adding a scenario

1. Copy a file in `data/scenarios/` and give every record a new, unique id.
2. Add a walkthrough test in `tests/test_scenario_<id>.py`.
3. Run `uv run pytest`. The loader rejects duplicate ids, cohort ids that don't match a user's
   profile, and references to unknown users, devices, builds, teams or bugs.
