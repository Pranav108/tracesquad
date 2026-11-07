"""scripts/export_agents.py sets the squad up on other platforms without leaking the answers or a URL."""

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "export_agents.py"
NAMES = [a["name"] for a in yaml.safe_load((ROOT / "squad.yaml").read_text())["agents"]]


def export(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT, timeout=60)


def frontmatter(text: str) -> dict:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "no frontmatter"
    return yaml.safe_load(match.group(1))


def test_claude_code_export_writes_six_subagents_and_the_room(tmp_path):
    out = export("claude-code", str(tmp_path))
    assert out.returncode == 0, out.stderr
    agents = sorted((tmp_path / ".claude" / "agents").glob("*.md"))
    assert [p.stem for p in agents] == sorted(NAMES)
    for path in agents:
        text = path.read_text()
        meta = frontmatter(text)
        assert meta["name"] == path.stem and meta["tools"] == "Bash" and meta["description"]
        assert (ROOT / "prompts" / f"{path.stem}.md").read_text() in text
        assert "## Working as a Claude Code subagent" in text and "~/.tracesquad/bin/tsq" in text
        assert not re.search(r"https?://", text)
    room = (tmp_path / ".claude" / "commands" / "tracesquad.md").read_text()
    assert frontmatter(room)["description"] and "$ARGUMENTS" in room
    assert all(name in room for name in NAMES) and "sweep" in room and "data/" in room


def test_claude_code_export_refuses_this_repo():
    out = export("claude-code", str(ROOT / "run"))
    assert out.returncode != 0 and "outside this repo" in out.stderr
    assert not (ROOT / "run").exists()


def test_json_export_carries_every_agent_and_the_protocol():
    out = export("json")
    assert out.returncode == 0, out.stderr
    doc = json.loads(out.stdout)
    assert [a["name"] for a in doc["agents"]] == NAMES
    assert "messages" in doc["protocol"] and doc["topology"]["owner_of_every_bug"] == "triage"
    for agent in doc["agents"]:
        assert "## Working with your team" in agent["system_prompt"]
        assert agent["api"] and agent["asks"]
        assert not re.search(r"https?://", agent["system_prompt"])
