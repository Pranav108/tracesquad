"""Export the six TraceSquad agents for an agent platform other than Switch (Switch: make_switch_template.py).

Usage:
    uv run python scripts/export_agents.py claude-code <project dir>
        Writes <project dir>/.claude/agents/<agent>.md (one Claude Code subagent per agent) and
        <project dir>/.claude/commands/tracesquad.md (the /tracesquad command: the main session becomes
        the room that carries messages between them). Use a project dir OUTSIDE this repo, so the
        agents can't read data/, which holds the answers.
    uv run python scripts/export_agents.py json [file]
        One JSON document (stdout, or file): every agent's name, description, who it asks, the
        endpoints it calls and its full system prompt, plus the protocol. For any agent SDK.

Both come from squad.yaml and prompts/*.md, so re-export after changing either. AGENTS.md explains how
to run the squad on any platform.
"""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SQUAD = yaml.safe_load((ROOT / "squad.yaml").read_text())
NAMES = [a["name"] for a in SQUAD["agents"]]

API_NOTE = """- Call the TraceSquad API only with `~/.tracesquad/bin/tsq` from your shell (see "Tools" above).
  Parse its JSON with `python3 -c` or `jq` if present. Never invent a response, and never go looking
  for the API's address, its source or its data files on this machine: everything you know comes from
  `tsq` and from your teammates."""

GENERIC_NOTES = f"""
## Working with your team

- Your teammates are agents: {", ".join(NAMES)}. Send each protocol message to the agents in its
  `to=`, the way your platform targets a message, in the bug's thread. A message wakes only the agents
  it is sent to; a `to=` the platform doesn't deliver wakes nobody.
- Read the thread before asking anything.
- Your instructions describe two rooms and a herald (a Switch setup). Without them, whoever runs the
  squad plays the herald: it hands Triage each report as a `[NEW BUG]` and shows the reporter Triage's
  `[PUBLIC]` messages. Everything else happens in the bug's one thread.
- Nothing runs on a timer. Triage's checks for stuck bugs are woken by a `sweep` message that someone
  outside the agents sends it about every 10 minutes.
{API_NOTE}
"""

CLAUDE_CODE_NOTES = f"""
## Working as a Claude Code subagent

- You run as a subagent. The main session is only the **room**: it keeps the bug's thread, delivers
  messages and runs the agents they are addressed to. You can't message a teammate yourself.
- Your task holds the bug's thread so far, then the message or messages addressed to you. Read the
  thread before asking anything: the answer may already be there.
- End every reply with the protocol messages you send, each starting with its header line, e.g.
  `[ASK] bug=RPT-123 from=Telios to=Triage chain=Kinetics→Telios`. The room posts them to the thread
  and runs the agents in `to=`. Your teammates are {", ".join(NAMES)}. Anything outside a protocol
  message reaches nobody, so never go quiet: every reply holds at least one message.
- A message addressed to the reporter, a team or the thread is shown to the person running the room.
- There is no public room and no herald here: the room plays the herald. It hands Triage the report as
  a `[NEW BUG]`, and shows Triage's `[PUBLIC]` messages to the person running it. There is no status card.
{API_NOTE}
"""

ROOM_COMMAND = f"""---
description: Run a bug report through the TraceSquad agents. You are only the room that carries their messages.
argument-hint: <bug report, e.g. "RPT-102 Checkout shows 'Something went wrong' after a coupon. user U-77105">
---
You are the **room** for TraceSquad, six agents that work a bug peer to peer: {", ".join(NAMES)}.
Each one is a subagent here. You carry their messages. You never do an agent's work, answer for one,
or decide anything about the bug.

Bug report: $ARGUMENTS

1. **Check the API:** run `~/.tracesquad/bin/tsq GET /health`. If it fails, stop and tell the user to
   start it with `scripts/serve.sh` in a clone of the TraceSquad repo.
2. **Keep the thread:** an ordered list of every message. It starts with the bug report, written as the
   herald would hand it over: `[NEW BUG] bug=<report id> from=herald to=Triage reporter=user`, then the
   report on the next line. The report id is the `RPT-…` id the report names, or, if it names none,
   `FB-` and 6 random lowercase letters and digits (Triage files it in the API under that id).
3. **Start:** run the `triage` subagent with the thread.
4. **Deliver, until the bug ends:** from each reply, take every protocol message (a block that starts
   with `[ASK]`, `[ANSWER]`, `[NOT MINE]`, `[CLAIM]`, `[REPORT]`, `[NUDGE]`, `[CLOSE]`, `[RCA]` or `[PUBLIC]`) and
   append it to the thread word for word. Then, for every agent named in a message's `to=`, run that
   subagent (its name in lower case) with the whole thread and a last line saying which messages are
   for it. Run agents that don't depend on each other in parallel. Show the user every `[PUBLIC]` (it is
   Triage talking to the reporter) and any message addressed to a team.
5. **Sweep:** when no message is waiting for an agent and the bug isn't closed, run `triage` with the
   thread and the word `sweep`. That is its check for stuck bugs.
6. **Stop** when Triage has posted a `[CLOSE]` and its `[PUBLIC]`, or its `[PUBLIC]` after Gremlin's `[RCA]`. Also
   stop after 60 agent runs, and say where the bug stands. Then summarize: the outcome, the culprit and
   the fix (if any), how it was verified, and the thread.

Never edit, merge or drop a message. Never call the API yourself beyond the health check. Never read
the TraceSquad repo's `data/` folder or its `/admin` routes: they hold the answers.
"""


def system_prompt(agent: dict, notes: str) -> str:
    return (ROOT / agent["prompt"]).read_text() + notes


def claude_code(project: Path) -> list[Path]:
    project = project.expanduser().resolve()
    if project == ROOT or ROOT in project.parents:
        sys.exit("Export to a project outside this repo: agents working inside it could read data/, which holds the answers.")
    agents_dir = project / ".claude" / "agents"
    commands_dir = project / ".claude" / "commands"
    agents_dir.mkdir(parents=True, exist_ok=True)
    commands_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for agent in SQUAD["agents"]:
        description = (f"TraceSquad {agent['display_name']}: {agent['description']}. "
                       f"Run it with the bug's thread when a message is addressed to {agent['display_name']}.")
        path = agents_dir / f"{agent['name']}.md"
        path.write_text("---\n"
                        f"name: {agent['name']}\n"
                        f"description: {json.dumps(description, ensure_ascii=False)}\n"
                        "tools: Bash\n"
                        "---\n\n" + system_prompt(agent, CLAUDE_CODE_NOTES))
        written.append(path)
    room = commands_dir / "tracesquad.md"
    room.write_text(ROOM_COMMAND)
    written.append(room)
    return written


def as_json() -> dict:
    return {
        "name": SQUAD["name"],
        "summary": SQUAD["summary"],
        "topology": SQUAD["topology"],
        "protocol": SQUAD["protocol"],
        "agents": [
            {
                "name": a["name"],
                "display_name": a["display_name"],
                "description": a["description"],
                "job": a["job"],
                "asks": a["asks"],
                "api": a["api"],
                "tools": ["a shell that can run ~/.tracesquad/bin/tsq"],
                "system_prompt": system_prompt(a, GENERIC_NOTES),
            }
            for a in SQUAD["agents"]
        ],
    }


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "claude-code":
        for path in claude_code(Path(sys.argv[2])):
            print(f"wrote {path}")
        print("Next: run scripts/serve.sh (in this repo), then open Claude Code in that project and run "
              "/tracesquad <bug report>.")
    elif len(sys.argv) >= 2 and sys.argv[1] == "json":
        text = json.dumps(as_json(), indent=2, ensure_ascii=False) + "\n"
        if len(sys.argv) >= 3:
            Path(sys.argv[2]).write_text(text)
            print(f"wrote {sys.argv[2]}")
        else:
            sys.stdout.write(text)
    else:
        sys.exit(__doc__)
