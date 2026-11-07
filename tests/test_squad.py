"""squad.yaml, the prompts and the Switch template must agree, and the template must deploy cleanly."""

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

from tracesquad.api import create_app

ROOT = Path(__file__).resolve().parent.parent
SQUAD = yaml.safe_load((ROOT / "squad.yaml").read_text())
AGENTS = {a["name"]: a for a in SQUAD["agents"]}
TEMPLATE_PATH = ROOT / "switch" / "tracesquad.template.yaml"
ENDPOINT = re.compile(r"(?<!tsq )\b(GET|POST) (/[A-Za-z0-9_{}./-]+)")
PLACEHOLDER = re.compile(r"\{(\$?[A-Za-z_][A-Za-z0-9_]*)\}")  # Switch's own placeholder pattern
SWITCH_BUILTINS = {"$creator", "$creator_email", "$date", "$timestamp", "$agents_dir"}


def generator():
    spec = importlib.util.spec_from_file_location("make_switch_template", ROOT / "scripts" / "make_switch_template.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def served() -> set[str]:
    paths = create_app().openapi()["paths"]
    return {f"{method.upper()} {path}" for path, ops in paths.items() for method in ops}


def test_every_prompt_is_an_agent_and_every_agent_has_a_prompt():
    prompts = {p.stem for p in (ROOT / "prompts").glob("*.md")}
    assert prompts == set(AGENTS)
    for name, agent in AGENTS.items():
        assert agent["prompt"] == f"prompts/{name}.md"
        for key in ("display_name", "description", "job", "owns", "never", "asks", "api"):
            assert agent.get(key), f"{name} has no {key} in squad.yaml"


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_api_list_is_exactly_what_the_prompt_names(name):
    text = (ROOT / AGENTS[name]["prompt"]).read_text()
    named = {f"{m} {p.rstrip('.')}" for m, p in ENDPOINT.findall(text)}
    listed = set(AGENTS[name]["api"])
    assert listed == named, f"squad.yaml {name}.api differs from its prompt: +{sorted(listed - named)} -{sorted(named - listed)}"
    assert listed <= served()


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_asks_edges_point_at_other_agents(name):
    targets = set(AGENTS[name]["asks"])
    assert targets <= set(AGENTS) - {name}
    text = (ROOT / AGENTS[name]["prompt"]).read_text()
    for target in targets:
        assert AGENTS[target]["display_name"] in text


def test_topology_names_real_agents():
    topology = SQUAD["topology"]
    assert topology["owner_of_every_bug"] in AGENTS and topology["talks_to_reporter"] in AGENTS
    assert topology["closes_fixed_bugs"].split()[0] in AGENTS
    assert topology["closes_other_bugs"].split()[0] in AGENTS


def test_docs_it_points_at_exist():
    for path in SQUAD["docs"].values():
        assert (ROOT / path).exists(), path
    assert (ROOT / SQUAD["api"]["client"]["source"]).exists()
    assert (ROOT / SQUAD["deploy"]["switch_template"]).exists()


def test_template_is_up_to_date():
    assert TEMPLATE_PATH.read_text() == generator().build(), "run: uv run python scripts/make_switch_template.py"


def template() -> dict:
    return yaml.safe_load(TEMPLATE_PATH.read_text())


def test_template_creates_the_squad_and_its_room():
    doc = template()
    assert doc["version"] == 2
    resources = doc["resources"]
    agents = {k: v for k, v in resources.items() if v["type"] == "agent"}
    assert set(agents) == set(AGENTS)
    for key, agent in agents.items():
        assert agent["name"] == key
        assert agent["provider"] and agent["machine"] and agent["directory"] and agent["instructions"]
        assert agent["addressing"] == "anyone"
    rooms = [v for v in resources.values() if v["type"] == "room"]
    assert len(rooms) == 1
    room = rooms[0]
    assert room["name"] == SQUAD["deploy"]["room"] and set(room["agents"]) == set(AGENTS)
    for name in AGENTS:
        assert f"@{{{name}.name}}" in room["kickoff"]


def test_template_never_gives_agents_the_repo_or_a_url():
    text = TEMPLATE_PATH.read_text()
    for agent in (v for v in template()["resources"].values() if v["type"] == "agent"):
        assert "repo" not in agent and "sources" not in agent, "agents must never get this repo: data/ holds the answers"
        assert "~/.tracesquad/bin/tsq" in agent["instructions"]
    assert not re.search(r"https?://", text)
    assert "data/scenarios" not in text and "/admin" not in text


def test_template_placeholders_are_all_declared():
    """Switch warns about every `{word}` no param declares, and save_template refuses a document with warnings."""
    doc = template()
    used = set(PLACEHOLDER.findall(TEMPLATE_PATH.read_text()))
    assert used - SWITCH_BUILTINS == set(doc["params"])
