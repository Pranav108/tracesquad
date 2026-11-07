"""Agent prompts must only point agents at endpoints that exist, and never at /admin."""

import re
from pathlib import Path

import pytest

import yaml

from tracesquad.api import create_app

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
AGENTS = [a["name"] for a in yaml.safe_load((ROOT / "squad.yaml").read_text())["agents"]]
# An endpoint as the prompts name it (`GET /fixes/{fix_id}`), not a concrete call (`tsq GET /fixes/FIX-1`).
ENDPOINT = re.compile(r"(?<!tsq )\b(GET|POST) (/[A-Za-z0-9_{}./-]+)")
TSQ_CALL = re.compile(r"~/\.tracesquad/bin/tsq (GET|POST) '?(/[^'`\s?]*)")


def routes() -> set[tuple[str, str]]:
    # The OpenAPI schema is what agents see, and it lists routes from included routers.
    paths = create_app().openapi()["paths"]
    return {(method.upper(), path) for path, ops in paths.items() for method in ops}


@pytest.mark.parametrize("agent", AGENTS)
def test_prompt_endpoints_exist(agent):
    text = (PROMPTS / f"{agent}.md").read_text()
    found = {(m, p.rstrip(".")) for m, p in ENDPOINT.findall(text)}
    assert found, f"{agent}.md names no endpoints"
    unknown = found - routes()
    assert not unknown, f"{agent}.md names endpoints that do not exist: {sorted(unknown)}"


@pytest.mark.parametrize("agent", AGENTS)
def test_prompt_hides_admin_and_names_peers(agent):
    text = (PROMPTS / f"{agent}.md").read_text()
    assert "/admin" not in text
    for peer in AGENTS:
        assert peer.capitalize() in text, f"{agent}.md does not mention {peer.capitalize()}"


def scenario_values() -> set[str]:
    """Ids and values that would give a scenario away if a prompt contained them."""
    from tracesquad.store import DATA_DIR, Store, load_dataset

    s = Store(load_dataset(DATA_DIR))
    values = set(s.users) | set(s.reports) | set(s.known_bugs) | set(s.fixes) | set(s.impacts)
    values |= {log.trace_id for log in s.logs}
    values |= set(s.changes) | set(s.prds) | set(s.threads) | {endpoint for _, endpoint in s.api_checks}
    for journey in s.journeys.values():
        for event in journey.events:
            for key in ("restaurant_id", "code", "order_id"):
                if key in event.params:
                    values.add(str(event.params[key]))
    return values


@pytest.mark.parametrize("agent", AGENTS)
def test_prompt_calls_the_api_through_tsq_and_holds_no_url(agent):
    text = (PROMPTS / f"{agent}.md").read_text()
    assert "## Tools: the TraceSquad API" in text
    assert "Call the API **only** through `tsq`" in text
    assert not re.search(r"https?://", text), f"{agent}.md contains a URL; agents find the API through tsq"
    assert "never invent a response" in text and "not reachable" in text


@pytest.mark.parametrize("agent", AGENTS)
def test_prompt_tsq_examples_hit_real_routes(agent):
    text = (PROMPTS / f"{agent}.md").read_text()
    patterns = [(m, re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", p) + "$")) for m, p in routes()]
    calls = TSQ_CALL.findall(text)
    assert calls, f"{agent}.md shows no tsq call"
    for method, path in calls:
        assert any(m == method and rx.match(path) for m, rx in patterns), f"{agent}.md: tsq {method} {path} matches no route"


@pytest.mark.parametrize("agent", AGENTS)
def test_prompt_has_no_scenario_values(agent):
    text = (PROMPTS / f"{agent}.md").read_text()
    leaked = sorted(v for v in scenario_values() if v in text)
    assert not leaked, f"{agent}.md gives away scenario values: {leaked}"


@pytest.mark.parametrize("agent", AGENTS)
def test_prompt_protocol_has_channel_and_rca(agent):
    text = (PROMPTS / f"{agent}.md").read_text()
    assert "channel=" in text and "[RCA]" in text


def test_scenario_values_cover_atlas_gremlin_data():
    assert {"CHG-401", "PRD-CHECKOUT-V3", "THR-121", "/v2/membership/status", "/orders/active/track"} <= scenario_values()


def test_verification_requires_a_baseline():
    kinetics = (PROMPTS / "kinetics.md").read_text()
    atlas = (PROMPTS / "atlas.md").read_text()
    assert "baseline" in kinetics and "inconclusive" in kinetics
    assert "baseline" in atlas


def test_atlas_searches_app_changes_by_release():
    atlas = (PROMPTS / "atlas.md").read_text()
    assert "released in or before the reporter's app version" in atlas


@pytest.mark.parametrize("agent", AGENTS)
def test_protocol_keeps_bugs_moving_and_ends_them(agent):
    text = (PROMPTS / f"{agent}.md").read_text()
    assert "[NUDGE]" in text and "[CLOSE]" in text
    assert "wakes only the agents it is sent to" in text
    assert "Never go quiet" in text and "`[REPORT]` to **Triage**" in text
    for outcome in ("duplicate", "known_open", "wont_fix", "already_fixed", "not_reproduced", "escalated"):
        assert outcome in text, f"{agent}.md protocol is missing the {outcome} outcome"


def test_triage_watches_and_closes():
    triage = (PROMPTS / "triage.md").read_text()
    assert "## Keeping bugs moving" in triage and "sweep" in triage
    assert "## How a bug ends" in triage
    for outcome in ("duplicate", "known_open", "wont_fix", "already_fixed", "not_reproduced", "escalated"):
        assert f"| `{outcome}` |" in triage


def test_atlas_checks_culprit_and_scopes_every_platform():
    atlas = (PROMPTS / "atlas.md").read_text()
    assert "all four" in atlas and "**Timing:**" in atlas and "**Platforms:**" in atlas
    assert '"platforms": ["android", "ios"]' in atlas and "every affected platform" in atlas
    assert "next release candidate" in atlas and "built_on" in atlas
    assert "Use the reporter's platform" not in atlas


def test_kinetics_baselines_on_release_candidate_per_platform():
    kinetics = (PROMPTS / "kinetics.md").read_text()
    assert "## Baselines on the next release candidate" in kinetics
    assert "every** platform passes" in kinetics and "twin" in kinetics


def test_gremlin_checks_before_closing():
    gremlin = (PROMPTS / "gremlin.md").read_text()
    assert "The culprit fits the evidence" in gremlin and "Every affected platform is covered" in gremlin
    assert "sent to **Triage**" in gremlin


def test_espida_and_telios_support_other_platforms():
    assert "by_platform" in (PROMPTS / "espida.md").read_text()
    assert "## Twins on another platform" in (PROMPTS / "telios.md").read_text()


@pytest.mark.parametrize("agent", AGENTS)
def test_every_prompt_knows_budgets_are_enforced(agent):
    text = (PROMPTS / f"{agent}.md").read_text()
    assert "**429**" in text and "GET /budget/{bug_ref}" in text
    assert "7 app runs per platform" in text and "4 API checks" in text


def test_kinetics_reads_runs_and_checks_fixes_in_their_env():
    kinetics = (PROMPTS / "kinetics.md").read_text()
    assert "### Reading a run" in kinetics and "never** a pass" in kinetics
    assert '"bug_ref": "RPT-123"' in kinetics and "preprod-atl-0002" in kinetics
    assert "with `env` set to **Atlas's env**" in kinetics
    assert 'always `"preprod"`' not in kinetics


def test_backend_fixes_name_their_env():
    atlas = (PROMPTS / "atlas.md").read_text()
    assert "preprod: {env, service, version}" in atlas and "the API refuses a third" in atlas
    assert "preprod_env" in (PROMPTS / "espida.md").read_text()
    assert "A budget is used up" in (PROMPTS / "triage.md").read_text()
    assert "quotes what the run showed" in (PROMPTS / "telios.md").read_text()


@pytest.mark.parametrize("agent", AGENTS)
def test_protocol_has_the_two_rooms_and_the_herald(agent):
    text = (PROMPTS / f"{agent}.md").read_text()
    assert "**public room**" in text and "**work log room**" in text and "**herald**" in text
    assert "[PUBLIC] bug=<report_id> from=Triage to=reporter" in text
    assert "Only Triage talks to the reporter, and only with `[PUBLIC]`." in text
    assert "don't post\nstatus updates" in text and "post nothing there and end your turn" in text


@pytest.mark.parametrize("agent", AGENTS)
def test_the_herald_reads_every_header_the_protocol_teaches(agent):
    """The card is built from headers, so every format in the prompts must parse to its own type."""
    from tracesquad.herald import parse_message

    text = (PROMPTS / f"{agent}.md").read_text()
    protocol = text.split("## How agents talk (shared protocol)", 1)[1]
    headers = re.findall(r"^\[([A-Z ]+)\] bug=<report_id>.*$", protocol, re.MULTILINE)
    assert set(headers) == {
        "ASK", "ANSWER", "NOT MINE", "CLAIM", "REPORT", "NUDGE", "CLOSE", "RCA", "PUBLIC", "NEW BUG", "FROM PUBLIC"
    }
    for line in re.findall(r"^\[[A-Z ]+\] bug=<report_id>.*$", protocol, re.MULTILINE):
        msg = parse_message(line)
        assert msg is not None and line.startswith(f"[{msg.type}]") and msg.bug == "<report_id>"


def test_triage_talks_to_the_reporter_in_plain_words():
    triage = (PROMPTS / "triage.md").read_text()
    assert "## Talking to the reporter" in triage
    assert "never holds internal details" in triage and "pre-prod env names" in triage
    assert "Don't send an acknowledgement or progress updates" in triage
    assert "**Post a status**" not in triage, "the herald's card replaced Triage's status posts"
    assert "other than your own `[PUBLIC]`" in triage, "a [PUBLIC] is not a dropped hand-off"
