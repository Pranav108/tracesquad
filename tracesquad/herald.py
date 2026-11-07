"""The herald: keeps a bug's public thread short while the squad works in a private work log.

Bugs are reported in a public room that anyone in the community can read. The six agents need dozens
of messages to work one bug, and most of them only matter to the agents. So the squad works in a
second room, the work log, which only the team can read, and the herald stands between the two.
It is a plain program, not an agent: it reads message headers and never writes prose of its own.

For each bug it:
- opens a thread in the work log for every new post in the public room (each top-level post there is a
  bug report; replies are the discussion) and sends the report to Triage there (`[NEW BUG]`);
- posts one status card in the reporter's public thread and edits it as the work moves. The card
  is built only from the protocol headers (type, `from=`, `to=`, `outcome=`) and links each piece of
  evidence to the exact message in the work log that carries it, so nobody has to read the log
  from the top. Agents' own words never reach the card;
- copies Triage's `[PUBLIC]` messages into the public thread, and sends anything people write in
  that thread back to Triage in the work log (`[FROM PUBLIC]`).

It talks to Mattermost's REST API with a bot token and polls both channels every couple of seconds.
State lives in a JSON file, so a restart carries on where it stopped.

    uv run python -m tracesquad.herald check     # resolve the bot and both channels, change nothing
    uv run python -m tracesquad.herald run       # the loop (scripts/herald.sh runs this)
    uv run python -m tracesquad.herald status    # the bugs it knows about

Setup, including the bot account: docs/HERALD.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("tracesquad.herald")

HOME = Path(os.environ.get("TRACESQUAD_HOME", Path.home() / ".tracesquad"))
DEFAULT_CONFIG = HOME / "herald.json"
DEFAULT_STATE = HOME / "herald-state.json"
DEFAULT_TOKEN_FILE = HOME / "herald-token"

AGENTS = ("triage", "telios", "kinetics", "espida", "atlas", "gremlin")
INVESTIGATORS = {"telios", "kinetics", "espida"}

# A protocol message: optional @mentions (send_targeted_message prepends them), then `[TYPE]` at the
# start of a line, then `key=value` tokens. A `[RCA]` mentioned mid-sentence is not a header.
HEADER = re.compile(
    r"^[ \t]*(?:@[\w.-]+[ \t,]*)*\[(ASK|ANSWER|NOT MINE|CLAIM|REPORT|NUDGE|CLOSE|RCA|PUBLIC|NEW BUG|FROM PUBLIC)\]([^\n]*)",
    re.MULTILINE,
)
TOKEN = re.compile(r"([A-Za-z_]+)=(\S*)")
EVIDENCE_LINE = re.compile(r"^[ \t]*(evidence|verification)[ \t]*:", re.MULTILINE | re.IGNORECASE)
MENTION = re.compile(r"@([A-Za-z][\w.-]*)")

STAGES = ("Received", "Investigating", "Fixing", "Verifying", "Wrapping up", "Done")
RECEIVED, INVESTIGATING, FIXING, VERIFYING, WRAPPING_UP, DONE = range(len(STAGES))

OUTCOMES = {
    "fixed": "✅ **Fixed**",
    "duplicate": "✅ **Closed: a known bug, already fixed in a newer app version**",
    "known_open": "📌 **Closed: a known bug the team is already tracking**",
    "wont_fix": "ℹ️ **Closed: the app works this way on purpose**",
    "already_fixed": "✅ **Closed: fixed in an upcoming release**",
    "not_reproduced": "❔ **Closed: the squad couldn't reproduce it**",
    "escalated": "📨 **Handed to the team that owns it**",
}

# Kept out of anything the herald copies into the public room, whatever Triage writes.
DEFAULT_REDACT = (
    r"\bU-\d{4,}\b",  # user ids
    r"\bpreprod(?:-[\w]+)+\b",  # a fix's own pre-prod env
    r"\b[a-z][\w-]*-service@\d[\w.]*\b",  # internal service versions
)


class HeraldError(RuntimeError):
    pass


# ── Reading protocol messages ─────────────────────────────────────────────────


@dataclass
class Message:
    type: str
    sender: str  # lower case, from `from=`
    to: list[str]  # lower case, from `to=`
    bug: str | None
    fields: dict[str, str]
    body: str  # what follows the header tokens: the rest of the header line, then the lines below
    has_evidence: bool


def parse_message(text: str) -> Message | None:
    """The first protocol header in a post, or None for a post that has none."""
    match = HEADER.search(text or "")
    if match is None:
        return None
    kind, rest = match.group(1), match.group(2)
    fields: dict[str, str] = {}
    words = rest.split()
    consumed = 0
    for word in words:
        token = TOKEN.fullmatch(word)
        if token is None:
            break
        fields[token.group(1).lower()] = token.group(2)
        consumed += 1
    inline = " ".join(words[consumed:])
    below = text[match.end():].strip("\n")
    body = "\n".join(part for part in (inline, below) if part.strip()).strip()
    to = [name.lower() for name in re.split(r"[,/+&]", fields.get("to", "")) if name]
    return Message(
        type=kind,
        sender=fields.get("from", "").lower(),
        to=to,
        bug=fields.get("bug") or None,
        fields=fields,
        body=body,
        has_evidence=bool(EVIDENCE_LINE.search(text)) or kind in ("RCA", "CLOSE"),
    )


# ── What one bug looks like ───────────────────────────────────────────────────


@dataclass
class Evidence:
    label: str
    post_id: str
    at: int


@dataclass
class Bug:
    key: str  # the reporter's public post id, or `log:<post id>` for a bug opened in the work log
    report_id: str
    reporter: str = ""
    opened_at: int = 0
    public_root_id: str | None = None
    card_post_id: str | None = None
    work_log_root_id: str | None = None
    stage: int = RECEIVED
    outcome: str | None = None
    closed_at: int | None = None
    now: list[str] = field(default_factory=list)
    now_since: int | None = None
    messages: int = 0
    agents: list[str] = field(default_factory=list)
    last_at: int = 0
    fix_out: bool = False
    evidence: list[Evidence] = field(default_factory=list)
    public_posts: int = 0
    forwarded: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Bug:
        data = dict(data)
        data["evidence"] = [Evidence(**e) for e in data.get("evidence", [])]
        return cls(**data)


def stage_for(msg: Message, bug: Bug) -> int:
    """How far a message says the bug has got. Only the header is read."""
    sender, to = msg.sender, set(msg.to)
    if msg.type in ("RCA", "CLOSE"):
        return DONE
    if (sender == "atlas" and "gremlin" in to and msg.type == "REPORT") or (
        sender == "gremlin" and msg.type in ("CLAIM", "REPORT") and bug.fix_out
    ):
        return WRAPPING_UP
    if (sender == "atlas" and "kinetics" in to) or (sender == "kinetics" and bug.fix_out):
        return VERIFYING
    if sender == "atlas" or ("atlas" in to and msg.type == "REPORT"):
        return FIXING
    if sender in INVESTIGATORS or to & INVESTIGATORS:
        return INVESTIGATING
    return RECEIVED


def evidence_label(msg: Message, bug: Bug) -> str:
    if msg.type == "RCA":
        return "Root cause analysis"
    if msg.type == "CLOSE":
        return "Closing note"
    return {
        "kinetics": "Fix verification" if bug.fix_out else "Reproduction",
        "espida": "Logs and impact",
        "telios": "Test setup",
        "atlas": "Fix (PR and builds)",
        "gremlin": "Release and PRD",
        "triage": "User and duplicate check",
    }.get(msg.sender, f"{msg.sender.capitalize()} report")


def observe(bug: Bug, msg: Message, post_id: str, at: int, agents: set[str]) -> None:
    """Fold one work-log message into the bug's state."""
    bug.messages += 1
    if msg.sender and msg.sender not in bug.agents:
        bug.agents.append(msg.sender)
    bug.last_at = max(bug.last_at, at)
    if msg.type == "PUBLIC":
        return
    if msg.sender == "atlas" and "kinetics" in msg.to:
        bug.fix_out = True
    if bug.outcome is None:
        if msg.type in ("RCA", "CLOSE"):
            # `stage` keeps the furthest point the work reached; `outcome` is what says it's done.
            bug.outcome = "fixed" if msg.type == "RCA" else (msg.fields.get("outcome") or "closed")
            bug.closed_at = at
            bug.now, bug.now_since = [], None
        else:
            bug.stage = max(bug.stage, stage_for(msg, bug))
            working = [msg.sender] if msg.type == "CLAIM" else [n for n in msg.to if n in agents]
            if working and working != bug.now:
                bug.now, bug.now_since = working, at
    if msg.has_evidence:
        label = evidence_label(msg, bug)
        for item in bug.evidence:
            if item.label == label:
                item.post_id, item.at = post_id, at
                break
        else:
            bug.evidence.append(Evidence(label, post_id, at))


# ── The card ──────────────────────────────────────────────────────────────────


def clock(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%I:%M %p").lstrip("0")


def duration(start: int, end: int) -> str:
    minutes = max(0, round((end - start) / 60000))
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


def stepper(bug: Bug) -> str:
    if bug.outcome is not None and bug.outcome != "fixed":
        # A bug closed early skips the stages it never reached.
        reached = [STAGES[i] for i in range(DONE) if i <= bug.stage] + [STAGES[DONE]]
        return " → ".join(f"✅ {name}" for name in dict.fromkeys(reached))
    steps = []
    for i, name in enumerate(STAGES):
        if bug.outcome is not None or i < bug.stage:
            steps.append(f"✅ {name}")
        elif i == bug.stage:
            steps.append(f"⏳ **{name}**")
        else:
            steps.append(f"⚪ {name}")
    return " → ".join(steps)


def render_card(bug: Bug, *, permalink: Callable[[str], str], names: dict[str, str], now_ms: int) -> str:
    """The public status card. Only headers, counts, times and links: never an agent's own words."""
    if bug.outcome is not None:
        status = OUTCOMES.get(bug.outcome, f"✅ **Closed ({bug.outcome})**")
        closed = bug.closed_at or now_ms
        headline = f"**{bug.report_id}** · {status} · closed {clock(closed)} after {duration(bug.opened_at, closed)}"
    elif bug.stage == RECEIVED:
        headline = f"**{bug.report_id}** · 📥 **Received** · the squad is on it"
    else:
        headline = f"**{bug.report_id}** · ⏳ **{STAGES[bug.stage]}** · updated {clock(bug.last_at or now_ms)}"
    lines = [headline, stepper(bug)]
    if bug.outcome is None and bug.now:
        who = ", ".join(names.get(n, n.capitalize()) for n in bug.now)
        since = f", since {clock(bug.now_since)}" if bug.now_since else ""
        lines.append(f"**Working on it:** {who}{since}")
    if bug.evidence:
        links = " · ".join(f"[{e.label}]({permalink(e.post_id)})" for e in bug.evidence)
        lines.append(f"**Evidence** (team only): {links}")
    if bug.work_log_root_id:
        end = bug.closed_at or bug.last_at or now_ms
        agents = len(bug.agents)
        summary = (
            f"{bug.messages} message{'s' * (bug.messages != 1)} · {agents} agent{'s' * (agents != 1)}"
            f" · {duration(bug.opened_at, end)}"
        )
        lines.append(f"**Work log** (team only): [{summary}]({permalink(bug.work_log_root_id)})")
    if bug.outcome is None:
        lines.append("_This card updates as the squad works. Triage replies here when there's news or a question for you._")
    return "\n".join(lines)


# ── Mattermost ────────────────────────────────────────────────────────────────


class Mattermost(Protocol):
    def me(self) -> dict[str, Any]: ...
    def user(self, user_id: str) -> dict[str, Any]: ...
    def my_channels(self, user_id: str) -> list[dict[str, Any]]: ...
    def channel(self, channel_id: str) -> dict[str, Any]: ...
    def team(self, team_id: str) -> dict[str, Any]: ...
    def posts_since(self, channel_id: str, since: int) -> list[dict[str, Any]]: ...
    def create_post(self, channel_id: str, message: str, root_id: str | None = None) -> dict[str, Any]: ...
    def patch_post(self, post_id: str, message: str) -> dict[str, Any]: ...


class MattermostREST:
    """Just the REST calls the herald needs, over urllib (no extra dependency)."""

    def __init__(self, url: str, token: str, timeout: float = 15.0) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.url}/api/v4{path}",
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise HeraldError(f"Mattermost {method} {path} answered {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise HeraldError(f"Mattermost at {self.url} is not reachable: {e.reason}") from e

    def me(self) -> dict[str, Any]:
        return self._call("GET", "/users/me")

    def user(self, user_id: str) -> dict[str, Any]:
        return self._call("GET", f"/users/{user_id}")

    def my_channels(self, user_id: str) -> list[dict[str, Any]]:
        return self._call("GET", f"/users/{user_id}/channels")

    def channel(self, channel_id: str) -> dict[str, Any]:
        return self._call("GET", f"/channels/{channel_id}")

    def team(self, team_id: str) -> dict[str, Any]:
        return self._call("GET", f"/teams/{team_id}")

    def posts_since(self, channel_id: str, since: int) -> list[dict[str, Any]]:
        listing = self._call("GET", f"/channels/{channel_id}/posts?since={since}")
        return list((listing or {}).get("posts", {}).values())

    def create_post(self, channel_id: str, message: str, root_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"channel_id": channel_id, "message": message}
        if root_id:
            body["root_id"] = root_id
        return self._call("POST", "/posts", body)

    def patch_post(self, post_id: str, message: str) -> dict[str, Any]:
        return self._call("PUT", f"/posts/{post_id}/patch", {"message": message})


# ── The herald ────────────────────────────────────────────────────────────────


@dataclass
class Config:
    mattermost_url: str
    public_channel: str  # id, name or display name; the bot must be a member
    work_log_channel: str
    triage: str = "triage"
    agents: list[str] = field(default_factory=lambda: list(AGENTS))
    ignore_users: list[str] = field(default_factory=lambda: ["admin", "switch-admin", "system-bot", "system"])
    report_id_pattern: str = r"\bRPT-\d+\b"
    # False: every top-level post in the public room is a report. True: only posts that mention triage.
    require_mention: bool = False
    redact_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_REDACT))
    poll_seconds: float = 2.0
    token_file: str = str(DEFAULT_TOKEN_FILE)
    state_file: str = str(DEFAULT_STATE)

    @classmethod
    def load(cls, path: Path) -> Config:
        if not path.exists():
            raise HeraldError(f"No herald config at {path}. See docs/HERALD.md for what goes in it.")
        data = json.loads(path.read_text())
        known = set(cls.__dataclass_fields__)
        unknown = set(data) - known
        if unknown:
            raise HeraldError(f"{path} has keys the herald doesn't know: {sorted(unknown)}")
        return cls(**data)

    def token(self) -> str:
        token = os.environ.get("TRACESQUAD_HERALD_TOKEN", "").strip()
        if token:
            return token
        path = Path(self.token_file).expanduser()
        if not path.exists():
            raise HeraldError(
                f"No bot token: set TRACESQUAD_HERALD_TOKEN or put it in {path} (see docs/HERALD.md)."
            )
        return path.read_text().strip()


@dataclass
class State:
    since: dict[str, int] = field(default_factory=dict)
    bugs: dict[str, Bug] = field(default_factory=dict)
    by_report: dict[str, str] = field(default_factory=dict)
    by_public_root: dict[str, str] = field(default_factory=dict)
    by_work_log_root: dict[str, str] = field(default_factory=dict)
    handled: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> State:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        data["bugs"] = {k: Bug.from_dict(v) for k, v in data.get("bugs", {}).items()}
        return cls(**data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)


class Herald:
    HANDLED_KEPT = 5000

    def __init__(self, mm: Mattermost, config: Config, *, now: Callable[[], float] = time.time) -> None:
        self.mm = mm
        self.config = config
        self._now = now
        self.state_path = Path(config.state_file).expanduser()
        self.state = State()
        self._handled: set[str] = set()
        self._usernames: dict[str, str] = {}
        self._dirty: set[str] = set()
        self.agents = {a.lower() for a in config.agents}
        self.names = {a.lower(): a.capitalize() for a in config.agents}
        self.triage = config.triage.lower()
        self.report_id = re.compile(config.report_id_pattern)
        self.redactions = [re.compile(p) for p in config.redact_patterns]
        self.me_id = ""
        self.public: dict[str, Any] = {}
        self.work_log: dict[str, Any] = {}
        self.team_name = ""

    # Setup

    def now_ms(self) -> int:
        return int(self._now() * 1000)

    def connect(self) -> None:
        """Find the bot and both channels. Changes nothing."""
        me = self.mm.me()
        self.me_id = me["id"]
        self._usernames[self.me_id] = me.get("username", "")
        channels = self.mm.my_channels(self.me_id)
        self.public = self._find(channels, self.config.public_channel, "public_channel")
        self.work_log = self._find(channels, self.config.work_log_channel, "work_log_channel")
        if self.public["id"] == self.work_log["id"]:
            raise HeraldError("public_channel and work_log_channel are the same channel; they must differ.")
        self.team_name = self.mm.team(self.public["team_id"])["name"]

    def start(self) -> None:
        self.connect()
        self.state = State.load(self.state_path)
        self._handled = set(self.state.handled)
        start = self.now_ms()
        for channel in (self.public, self.work_log):
            # A first start begins now: old threads in the room are not this herald's bugs.
            self.state.since.setdefault(channel["id"], start)
        self._save()
        log.info(
            "herald %s watching public %r and work log %r on team %s",
            self._usernames[self.me_id], self.public.get("display_name"), self.work_log.get("display_name"), self.team_name,
        )

    def _find(self, channels: list[dict[str, Any]], ref: str, key: str) -> dict[str, Any]:
        wanted = ref.strip().lower()
        for channel in channels:
            if wanted in (channel["id"].lower(), channel.get("name", "").lower(), channel.get("display_name", "").lower()):
                return channel
        names = sorted(c.get("display_name") or c.get("name", "") for c in channels)
        raise HeraldError(
            f"{key} {ref!r} is not a channel the herald's bot is a member of. Add the bot to it. "
            f"It is in: {names}"
        )

    def permalink(self, post_id: str) -> str:
        return f"{self.config.mattermost_url.rstrip('/')}/{self.team_name}/pl/{post_id}"

    # The loop

    def run_forever(self) -> None:
        self.start()
        delay = self.config.poll_seconds
        while True:
            try:
                self.poll_once()
                delay = self.config.poll_seconds
            except HeraldError as e:  # one failed poll must not stop the herald
                log.error("%s", e)
                delay = min(max(delay * 2, self.config.poll_seconds), 60)
            time.sleep(delay)

    def poll_once(self) -> None:
        for channel, handle in ((self.public, self._on_public), (self.work_log, self._on_work_log)):
            cid = channel["id"]
            posts = self.mm.posts_since(cid, self.state.since.get(cid, 0))
            for post in sorted(posts, key=lambda p: p.get("create_at", 0)):
                # One millisecond back, so a post created in the same millisecond is never skipped;
                # `handled` keeps anything seen twice from being handled twice.
                self.state.since[cid] = max(self.state.since.get(cid, 0), post.get("create_at", 0) - 1)
                pid = post.get("id", "")
                if not pid or pid in self._handled or post.get("delete_at"):
                    continue
                # Handled at most once: a post that failed half-way is logged, never repeated.
                self._handled.add(pid)
                self.state.handled.append(pid)
                if post.get("type") or post.get("user_id") == self.me_id:
                    continue  # system messages, and the herald's own posts and edits
                try:
                    handle(post)
                except HeraldError as e:
                    log.error("could not handle post %s: %s", pid, e)
        for key in sorted(self._dirty):
            try:
                self._refresh_card(self.state.bugs[key])
            except HeraldError as e:
                log.error("could not update the card for %s: %s", self.state.bugs[key].report_id, e)
        self._dirty.clear()
        self.state.handled = self.state.handled[-self.HANDLED_KEPT:]
        self._save()

    def _save(self) -> None:
        self.state.save(self.state_path)

    # The public room

    def _on_public(self, post: dict[str, Any]) -> None:
        text = post.get("message", "")
        author = self._username(post.get("user_id", ""))
        if author.lower() in self._ignored() or parse_message(text) is not None:
            return  # agents and Switch's own accounts: nothing they post here is a report
        root = post.get("root_id") or ""
        if root:
            key = self.state.by_public_root.get(root)
            if key is not None:
                self._forward_to_triage(self.state.bugs[key], author, text)
            return
        # A top-level post is a new report: people don't have to tag anyone.
        if self.config.require_mention and not re.search(rf"@{re.escape(self.triage)}\b", text, re.IGNORECASE):
            return
        self._open_bug(post, author, text)

    def _open_bug(self, post: dict[str, Any], author: str, text: str) -> None:
        found = self.report_id.search(text)
        report_id = found.group(0) if found else f"FB-{post['id'][:6]}"
        bug = Bug(
            key=post["id"],
            report_id=report_id,
            reporter=author,
            opened_at=post.get("create_at") or self.now_ms(),
            public_root_id=post["id"],
        )
        opener = (
            f"@{self.triage} [NEW BUG] bug={report_id} from=herald to={self.names.get(self.triage, 'Triage')} reporter={author}\n"
            f"{self._quote(self._defang(text))}\n"
            "This is the bug's work-log thread: the whole squad works it here. The public thread shows only "
            "the herald's status card and your [PUBLIC] messages."
        )
        root = self.mm.create_post(self.work_log["id"], opener)
        bug.work_log_root_id = root["id"]
        self._remember(bug)
        card = self.mm.create_post(self.public["id"], self._card(bug), root_id=post["id"])
        bug.card_post_id = card["id"]
        log.info("opened %s for %s: work log %s, card %s", report_id, author, root["id"], card["id"])

    def _forward_to_triage(self, bug: Bug, author: str, text: str) -> None:
        if not bug.work_log_root_id:
            return
        message = (
            f"@{self.triage} [FROM PUBLIC] bug={bug.report_id} from=herald to={self.names.get(self.triage, 'Triage')} author={author}\n"
            f"{self._quote(self._defang(text))}"
        )
        self.mm.create_post(self.work_log["id"], message, root_id=bug.work_log_root_id)
        bug.forwarded += 1
        log.info("forwarded a public reply on %s from %s", bug.report_id, author)

    # The work log

    def _on_work_log(self, post: dict[str, Any]) -> None:
        msg = parse_message(post.get("message", ""))
        if msg is None or msg.type in ("NEW BUG", "FROM PUBLIC"):
            return
        bug = self._bug_for(msg, post)
        if bug is None:
            return
        observe(bug, msg, post["id"], post.get("create_at") or self.now_ms(), self.agents)
        self._dirty.add(bug.key)
        if msg.type == "PUBLIC":
            self._publish(bug, msg)

    def _bug_for(self, msg: Message, post: dict[str, Any]) -> Bug | None:
        key = self.state.by_report.get(msg.bug) if msg.bug else None
        if key is None and post.get("root_id"):
            key = self.state.by_work_log_root.get(post["root_id"])
        if key is not None:
            return self.state.bugs[key]
        if not msg.bug:
            return None
        # Work that started in the work log itself: tracked, but there is no public thread to update.
        bug = Bug(
            key=f"log:{post.get('root_id') or post['id']}",
            report_id=msg.bug,
            opened_at=post.get("create_at") or self.now_ms(),
            work_log_root_id=post.get("root_id") or post["id"],
        )
        self._remember(bug)
        return bug

    def _publish(self, bug: Bug, msg: Message) -> None:
        if msg.sender != self.triage:
            log.warning("ignored a [PUBLIC] on %s from %s: only %s talks to the reporter", bug.report_id, msg.sender, self.triage)
            return
        if not bug.public_root_id or not msg.body:
            return
        body = self._defang(msg.body)
        for pattern in self.redactions:
            body, count = pattern.subn("[removed]", body)
            if count:
                log.warning("redacted %d match(es) of %s from a [PUBLIC] on %s", count, pattern.pattern, bug.report_id)
        self.mm.create_post(self.public["id"], f"**{self.names.get(self.triage, 'Triage')}:** {body}", root_id=bug.public_root_id)
        bug.public_posts += 1
        log.info("published a message from %s on %s", self.triage, bug.report_id)

    # Helpers

    def _card(self, bug: Bug) -> str:
        return render_card(bug, permalink=self.permalink, names=self.names, now_ms=self.now_ms())

    def _refresh_card(self, bug: Bug) -> None:
        if bug.card_post_id:
            self.mm.patch_post(bug.card_post_id, self._card(bug))

    def _remember(self, bug: Bug) -> None:
        self.state.bugs[bug.key] = bug
        self.state.by_report[bug.report_id] = bug.key
        if bug.public_root_id:
            self.state.by_public_root[bug.public_root_id] = bug.key
        if bug.work_log_root_id:
            self.state.by_work_log_root[bug.work_log_root_id] = bug.key

    def _ignored(self) -> set[str]:
        return {u.lower() for u in self.config.ignore_users} | self.agents

    def _username(self, user_id: str) -> str:
        if user_id not in self._usernames:
            try:
                self._usernames[user_id] = self.mm.user(user_id).get("username", user_id)
            except HeraldError:
                return user_id
        return self._usernames[user_id]

    def _defang(self, text: str) -> str:
        """`@triage` in copied text would wake that agent in the room it lands in; keep the name, drop the @."""
        return MENTION.sub(lambda m: m.group(1) if m.group(1).lower() in self.agents else m.group(0), text)

    @staticmethod
    def _quote(text: str) -> str:
        return "\n".join(f"> {line}" if line.strip() else ">" for line in text.strip().splitlines()) or "> (empty)"


# ── Command line ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tracesquad.herald", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["check", "run", "status"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"default: {DEFAULT_CONFIG}")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s herald %(levelname)s %(message)s")
    try:
        config = Config.load(args.config)
        if args.command == "status":
            state = State.load(Path(config.state_file).expanduser())
            for bug in sorted(state.bugs.values(), key=lambda b: b.opened_at):
                where = STAGES[bug.stage] if bug.outcome is None else f"closed ({bug.outcome})"
                print(f"{bug.report_id:10} {where:20} {bug.messages:3} messages  reporter={bug.reporter or '-'}")
            return 0
        herald = Herald(MattermostREST(config.mattermost_url, config.token()), config)
        if args.command == "check":
            herald.connect()
            print(f"bot: {herald._usernames[herald.me_id]}  team: {herald.team_name}")
            print(f"public channel:   {herald.public.get('display_name')} ({herald.public['id']}, type {herald.public.get('type')})")
            print(f"work log channel: {herald.work_log.get('display_name')} ({herald.work_log['id']}, type {herald.work_log.get('type')})")
            if herald.work_log.get("type") != "P":
                print("warning: the work log is not a private channel, so anyone on the team can read it")
            return 0
        herald.run_forever()
        return 0
    except HeraldError as e:
        print(f"herald: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
