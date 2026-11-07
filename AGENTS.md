# AGENTS.md: for AI agents working with this repository

You've been pointed at **TraceSquad**: six AI agents that take an app bug report to a verified fix and
an RCA, plus the mock API they work against. This file tells you what to do, depending on what you
were asked.

## You were asked to set up the squad (create its agents or subagents)

The squad is defined as data, so don't design agents of your own. Create exactly what
[`squad.yaml`](squad.yaml) describes.

1. **Read [`squad.yaml`](squad.yaml).** `agents:` has six entries. Each has a `name` (create the agent
   under exactly this name, because the agents address each other by it), a `description`, a `prompt`
   file holding its full system prompt, `asks` (who it asks for what) and `api` (the endpoints it calls).
   `topology:` and `protocol:` say how they work together.
2. **Pick the recipe for your platform:**

   | Platform | What to do |
   |---|---|
   | **Switch** (switch-buddy, or any agent that can manage agents) | Follow [`SWITCH.md`](SWITCH.md). One `create_room_from_yaml` call with [`switch/tracesquad.template.yaml`](switch/tracesquad.template.yaml) creates the six agents and their room. |
   | **Claude Code** | `uv run python scripts/export_agents.py claude-code <project dir outside this repo>`. It writes six subagents to `.claude/agents/` and a `/tracesquad` command to `.claude/commands/`. In that project, `/tracesquad <bug report>` runs a bug, with the main session acting only as the room. |
   | **Anything else** (Claude Agent SDK, OpenAI Agents SDK, LangGraph, CrewAI, your own loop) | `uv run python scripts/export_agents.py json squad.json` gives each agent's name, description and full system prompt. Then follow [the generic recipe](#the-generic-recipe). |

3. **Make sure the agents can reach the API.** On the machine the agents run on,
   `~/.tracesquad/bin/tsq doctor` should end with `tsq will use: http://…`. If `tsq` is missing or
   nothing answers, the person starts the API from a clone of this repo with `scripts/serve.sh` (it
   needs [uv](https://docs.astral.sh/uv/)). That also installs `tsq`.
4. **Ask before you create anything that runs**, and say what you'll create: six agents, where they
   run, and what they can do (a shell).

### The generic recipe

Every platform needs the same four things.

- **Six agents**, one per `squad.yaml` entry, named exactly as written, each with its system prompt.
  The `json` export already adds a "Working with your team" section. Adapt it if your platform
  addresses messages in some other way.
- **One tool: a shell that can run `~/.tracesquad/bin/tsq`.** Agents call the API only through it,
  e.g. `tsq GET /users/U-12345`. They need no URL and no access to this repository.
- **A shared thread per bug** where a message is delivered only to the agents in its `to=`, and wakes
  them. If your platform has no rooms, write a loop that plays the room. The `/tracesquad` command
  that `export_agents.py claude-code` writes holds the exact rules: keep the thread, deliver each
  message to the agents in its `to=`, and never answer for an agent.
- **A `sweep`:** something sends triage the word `sweep` about every 10 minutes while a bug is open.

Then report a bug to triage, giving the report id, its text and the user id. The demo has five
reports: `~/.tracesquad/bin/tsq GET /reports/RPT-101`, and so on up to `RPT-105`.

### Rules that keep the demo honest

- **Never give the agents this repository.** `data/`, `docs/superpowers/` and the API's `/admin`
  routes hold every scenario's answer. Run the agents from a folder outside the repo.
- **Never put the API's URL in an agent's instructions.** Agents find the API through `tsq`
  ([how](SWITCH.md#how-agents-find-the-api)), so moving the API changes nothing for them.
- **Don't rename the agents, and don't add a coordinator.** The agents ask each other directly, and
  Triage owns every bug.

## You were asked to explain the project

- [`README.md`](README.md): what it does, why, and how to run it.
- [`docs/SYSTEM.md`](docs/SYSTEM.md): how the agents reason, talk and finish, with flow diagrams.
- [`squad.yaml`](squad.yaml): the structure, as data.
- [`docs/API.md`](docs/API.md): the mock API.

## You were asked to change the code

- Setup and tests: `uv sync`, then `uv run pytest`. All tests must pass.
- `prompts/<agent>.md` is the source of truth for each agent. `squad.yaml` must list exactly the
  endpoints each prompt names, and the tests check that.
- After changing a prompt or `squad.yaml`, run `uv run python scripts/make_switch_template.py`. The
  tests fail while the Switch template is stale.
- Never put a URL, a scenario id or an `/admin` route in a prompt. The tests check that too.
- To add a scenario, see "Adding a scenario" in the README.
