"""Agent prompts must only point agents at endpoints that exist, and never at /admin."""

import re
from pathlib import Path

import pytest

from bugmock.api import create_app

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
AGENTS = ["triage", "telios", "kinetics", "espida"]
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
