"""The herald: a short public thread for each bug, built from the work log's message headers."""

import itertools
import json

import pytest

from tracesquad.herald import (
    DONE,
    FIXING,
    INVESTIGATING,
    RECEIVED,
    VERIFYING,
    WRAPPING_UP,
    Bug,
    Config,
    Herald,
    HeraldError,
    main,
    observe,
    parse_message,
    render_card,
    stage_for,
)

AGENTS = {"triage", "telios", "kinetics", "espida", "atlas", "gremlin"}


class FakeMattermost:
    """Posts, users and channels in memory, with the REST calls the herald makes."""

    def __init__(self):
        self.ids = (f"p{n:04d}" for n in itertools.count(1))
        self.clock = 1_000_000
        self.users = {"u-herald": "tracesquad", "u-rep": "user", "u-admin": "admin", "u-bob": "bob"}
        self.channels = [
            {"id": "c-public", "name": "generic-feedback", "display_name": "generic feedback", "team_id": "t1", "type": "O"},
            {"id": "c-log", "name": "generic-feedback-worklog", "display_name": "generic feedback work log", "team_id": "t1", "type": "P"},
        ]
        self.posts: dict[str, dict] = {}

    # What people and agents do

    def post(self, channel, user, message, root_id=""):
        self.clock += 1000
        pid = next(self.ids)
        self.posts[pid] = {
            "id": pid, "channel_id": channel, "user_id": user, "message": message, "root_id": root_id,
            "create_at": self.clock, "update_at": self.clock, "delete_at": 0, "type": "",
        }
        return pid

    def thread(self, root_id):
        return [p for p in sorted(self.posts.values(), key=lambda p: p["create_at"]) if p["root_id"] == root_id]

    # The herald's calls

    def me(self):
        return {"id": "u-herald", "username": "tracesquad"}

    def user(self, user_id):
        return {"id": user_id, "username": self.users.get(user_id, user_id)}

    def my_channels(self, user_id):
        return self.channels

    def channel(self, channel_id):
        return next(c for c in self.channels if c["id"] == channel_id)

    def team(self, team_id):
        return {"id": team_id, "name": "switch"}

    def posts_since(self, channel_id, since):
        return [dict(p) for p in self.posts.values() if p["channel_id"] == channel_id and p["update_at"] > since]

    def create_post(self, channel_id, message, root_id=None):
        return {"id": self.post(channel_id, "u-herald", message, root_id or "")}

    def patch_post(self, post_id, message):
        self.clock += 1
        self.posts[post_id].update(message=message, update_at=self.clock)
        return self.posts[post_id]


@pytest.fixture
def mm():
    return FakeMattermost()


@pytest.fixture
def config(tmp_path):
    return Config(
        mattermost_url="http://mm.test",
        public_channel="generic feedback",
        work_log_channel="c-log",
        state_file=str(tmp_path / "state.json"),
    )


@pytest.fixture
def herald(mm, config):
    h = Herald(mm, config, now=lambda: mm.clock / 1000)
    h.start()
    return h


def agent(mm, root, text):
    """An agent's post in the work log. Switch posts it as the admin user when the agent has no bot."""
    mm.post("c-log", "u-admin", text, root)


def report(mm, herald, text="@Triage new bug RPT-101: Renewed Gold yesterday but the app shows 'Join Gold'. user U-48213"):
    root = mm.post("c-public", "u-rep", text)
    herald.poll_once()
    bug = herald.state.bugs[root]
    return root, bug


def card(mm, bug):
    return mm.posts[bug.card_post_id]["message"]


# ── Parsing ───────────────────────────────────────────────────────────────────


def test_parse_reads_the_header_after_targeted_mentions():
    msg = parse_message(
        "@Atlas [REPORT] bug=RPT-101 from=Kinetics to=Atlas\nsummary: reproduced 1/1\nevidence: run RUN-0001\nnext: fix it"
    )
    assert (msg.type, msg.sender, msg.to, msg.bug) == ("REPORT", "kinetics", ["atlas"], "RPT-101")
    assert msg.has_evidence and msg.body.startswith("summary: reproduced")


def test_parse_keeps_claim_text_and_multiple_targets():
    msg = parse_message("[CLAIM] bug=RPT-102 from=Telios eta=18 doing: building the twin on ios")
    assert msg.type == "CLAIM" and msg.fields["eta"] == "18" and msg.body == "doing: building the twin on ios"
    assert parse_message("[ASK] bug=RPT-102 from=Atlas to=Kinetics,Espida").to == ["kinetics", "espida"]
    assert parse_message("[NOT MINE] bug=RPT-1 from=Espida to=Atlas try=Telios").type == "NOT MINE"


def test_parse_ignores_a_type_named_mid_sentence():
    assert parse_message("Gremlin will post the [RCA] once Kinetics has verified it.") is None
    assert parse_message("") is None


# ── Stages, evidence and the card ─────────────────────────────────────────────


def run(bug, *texts):
    for n, text in enumerate(texts):
        observe(bug, parse_message(text), f"post{n}", 1_000_000 + n * 60_000, AGENTS)


def test_stages_follow_the_headers_and_never_go_back():
    bug = Bug(key="k", report_id="RPT-101", opened_at=1_000_000)
    run(bug, "[ASK] bug=RPT-101 from=Triage to=Espida\nquestion: what happened?")
    assert bug.stage == INVESTIGATING and bug.now == ["espida"]
    run(bug, "[REPORT] bug=RPT-101 from=Kinetics to=Atlas\nsummary: reproduced\nevidence: RUN-1")
    assert bug.stage == FIXING
    run(bug, "[ASK] bug=RPT-101 from=Telios to=Triage\nquestion: which coupon?")
    assert bug.stage == FIXING, "a late question does not move the card back"
    run(bug, "[ASK] bug=RPT-101 from=Atlas to=Kinetics\nquestion: please verify ATL-0001")
    assert bug.stage == VERIFYING and bug.fix_out
    run(bug, "[REPORT] bug=RPT-101 from=Atlas to=Gremlin\nsummary: verified\nevidence: CHK-2")
    assert bug.stage == WRAPPING_UP
    run(bug, "[RCA] bug=RPT-101 from=Gremlin to=Triage\nwhat_happened: stale status")
    assert bug.outcome == "fixed" and bug.now == [] and bug.closed_at
    assert bug.stage == WRAPPING_UP, "the stage records how far the work got; the outcome closes it"
    assert stage_for(parse_message("[CLOSE] bug=RPT-101 from=Triage outcome=duplicate"), bug) == DONE


def test_evidence_is_labelled_by_who_found_it_and_points_at_the_latest_post():
    bug = Bug(key="k", report_id="RPT-101")
    run(
        bug,
        "[REPORT] bug=RPT-101 from=Kinetics to=Atlas\nsummary: reproduced\nevidence: RUN-1",
        "[ANSWER] bug=RPT-101 from=Espida to=Atlas\nanswer: stale cache\nevidence: trace T-9",
        "[ASK] bug=RPT-101 from=Atlas to=Kinetics\nquestion: verify",
        "[REPORT] bug=RPT-101 from=Kinetics to=Atlas\nsummary: fix works\nevidence: CHK-2",
        "[ANSWER] bug=RPT-101 from=Espida to=Atlas\nanswer: 41 users\nevidence: impact",
    )
    assert [(e.label, e.post_id) for e in bug.evidence] == [
        ("Reproduction", "post0"),
        ("Logs and impact", "post4"),
        ("Fix verification", "post3"),
    ]


def test_the_card_carries_no_agent_words_and_no_mentions():
    bug = Bug(key="k", report_id="RPT-101", opened_at=1_000_000, work_log_root_id="root")
    run(
        bug,
        "[CLAIM] bug=RPT-101 from=Kinetics doing: running U-48213 on preprod-atl-0001",
        "[REPORT] bug=RPT-101 from=Kinetics to=Atlas\nsummary: membership-service@3.12.0 stale for U-48213\nevidence: RUN-0001",
    )
    text = render_card(bug, permalink=lambda p: f"https://mm/pl/{p}", names={}, now_ms=1_300_000)
    for secret in ("U-48213", "preprod", "membership-service", "RUN-0001", "@"):
        assert secret not in text
    assert "[Reproduction](https://mm/pl/post1)" in text
    assert "[2 messages · 1 agent · 1 min](https://mm/pl/root)" in text
    assert "⏳ **Fixing**" in text and "**Working on it:** Atlas" in text


def test_an_early_close_skips_the_stages_it_never_reached():
    bug = Bug(key="k", report_id="RPT-104", opened_at=1_000_000)
    run(bug, "[CLOSE] bug=RPT-104 from=Triage outcome=duplicate\nsummary: known bug\nowner: BUG-1\nevidence: x")
    text = render_card(bug, permalink=str, names={}, now_ms=1_000_000)
    assert "Closed: a known bug, already fixed in a newer app version" in text
    assert "✅ Received → ✅ Done" in text and "Fixing" not in text
    assert "This card updates" not in text


# ── The herald against Mattermost ─────────────────────────────────────────────


def test_a_report_opens_a_work_log_thread_and_a_card(mm, herald):
    root, bug = report(mm, herald)
    opener = mm.posts[bug.work_log_root_id]
    assert opener["channel_id"] == "c-log" and opener["root_id"] == ""
    assert opener["message"].startswith("@triage [NEW BUG] bug=RPT-101 from=herald to=Triage reporter=user\n> Triage new bug RPT-101")
    assert "@Triage" not in opener["message"].split("\n", 1)[1], "only the header addresses triage"
    reply = mm.thread(root)
    assert [p["id"] for p in reply] == [bug.card_post_id], "the public thread gets the card and nothing else"
    assert "📥 **Received**" in card(mm, bug) and "http://mm.test/switch/pl/" + bug.work_log_root_id in card(mm, bug)


def test_only_reports_to_triage_open_bugs(mm, herald):
    mm.post("c-public", "u-rep", "Is anyone else seeing slow menus today?")
    mm.post("c-public", "u-admin", "@Triage hello from Switch")
    mm.post("c-public", "u-rep", "[REPORT] bug=RPT-9 from=Kinetics to=Atlas")
    herald.poll_once()
    assert herald.state.bugs == {}


def test_the_card_follows_the_work_log(mm, herald):
    _, bug = report(mm, herald)
    log_root = bug.work_log_root_id
    agent(mm, log_root, "@Espida [ASK] bug=RPT-101 from=Triage to=Espida\nquestion: backend for the user?")
    agent(mm, log_root, "@Atlas [REPORT] bug=RPT-101 from=Espida to=Atlas\nsummary: stale cache\nevidence: trace T-1")
    herald.poll_once()
    text = card(mm, bug)
    assert "⏳ **Fixing**" in text and "[Logs and impact](" in text and "3 messages" not in text
    assert "[2 messages · 2 agents" in text
    agent(mm, log_root, "@Triage [RCA] bug=RPT-101 from=Gremlin to=Triage\nwhat_happened: x")
    herald.poll_once()
    assert "✅ **Fixed**" in card(mm, bug) and "[Root cause analysis](" in card(mm, bug)


def test_triage_public_messages_reach_the_reporter_without_internal_details(mm, herald):
    root, bug = report(mm, herald)
    agent(
        mm, bug.work_log_root_id,
        "[PUBLIC] bug=RPT-101 from=Triage to=reporter\nFixed: the app now shows Gold. @Kinetics checked it on "
        "preprod-atl-0001 for U-48213 (membership-service@3.12.1).",
    )
    herald.poll_once()
    posted = [p for p in mm.thread(root) if p["id"] != bug.card_post_id]
    assert len(posted) == 1
    text = posted[0]["message"]
    assert text.startswith("**Triage:** Fixed: the app now shows Gold.")
    assert "@" not in text and "U-48213" not in text and "preprod-atl" not in text and "membership-service@" not in text
    assert text.count("[removed]") == 3


def test_only_triage_may_speak_in_public(mm, herald):
    root, bug = report(mm, herald)
    agent(mm, bug.work_log_root_id, "[PUBLIC] bug=RPT-101 from=Atlas to=reporter\nI fixed it!")
    herald.poll_once()
    assert [p["id"] for p in mm.thread(root)] == [bug.card_post_id]


def test_replies_in_the_public_thread_go_to_triage(mm, herald):
    root, bug = report(mm, herald)
    mm.post("c-public", "u-bob", "Same here on iOS, @Atlas please look", root)
    mm.post("c-public", "u-admin", "Switch notice", root)
    herald.poll_once()
    forwarded = [p for p in mm.thread(bug.work_log_root_id)]
    assert len(forwarded) == 1
    assert forwarded[0]["message"] == (
        "@triage [FROM PUBLIC] bug=RPT-101 from=herald to=Triage author=bob\n> Same here on iOS, Atlas please look"
    )


def test_the_herald_ignores_its_own_posts_and_handles_each_post_once(mm, herald):
    _, bug = report(mm, herald)
    agent(mm, bug.work_log_root_id, "[ASK] bug=RPT-101 from=Triage to=Telios\nquestion: set up")
    herald.poll_once()
    herald.poll_once()
    herald.poll_once()
    assert bug.messages == 1
    assert len(mm.thread(bug.work_log_root_id)) == 1, "no [FROM PUBLIC] for the herald's own card edits"


def test_a_restart_carries_on_from_the_state_file(mm, config):
    first = Herald(mm, config, now=lambda: mm.clock / 1000)
    first.start()
    root, bug = report(mm, first)
    second = Herald(mm, config, now=lambda: mm.clock / 1000)
    second.start()
    agent(mm, bug.work_log_root_id, "[CLAIM] bug=RPT-101 from=Kinetics doing: reproducing")
    second.poll_once()
    assert list(second.state.bugs) == [root], "the report was not opened twice"
    assert "**Working on it:** Kinetics" in mm.posts[bug.card_post_id]["message"]


def test_work_started_in_the_work_log_is_tracked_without_a_card(mm, herald):
    agent(mm, "", "[ASK] bug=RPT-777 from=Triage to=Espida\nquestion: ?")
    herald.poll_once()
    (bug,) = herald.state.bugs.values()
    assert bug.report_id == "RPT-777" and bug.card_post_id is None and bug.messages == 1


def test_a_first_start_ignores_history(mm, config):
    mm.post("c-public", "u-rep", "@Triage new bug RPT-101: old thread")
    h = Herald(mm, config, now=lambda: mm.clock / 1000)
    h.start()
    h.poll_once()
    assert h.state.bugs == {}


def test_channels_must_be_the_bots_and_different(mm, config):
    config.work_log_channel = "nope"
    with pytest.raises(HeraldError, match="not a channel the herald's bot is a member of"):
        Herald(mm, config).connect()
    config.work_log_channel = "generic-feedback"
    with pytest.raises(HeraldError, match="must differ"):
        Herald(mm, config).connect()


def test_config_rejects_unknown_keys_and_needs_a_token(tmp_path, monkeypatch):
    path = tmp_path / "herald.json"
    path.write_text(json.dumps({"mattermost_url": "x", "public_channel": "a", "work_log_channel": "b", "colour": "red"}))
    with pytest.raises(HeraldError, match="colour"):
        Config.load(path)
    path.write_text(json.dumps({"mattermost_url": "x", "public_channel": "a", "work_log_channel": "b", "token_file": str(tmp_path / "t")}))
    monkeypatch.delenv("TRACESQUAD_HERALD_TOKEN", raising=False)
    with pytest.raises(HeraldError, match="No bot token"):
        Config.load(path).token()
    (tmp_path / "t").write_text("abc\n")
    assert Config.load(path).token() == "abc"
    assert main(["status", "--config", str(tmp_path / "missing.json")]) == 1


def test_bug_state_round_trips():
    bug = Bug(key="k", report_id="RPT-1")
    run(bug, "[REPORT] bug=RPT-1 from=Kinetics to=Atlas\nsummary: x\nevidence: y")
    from dataclasses import asdict

    assert Bug.from_dict(json.loads(json.dumps(asdict(bug)))) == bug
    assert RECEIVED < INVESTIGATING
