# Bugmock Data Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a small HTTP service that serves hand-written JSON mock data for five bug scenarios. The Triage, Telios, Kinetics and Espida agents will be built against it later.

**Architecture:** All data lives in JSON files: `data/shared.json` plus one file per scenario. A FastAPI app loads and validates the files at startup and serves them through endpoints grouped by the agent that uses them. The only state is a small in-memory "sandbox": the mock users Telios creates, the sandbox service versions, and the sandbox logs. That state exists so a Kinetics reproduction run can depend on what Telios set up. It resets on restart or on `POST /sandbox/reset`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, uvicorn, pytest with FastAPI's TestClient, uv. This is the same stack as `switch/core`, the agent platform these agents will run on.

**Spec:** There is no separate spec file. The architecture was agreed in chat on 2026-11-05 and is summarized under **Context** below. The five scenarios under **Scenarios** are the spec for the data.

## Context

These agents are built later, not in this plan:

- **Triage** is the first contact for a Slack bug report. It checks known bugs for duplicates, reads the user's profile and journey, works out the user's cohort (platform · app version · city · group · plan), and classifies the bug.
- **Telios** prepares reproductions. It gets the app build for the user's version, and creates a mock user in the sandbox by calling setup APIs in the right order. It never reproduces or tests anything.
- **Kinetics** reproduces bugs in the app using Telios's build and mock user. It also re-checks frontend fixes.
- **Espida** reads backend and client logs (from prod and from the sandbox), traces, deploys, and error impact.
- **The FE and BE teams** fix bugs. Kinetics checks FE fixes. A BE fix is checked in three steps: Telios sets up the mock user on the updated sandbox, Kinetics runs the steps, and Espida reads the sandbox logs.

There is no fixed flow: any agent can ask any other agent. The data therefore has to answer questions that are off the expected path too, for example logs for a UI-only bug, a reproduction attempt for a backend bug, or a reproduction on the wrong device.

## Global Constraints

- Python `>=3.12`. Runtime dependencies are only `fastapi`, `pydantic>=2` and `uvicorn`; dev dependencies are `pytest` and `httpx`.
- Data lives only in JSON files under `data/`. There is no database and no query language. The only in-memory state is the sandbox: mock users, sandbox service versions, sandbox logs, and the run counter.
- Every person, phone number and URL is fake. URLs use the `example.invalid` domain, and phone numbers use the format `+91-90000-0XXXX`.
- Timestamps are ISO 8601 with an offset, written in IST (`+05:30`). Scenario events fall between 2026-11-02 and 2026-11-04.
- Agent-facing responses never include `scenario_id`, `expected_*` fields, or repro rules. Those appear only under `/admin/*`.
- ID formats:
  - user `U-#####`, report `RPT-###`, known bug `BUG-####`
  - trace `tr-<scenario>-<n>` (e.g. `tr-gold01-1`), log `LOG-<scenario>-<n>`, deploy `DEP-###`, fix `FIX-<scenario>` (e.g. `FIX-GOLD-01`)
  - build `<platform>-<app_version>` (e.g. `android-18.2`, `android-18.6-rc1`)
  - cohort `<platform>-<app_version>-<city>-<group>-<plan>` (e.g. `android-18.5-DEL-G7-gold_annual`)
  - mock user `MU-####`, numbered from `MU-0001`; repro run `RUN-####`, numbered from `RUN-0001`
- The service runs on port `8090`.

## Review Focus

1. A mistyped or unknown ID (user, trace, build, mock user, fix) returns 404 with a message naming the ID, never a 500. Tests in Tasks 3 and 4.
2. Setup calls made in the wrong order (e.g. `activate_plan` before `set_address`) return 409 naming the missing prerequisite and the setup API that provides it, so Telios can fix its plan. Test in Task 4.
3. A repro run whose build, mock user and device are on different platforms returns 422 naming both platforms. Test in Task 5.
4. Log time filters given in `Z` and in `+05:30` that describe the same window return the same entries. Test in Task 3.
5. `POST /sandbox/reset` clears mock users, sandbox logs and service versions, and the next mock user is `MU-0001` again. Test in Task 4.

## File Structure

```
bugmock/
  pyproject.toml
  README.md                     # how to run, endpoint list, scenario index
  data/
    shared.json                 # cohort dimensions, devices, builds, setup APIs, teams, sandbox defaults
    scenarios/
      GOLD-01.json  CART-02.json  MENU-03.json  PAY-04.json  TRACK-05.json
  bugmock/
    __init__.py
    models.py                   # Pydantic models for every record type
    store.py                    # loads, merges, validates and indexes the JSON (read-only)
    errors.py                   # ApiError(status_code, detail)
    sandbox.py                  # in-memory mock users, setup validation, sandbox services and logs
    repro.py                    # repro rule matching
    api.py                      # FastAPI app, routes grouped by agent
  tests/
    conftest.py                 # TestClient fixture; resets the sandbox before each test
    test_store.py  test_read_api.py  test_sandbox.py  test_repro.py
    test_scenario_gold01.py  test_scenario_cart02.py  test_scenario_menu03.py
    test_scenario_pay04.py  test_scenario_track05.py
```

## Data Model

All models live in `bugmock/models.py` and are Pydantic v2 `BaseModel`s. Fields are required unless marked `| None` or given a default.

```python
class CohortDimensions: platforms: list[str]; app_versions: list[str]; cities: dict[str, str]; groups: dict[str, str]; plans: list[str]
class Device:      device_id: str; model: str; platform: Literal["android","ios"]; os_version: str; screen: Literal["small","regular","large"]
class Build:       build_id: str; platform: Literal["android","ios"]; app_version: str; source: Literal["s3","play","github_actions"]; branch: str; download_url: str; ready_in_minutes: int
class SetupApi:    name: str; path: str; params: dict[str, str]; requires: list[str]; adds_tags: list[str]
class Team:        team_id: str; name: str; kind: Literal["frontend","backend"]; owns: list[str]; channel: str
class KnownBug:    bug_id: str; title: str; status: Literal["open","fixed","wont_fix"]; layer: Literal["frontend","backend","both"]
                   affected_platforms: list[str]; affected_versions: list[str]; affected_os: list[str] | None
                   fixed_in: str | None; thread_url: str; summary: str; error_signature: str | None
class Report:      report_id: str; scenario_id: str; channel: str; posted_at: datetime; reporter: str; user_id: str; text: str; attachments: list[str]
class User:        user_id: str; name: str; phone: str; platform: Literal["android","ios"]; app_version: str; device_id: str
                   city: str; group: str; plan: str; plan_status: Literal["active","expired","none"]; cohort_id: str
                   signup_date: date; flags: dict[str, str]
class JourneyEvent: ts: datetime; screen: str; action: str; params: dict[str, Any] = {}
class Journey:     user_id: str; events: list[JourneyEvent]
class LogEntry:    log_id: str; ts: datetime; env: Literal["prod","sandbox"]; source: Literal["backend","client"]; service: str
                   endpoint: str | None; method: str | None; status: int | None; level: Literal["info","warn","error"]
                   trace_id: str; user_id: str; app_version: str | None; message: str
                   error_signature: str | None; response_excerpt: dict[str, Any] | None
class LogTemplate: source: Literal["backend","client"]; service: str; endpoint: str | None; method: str | None; status: int | None
                   level: Literal["info","warn","error"]; message: str; error_signature: str | None; response_excerpt: dict[str, Any] | None
class Deploy:      deploy_id: str; service: str; version: str; deployed_at: datetime; change: str
class Impact:      error_signature: str; first_seen: datetime; affected_users: int; by_app_version: dict[str, int]; note: str
class Trigger:     screen: str; action: str; params: dict[str, Any] = {}
class BackendCondition: service: str; versions: list[str]
class ReproRule:   rule_id: str; scenario_id: str; trigger: Trigger; requires_tags: list[str]
                   affected_builds: list[str]          # build_ids, or ["*"] for any build
                   devices: list[str] | None           # device_ids, or None for any device
                   backend: BackendCondition | None    # reproduces only while the sandbox runs one of these versions
                   observed: str; artifacts: dict[str, str]; network: list[dict[str, Any]]
                   sandbox_logs: list[LogTemplate]     # written when the rule reproduces
                   sandbox_logs_ok: list[LogTemplate]  # written when the trigger is hit but the rule does not reproduce
class Fix:         fix_id: str; team_id: str; layer: Literal["frontend","backend"]; title: str; pr_url: str
                   bug_ref: str                        # a known bug_id (PAY-04: BUG-1152), else the scenario's report_id (e.g. RPT-101)
                   ships_in: str                       # a build_id, or "<service>@<version>"
class Scenario:    scenario_id: str; title: str; report_id: str
                   expected_class: Literal["backend","frontend","ui","duplicate","both"]
                   duplicate_of: str | None; fix_id: str | None; expected_path: list[str]; unexpected_paths: list[str]
class Dataset:     cohort_dimensions: CohortDimensions; sandbox_defaults: dict[str, str]
                   devices, builds, setup_apis, teams, known_bugs, reports, users, journeys, logs, deploys,
                   impacts, repro_rules, fixes, scenarios: list[<matching model>] (each defaults to [])
```

**File shape:** each JSON file is a partial `Dataset` with the same top-level keys, all of them optional. The loader concatenates lists that share a key. `cohort_dimensions` and `sandbox_defaults` appear only in `shared.json`. Each scenario file has exactly one entry in `scenarios`, and holds that scenario's `reports`, `users`, `journeys`, `logs`, `deploys`, `impacts`, `known_bugs`, `repro_rules` and `fixes`.

**Tags:** a mock user's state is a list of tags such as `user`, `address:PNQ` or `coupon:SAVE50`. A requirement `r` is met when some tag equals `r` or starts with `r + ":"`. So the requirement `address` is met by the tag `address:PNQ`.

## Shared Data (`data/shared.json`)

**cohort_dimensions**
- platforms: `android`, `ios`
- app_versions: `18.2`, `18.3`, `18.4`, `18.5` (18.5 is the current prod version)
- cities: `DEL` Delhi NCR, `BOM` Mumbai, `BLR` Bengaluru, `PNQ` Pune, `HYD` Hyderabad
- groups: `G1` New, `G2` Occasional, `G3` Regular, `G4` Frequent, `G5` High spender, `G6` Lapsed, `G7` Gold loyalist, `G8` Corporate, `G9` Student, `G10` Late-night
- plans: `none`, `gold_monthly`, `gold_annual`, `gold_trial`

**devices**

| device_id | model | platform | os | screen |
|---|---|---|---|---|
| `pixel-7` | Pixel 7 | android | 14 | regular |
| `galaxy-m32` | Galaxy M32 | android | 14 | regular |
| `oneplus-nord` | OnePlus Nord | android | 13 | regular |
| `redmi-note-10` | Redmi Note 10 | android | 12 | regular |
| `iphone-15` | iPhone 15 | ios | 17.5 | regular |
| `iphone-se-2` | iPhone SE (2nd gen) | ios | 17.5 | small |

**builds** (`download_url` = `https://builds.example.invalid/<build_id>.<apk|ipa>`)

| build_id | source | branch | ready_in_minutes |
|---|---|---|---|
| `android-18.2` | github_actions | `release/18.2` | 18 |
| `android-18.3` | github_actions | `release/18.3` | 18 |
| `android-18.4` | play | `release/18.4` | 0 |
| `android-18.5` | s3 | `release/18.5` | 0 |
| `android-18.6-rc1` | s3 | `release/18.6` | 0 |
| `ios-18.4` | s3 | `release/18.4` | 0 |
| `ios-18.5` | s3 | `release/18.5` | 0 |
| `ios-18.6-rc1` | s3 | `release/18.6` | 0 |

**setup_apis** (`path` is `/sandbox/users/{mock_user_id}/setup/<name>`, except `create_user`, whose path is `/sandbox/users`)

| name | params | requires | adds_tags |
|---|---|---|---|
| `create_user` | `cohort_id` | — | `user`, `cohort:{cohort_id}` |
| `set_address` | `city`, `area` | `user` | `address:{city}` |
| `set_group` | `group` | `user` | `group:{group}` |
| `activate_plan` | `plan` | `address` | `plan:{plan}`, `plan_status:active` |
| `renew_plan` | `plan` | `plan` | `gold_renewed` |
| `add_payment_method` | `type` | `user` | `payment_method:{type}` |
| `fill_cart` | `restaurant_id`, `items` | `address` | `cart`, `cart_restaurant:{restaurant_id}` |
| `apply_coupon` | `code` | `cart` | `coupon:{code}` |
| `place_order` | `restaurant_id`, `items` | `address`, `payment_method` | `order:active` |

**teams** (`channel` = `#team-<team_id>`)

| team_id | kind | owns |
|---|---|---|
| `membership-be` | backend | membership-service |
| `payments-be` | backend | payment-service |
| `cart-be` | backend | cart-service, checkout-service |
| `logistics-be` | backend | order-tracking-service |
| `checkout-fe` | frontend | cart, checkout and payment screens |
| `discovery-fe` | frontend | home, search and restaurant screens |
| `orders-fe` | frontend | order_tracking screen |

**sandbox_defaults** (these match the prod versions): `membership-service` 3.12.0, `payment-service` 9.0.3, `cart-service` 4.8.2, `checkout-service` 7.1.4, `order-tracking-service` 5.3.0, `restaurant-service` 2.19.0, `promo-service` 1.7.0, `search-service` 11.4.0

## API Surface

| Used by | Method & path | Returns |
|---|---|---|
| Triage | `GET /reports/{report_id}` | Report without `scenario_id` |
| Triage | `GET /known-bugs`, `GET /known-bugs/{bug_id}` | KnownBug list / one |
| Triage | `GET /users/{user_id}` | User |
| Triage | `GET /users/{user_id}/journey` | Journey |
| Triage | `GET /cohorts/{cohort_id}` | `{cohort_id, platform, app_version, city: {code, name}, group: {id, label}, plan}` |
| Espida | `GET /logs?user_id=&env=prod&source=&service=&from=&to=` | LogEntry list sorted by `ts`; `env` defaults to `prod`; `env=sandbox` reads sandbox logs |
| Espida | `GET /traces/{trace_id}` | LogEntry list (prod and sandbox) for that trace |
| Espida | `GET /deploys?service=` | Deploy list sorted by `deployed_at` |
| Espida | `GET /impact/{error_signature}` | Impact |
| Telios | `GET /builds`, `GET /builds/{build_id}` | Build list / one |
| Telios | `GET /setup-apis` | SetupApi list |
| Telios | `POST /sandbox/users` body `{cohort_id}` | MockUser |
| Telios | `POST /sandbox/users/{mock_user_id}/setup/{api_name}` body = params object | MockUser |
| Telios, Kinetics | `GET /sandbox/users/{mock_user_id}` | MockUser |
| Kinetics | `GET /devices` | Device list |
| Kinetics | `POST /repro/runs` body ReproRequest | ReproResult |
| Teams | `GET /teams` | Team list |
| Teams | `GET /fixes?bug_ref=`, `GET /fixes/{fix_id}` | Fix list / one |
| Teams | `POST /sandbox/deploy` body `{service, version}`; `GET /sandbox/services` | current sandbox service versions |
| Admin | `GET /admin/scenarios`, `GET /admin/scenarios/{scenario_id}` | Scenario list / one scenario's full data, including repro rules |
| Admin | `POST /sandbox/reset` | `{"reset": true}` |

Errors use the body `{"detail": "<message naming the id or problem>"}`. Unknown IDs return 404, wrong setup order returns 409, and bad params or a platform mismatch return 422. A filter that matches nothing returns `[]`.

## Scenarios

Each scenario lists the exact values its JSON file must contain. The implementer writes the JSON from these values. A value marked *(free)* can be anything realistic that fits the constraints. All reports are posted in channel `#app-bugs` by reporter `@support-agent-1`.

| ID | Bug | Class | Owner |
|---|---|---|---|
| GOLD-01 | Gold benefits missing after renewal | backend | membership-be |
| CART-02 | "Something went wrong" at checkout after a coupon | frontend (reported as unclear) | checkout-fe |
| MENU-03 | Restaurant name overlaps the rating badge | ui | discovery-fe |
| PAY-04 | UPI payment stuck on "Processing" | duplicate of BUG-1152 | — |
| TRACK-05 | Order tracking screen blank after a backend change | both (API contract mismatch) | logistics-be fixes; orders-fe informed |

### Scenario 1: GOLD-01, Gold benefits missing after renewal

**Story:** The user renewed Gold Annual and the payment succeeded, but the app still shows "Join Gold" and charges delivery fees. The cause is membership-service 3.12.0: it raised the status cache TTL from 5 minutes to 24 hours and moved cache invalidation to an async job that skips `membership.renewed` events. The status endpoint therefore keeps serving a stale `expired`.

- **Report** `RPT-101` at `2026-11-04T10:12:00+05:30`: "Renewed Gold yesterday, money got deducted, but the app still shows 'Join Gold' and I'm paying delivery fees. user_id U-48213". Attachments: `https://files.example.invalid/rpt-101-home.png`.
- **User** `U-48213`: "Test User 48213", android, 18.5, `pixel-7`, DEL, G7, gold_annual, plan_status `expired`, cohort `android-18.5-DEL-G7-gold_annual`, signed up 2023-02-11, flags `{"home_v2": "on"}`.
- **Journey:**
  - 2026-11-03: 20:10 `profile/open` · 20:11 `gold/open` · 20:12 `gold/tap_renew {plan: gold_annual}` · 20:14 `payment/pay_upi {amount: 799}` · 20:14 `payment/success` · 20:15 `home/open {banner: "Join Gold"}`
  - 2026-11-04: 09:58 `cart/open {delivery_fee: 40}` · 10:01 `help/open`
- **Prod logs:**
  - `tr-gold01-1`, 2026-11-03 20:14:05: payment-service `POST /gold/renew` 200, info, "renewal.success plan=gold_annual"
  - `tr-gold01-1`, 20:14:06: membership-service, no endpoint, info, "consumed membership.renewed; cache invalidation deferred to async job"
  - `tr-gold01-2`, 2026-11-04 09:58:10: membership-service `GET /v2/membership/status` 200, warn, "served from cache (age 13h)", signature `membership.stale_status_after_renewal`, excerpt `{"status": "expired", "cache_hit": true}`
  - `tr-gold01-3`, 09:58:11 (distractor): promo-service `GET /promos/banner` 404, warn, "no banner configured for city DEL"
- **Deploys:** `DEP-201` membership-service 3.12.0 at 2026-11-02T16:00+05:30, "Status cache TTL 5m → 24h; cache invalidation moved to async job". `DEP-202` (distractor) search-service 11.4.0 at 2026-11-03T12:00+05:30, "Ranking tweak for late-night search".
- **Impact:** `membership.stale_status_after_renewal`, first seen 2026-11-02T16:20+05:30, 1284 users, by version `{"18.4": 402, "18.5": 882}`, note "Only users who renewed after 2026-11-02 16:00".
- **Known bugs (near miss):** `BUG-1180` "Gold badge missing on iOS profile screen": fixed, frontend, ios, versions 18.3; fixed in 18.4; signature `null`.
- **Repro rule** `R-GOLD01`:
  - trigger `home/open`; requires `plan:gold_annual`, `gold_renewed`; builds `["*"]`; devices `null`; backend membership-service in `["3.12.0"]`
  - observed: "Home shows the 'Join Gold' banner; cart shows ₹40 delivery fee"
  - artifacts: video and screenshot URLs *(free)*; network: the status call with the excerpt above
  - sandbox_logs: membership-service status call 200, warn, the same signature, excerpt `{"status": "expired", "cache_hit": true}`
  - sandbox_logs_ok: membership-service status call 200, info, excerpt `{"status": "active", "cache_hit": false}`
- **Fix** `FIX-GOLD-01`: membership-be, backend, "Invalidate status cache synchronously on membership.renewed", `https://git.example.invalid/membership-service/pull/4412`, ships in `membership-service@3.12.1`.
- **Expected path:**
  1. Triage finds no duplicate (BUG-1180 is an iOS badge bug), reads the user and journey, and classifies it as backend.
  2. Espida finds renewal.success followed by a stale status, DEP-201, and an impact of 1284 users. It reports to membership-be.
  3. membership-be fixes it and runs `POST /sandbox/deploy` with membership-service 3.12.1.
  4. Telios sets up the mock user: `create_user` → `set_address DEL` → `set_group G7` → `activate_plan gold_annual` → `renew_plan gold_annual`.
  5. Kinetics runs `android-18.5` on `pixel-7` with step `home/open`. The result is not_reproduced, which means the fix passes.
  6. Espida's sandbox logs show `status: active`.
- **Unexpected paths the data supports:**
  - Kinetics reproduces before the fix: the result is reproduced.
  - Telios skips `renew_plan`: the result is not_reproduced. The journey shows `tap_renew`.
  - Someone asks about BUG-1180's area: the user's logs contain nothing about it.

### Scenario 2: CART-02, "Something went wrong" at checkout after a coupon

**Story:** On app versions 18.2–18.5, checkout crashes while rendering discounts when two discount rows exist (a Gold discount plus a coupon). The coupon row has no `label`, which the checkout API v3 contract marks as optional. The backend returns valid 200 responses, so this is a frontend bug. The fix ships in 18.6-rc1.

- **Report** `RPT-102` at `2026-11-04T13:40:00+05:30`: "Checkout shows 'Something went wrong' right after I apply a coupon. Works fine without the coupon. user U-77105". No attachments. The report does **not** name the coupon; the code exists only in the journey.
- **User** `U-77105`: android, 18.2, `redmi-note-10`, PNQ, G3, gold_monthly, plan_status `active`, cohort `android-18.2-PNQ-G3-gold_monthly`, flags `{"checkout_v3": "on"}`.
- **Journey** (2026-11-04): 13:31 `restaurant/open {restaurant_id: R-3391}` · 13:32 `restaurant/add_item {item_id: I-88, qty: 1}` · 13:32 `restaurant/add_item {item_id: I-91, qty: 2}` · 13:33 `cart/open` · 13:34 `cart/apply_coupon {code: SAVE50}` · 13:34 `checkout/open` · 13:34 `checkout/error_dialog {message: "Something went wrong"}` · 13:35 `cart/open` · 13:36 `checkout/open` · 13:36 `checkout/error_dialog`
- **Prod logs:**
  - `tr-cart02-1`, 13:34:02: cart-service `POST /cart/coupon` 200, info, "coupon SAVE50 applied"
  - `tr-cart02-2`, 13:34:05: checkout-service `GET /checkout/summary` 200, info, excerpt `{"discounts": [{"type": "gold", "label": "Gold discount", "amount": 30}, {"type": "coupon", "code": "SAVE50", "amount": 50}]}`
  - `tr-cart02-2`, 13:34:05: client, service `android-app`, error, "TypeError: Cannot read property 'label' of undefined at DiscountRow", signature `app.checkout.discount_row_crash`, app_version 18.2
  - `tr-cart02-3`, 13:36:04: the same client error again
  - `tr-cart02-4`, 13:31:20 (distractor): restaurant-service `GET /restaurants/R-3391/menu` 200, warn, "slow response 2.4s"
- **Deploys:** `DEP-203` (distractor) restaurant-service 2.19.0 at 2026-11-04T11:00+05:30, "Menu image CDN switch".
- **Impact:** `app.checkout.discount_row_crash`, first seen 2026-10-21T09:00+05:30, 3410 users, by version `{"18.2": 950, "18.3": 1120, "18.4": 820, "18.5": 520}`, note "Only orders with both a Gold discount and a coupon".
- **Known bugs (near miss):** `BUG-1207` "SAVE50 not applicable with Gold on orders under ₹199": wont_fix, backend, android+ios, versions 18.4 and 18.5, fixed_in `null`.
- **Repro rule** `R-CART02`:
  - trigger `checkout/open`; requires `plan:gold_monthly`, `cart`, `coupon:SAVE50`; builds `android-18.2`, `android-18.3`, `android-18.4`, `android-18.5`, `ios-18.4`, `ios-18.5`; devices `null`; backend `null`
  - observed: "Checkout shows a 'Something went wrong' dialog; the discount section never renders"
  - network: the coupon call and the summary call from the logs above
  - sandbox_logs: the client error with the same signature
  - sandbox_logs_ok: client, info, "checkout rendered with 2 discount rows"
- **Fix** `FIX-CART-02`: checkout-fe, frontend, "Render discount rows when label is missing", `https://git.example.invalid/consumer-app/pull/9921`, ships in `android-18.6-rc1`.
- **Expected path:**
  1. Triage finds no duplicate (BUG-1207 is a different issue). The bug looks unclear, so Triage asks Espida.
  2. Espida finds backend 200s plus a client crash signature, so it points to the frontend.
  3. Kinetics asks Telios for a setup. Telios gets `android-18.2`, which comes from github_actions and takes 18 minutes.
  4. Telios runs `create_user` → `set_address PNQ` → `set_group G3` → `activate_plan gold_monthly` → `fill_cart R-3391` → `apply_coupon SAVE50`. It has to ask Triage for the coupon code, which only the journey has.
  5. Kinetics runs `android-18.2` on `redmi-note-10` with `cart/open` and `checkout/open`. The result is reproduced, and it reports to checkout-fe.
  6. After the fix, Kinetics re-runs on `android-18.6-rc1`. The result is not_reproduced, which means the fix passes.
- **Unexpected paths the data supports:**
  - Telios skips the coupon: the result is not_reproduced.
  - Kinetics uses an ios build with this android mock user: 422.
  - Espida filters `source=client`: only the crash entries come back.

### Scenario 3: MENU-03, restaurant name overlaps the rating badge

**Story:** On iOS 18.4–18.5, small screens (iPhone SE) render very long restaurant names over the rating badge. This is purely a layout bug. The backend is fine, and no error is logged anywhere.

- **Report** `RPT-103` at `2026-11-04T19:05:00+05:30`: "On some restaurant pages the name runs over the rating so I can't read either. Screenshot attached. user U-23017". Attachments: `https://files.example.invalid/rpt-103-restaurant.png`. The report does **not** name the device; the device is only in the profile.
- **User** `U-23017`: ios, 18.5, `iphone-se-2`, BLR, G1, plan `none`, plan_status `none`, cohort `ios-18.5-BLR-G1-none`, flags `{}`.
- **Journey** (2026-11-04): 18:58 `search/query {q: "biryani"}` · 18:59 `search/open_result {restaurant_id: R-5520}` · 18:59 `restaurant/open {restaurant_id: R-5520, name: "Shree Annapoorna Ruchi Military Hotel & Biryani Mane"}` · 19:00 `restaurant/scroll` · 19:02 `search/open_result {restaurant_id: R-2210}` · 19:02 `restaurant/open {restaurant_id: R-2210, name: "Nandini Kitchen"}` · 19:04 `help/open`
- **Prod logs** (all info, all 200):
  - `tr-menu03-1`: restaurant-service `GET /restaurants/R-5520`, excerpt `{"name_length": 52, "rating": 4.1}`
  - `tr-menu03-2`: restaurant-service `GET /restaurants/R-2210`, excerpt `{"name_length": 15, "rating": 4.4}`
  - `tr-menu03-3`: search-service `GET /search?q=biryani`
- **Deploys, impact, known bugs:** none.
- **Repro rule** `R-MENU03`:
  - trigger `restaurant/open` with params `{restaurant_id: R-5520}`; requires none; builds `ios-18.4`, `ios-18.5`; devices `iphone-se-2`; backend `null`
  - observed: "Restaurant name wraps onto three lines and overlaps the 4.1★ rating badge"
  - network: the R-5520 call; sandbox_logs: none; sandbox_logs_ok: none
- **Fix** `FIX-MENU-03`: discovery-fe, frontend, "Clamp restaurant name to two lines and move the rating badge below it on small screens", `https://git.example.invalid/consumer-app/pull/9934`, ships in `ios-18.6-rc1`.
- **Expected path:**
  1. Triage finds no duplicate and classifies it as ui.
  2. Telios gets `ios-18.5` (from s3, ready immediately) and runs `create_user` → `set_address BLR` → `set_group G1`.
  3. Kinetics runs `ios-18.5` on `iphone-se-2` with `restaurant/open {restaurant_id: R-5520}`. The result is reproduced, and it reports to discovery-fe.
  4. After the fix, Kinetics runs `ios-18.6-rc1`. The result is not_reproduced, which means the fix passes.
- **Unexpected paths the data supports:**
  - Kinetics uses `iphone-15`: not_reproduced, so it must ask Triage for the device.
  - Kinetics opens R-2210: not_reproduced, because that name is short.
  - Espida checks the logs: only 200s.

### Scenario 4: PAY-04, UPI payment stuck on "Processing" (duplicate)

**Story:** This is a known bug, BUG-1152. On Android 14 with app 18.2–18.3, the UPI intent result never comes back to the app, so payment spins on "Processing". It was fixed in 18.4. The reporting user is on 18.3, so the right answer is "known issue, fixed in 18.4, please update".

- **Report** `RPT-104` at `2026-11-04T21:20:00+05:30`: "UPI payment keeps spinning on 'Processing', had to cancel the order. user U-61540".
- **User** `U-61540`: android, 18.3, `galaxy-m32`, BOM, G2, plan `none`, plan_status `none`, cohort `android-18.3-BOM-G2-none`, flags `{}`.
- **Journey** (2026-11-04): 21:12 `cart/open` · 21:13 `checkout/open` · 21:13 `payment/pay_upi {amount: 412}` · 21:13 `payment/processing` · 21:16 `payment/cancel` · 21:17 `help/open`
- **Prod logs:**
  - `tr-pay04-1`, 21:13:10: payment-service `POST /payments/upi/intent` 200, info, "intent created"
  - `tr-pay04-1`, 21:16:10: client `android-app`, warn, "upi_intent_timeout after 180s", signature `app.payment.upi_intent_timeout`, app_version 18.3
  - `tr-pay04-2`, 21:16:20: payment-service `POST /payments/cancel` 200, info
- **Known bugs:**
  - `BUG-1152` "UPI payment stuck on 'Processing' on Android 14": fixed, frontend, android, versions 18.2 and 18.3, affected_os `["14"]`, fixed in 18.4, thread `https://chat.example.invalid/app-bugs/p/1152`, signature `app.payment.upi_intent_timeout`
  - `BUG-1166` (near miss) "Card payments failing for one issuer bank": fixed, backend, android+ios, versions 18.4 and 18.5, fixed in `payment-service@9.0.2`
- **Impact:** `app.payment.upi_intent_timeout`, first seen 2026-09-30T10:00+05:30, 610 users, by version `{"18.2": 180, "18.3": 430}`, note "No occurrences on 18.4+".
- **Repro rule** `R-PAY04`:
  - trigger `payment/pay_upi`; requires `cart`, `payment_method:upi`; builds `android-18.2`, `android-18.3`; devices `galaxy-m32`, `pixel-7` (the Android 14 devices); backend `null`
  - observed: "Payment stays on 'Processing' for 3 minutes, then times out"
  - sandbox_logs: the client timeout with the same signature; sandbox_logs_ok: client, info, "upi intent result received"
- **Fix** `FIX-PAY-04`: bug_ref `BUG-1152`, checkout-fe, frontend, "Handle UPI intent result on Android 14", `https://git.example.invalid/consumer-app/pull/9655`, ships in `android-18.4`.
- **Expected path:** Triage matches BUG-1152: android, version 18.3 is affected, the device runs Android 14, and it's fixed in 18.4. Triage replies "Known issue BUG-1152, fixed in 18.4, please update" with the thread link. Done.
- **Unexpected paths the data supports:**
  - Espida finds the matching signature.
  - Telios runs `create_user` → `set_address BOM` → `set_group G2` → `add_payment_method upi` → `fill_cart R-1200`. Kinetics then runs `android-18.3` on `galaxy-m32` with `checkout/open` and `payment/pay_upi`: reproduced.
  - On `android-18.4`: not_reproduced, which confirms the update advice.
  - On `redmi-note-10` (Android 12): not_reproduced.

### Scenario 5: TRACK-05, order tracking screen blank after a backend change

**Story:** order-tracking-service 5.3.0 was deployed on 2026-11-04 at 11:30. It changed `eta` from an integer number of minutes to an object `{min, max}` (schema v2) for every client. Apps on 18.4+ handle v2. Apps on 18.2–18.3 crash rendering the tracking header and show a blank screen. Old app versions can't be patched, so the backend fixes it by serving schema v1 to apps below 18.4 (5.3.1).

- **Report** `RPT-105` at `2026-11-04T20:45:00+05:30`: "Track order screen is completely blank. Ordered 20 minutes ago and can't see where it is. user U-90877".
- **User** `U-90877`: android, 18.3, `oneplus-nord`, HYD, G4, gold_trial, plan_status `active`, cohort `android-18.3-HYD-G4-gold_trial`, flags `{}`.
- **Journey** (2026-11-04): 20:24 `checkout/place_order {order_id: O-551203, restaurant_id: R-7781}` · 20:25 `order_tracking/open {order_id: O-551203}` · 20:25 `order_tracking/blank_screen` · 20:31 `order_tracking/open {order_id: O-551203}` · 20:31 `order_tracking/blank_screen` · 20:44 `help/open`
- **Prod logs:**
  - `tr-track05-1`, 20:25:03: order-tracking-service `GET /orders/O-551203/track` 200, info, excerpt `{"schema_version": 2, "eta": {"min": 25, "max": 35}, "status": "preparing"}`
  - `tr-track05-1`, 20:25:03: client `android-app`, error, "TypeError: eta.toFixed is not a function at TrackingHeader", signature `app.tracking.eta_type_error`, app_version 18.3
  - `tr-track05-2`, 20:31:02: the same pair again
- **Deploys:** `DEP-205` order-tracking-service 5.3.0 at 2026-11-04T11:30+05:30, "ETA returned as a range {min, max} (schema v2) for all clients".
- **Impact:** `app.tracking.eta_type_error`, first seen 2026-11-04T11:34+05:30, 9870 users, by version `{"18.2": 3100, "18.3": 6770}`, note "No occurrences on 18.4+".
- **Known bugs (near miss):** `BUG-1190` "Tracking map not loading on slow networks": open, frontend, android, versions 18.4 and 18.5, fixed_in `null`.
- **Repro rule** `R-TRACK05`:
  - trigger `order_tracking/open`; requires `order:active`; builds `android-18.2`, `android-18.3`; devices `null`; backend order-tracking-service in `["5.3.0"]`
  - observed: "Tracking screen renders blank white; no ETA, no map"
  - sandbox_logs: the backend 200 with the schema v2 excerpt, plus the client error with the same signature
  - sandbox_logs_ok: backend 200, info, excerpt `{"schema_version": 1, "eta": 30, "status": "preparing"}`
- **Fix** `FIX-TRACK-05`: logistics-be, backend, "Serve tracking schema v1 to app versions below 18.4", `https://git.example.invalid/order-tracking-service/pull/731`, ships in `order-tracking-service@5.3.1`.
- **Expected path:**
  1. Triage finds no duplicate (BUG-1190 is the map) and classifies it as unclear.
  2. Espida finds a backend 200, a client type error, DEP-205, and impact only on versions ≤18.3. That makes it both: the backend broke the contract for old clients.
  3. logistics-be fixes it, and orders-fe is informed.
  4. logistics-be runs `POST /sandbox/deploy` with order-tracking-service 5.3.1.
  5. Telios runs `create_user` → `set_address HYD` → `set_group G4` → `activate_plan gold_trial` → `add_payment_method upi` → `place_order R-7781`.
  6. Kinetics runs `android-18.3` with `order_tracking/open`. The result is not_reproduced, which means the fix passes.
  7. Espida's sandbox logs show `schema_version: 1`.
- **Unexpected paths the data supports:**
  - Before the fix, `android-18.4`: not_reproduced, which is a clue that newer apps cope.
  - Telios skips `place_order`: not_reproduced.
  - `place_order` before `add_payment_method`: 409.

---

## Tasks

Run all commands from `the repository root`.

### Task 1: Project skeleton, models, loader, shared data

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `bugmock/__init__.py`, `bugmock/models.py`, `bugmock/store.py`, `data/shared.json`, `tests/test_store.py`

**Interfaces:**
- Produces:
  - every model in **Data Model**, in `bugmock/models.py`
  - `bugmock.store.DataError(Exception)`
  - `bugmock.store.DATA_DIR: Path`, which points at `<repo>/data`
  - `bugmock.store.load_dataset(data_dir: Path) -> Dataset`: reads `shared.json` and `scenarios/*.json` (sorted by name), concatenates lists that share a key, validates, then runs the integrity checks below
  - `bugmock.store.parse_cohort_id(cohort_id: str, dims: CohortDimensions) -> dict[str, str]`: splits on `-` into exactly 5 parts (`platform`, `app_version`, `city`, `group`, `plan`). Raises `DataError` if the count is wrong or any part is not a known dimension value.
  - `class Store`, with `__init__(self, dataset: Dataset)`:
    - attribute `dataset`
    - dict indexes keyed by ID: `users`, `reports`, `known_bugs`, `journeys` (keyed by user_id), `builds`, `devices`, `setup_apis` (keyed by name), `teams`, `fixes`, `scenarios`, `impacts` (keyed by error_signature)
    - lists: `logs`, `deploys`, `repro_rules`
  - Integrity checks, each raising `DataError` with the offending ID in the message:
    - no duplicate IDs within any collection
    - each `user.cohort_id` equals `f"{platform}-{app_version}-{city}-{group}-{plan}"`, and every part is valid
    - each `user.device_id` exists, and its platform matches the user's
    - `report.user_id`, `journey.user_id`, prod `log.user_id`, `scenario.report_id`, `scenario.fix_id`, `scenario.duplicate_of` (checked against known_bugs) and `fix.team_id` all exist
    - repro rule `affected_builds` (unless `"*"`) and `devices` exist
    - each `fix.bug_ref` exists in either known_bugs or reports
    - `cohort_dimensions` appears exactly once
  - A missing or empty `data/scenarios/` folder is valid: it loads shared data only.

- [ ] **Step 1: Initialise the project.** Run `git init`. Create a `pyproject.toml` named `bugmock` with `requires-python = ">=3.12"`, the dependencies from Global Constraints, and pytest `testpaths = ["tests"]`. The `.gitignore` covers `.venv/` and `__pycache__/`. Run `uv sync`. Expected: it exits 0.
- [ ] **Step 2: Write the failing tests** in `tests/test_store.py`. A helper `write_dataset(tmp_path, shared: dict, scenarios: dict[str, dict]) -> Path` writes files into `tmp_path`.

```python
def test_shared_data_loads():
    ds = load_dataset(DATA_DIR)
    assert len(ds.cohort_dimensions.groups) == 10
    assert set(ds.cohort_dimensions.cities) == {"DEL", "BOM", "BLR", "PNQ", "HYD"}
    assert len(ds.setup_apis) == 9 and len(ds.builds) == 8 and len(ds.devices) == 6 and len(ds.teams) == 7

def test_duplicate_id_rejected(tmp_path):    # two scenario files both define user U-00001 → DataError matching "U-00001"
def test_cohort_mismatch_rejected(tmp_path): # user with city PNQ but cohort_id ...-DEL-... → DataError matching the user_id
def test_unknown_device_rejected(tmp_path):  # user.device_id "nokia-1" → DataError matching "nokia-1"
def test_parse_cohort_id():
    dims = load_dataset(DATA_DIR).cohort_dimensions
    assert parse_cohort_id("android-18.5-DEL-G7-gold_annual", dims) == {
        "platform": "android", "app_version": "18.5", "city": "DEL", "group": "G7", "plan": "gold_annual"}
    with pytest.raises(DataError): parse_cohort_id("android-18.5-XXX-G7-gold_annual", dims)
```

- [ ] **Step 3: Run the tests.** Command: `uv run pytest tests/test_store.py -v`. Expected: FAIL with an ImportError.
- [ ] **Step 4: Implement** `models.py` and `store.py`, and write `data/shared.json` from **Shared Data**.
- [ ] **Step 5: Run the tests again.** Command: `uv run pytest tests/test_store.py -v`. Expected: 5 passed.
- [ ] **Step 6: Commit.** Run `git add -A && git commit -m "feat: models, JSON loader and shared data"`.

### Task 2: GOLD-01 scenario data

**Files:**
- Create: `data/scenarios/GOLD-01.json`
- Modify: `tests/test_store.py`

**Interfaces:**
- Consumes: `load_dataset`, `Store`, `DATA_DIR` (Task 1)

- [ ] **Step 1: Write the failing test.**

```python
def test_gold01_records():
    s = Store(load_dataset(DATA_DIR))
    assert s.users["U-48213"].cohort_id == "android-18.5-DEL-G7-gold_annual"
    assert s.reports["RPT-101"].user_id == "U-48213"
    assert s.scenarios["GOLD-01"].expected_class == "backend"
    assert any(l.error_signature == "membership.stale_status_after_renewal" for l in s.logs)
    assert [d.version for d in s.deploys if d.deploy_id == "DEP-201"] == ["3.12.0"]
    assert s.fixes["FIX-GOLD-01"].ships_in == "membership-service@3.12.1"
    assert s.known_bugs["BUG-1180"].status == "fixed"
```

- [ ] **Step 2: Run the test.** Command: `uv run pytest tests/test_store.py::test_gold01_records -v`. Expected: FAIL with a KeyError on `U-48213`.
- [ ] **Step 3: Write `data/scenarios/GOLD-01.json`** from **Scenario 1**.
- [ ] **Step 4: Run the full test file.** Command: `uv run pytest tests/test_store.py -v`. Expected: all pass.
- [ ] **Step 5: Commit.** Run `git add -A && git commit -m "data: GOLD-01 scenario"`.

### Task 3: Read-only API

**Files:**
- Create: `bugmock/errors.py`, `bugmock/api.py`, `tests/conftest.py`, `tests/test_read_api.py`

**Interfaces:**
- Consumes: `Store`, `load_dataset`, `parse_cohort_id`, `DATA_DIR` (Task 1)
- Produces:
  - `bugmock.errors.ApiError(Exception)`, with `__init__(self, status_code: int, detail: str)`. `api.py` registers a handler that returns `JSONResponse({"detail": detail}, status_code)`.
  - `bugmock.api.create_app(data_dir: Path = DATA_DIR) -> FastAPI`, which stores a `Store` on `app.state.store`. Module-level `app = create_app()`.
  - `tests/conftest.py` fixture `client() -> TestClient` built on `create_app()`. Task 4 extends it to reset the sandbox.
  - Every GET route in **API Surface** except the `/sandbox/*` ones. On `/logs`, `env=sandbox` returns `[]` until Task 4. `from`/`to` are parsed as timezone-aware datetimes and compared with each other. Reports are returned without `scenario_id`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_get_user(client):        r = client.get("/users/U-48213"); assert r.status_code == 200 and r.json()["cohort_id"] == "android-18.5-DEL-G7-gold_annual"
def test_unknown_user_404(client): r = client.get("/users/U-00000"); assert r.status_code == 404 and "U-00000" in r.json()["detail"]
def test_report_hides_scenario(client): assert "scenario_id" not in client.get("/reports/RPT-101").json()
def test_cohort_breakdown(client):
    c = client.get("/cohorts/android-18.5-DEL-G7-gold_annual").json()
    assert c["city"] == {"code": "DEL", "name": "Delhi NCR"} and c["group"] == {"id": "G7", "label": "Gold loyalist"}
def test_bad_cohort_422(client):  assert client.get("/cohorts/android-18.5-XXX-G7-gold_annual").status_code == 422
def test_logs_window_timezones(client):
    z = client.get("/logs", params={"user_id": "U-48213", "from": "2026-11-04T04:00:00Z", "to": "2026-11-04T05:00:00Z"}).json()
    ist = client.get("/logs", params={"user_id": "U-48213", "from": "2026-11-04T09:30:00+05:30", "to": "2026-11-04T10:30:00+05:30"}).json()
    assert z == ist and any(l["error_signature"] == "membership.stale_status_after_renewal" for l in z)
def test_trace(client): assert {l["service"] for l in client.get("/traces/tr-gold01-1").json()} == {"payment-service", "membership-service"}
def test_unknown_trace_404(client): assert client.get("/traces/tr-nope").status_code == 404
def test_build_lookup(client):
    assert client.get("/builds/android-18.2").json()["source"] == "github_actions"
    assert client.get("/builds/android-17.9").status_code == 404
def test_admin_scenario_has_rules(client): assert client.get("/admin/scenarios/GOLD-01").json()["repro_rules"][0]["rule_id"] == "R-GOLD01"
```

- [ ] **Step 2: Run the tests.** Command: `uv run pytest tests/test_read_api.py -v`. Expected: FAIL with an ImportError.
- [ ] **Step 3: Implement** `errors.py`, `api.py` and `conftest.py`. `GET /admin/scenarios/{id}` returns `{"scenario": Scenario, "report": Report, "user": User, "logs": [prod logs for that user], "repro_rules": [rules with that scenario_id], "fixes": [fix_id + fixes whose bug_ref is the report or duplicate_of], "known_bugs": [the scenario file's known bugs]}`. That means the loader keeps a `scenario_id → known_bug_ids` map while it merges files.
- [ ] **Step 4: Run the tests again.** Command: `uv run pytest -v`. Expected: all pass.
- [ ] **Step 5: Commit.** Run `git add -A && git commit -m "feat: read-only API for triage, espida, telios and teams"`.

### Task 4: Sandbox (mock users, setup calls, deploys, reset)

**Files:**
- Create: `bugmock/sandbox.py`, `tests/test_sandbox.py`
- Modify: `bugmock/api.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: `Store`, `parse_cohort_id` (Task 1); `ApiError` (Task 3)
- Produces:
  - `class MockUser(BaseModel)`: `mock_user_id: str; cohort_id: str; platform: str; app_version: str; login: dict[str, str]; tags: list[str]; calls: list[dict[str, Any]]`
  - `has_tag(tags: list[str], requirement: str) -> bool`, using the rule in **Tags**
  - `class Sandbox`, with `__init__(self, store: Store)`:
    - attributes `services: dict[str, str]`, `logs: list[LogEntry]`, `users: dict[str, MockUser]`
    - `create_user(cohort_id: str) -> MockUser`: an invalid cohort is a 422 `ApiError`. Login is `{"phone": f"+91-90000-0{n:04d}", "otp": "000000"}`. Tags come from the `create_user` catalog entry.
    - `apply(mock_user_id: str, api_name: str, params: dict[str, Any]) -> MockUser`, with errors in this order: unknown user → 404; unknown API, or `create_user` → 404; missing param → 422 naming it; unmet requirement → 409 with detail `"missing prerequisite '<req>': call <api that adds it> first"`. On success it appends the call and the expanded `adds_tags` (`str.format(**params)`), skipping duplicates.
    - `get(mock_user_id: str) -> MockUser` (404 if unknown)
    - `deploy(service: str, version: str) -> dict[str, str]`: 404 if the service isn't in `sandbox_defaults`
    - `next_run_id() -> str`, giving `RUN-0001`, `RUN-0002`, …
    - `reset() -> None`: clears users, logs and counters, and restores the services from `sandbox_defaults`
  - `app.state.sandbox`, plus the `/sandbox/*` routes from **API Surface**. `GET /logs?env=sandbox` reads `sandbox.logs` with the same filters. The `client` fixture calls `POST /sandbox/reset` before yielding.

- [ ] **Step 1: Write the failing tests.**

```python
def test_sequential_ids_and_login(client):
    a = client.post("/sandbox/users", json={"cohort_id": "android-18.5-DEL-G7-gold_annual"}).json()
    b = client.post("/sandbox/users", json={"cohort_id": "android-18.5-DEL-G7-gold_annual"}).json()
    assert (a["mock_user_id"], b["mock_user_id"]) == ("MU-0001", "MU-0002")
    assert a["login"] == {"phone": "+91-90000-00001", "otp": "000000"} and a["platform"] == "android"
def test_setup_in_order(client):      # set_address{city:DEL,area:Saket} → set_group{group:G7} → activate_plan{plan:gold_annual}
    ...                                # assert {"address:DEL","group:G7","plan:gold_annual","plan_status:active"} <= set(tags)
def test_wrong_order_409(client):     # activate_plan first → 409; "address" in detail and "set_address" in detail
def test_missing_param_422(client):   # set_address with {"city": "DEL"} only → 422; "area" in detail
def test_unknown_mock_user_404(client): assert client.get("/sandbox/users/MU-9999").status_code == 404
def test_bad_cohort_422(client):      # POST /sandbox/users with "android-18.5-XXX-G7-gold_annual" → 422
def test_deploy_and_reset(client):
    client.post("/sandbox/deploy", json={"service": "membership-service", "version": "3.12.1"})
    assert client.get("/sandbox/services").json()["membership-service"] == "3.12.1"
    client.post("/sandbox/users", json={"cohort_id": "android-18.5-DEL-G7-gold_annual"})
    client.post("/sandbox/reset")
    assert client.get("/sandbox/services").json()["membership-service"] == "3.12.0"
    assert client.post("/sandbox/users", json={"cohort_id": "android-18.5-DEL-G7-gold_annual"}).json()["mock_user_id"] == "MU-0001"
    assert client.get("/logs", params={"env": "sandbox"}).json() == []
def test_deploy_unknown_service_404(client): assert client.post("/sandbox/deploy", json={"service": "nope", "version": "1"}).status_code == 404
```

- [ ] **Step 2: Run the tests.** Command: `uv run pytest tests/test_sandbox.py -v`. Expected: FAIL with 404s, because the routes don't exist yet.
- [ ] **Step 3: Implement** `sandbox.py`, the routes, and the fixture reset.
- [ ] **Step 4: Run the tests again.** Command: `uv run pytest -v`. Expected: all pass.
- [ ] **Step 5: Commit.** Run `git add -A && git commit -m "feat: in-memory sandbox for telios setup calls"`.

### Task 5: Repro runs, plus the GOLD-01 walkthrough

**Files:**
- Create: `bugmock/repro.py`, `tests/test_repro.py`, `tests/test_scenario_gold01.py`
- Modify: `bugmock/api.py`

**Interfaces:**
- Consumes: `Store` (Task 1), `ApiError` (Task 3), `Sandbox` and `has_tag` (Task 4)
- Produces:
  - `class ReproStep(BaseModel)`: `screen: str; action: str; params: dict[str, Any] = {}`
  - `class ReproRequest(BaseModel)`: `build_id: str; mock_user_id: str; device_id: str; steps: list[ReproStep]`
  - `class ReproResult(BaseModel)`: `run_id: str; result: Literal["reproduced","not_reproduced"]; observed: str; artifacts: dict[str, str]; network: list[dict[str, Any]]`
  - `step_matches(step: ReproStep, trigger: Trigger) -> bool`: screen and action are equal, and `trigger.params` is a subset of `step.params`
  - `run_repro(req: ReproRequest, store: Store, sandbox: Sandbox) -> ReproResult`
  - Routes `POST /repro/runs` and `GET /devices`

`run_repro` algorithm, which the signature does not determine:
```
build, device, user = lookups → 404 ApiError naming the unknown id
if not build.platform == device.platform == user.platform → 422 "platform mismatch: build <p>, device <p>, mock user <p>"
run_id = sandbox.next_run_id()
for rule in store.repro_rules (file order):
    if no step matches rule.trigger: continue
    ok = all(has_tag(user.tags, t) for t in rule.requires_tags)
         and ("*" in rule.affected_builds or build.build_id in rule.affected_builds)
         and (rule.devices is None or device.device_id in rule.devices)
         and (rule.backend is None or sandbox.services[rule.backend.service] in rule.backend.versions)
    if ok: write rule.sandbox_logs; return reproduced with rule.observed / artifacts / network
    write rule.sandbox_logs_ok
return not_reproduced, observed "Completed all steps; no problem seen.",
       artifacts {"video_url": f"https://artifacts.example.invalid/{run_id}.mp4"}, network []
```
Writing a template creates a `LogEntry` with `log_id=f"SBX-{run_id}-{i}"`, `ts=now` in IST, `env="sandbox"`, `user_id=mock_user_id`, `trace_id=f"tr-{run_id}"` and `app_version=build.app_version`.

- [ ] **Step 1: Write the failing tests.** In `test_repro.py`:

```python
def test_step_matches_param_subset():
    t = Trigger(screen="restaurant", action="open", params={"restaurant_id": "R-5520"})
    assert step_matches(ReproStep(screen="restaurant", action="open", params={"restaurant_id": "R-5520", "x": 1}), t)
    assert not step_matches(ReproStep(screen="restaurant", action="open", params={"restaurant_id": "R-2210"}), t)
def test_platform_mismatch_422(client):  # android mock user + build ios-18.5 + device iphone-15 → 422; "android" and "ios" in detail
def test_unknown_build_404(client):      # build "android-17.9" → 404 naming it
```

Add a fixture to `tests/conftest.py`: `setup_user(client) -> Callable[[str, list[tuple[str, dict]]], str]`. It creates a mock user for the cohort, applies each call in order, asserts every response is 200, and returns the mock_user_id. Tasks 6–9 reuse it.

```python
GOLD_CALLS = [("set_address", {"city": "DEL", "area": "Saket"}), ("set_group", {"group": "G7"}),
              ("activate_plan", {"plan": "gold_annual"}), ("renew_plan", {"plan": "gold_annual"})]
def test_gold01_expected_path(client, setup_user):
    mu = setup_user("android-18.5-DEL-G7-gold_annual", GOLD_CALLS)
    run = lambda: client.post("/repro/runs", json={"build_id": "android-18.5", "mock_user_id": mu, "device_id": "pixel-7",
                                                    "steps": [{"screen": "home", "action": "open"}]}).json()
    first = run(); assert first["result"] == "reproduced" and "Join Gold" in first["observed"]
    client.post("/sandbox/deploy", json={"service": "membership-service", "version": "3.12.1"})
    assert run()["result"] == "not_reproduced"
    logs = client.get("/logs", params={"env": "sandbox", "user_id": mu}).json()
    assert logs[-1]["response_excerpt"]["status"] == "active"
def test_gold01_without_renewal(client, setup_user):  # GOLD_CALLS[:3] only → not_reproduced
```

- [ ] **Step 2: Run the tests.** Command: `uv run pytest tests/test_repro.py tests/test_scenario_gold01.py -v`. Expected: FAIL with an ImportError.
- [ ] **Step 3: Implement** `repro.py`, the routes, and the `setup_user` fixture.
- [ ] **Step 4: Run the tests again.** Command: `uv run pytest -v`. Expected: all pass.
- [ ] **Step 5: Commit.** Run `git add -A && git commit -m "feat: repro runs and GOLD-01 walkthrough"`.

### Tasks 6–9: The remaining four scenarios

Each task has the same shape:
1. Write the walkthrough test.
2. Run it. Expected: FAIL with a 404 or 422, because the data is missing.
3. Write the scenario JSON from its section under **Scenarios**.
4. Run `uv run pytest -v`. Expected: all pass.
5. Commit with `data: <ID> scenario`.

All four consume the `setup_user(cohort, calls) -> mock_user_id` fixture from Task 5, which fails the test if any setup call is not 200, plus `POST /repro/runs`. Below, `run(build, device, steps)` stands for a local helper that posts a ReproRequest for the test's mock user and returns the JSON.

#### Task 6: CART-02

**Files:** create `data/scenarios/CART-02.json` and `tests/test_scenario_cart02.py`.

```python
CART_CALLS = [("set_address", {"city": "PNQ", "area": "Baner"}), ("set_group", {"group": "G3"}),
              ("activate_plan", {"plan": "gold_monthly"}),
              ("fill_cart", {"restaurant_id": "R-3391", "items": [{"item_id": "I-88", "qty": 1}, {"item_id": "I-91", "qty": 2}]}),
              ("apply_coupon", {"code": "SAVE50"})]
STEPS = [{"screen": "cart", "action": "open"}, {"screen": "checkout", "action": "open"}]
def test_cart02_expected_path(client, setup_user):
    assert client.get("/builds/android-18.2").json()["ready_in_minutes"] == 18
    mu = setup_user("android-18.2-PNQ-G3-gold_monthly", CART_CALLS)
    r = run("android-18.2", "redmi-note-10", STEPS); assert r["result"] == "reproduced" and "Something went wrong" in r["observed"]
    assert run("android-18.6-rc1", "redmi-note-10", STEPS)["result"] == "not_reproduced"
def test_cart02_coupon_only_in_journey(client):
    assert "SAVE50" not in client.get("/reports/RPT-102").json()["text"]
    events = client.get("/users/U-77105/journey").json()["events"]
    assert any(e["action"] == "apply_coupon" and e["params"]["code"] == "SAVE50" for e in events)
def test_cart02_without_coupon(client, setup_user):  # CART_CALLS[:4] → not_reproduced on android-18.2
def test_cart02_client_logs(client):
    logs = client.get("/logs", params={"user_id": "U-77105", "source": "client"}).json()
    assert len(logs) == 2 and {l["error_signature"] for l in logs} == {"app.checkout.discount_row_crash"}
```

#### Task 7: MENU-03

**Files:** create `data/scenarios/MENU-03.json` and `tests/test_scenario_menu03.py`.

```python
MENU_CALLS = [("set_address", {"city": "BLR", "area": "Indiranagar"}), ("set_group", {"group": "G1"})]
OPEN = lambda rid: [{"screen": "restaurant", "action": "open", "params": {"restaurant_id": rid}}]
def test_menu03_small_screen(client, setup_user):   # ios-18.5 + iphone-se-2 + OPEN("R-5520") → reproduced, "overlaps" in observed
def test_menu03_regular_screen(client, setup_user): # ios-18.5 + iphone-15 + OPEN("R-5520") → not_reproduced
def test_menu03_short_name(client, setup_user):     # ios-18.5 + iphone-se-2 + OPEN("R-2210") → not_reproduced
def test_menu03_fixed_build(client, setup_user):    # ios-18.6-rc1 + iphone-se-2 + OPEN("R-5520") → not_reproduced
def test_menu03_logs_clean(client):
    logs = client.get("/logs", params={"user_id": "U-23017"}).json()
    assert logs and all(l["level"] == "info" and l["status"] == 200 for l in logs)
    assert client.get("/users/U-23017").json()["device_id"] == "iphone-se-2"
```

#### Task 8: PAY-04

**Files:** create `data/scenarios/PAY-04.json` and `tests/test_scenario_pay04.py`.

```python
PAY_CALLS = [("set_address", {"city": "BOM", "area": "Andheri"}), ("set_group", {"group": "G2"}),
             ("add_payment_method", {"type": "upi"}), ("fill_cart", {"restaurant_id": "R-1200", "items": [{"item_id": "I-12", "qty": 1}]})]
STEPS = [{"screen": "checkout", "action": "open"}, {"screen": "payment", "action": "pay_upi"}]
def test_pay04_known_bug_matches_user(client):
    bug, user = client.get("/known-bugs/BUG-1152").json(), client.get("/users/U-61540").json()
    device = next(d for d in client.get("/devices").json() if d["device_id"] == user["device_id"])
    assert bug["fixed_in"] == "18.4" and user["app_version"] in bug["affected_versions"] and device["os_version"] in bug["affected_os"]
    assert client.get("/admin/scenarios/PAY-04").json()["scenario"]["duplicate_of"] == "BUG-1152"
def test_pay04_repro_matrix(client, setup_user):
    # android-18.3 + galaxy-m32 → reproduced; android-18.4 + galaxy-m32 → not_reproduced; android-18.3 + redmi-note-10 → not_reproduced
def test_pay04_fix_record(client):
    assert [f["ships_in"] for f in client.get("/fixes", params={"bug_ref": "BUG-1152"}).json()] == ["android-18.4"]
```

#### Task 9: TRACK-05

**Files:** create `data/scenarios/TRACK-05.json` and `tests/test_scenario_track05.py`.

```python
TRACK_CALLS = [("set_address", {"city": "HYD", "area": "Madhapur"}), ("set_group", {"group": "G4"}),
               ("activate_plan", {"plan": "gold_trial"}), ("add_payment_method", {"type": "upi"}),
               ("place_order", {"restaurant_id": "R-7781", "items": [{"item_id": "I-301", "qty": 1}]})]
STEPS = [{"screen": "order_tracking", "action": "open"}]
def test_track05_order_needs_payment_409(client, setup_user):
    # setup_user(TRACK_CALLS[:3]), then POST place_order directly → 409; "payment_method" and "add_payment_method" in detail
def test_track05_expected_path(client, setup_user):
    # android-18.3 + oneplus-nord → reproduced; deploy order-tracking-service 5.3.1 → not_reproduced;
    # last sandbox log for the mock user has response_excerpt["schema_version"] == 1
def test_track05_newer_app_copes(client, setup_user):  # before any deploy: android-18.4 + oneplus-nord → not_reproduced
def test_track05_evidence(client):
    assert any(d["deploy_id"] == "DEP-205" and d["version"] == "5.3.0"
               for d in client.get("/deploys", params={"service": "order-tracking-service"}).json())
    assert set(client.get("/impact/app.tracking.eta_type_error").json()["by_app_version"]) == {"18.2", "18.3"}
```

### Task 10: Leak check, README, smoke run

**Files:**
- Create: `README.md`, `tests/test_contract.py`

- [ ] **Step 1: Write the tests.**

```python
def test_all_five_scenarios(client):
    got = {s["scenario_id"]: s["expected_class"] for s in client.get("/admin/scenarios").json()}
    assert got == {"GOLD-01": "backend", "CART-02": "frontend", "MENU-03": "ui", "PAY-04": "duplicate", "TRACK-05": "both"}
AGENT_PATHS = ["/reports/RPT-101", "/reports/RPT-105", "/users/U-90877", "/users/U-77105/journey", "/known-bugs",
               "/logs?user_id=U-77105", "/deploys", "/builds", "/setup-apis", "/teams", "/fixes", "/devices"]
@pytest.mark.parametrize("path", AGENT_PATHS)
def test_agent_routes_do_not_leak(client, path):
    body = client.get(path).text
    assert "scenario_id" not in body and "expected_" not in body and "rule_id" not in body
```

- [ ] **Step 2: Run the tests.** Command: `uv run pytest tests/test_contract.py -v`. Expected: PASS. If any route leaks, fix it in `api.py` and run again.
- [ ] **Step 3: Write `README.md`.** It covers how to run (`uv sync`, then `uv run uvicorn bugmock.api:app --port 8090`), the **API Surface** table, a scenario index (ID, bug, class, report ID, user ID), and "Adding a scenario": copy a scenario file, keep IDs unique, add a walkthrough test, run `uv run pytest`.
- [ ] **Step 4: Smoke run.** Start `uv run uvicorn bugmock.api:app --port 8090` in the background, then run `curl -s localhost:8090/users/U-48213`. Expected: JSON with `"cohort_id":"android-18.5-DEL-G7-gold_annual"`. Stop the server afterwards.
- [ ] **Step 5: Run the full suite.** Command: `uv run pytest -v`. Expected: all pass.
- [ ] **Step 6: Commit.** Run `git add -A && git commit -m "docs: README; test: no scenario leaks on agent routes"`.
