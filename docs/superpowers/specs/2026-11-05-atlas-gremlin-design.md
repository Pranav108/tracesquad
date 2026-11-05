# Atlas and Gremlin: from "bug found" to "verified fix and closed loop" (design)

Status: approved in chat (playback on 2026-11-05). Calls marked **(Claude's call)** were not discussed and can be overridden.

## Intent

Today the agents stop at "here is the evidence, team X please fix it". The user wants the system to
deliver the **solution** as well:
- a fix with a PR
- an updated build (frontend) or a pre-prod deployment (backend)
- proof that the fix works
- a product-level close: the PRD updated, the teams and related threads informed, the release noted, and a final RCA

The code changes, builds and deploys are all **mocked** in Bugmock, like the rest of the data. Two new
agents carry this:

- **Atlas** owns the fix. It finds the change that caused the bug, "fixes" it, and hands over a build or a pre-prod environment.
- **Gremlin** is the product and program manager. It updates PRDs, release notes and related threads, and writes the final RCA that closes the bug.

## Goals

1. Add Atlas and Gremlin as agents, each with a ready-to-paste prompt, following the same pattern as the other four.
2. Kinetics gains a second way to verify. Frontend fixes are checked by running the new build in the app (as now). Backend fixes are checked by calling the fixed API on pre-prod as the mock user.
3. Give Atlas and Gremlin realistic mock data and endpoints in Bugmock, for all five scenarios.
4. Update the existing prompts (Triage, Telios, Kinetics, Espida), `docs/SYSTEM.md` and the README to describe the new loop.
5. Keep everything testable, in the same style as the existing suite.

## Non-goals

- Fixing real code, building real apps or deploying anything real.
- Creating Slack channels or moving discussions between them. That is future work; the agents only need to be **ready** for it.
- Simulating human review of Atlas's PRs beyond what Bugmock records.

## Anti-goals (a failure even if everything "works")

- Atlas can get the right fix by **looking it up** rather than by diagnosing it. The fix must come from Atlas naming the right layer and component.
- A wrong fix by Atlas still verifies as "fixed".
- Prompts or agent-facing endpoints leak scenario answers (the existing leak tests must keep passing and cover the new prompts).
- Atlas touches "prod". It only deploys to pre-prod, which is the existing sandbox.

## The loop, as agreed

1. **Triage, Espida and Telios are unchanged in role.** Triage checks for duplicates, reads the user's context and classifies the bug. Espida reads the logs, and Telios builds mock users.
2. **Bugs go to Atlas, not to a team.**
   - Kinetics hands a bug it has confirmed in the app to Atlas.
   - Espida hands a backend fault it has established from the logs to Atlas. **(Claude's call:** this means backend bugs don't need an app repro first.)
3. **Atlas fixes the bug:**
   - It reads the evidence in the thread, then the recent changes (merged PRs) for the suspect app area or service, and picks the change that caused the bug.
   - It decides the layer (frontend or backend) and the target: a service name for backend, or a screen and platform for frontend.
   - It submits a fix. Bugmock returns a PR, and then:
     - **Frontend:** a new build id to test.
     - **Backend:** the fix deployed to pre-prod.
   - For a backend fix, Atlas names the API call that proves it: the call that was failing, from Espida's evidence or Kinetics's network capture.
4. **Kinetics verifies:**
   - **Frontend:** it runs the new build with the same mock user and the same steps (as now).
   - **Backend:** it calls the API from `verify_with` on pre-prod as the mock user, and compares the response with the expectation.
   - Telios adjusts the mock user's data if that's needed. Espida can confirm the result from the sandbox logs.
5. **If verification fails,** Kinetics tells Atlas, which re-diagnoses and submits again, at most 2 attempts per bug. After that, it escalates to the owning team in the thread.
6. **Once verification passes,** Atlas hands Gremlin the verified fix: the PR, the build or environment, the verification run or check id, the culprit change, and its root-cause note.
7. **Gremlin closes the loop:**
   - It updates the running PRD for the affected feature, adding a changelog entry and, where needed, a known-issue note.
   - It finds the release the fix lands in (an app release, or the backend hotfix train) and adds a release note.
   - It searches other channels for threads about the issue and replies with the outcome.
   - It informs the owning team. For UI or app changes, that's the app team.
   - It writes the **final RCA** (what happened, why, how it was fixed, the proof, the impact and follow-ups), stores it in Bugmock and posts it in the bug thread. This message closes the bug.
8. **People still review and merge** Atlas's PRs. Atlas never merges and never deploys to prod.
9. **Future channel movement:** every protocol message carries an optional `channel=` field. Gremlin's prompt says that if the work happened in a temporary channel, the final RCA is also posted back to the original bug thread. Nothing creates or moves channels.

Triage stays the reporter's contact for questions. **(Claude's call:** Triage no longer sends a closing
message; Gremlin's RCA is the close, and Triage marks the bug closed when it sees the RCA.)

## Updated roles

| Agent | Change |
|---|---|
| Triage | Unchanged, except that it no longer closes bugs that go through a fix. Gremlin's RCA closes them. Triage still closes **duplicates** itself, because there is nothing to fix. |
| Espida | Sends backend findings to **Atlas** (not straight to the team). It confirms backend fixes from the sandbox logs when asked. |
| Telios | Unchanged. It also adjusts mock-user data when Atlas or Kinetics need different state to verify a fix. |
| Kinetics | Sends confirmed bugs to **Atlas**. It verifies **frontend** fixes in the app, and **backend** fixes with an API call on pre-prod. |
| **Atlas** (new) | Owns the fix. It reads recent changes, picks the culprit, submits a fix (PR plus build or pre-prod deploy), and hands the verified fix to Gremlin. It never merges and never touches prod. |
| **Gremlin** (new) | Product and program manager. It owns PRDs, the release calendar and related threads in other channels. It informs teams, and it writes and posts the final RCA, which closes the bug. |
| FE / BE teams (people) | They review Atlas's PRs and hear from Gremlin. In the demo, the operator plays them. |

## New mock data and endpoints

Everything is still hand-written JSON plus the in-memory sandbox. The sandbox is "pre-prod". New
records go into each scenario's file. Release data goes into `shared.json`.

### For Atlas

**Recent changes** (merged PRs), with the culprit and distractors for each scenario:

| Field | Meaning |
|---|---|
| `change_id` | e.g. `CHG-401` |
| `repo` | `consumer-app` or a service name |
| `area` | A service name, or an app screen (`checkout`, `restaurant`, `order_tracking`, `payment`, `home`) |
| `platforms` | For app changes: `["android"]`, `["ios"]` or both. `null` for services |
| `title`, `summary`, `pr_url`, `team_id`, `merged_at` | The usual PR details |
| `released_in` | An app version (`18.4`) or `<service>@<version>` |

`GET /changes?repo=&area=&since=` returns changes newest first.

**Fix specs.** The hidden `Fix` records gain `target` (a service name for backend fixes, or a screen
for frontend fixes) and `platforms` (for frontend fixes). They stay hidden: they are only used to decide
whether Atlas's fix works.

**`POST /atlas/fixes`.** The body is `{bug_ref, layer, target, platform (frontend only), culprit_change_id, summary}`.

**A right fix and a wrong fix look identical in the response.** Only verification tells them apart.

| Input | What happens |
|---|---|
| Any valid submission | Returns `attempt_id` (`ATL-0001`, …), a generated `pr_url` and `status: "pr_opened"`, plus the artifact below. It is recorded as an attempt. |
| **Frontend** | Registers a new build `<platform>-<reporter's app version>-atlas-<n>`. Its base is that platform's build of the reporter's app version, and it carries a hidden `fixes_scenario`: the scenario id if `target` and `platform` match the scenario's fix, else `null`. Returns `build_id`. |
| **Backend** | Deploys `<current base version>-atlas-<n>` of `target` to the sandbox. Bugmock remembers whether that deploy fixes the scenario (it does if `target` matches). Returns `preprod: {service, version}`. |
| Unknown `bug_ref`, unknown `culprit_change_id`, or a backend `target` that isn't a sandbox service | 404 naming it |
| `layer` not frontend/backend, or a frontend submission without `platform` | 422 |
| No build for that platform at the reporter's app version (e.g. `ios` for an android 18.3 reporter) | 422 "no ios build for app version 18.3; the reporter is on android" |

- `culprit_change_id` is checked to exist and stored for the RCA. It does **not** affect whether the fix works.
- Dynamic builds appear in `GET /builds/{build_id}`, are accepted by `POST /repro/runs`, and are cleared by reset.
- **Resolving fixes in repro runs and API checks.** A dynamic build counts as its base build, unless its `fixes_scenario` is the rule's scenario, in which case it is "not affected". A service version `X-atlas-n` counts as `X`, unless that deploy fixes the rule's scenario, in which case it is "not buggy".
- **The server returns no `verify_with`.** Atlas states the verifying call itself in its hand-off to Kinetics: the call that was failing, from Espida's evidence or Kinetics's network capture. A wrong backend fix leaves that call still failing, so Kinetics sees the buggy response.
- `GET /fixes?bug_ref=` lists Atlas's attempts for the bug (PR URL, layer, target and artifact, with no right-or-wrong flag), plus historical fixes that are already published (PAY-04's).

### For Kinetics (backend verification)

**API checks** are per-scenario definitions of the pre-prod endpoints Kinetics can call:

```
{check_def_id, scenario_id, service, method, endpoint,
 requires_tags, missing_response: {status, body},
 buggy_when: {versions, app_versions (optional), tags (optional)},
 buggy_response: {status, body}, ok_response: {status, body}}
```

**`POST /api-checks`.** The body is `{env: "preprod", mock_user_id, method, endpoint}`.

- It finds the definition by method and endpoint. If none matches, it returns 404 "no such endpoint on preprod".
- If the mock user lacks `requires_tags`, it returns `missing_response`.
- Otherwise it returns `buggy_response` while the sandbox runs a buggy version (and the user's app version and tags match `buggy_when`), and `ok_response` once it doesn't.
- The response is `{check_id: "CHK-0001", status, body, served_by: "<service>@<version>", app_version}`.
- It also writes a sandbox log line, so Espida can see the call.

The definitions are:

| Scenario | Endpoint | Buggy | Fixed |
|---|---|---|---|
| GOLD-01 | `GET /v2/membership/status` (requires `plan`; buggy needs `gold_renewed` on 3.12.0) | `{"status": "expired", "cache_hit": true}` | `{"status": "active", "cache_hit": false}` |
| TRACK-05 | `GET /orders/active/track` (requires `order:active`; buggy on 5.3.0 for app 18.2–18.3) | `{"schema_version": 2, "eta": {"min": 25, "max": 35}}` | `{"schema_version": 1, "eta": 30}` |

CART-02 and MENU-03 are frontend bugs, so they are verified in the app. PAY-04 is a duplicate and
never reaches Atlas.

### For Gremlin

| Data | Fields | Endpoints |
|---|---|---|
| PRDs | `prd_id`, `title`, `feature`, `owner_team`, `status` (`live` / `in_progress`), `target_release`, `summary`, `sections[{heading, body}]`, `known_issues[]`, `changelog[{date, change, reason, bug_ref}]` | `GET /prds`, `GET /prds/{prd_id}`, `POST /prds/{prd_id}/updates` with `{change, reason, bug_ref, known_issue (optional)}`. It appends to `changelog`, and, when `known_issue` is given, to `known_issues`, in memory |
| Releases | `release_id`, `kind` (`app` / `backend`), `version`, `status` (`released` / `in_qa` / `planned`), `code_cutoff`, `release_date`, `notes[]` | `GET /releases`, `POST /releases/{release_id}/notes` with `{bug_ref, note}` |
| Threads in other channels | `thread_id`, `channel`, `title`, `started_at`, `prd_id`, `messages[{author, ts, text}]` | `GET /threads?q=` (case-insensitive search over title and messages), `GET /threads/{thread_id}`, `POST /threads/{thread_id}/replies` with `{text, bug_ref}` |
| RCAs | `bug_ref`, `title`, `what_happened`, `root_cause`, `culprit_change_id`, `fix{pr_url, build_id or preprod}`, `verification{run_id or check_id}`, `impact`, `follow_ups[]` | `POST /rca`, `GET /rca/{bug_ref}` |

Everything Gremlin writes is in-memory, visible through the GET endpoints, and cleared by reset.

**Releases** (shared):
- app `18.5`: released 2026-10-28
- app `18.6`: in QA, code cutoff 2026-11-10, release 2026-11-17
- app `18.7`: planned
- backend hotfix train `hotfix-2026-11-06`: planned, daily

### Per-scenario content

| Scenario | Culprit change (and distractors) | PRD | Related threads |
|---|---|---|---|
| GOLD-01 | `CHG-401` membership-service "Status cache TTL 5m → 24h; invalidation via async job", released in `membership-service@3.12.0`. Distractors: payment-service "Renewal receipt emails", promo-service "City banners" | `PRD-GOLD-RENEW` "Gold membership renewals" (live, owner membership-be) | `#gold-support` "Members see 'Join Gold' right after renewing". Distractor: `#gold-launch` "Annual pricing experiment" |
| CART-02 | `CHG-411` consumer-app "Checkout v3: new DiscountRow component", released in 18.2 (android, ios). Distractors: checkout-service "Coupons listed in discounts, label optional per contract v3" (Sep, `@7.0.0`, **not** the culprit: the contract allows it), restaurant-service "Menu image CDN" | `PRD-CHECKOUT-V3` "Checkout v3: discounts and coupons" (live, owner checkout-fe; its contract section says coupon rows may omit `label`) | `#checkout-v3` "QA: Gold discount + coupon combos crashing?" |
| MENU-03 | `CHG-421` consumer-app "Restaurant header: name and rating on one row", released in 18.4 (ios). Distractor: "Search card spacing" 18.5 | `PRD-RESTO-HEADER` "Restaurant page header redesign" (live, owner discovery-fe) | `#design-reviews` "Header with long names on small screens?", where a designer raised exactly this before launch |
| TRACK-05 | `CHG-431` order-tracking-service "ETA returned as {min, max} (schema v2) for all clients", released in `@5.3.0`. Related: `CHG-432` consumer-app "Tracking: support ETA ranges" 18.4 (explains why 18.4+ copes). Distractor: "Courier location polling 10s" | `PRD-TRACK-ETA` "Order tracking: ETA ranges" (in progress, owner orders-fe) | `#logistics-oncall` "Tracking v2 rollout", `#app-release` "Force-update for 18.2/18.3?" |
| PAY-04 | `CHG-441` consumer-app "Handle UPI intent result on Android 14", 18.4 (the old fix) | none | none (a duplicate: Triage closes it) |

## Protocol changes

- Message headers gain an optional `channel=<channel>`. This prepares for future temporary per-bug channels; for now it is always the bug thread.
- A new message type, `[RCA]`, posted only by Gremlin: `bug=… from=Gremlin`, then `what_happened:`, `root_cause:`, `fix:`, `verification:`, `impact:`, `follow_ups:`. It closes the bug.
- Atlas uses `[REPORT]` to hand Kinetics a fix to verify, and Kinetics replies with `[ANSWER]` (verified or not). Atlas then hands the verified fix to Gremlin with `[REPORT]`.

## Operator-only routes

`POST /sandbox/deploy` and `POST /fixes/{fix_id}/publish` stay available to the operator, playing the
teams, but are **left out of `/openapi.json`** (like `/sandbox/reset`), and no prompt mentions them.
Without this, an agent could deploy an easily guessed patch version, or publish a fix, and skip
Atlas and verification. Existing tests may keep calling them.

"Closed" is a thread message only: Gremlin's `[RCA]`, or Triage's reply for a duplicate. Bugmock keeps
no bug status.

## Deliverables

1. Bugmock code and data for everything under **New mock data and endpoints**, with tests in the existing style: TDD, scenario walkthroughs extended through Atlas, verification and Gremlin, and tests for wrong fixes.
2. `prompts/atlas.md` and `prompts/gremlin.md`, in the same structure as the others: role, team directory, tools with the live base URL and every param, playbook, shared protocol.
3. The four existing prompts updated: the new team directory rows, the hand-offs to Atlas, Kinetics's API verification, `channel=` and `[RCA]` in the protocol.
4. `tests/test_prompts.py` covering all six prompts (endpoints exist, no `/admin`, every peer named, base URL present, no scenario values).
5. `docs/SYSTEM.md` and the README updated, including new sequence diagrams for a frontend fix (CART-02) and a backend fix (GOLD-01) through Atlas and Gremlin.

## Calls Claude made (check these)

1. Backend bugs that Espida has established from the logs can go to Atlas without an app repro.
2. Gremlin isn't involved in duplicates. Triage still closes those.
3. Atlas gets at most 2 fix attempts per bug (a prompt rule; the server doesn't enforce it).
4. A "wrong fix" still returns a PR, but its artifact has no effect, so verification catches it.
5. Pre-prod is the existing sandbox, not a separate environment.
6. The TRACK-05 API check's fixed response is the old-app response (`schema_version: 1`), because the reporter's cohort is on 18.3.
7. Right and wrong fixes look identical until verification. Builds and versions are always `-atlas-n`, nothing is auto-published, and the server returns no `verify_with`, so Atlas can't find the answer by trial and lookup.
8. `/sandbox/deploy` and `/fixes/{id}/publish` are hidden from agents and kept for the operator.
9. "Closed" is a thread message, not stored state.
10. The PRD update body is `{change, reason, bug_ref, known_issue?}`.
11. `culprit_change_id` must exist, but it doesn't decide whether the fix works.

## Left to the builder

The exact JSON for the new records, beyond the values above; the wording of PR titles and thread
messages; the `CHK-`, attempt and dynamic-build numbering; and how much a walkthrough test asserts
about Gremlin's writes.
