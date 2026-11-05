"""Agent prompts must only point agents at endpoints that exist, and never at /admin."""

import re
from pathlib import Path

import pytest

from bugmock.api import create_app

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
AGENTS = ["triage", "telios", "kinetics", "espida", "atlas", "gremlin"]
ENDPOINT = re.compile(r"\b(GET|POST) (/[A-Za-z0-9_{}./-]+)")


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
    from bugmock.store import DATA_DIR, Store, load_dataset

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
def test_prompt_has_base_url_and_no_scenario_values(agent):
    text = (PROMPTS / f"{agent}.md").read_text()
    assert re.search(r"\*\*Base URL:\*\* `https://[^`]+`", text), f"{agent}.md has no base URL line"
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
