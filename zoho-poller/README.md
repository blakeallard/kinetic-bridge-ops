# Bevco BE-9 Task Workflow — Setup Guide

Two pieces, two environments. Read this once, then forget the mechanics and just use it.

## Piece 1 — The Chat skill (`bevco-task-intake`)

**Lives in:** Claude Chat (this app)
**Install:** Upload the `bevco-task-intake/` folder as a custom skill in Claude.ai (Settings → Capabilities → Skills, or wherever skill upload lives in your plan).
**Runs:** Automatically, any time you paste task content into a conversation. No need to invoke it by name.

What it does:
1. Parses whatever Zoho task data you give it (raw JSON, copied text, or just a title/description)
2. Auto-fills the BEVCO Diagnostic Worksheet
3. Classifies the task against your Tier 1/2/3 framework
4. **Stops and checks in with you** — shows the filled worksheet + tier + proposed next action
5. Once you confirm, drafts the actual deliverable (runbook, one-pager, diagram spec, etc.)

## Piece 2 — The Claude Code poller (`bevco-zoho-poller`)

**Lives in:** Claude Code, on your machine, scheduled via cron
**Runs:** On a schedule (e.g. every 30 min during work hours) — this is the only piece that can actually run unattended and "watch" Zoho

What it does:
1. Calls `ZohoProjects_get_tasks_by_portal` to pull current tasks
2. Diffs against the last-seen task list (`last_seen_tasks.json`)
3. Writes `new_task_alerts.md` if anything new shows up
4. Each alert includes a note reminding you to paste the task into Claude Chat

### Setup

```bash
cd bevco-zoho-poller
chmod +x run_poll.sh
```

Test it manually first:
```bash
./run_poll.sh
cat new_task_alerts.md
```

Then schedule with cron:
```bash
crontab -e
# Add this line:
*/30 9-18 * * 1-5  cd /path/to/bevco-zoho-poller && ./run_poll.sh >> poll.log 2>&1
```

This runs every 30 minutes, 9am–6pm, Monday–Friday.

## The full loop, end to end

1. **(Code, scheduled)** Poller detects a new task → writes alert → you see it next time you check `new_task_alerts.md` or your terminal/log
2. **(You)** Copy the task block from the alert, paste into Claude Chat
3. **(Chat, automatic)** Skill fires → worksheet filled → tier classified → checks in with you
4. **(You)** Confirm or correct
5. **(Chat)** Drafts the deliverable
6. **(You, or Code)** If the deliverable requires actual Zoho writes, hand the spec to Claude Code to execute; if it's a document/diagram, it's already done

## Notes

- The poller script doesn't call Zoho directly — it relies on Claude Code's `claude -p` to do the actual MCP call, since that's the environment with reliable Zoho access (see tool_search sync issues in Claude Chat).
- If Claude Code's `--output-format json` shape changes in a future version, the JSON-extraction step in `run_poll.sh` may need adjusting — check `poll_error.log` if the poller starts failing silently.
- Tier framework lives in three places by design (this skill, your CLAUDE.md, and Claude's memory) — if you ever change your permission tiers, update all three.
