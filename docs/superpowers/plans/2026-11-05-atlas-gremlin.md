# Atlas and Gremlin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Bugmock and the agent prompts so that two new agents can carry a bug from "found" to "verified fix and closed loop": Atlas (fixes) and Gremlin (product and program manager, final RCA).

**Architecture:** New hand-written JSON records (changes, API-check definitions, PRDs, releases, threads), served by new FastAPI routes. The in-memory sandbox (pre-prod) gains:
- Atlas fix attempts and the `-atlas-n` builds and versions they create
- API checks
- Gremlin's writes

A right and a wrong Atlas fix look identical. Only repro runs and API checks reveal whether a fix works. Then the prompts and docs are updated.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest with TestClient, uv (unchanged).

**Spec:** `docs/superpowers/specs/2026-11-05-atlas-gremlin-design.md`. Read it before starting. It has all the per-scenario values.

## Global Constraints

- No new dependencies. Data stays in JSON under `data/`, and new state lives in the in-memory `Sandbox`, cleared by `reset()`.
- Agent-facing responses never reveal whether an Atlas fix is right: no `fixes_scenario`, no flag, no real fix PR URL, nothing auto-published.
- `POST /sandbox/deploy`, `POST /fixes/{fix_id}/publish` and `POST /sandbox/reset` are left out of `/openapi.json` (`include_in_schema=False`), and no prompt mentions them.
- ID formats: attempt `ATL-####`, API check `CHK-####`, change `CHG-###`, check definition `API-<scenario>`, PRD `PRD-<NAME>`, thread `THR-###`, release `app-18.5`, `app-18.6`, `app-18.7`, `hotfix-2026-11-06`.
- Atlas artifacts:
  - frontend build: `<platform>-<reporter app_version>-atlas-<n>`
  - backend version: `<base version>-atlas-<n>`
  - PR URL: `https://git.example.invalid/<consumer-app or service>/pull/<7000+n>`
  - `n` is the attempt number.
- Fake data only (`example.invalid` URLs). Prompts contain no scenario values (the existing leak test enforces this).

## Review Focus

1. A frontend fix for a platform that has no build at the reporter's app version returns 422 naming both. Task 4 test.
2. A wrong backend fix deployed after a right one on the same service brings the bug back (the latest deploy wins). Task 4 test.
3. An API check by a mock user that lacks the needed state returns the definition's `missing_response`, never a 500. Task 5 test.
4. Gremlin writes to an unknown PRD, release or thread, or an RCA for an unknown report, return 404 naming the id. Task 6 test.
5. `POST /sandbox/reset` clears attempts, dynamic builds, `fixed_by_deploy`, checks and Gremlin's writes, and numbering restarts at `ATL-0001` and `CHK-0001`. Task 6 test.

## File Structure

```
bugmock/models.py      + Change, ApiCheckDef, Prd, Release, Thread; Fix gains target, platforms; Build.source gains "atlas"
bugmock/store.py       + collections, indexes and integrity checks for the new records
bugmock/sandbox.py     + attempts, dynamic builds, fixed_by_deploy, checks, Gremlin state; base_version()
bugmock/atlas.py       NEW: submit_fix()
bugmock/checks.py      NEW: run_api_check()
bugmock/repro.py       resolve dynamic builds and -atlas-n versions
bugmock/api.py         + routes for changes, prds, releases, threads, atlas, api-checks, Gremlin writes; operator routes hidden
data/shared.json       + releases
data/scenarios/*.json  + changes, api_checks, prds, threads; fixes gain target, platforms
prompts/atlas.md, prompts/gremlin.md   NEW; the other four prompts updated
tests/test_atlas.py, test_api_checks.py, test_gremlin.py, test_fix_loop.py   NEW
docs/SYSTEM.md, README.md   updated
```

---

## Tasks

Run everything from the repo root. Each task ends by running `uv run pytest -q` (all pass) and committing.

### Task 1: Models, loader and release data

**Files:** modify `bugmock/models.py`, `bugmock/store.py`, `data/shared.json`, and every `data/scenarios/*.json` (add `target` and `platforms` to each fix). Test: `tests/test_store.py`.

**Interfaces (produces):**
- `Change`: `change_id, repo, area, platforms: list[str] | None, title, summary, pr_url, team_id, merged_at: datetime, released_in`
- `ApiResponse`: `status: int, body: dict[str, Any]`
- `BuggyWhen`: `versions: list[str], app_versions: list[str] | None = None, tags: list[str] = []`
- `ApiCheckDef`: `check_def_id, scenario_id, service, method, endpoint, requires_tags: list[str], missing_response: ApiResponse, buggy_when: BuggyWhen, buggy_response: ApiResponse, ok_response: ApiResponse`
- `PrdSection`: `heading, body`
- `ChangelogEntry`: `date: date, change, reason, bug_ref: str | None`
- `Prd`: `prd_id, title, feature, owner_team, status: Literal["live","in_progress"], target_release, summary, sections: list[PrdSection], known_issues: list[str], changelog: list[ChangelogEntry]`
- `Release`: `release_id, kind: Literal["app","backend"], version, status: Literal["released","in_qa","planned"], code_cutoff: date | None, release_date: date | None, notes: list[str]`
- `ThreadMessage`: `author, ts: datetime, text`
- `Thread`: `thread_id, channel, title, started_at: datetime, prd_id: str | None, messages: list[ThreadMessage]`
- `Fix` gains `target: str` and `platforms: list[str] = []`. `Build.source` gains `"atlas"`.
- `Dataset` and `Store` gain `changes`, `api_checks`, `prds`, `releases`, `threads`:
  - `ID_FIELDS`: `change_id`, `check_def_id`, `prd_id`, `release_id`, `thread_id`
  - `Store` dict indexes with the same names (`api_checks` keyed by `(method, endpoint)`)
- Integrity checks (each raises `DataError` naming the id):
  - `change.team_id` and `prd.owner_team` exist in teams
  - `api_check.service` and every backend `fix.target` are in `sandbox_defaults`
  - `thread.prd_id` (when set) exists
  - `api_check.scenario_id` exists

- [ ] **Step 1:** Add the tests and run them. Expected: FAIL.
  - `test_releases_loaded`: `{r.release_id for r in ds.releases} == {"app-18.5","app-18.6","app-18.7","hotfix-2026-11-06"}`
  - `test_fix_targets`: GOLD and TRACK targets are their services; CART is `checkout` with platforms `["android","ios"]`; MENU is `restaurant` `["ios"]`; PAY is `payment` `["android"]`
  - `test_api_check_service_must_exist(tmp_path)`: an unknown service raises a DataError naming it
- [ ] **Step 2:** Implement. Add the releases from the spec to `shared.json`, and the targets and platforms to the fixes. Run `uv run pytest -q`. Expected: all pass. Commit `feat: models and loader for atlas and gremlin data`.

### Task 2: Scenario data for Atlas, Kinetics checks and Gremlin

**Files:** modify the five `data/scenarios/*.json` files with values from the spec's **Per-scenario content** and **API checks** tables. Test: `tests/test_store.py`.

- Changes: the culprit plus the distractors listed in the spec. `merged_at` falls before the scenario's first error. CART's checkout-service distractor is dated 2026-09-15 with `released_in: "checkout-service@7.0.0"`.
- API checks:
  - `API-GOLD-01`: `GET /v2/membership/status`, requires `plan`, missing response `200 {"status": "none"}`, buggy when `versions ["3.12.0"]` and `tags ["gold_renewed"]`
  - `API-TRACK-05`: `GET /orders/active/track`, requires `order:active`, missing response `404 {"error": "no active order"}`, buggy when `versions ["5.3.0"]` and `app_versions ["18.2","18.3"]`
  - Buggy and ok bodies as in the spec table.
- PRDs and threads: one PRD per scenario except PAY-04, plus the listed threads. Each thread has 2–4 messages from fake handles. PRD-CHECKOUT-V3 has a "Contract" section saying coupon rows may omit `label`.

- [ ] **Step 1:** Add `test_atlas_gremlin_data` and run it. Expected: FAIL.

```python
s = Store(load_dataset(DATA_DIR))
assert s.changes["CHG-401"].released_in == "membership-service@3.12.0"
assert s.changes["CHG-411"].area == "checkout" and s.changes["CHG-421"].platforms == ["ios"]
assert s.api_checks[("GET", "/v2/membership/status")].check_def_id == "API-GOLD-01"
assert {"PRD-GOLD-RENEW", "PRD-CHECKOUT-V3", "PRD-RESTO-HEADER", "PRD-TRACK-ETA"} <= set(s.prds)
assert any("label" in sec.body for sec in s.prds["PRD-CHECKOUT-V3"].sections)
assert {t.channel for t in s.threads.values()} >= {"#gold-support", "#checkout-v3", "#design-reviews", "#logistics-oncall", "#app-release"}
```

- [ ] **Step 2:** Write the data. Run `uv run pytest -q`. Expected: all pass, including the prompt leak test. Commit `data: changes, api checks, prds and threads`.

### Task 3: Read routes and hidden operator routes

**Files:** modify `bugmock/api.py`. Test: `tests/test_read_api.py`.

**Interfaces (produces):** these routes:
- `GET /changes?repo=&area=&since=`: `since` is a `YYYY-MM-DD` date, filtering `merged_at.date() >= since`. Newest first.
- `GET /prds`, `GET /prds/{prd_id}`
- `GET /releases`
- `GET /threads?q=`: case-insensitive substring match over the title and message texts
- `GET /threads/{thread_id}`

Tag groups: "Atlas: recent changes", "Gremlin: PRDs, releases, threads". `POST /sandbox/deploy` and `POST /fixes/{fix_id}/publish` get `include_in_schema=False`.

- [ ] **Step 1:** Add the tests and run them. Expected: FAIL.
  - `test_changes_filter`: `/changes?repo=membership-service` returns `CHG-401` first; `/changes?area=checkout&since=2026-10-01` contains `CHG-411` and not the checkout-service distractor
  - `test_threads_search`: `/threads?q=join gold` contains the `#gold-support` thread, and `/threads?q=zzz` returns `[]`
  - `test_prd_and_unknown_404`: `/prds/PRD-NOPE` returns 404 naming it
  - `test_operator_routes_hidden`: `/sandbox/deploy` and `/fixes/{fix_id}/publish` are not in the openapi paths
- [ ] **Step 2:** Implement and run `uv run pytest -q`. Expected: all pass. Commit `feat: read routes for changes, prds, releases, threads; hide operator routes`.

### Task 4: Atlas fix submissions, and resolving them in repro runs

**Files:** create `bugmock/atlas.py` and `tests/test_atlas.py`; modify `bugmock/sandbox.py`, `bugmock/repro.py` and `bugmock/api.py`.

**Interfaces (produces):**

In `sandbox.py`:
- `base_version(version: str) -> str` strips a trailing `-atlas-<n>`.
- `class DynamicBuild(Build)` adds `base_build_id: str` and `fixes_scenario: str | None`, which is never serialized to agents.
- `Sandbox` gains:
  - `attempts: list[dict]`
  - `dynamic_builds: dict[str, DynamicBuild]`
  - `fixed_by_deploy: dict[str, str | None]`: service → the scenario its current deploy fixes
  - `next_attempt_no() -> int`
  - `deploy()` (the operator route) sets `fixed_by_deploy[service] = None`
  - `reset()` clears all of these

In `atlas.py`:
- `class FixRequest(BaseModel)`: `bug_ref: str; layer: Literal["frontend","backend"]; target: str; platform: Literal["android","ios"] | None = None; culprit_change_id: str; summary: str`
- `submit_fix(req: FixRequest, store: Store, sandbox: Sandbox) -> dict`. It returns `{attempt_id, bug_ref, layer, target, platform, pr_url, status: "pr_opened", culprit_change_id, summary}`, plus `build_id` (frontend) or `preprod: {service, version}` (backend). Error order:
  1. unknown `bug_ref` (report) → 404
  2. unknown `culprit_change_id` → 404
  3. frontend without `platform` → 422
  4. backend `target` not in sandbox services → 404
  5. frontend with no base build `<platform>-<reporter app_version>` → 422 `"no <platform> build for app version <v>; the reporter is on <user platform>"`
- Right fix: the scenario is `report.scenario_id`, its fix is `store.fixes[scenario.fix_id]`, and it is right when `layer == fix.layer and target == fix.target and (layer == "backend" or platform in fix.platforms)`.

In `api.py`:
- `POST /atlas/fixes`
- `GET /builds` and `GET /builds/{build_id}` include dynamic builds, excluding `base_build_id` and `fixes_scenario`
- `GET /fixes?bug_ref=` returns published static fixes (excluding `published`, `target` and `platforms`) plus the attempts for that `bug_ref`

In `repro.py`:
- A dynamic build counts as its base, unless its `fixes_scenario == rule.scenario_id`, which makes it unaffected.
- The backend is buggy when `base_version(services[svc]) in rule.backend.versions` and `fixed_by_deploy.get(svc) != rule.scenario_id`.

- [ ] **Step 1:** Add the tests and run them. Expected: FAIL.
  - `test_frontend_fix_right_and_wrong_look_alike`: for CART-02, set up the user (reuse the calls from `test_scenario_cart02.py`), then:
    - the right fix (`checkout`, android, `CHG-411`) gives `build_id == "android-18.2-atlas-1"`, and the repro is `not_reproduced`
    - the wrong fix (`cart`) gives `"android-18.2-atlas-2"`, and the repro is `reproduced`
    - both responses have the same key set, and neither contains `fixes_scenario`
  - `test_backend_fix_and_latest_deploy_wins`: for GOLD-01, set up the user, then:
    - the right fix (`membership-service`, `CHG-401`) gives `preprod.version == "3.12.0-atlas-1"`, and the repro on `home/open` is `not_reproduced`
    - a wrong fix on the same service next gives `"3.12.0-atlas-2"`, and the repro is `reproduced` again
  - `test_fix_errors`:
    - an unknown `culprit_change_id` returns 404
    - `ios` for RPT-105 (android 18.3) returns 422 containing `"ios"` and `"18.3"`
    - a frontend submission without `platform` returns 422
    - backend `target: "nope-service"` returns 404
  - `test_fixes_lists_attempts`: after one attempt, `/fixes?bug_ref=RPT-102` has one item with `attempt_id`, and no `fixes_scenario` or `target` from the hidden fix
- [ ] **Step 2:** Implement and run `uv run pytest -q`. Expected: all pass (the existing GOLD/TRACK tests that use `/sandbox/deploy` still pass). Commit `feat: atlas fix submissions with indistinguishable artifacts`.

### Task 5: API checks for verifying backend fixes

**Files:** create `bugmock/checks.py` and `tests/test_api_checks.py`; modify `bugmock/api.py` and `bugmock/sandbox.py` (add `next_check_id()`, numbering `CHK-0001`).

**Interfaces (produces):**
- `class CheckRequest(BaseModel)`: `env: Literal["preprod"]; mock_user_id: str; method: str; endpoint: str`
- `run_api_check(req: CheckRequest, store: Store, sandbox: Sandbox) -> dict` returns `{check_id, status, body, served_by: "<service>@<version>", app_version}`. It works like this:
  1. Look up the definition by `(method.upper(), endpoint)`. If there is none, return 404 `"no such endpoint on preprod: <METHOD> <endpoint>"`.
  2. If the user lacks a `requires_tags` tag, return `missing_response`.
  3. If all of these hold, return `buggy_response`: `base_version(current) in buggy_when.versions`, `fixed_by_deploy.get(service) != def.scenario_id`, the user's `app_version` is in `buggy_when.app_versions` (when set), and the user has every tag in `buggy_when.tags`.
  4. Otherwise return `ok_response`.
  5. Append one sandbox `LogEntry`: `source="backend"`, the definition's service, method and endpoint, `status`, `response_excerpt=body`, `level` `"info"`, `trace_id=f"tr-{check_id}"`.
- Route: `POST /api-checks`, tag "Kinetics: devices, repro runs and API checks".

- [ ] **Step 1:** Add the tests and run them. Expected: FAIL.
  - `test_gold_check_before_and_after_atlas`: with GOLD calls, the check body has `status` `"expired"`; after the right Atlas fix it has `status` `"active"` and `served_by == "membership-service@3.12.0-atlas-1"`. Both appear in `/logs?env=sandbox&user_id=<mu>`.
  - `test_track_check_old_app`: with TRACK calls, the check gives `schema_version` 2; after the right Atlas fix (`order-tracking-service`, `CHG-431`) it gives 1.
  - `test_check_missing_state`: a GOLD-cohort user with no plan gets `200 {"status": "none"}`; a TRACK-cohort user with no order gets 404 `{"error": "no active order"}` as the **body** (the HTTP response itself is 200).
  - `test_check_unknown_endpoint_and_env`: an unknown endpoint returns 404, and `env: "prod"` returns 422.
- [ ] **Step 2:** Implement and run `uv run pytest -q`. Expected: all pass. Commit `feat: preprod api checks for backend verification`.

### Task 6: Gremlin writes and RCA

**Files:** create `tests/test_gremlin.py`; modify `bugmock/sandbox.py` and `bugmock/api.py`.

**Interfaces (produces):**
- `Sandbox` gains `prd_changelog: dict[str, list[dict]]`, `prd_known_issues: dict[str, list[str]]`, `release_notes: dict[str, list[str]]`, `thread_replies: dict[str, list[dict]]` and `rcas: dict[str, dict]`, all cleared by `reset()`.
- Routes, under the tag "Gremlin: PRDs, releases, threads, RCA":
  - `POST /prds/{prd_id}/updates` with `{change, reason, bug_ref, known_issue: str | None}`. It appends `{date: today IST, change, reason, bug_ref}`, plus the known issue when given. Returns the merged PRD.
  - `POST /releases/{release_id}/notes` with `{bug_ref, note}`. Returns the merged release.
  - `POST /threads/{thread_id}/replies` with `{text, bug_ref}`. It appends `{author: "Gremlin", ts: now IST, text}`. Returns the merged thread.
  - `POST /rca` with `{bug_ref, title, what_happened, root_cause, culprit_change_id, fix: dict, verification: dict, impact, follow_ups: list[str]}`. `bug_ref` must be a report (404 otherwise). It stores the RCA and returns it.
  - `GET /rca/{bug_ref}` returns 404 if there is none.
- GET `/prds`, `/releases` and `/threads` return the static data merged with these writes.

- [ ] **Step 1:** Add the tests and run them. Expected: FAIL.
  - `test_prd_update_and_known_issue`: the change shows in the changelog with `bug_ref` RPT-101, and the known issue shows in `known_issues`
  - `test_release_note_and_thread_reply`: both appear on the following GETs
  - `test_rca_roundtrip`: POST then GET `/rca/RPT-101`, with the fields equal
  - `test_gremlin_unknown_ids_404`: a PRD, release, thread or RCA for an unknown report returns 404 naming the id
  - `test_reset_clears_fix_loop_state`: after an Atlas attempt, an API check and the Gremlin writes, `POST /sandbox/reset` returns everything to the static data, and the next attempt and check are `ATL-0001` and `CHK-0001`
- [ ] **Step 2:** Implement and run `uv run pytest -q`. Expected: all pass. Commit `feat: gremlin writes and rca`.

### Task 7: Whole-loop walkthroughs

**Files:** create `tests/test_fix_loop.py`. The loop must pass using the API only.

- [ ] **Step 1:** Write and run the tests. Expected: PASS. Earlier tasks built the parts, so this is the integration gate; if one fails, fix the code it exposes.
  - `test_cart02_full_loop`: Telios setup, then a Kinetics repro (`reproduced`), then the right Atlas fix, then a repro on the new build (`not_reproduced`), then the Gremlin writes: a PRD-CHECKOUT-V3 update, an `app-18.6` note, a `#checkout-v3` reply, and an RCA whose `fix.build_id` is the Atlas build and whose `verification.run_id` is the passing run. Then `GET /rca/RPT-102` matches.
  - `test_gold01_full_loop`: setup, then a check (`expired`), then the right Atlas fix, then a check (`active`) and a repro (`not_reproduced`), then a `hotfix-2026-11-06` note and an RCA with `verification.check_id`.
  - `test_wrong_fix_then_retry`: on TRACK-05, a wrong frontend fix (`order_tracking`, android) gives a build where the repro still reproduces. A second, right backend fix gives a check with `schema_version` 1.
- [ ] **Step 2:** Commit `test: whole fix loop through atlas, kinetics and gremlin`.

### Task 8: Prompts

**Files:** create `prompts/atlas.md` and `prompts/gremlin.md`; modify the other four prompts and `tests/test_prompts.py` (`AGENTS` gains `atlas` and `gremlin`).

- Both new prompts use the existing structure: role, team directory (all six agents plus people), tools (live base URL, every endpoint with its params, neutral example values), playbook, shared protocol.
- The **Atlas** playbook:
  1. Read the thread's evidence.
  2. `GET /changes` for the suspect area or service, and pick the culprit by time and content.
  3. Decide the layer and target.
  4. Submit the fix.
  5. Hand Kinetics a `[REPORT]` with the build to test (frontend), or the pre-prod service and version plus the exact failing call to re-check (backend). For a backend fix, also ask Espida to watch the sandbox logs.
  6. On a failed verification, re-diagnose. Two attempts at most, then `[REPORT]` to the owning team.
  7. On success, hand Gremlin the PR, the artifact, the run or check id, the culprit and a root-cause note.
- The **Gremlin** playbook:
  1. Read the thread.
  2. Find the PRD (`GET /prds`), update it (adding a known issue if users must update the app), and note the fix on its release (an app release by version, or `hotfix-2026-11-06` for backend).
  3. `GET /threads?q=` with the symptom keywords, and reply in the related threads.
  4. Inform the owning team. For app or UI fixes, that is the app team's channel from `GET /teams`.
  5. `POST /rca`, then post the `[RCA]` message in the bug thread. If the discussion happened elsewhere (`channel=`), post it back to the original bug thread too.
- Updates to the other four prompts:
  - **Directory:** add Atlas and Gremlin rows.
  - **Protocol:** an optional `channel=` field, and the `[RCA]` message (Gremlin only).
  - **Triage:** a fixed bug is closed by Gremlin's `[RCA]`; duplicates are still closed by Triage.
  - **Espida:** backend findings go to Atlas; it confirms backend fixes from the sandbox logs.
  - **Kinetics:** confirmed bugs go to Atlas. It verifies frontend fixes in the app on Atlas's build, and backend fixes with `POST /api-checks` (all params documented), then reports the result to Atlas.
  - **Telios:** a backend fix is now deployed by Atlas, not by teams.
- No prompt mentions `/sandbox/deploy`, `/fixes/{fix_id}/publish` or `/admin`.

- [ ] **Step 1:** Extend `AGENTS` and run `uv run pytest tests/test_prompts.py -q`. Expected: FAIL (the new files are missing).
- [ ] **Step 2:** Write and update the prompts. Run `uv run pytest -q`. Expected: all pass. Commit `docs: atlas and gremlin prompts; existing prompts join the fix loop`.

### Task 9: Docs and live URL

**Files:** modify `docs/SYSTEM.md` and `README.md`.

- **`docs/SYSTEM.md`:**
  - Agents table with six agents.
  - The big-picture diagram adds Atlas and Gremlin and the new data groups.
  - The data tables add changes, API checks, PRDs, releases, threads and RCAs.
  - Protocol: `channel=` and `[RCA]`.
  - Conclusions: "6.6 Atlas: which change, which layer" and "6.7 Gremlin: closing the loop".
  - "When is a bug done?" is rewritten for the new loop.
  - Sequence diagrams: replace 7.1 (CART-02) and 7.2 (GOLD-01) with the full loop through Atlas, Kinetics verification and Gremlin.
  - Demo steps: the operator no longer deploys or publishes for new bugs.
- **`README.md`:** an endpoint table with the new routes, and a prompts list with six agents.
- [ ] **Step 1:** Update both. Run `uv run pytest -q`. Expected: all pass. Commit `docs: system guide covers atlas and gremlin`.
- [ ] **Step 2:** Restart the tunnel so the new code is live: stop the running `scripts/tunnel.sh` and start it again. It prints a new `BUGMOCK_URL` and rewrites the prompts. Check `GET <url>/prds` returns 200 and `GET <url>/openapi.json` lists `/atlas/fixes`. Commit the updated prompt URLs: `chore: prompts point at the new tunnel URL`.
