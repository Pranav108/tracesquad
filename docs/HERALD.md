# The herald

Bugs are reported in a public room that anyone in the community can read: the reporter, other users,
developers and product people. Working one bug takes the squad dozens of messages (one GOLD-01 run
took 38), and almost none of them are useful to someone who only wants to know what's going on.
Putting all of them in the reporter's thread buries the answer.

So the squad works in a second room, the **work log**: a private channel only the team can read. The
**herald** is the small program that links the two rooms. It's a Mattermost bot, not an agent. It
reads message headers and never writes prose of its own.

## What people see

The reporter's thread in the public room holds three kinds of post, and nothing else:

```
user      @Triage new bug RPT-101: Renewed Gold yesterday, money got deducted, but the app still
          shows 'Join Gold'. user U-48213

TraceSquad  RPT-101 · ✅ Fixed · closed 5:01 PM after 21 min                  ← the status card,
            ✅ Received → ✅ Investigating → ✅ Fixing → ✅ Verifying → ✅ Wrapping up → ✅ Done
            Evidence (team only): Reproduction · Logs and impact · Fix (PR and builds) ·
                                  Fix verification · Root cause analysis
            Work log (team only): 38 messages · 5 agents · 21 min

TraceSquad  Triage: Fixed. After renewing, the app kept showing an old expired Gold status for up
            to a day. The fix ships in the backend hotfix on 6 Nov; nothing to do on your side.
```

- **The status card** is posted within seconds of the report and edited in place as the work moves
  on. Edits don't notify anyone, so a long investigation adds no noise.
- **Evidence links** open the exact message in the work log that carries that evidence, so a
  developer jumps straight to the reproduction or the RCA instead of reading 38 messages. They only
  open for people in the private work-log channel.
- **Triage's messages** are the only words written for people: a question only the reporter can
  answer, and the outcome when the bug closes.

| Who | Reads |
|---|---|
| The reporter, anyone in the community | The card and Triage's messages |
| Developers, product | The evidence links, straight into the work log |
| Anyone checking how the squad got there | The whole work log thread |

## What the herald does

1. **A new report.** A root post in the public channel that mentions `@triage` opens a bug. The
   report id is the first match of `report_id_pattern` (`RPT-<digits>` by default). The herald posts a
   `[NEW BUG]` to triage in the work log, which starts the bug's work-log thread, and posts the card in
   the reporter's thread.
2. **The work log.** Every post in the work log with a protocol header (`[ASK]`, `[REPORT]`, …, with
   `bug=`, `from=`, `to=`) updates its bug's card. Only the header is read:

   | The card shows | When |
   |---|---|
   | Investigating | A message from or to Telios, Kinetics or Espida |
   | Fixing | A message from Atlas, or a `[REPORT]` to Atlas |
   | Verifying | Atlas sends Kinetics a message (a fix to verify), or Kinetics posts after that |
   | Wrapping up | Atlas hands Gremlin the verified fix, or Gremlin claims or reports after it |
   | Done | Gremlin's `[RCA]` (fixed), or Triage's `[CLOSE]` with its `outcome=` |
   | Working on it | The sender of the latest `[CLAIM]`, or the agents in the latest message's `to=` |
   | Evidence | Each message with an `evidence:` line, every `[CLOSE]` and every `[RCA]`, labelled by who sent it (Kinetics: "Reproduction", then "Fix verification" once a fix is out; Espida: "Logs and impact"; Atlas: "Fix (PR and builds)"; …). The latest one per label is linked |

   The card never moves backwards, and a bug closed early (a duplicate, say) skips the stages it
   never reached.
3. **Triage talks to the reporter.** A `[PUBLIC] bug=… from=Triage` in the work log is copied into the
   public thread. `@` is dropped from agent names (so nobody wakes), and anything matching
   `redact_patterns` (user ids, pre-prod env names, internal service versions) becomes `[removed]`.
   A `[PUBLIC]` from any other agent is ignored.
4. **Replies.** Anything people write in a bug's public thread goes to triage in the work log as
   `[FROM PUBLIC] bug=… author=<who>`, quoted.

The herald ignores its own posts, system messages, Switch's accounts (`ignore_users`) and the agents.
It handles each post once, saves its state after every poll, and on its very first start ignores
everything already in the channels.

## Set it up

You need the two channels (in Switch, the template creates both rooms: `tracesquad` and the private
`tracesquad-worklog`), and a Mattermost bot that is a member of both.

**1. Create the bot and its token.** As a Mattermost admin, in System Console → Integrations → Bot
Accounts, or with `mmctl`:

```bash
mmctl bot create tracesquad --display-name TraceSquad --description "Status cards for TraceSquad bugs"
mmctl token generate tracesquad herald            # prints the token once
mmctl team users add <team> tracesquad
mmctl channel users add <team>:<public channel name> tracesquad
mmctl channel users add <team>:<work log channel name> tracesquad
```

On Switch's local Mattermost (Switch Console's managed server), run these inside its container as
`docker exec <mattermost container> mmctl --local …`. Local mode is already enabled there.

**2. Save the token** where only you can read it:

```bash
mkdir -p ~/.tracesquad && umask 077 && printf '%s\n' '<token>' > ~/.tracesquad/herald-token
```

Or set `TRACESQUAD_HERALD_TOKEN` instead.

**3. Write `~/.tracesquad/herald.json`:**

```json
{
  "mattermost_url": "http://localhost:8065",
  "public_channel": "tracesquad",
  "work_log_channel": "tracesquad-worklog"
}
```

**4. Check it, then run it:**

```bash
scripts/herald.sh check     # finds the bot and both channels; warns if the work log isn't private
scripts/herald.sh           # runs until Ctrl-C; or: nohup scripts/herald.sh > ~/.tracesquad/herald.log 2>&1 &
scripts/herald.sh status    # the bugs it is tracking
```

## Configuration

| Key | Default | Meaning |
|---|---|---|
| `mattermost_url` | required | The address people open Mattermost at. Evidence links are built on it |
| `public_channel` | required | Id, name or display name of the public channel |
| `work_log_channel` | required | Id, name or display name of the work log channel |
| `triage` | `triage` | The agent reports go to, and the only one allowed to post `[PUBLIC]` |
| `agents` | the six | Agent names: never treated as reporters, and their `@` is dropped in copied text |
| `ignore_users` | `admin`, `switch-admin`, `system` | Accounts whose posts never open a bug or count as a reply |
| `report_id_pattern` | `\bRPT-\d+\b` | How a report id is found in a report. Without one the id is `FB-<post id>` |
| `redact_patterns` | user ids, `preprod-…`, `<name>-service@<version>` | Removed from every `[PUBLIC]` before it's posted |
| `poll_seconds` | `2` | How often both channels are read |
| `token_file` | `~/.tracesquad/herald-token` | Where the bot token is, unless `TRACESQUAD_HERALD_TOKEN` is set |
| `state_file` | `~/.tracesquad/herald-state.json` | The bugs it knows, and where it stopped reading |

## Limits

- **Polling, not a socket.** Cards lag the work log by up to `poll_seconds`.
- **One herald per pair of channels.** Two would post two cards.
- **Mattermost only.** The card is a Mattermost post the bot edits; Slack would need its own client.
- **Redaction is a safety net,** not the privacy rule. The rule is in Triage's instructions: a
  `[PUBLIC]` holds plain words and nothing internal.
