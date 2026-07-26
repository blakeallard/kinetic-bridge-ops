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

## Piece 3 — Local task workspace sync (`sync_local_task_workspaces.py`)

**Lives in:** the same `bevco-zoho-poller` folder, runs automatically at the end of `run_poll.sh`
**Runs:** every time the poller runs (every 30 min, scheduled via the existing cron entry — no scheduler changes needed)

What it does:
1. Reads `new_tasks.json` (written by `bevco_task_poller.py` on every run — the raw list of tasks detected as new *this run*, `[]` if none)
2. For each new task, creates or updates a local folder under `/Users/blakeallard/bevco/task-workspaces/<task-key>-<slug>/` (override with `--workspace-root`)
3. Writes `.zoho_task_metadata.json` (task id, key, name, project, portal, status, owner, timestamps, description, Zoho link) — safe to overwrite every sync
4. Writes/refreshes `HANDOFF.md` — an auto-generated header (task summary + metadata table) inside `<!-- zoho-sync:start/end -->` markers, so any manual notes you add below the markers survive future resyncs

This is a pure local file operation — no Zoho API calls, no credentials, no Cliq notifications. It never touches WorkDrive sync, the GitHub repo-lifecycle tool, or `bevco/repos/`.

### Manual test

```bash
cd bevco-zoho-poller
python3 sync_local_task_workspaces.py --input new_tasks.json --dry-run   # preview only
python3 sync_local_task_workspaces.py --input new_tasks.json            # apply
```

To test against a specific task without waiting for a real new one, hand-build a small JSON list (an array of raw Zoho task objects, same shape as entries in `tasks_latest.json`'s `data.tasks`) and pass it via `--input`.

### Recovery

- **Workspace folders are never auto-deleted or moved.** If a sync fails partway, rerun `sync_local_task_workspaces.py` against the same `new_tasks.json` — it's idempotent (matches existing folders by stored `task_id`, falls back to task-key prefix) and won't duplicate a folder.
- To force a clean metadata rewrite for one task, delete that task's `.zoho_task_metadata.json` and rerun — `HANDOFF.md`'s manual content (anything below the `zoho-sync:end` marker) is untouched either way.
- If `run_poll.sh` logs `[WARN] Local task workspace sync failed`, the poller's detection/alert step already succeeded — check the workspace-sync output above that line in `poll.log` for the actual error. A sync failure never blocks or invalidates task detection.

## The full loop, end to end

1. **(Code, scheduled)** Poller detects a new task → `new_tasks.json` is written → a local task workspace is created/synced under `/Users/blakeallard/bevco/task-workspaces/<task-key>-<slug>/`
2. **(You, or Claude/Codex directly)** Open/`cd` into that workspace — `HANDOFF.md` is the starting context: task summary, metadata table, and Zoho link, ready for Claude/Codex to pick up immediately
3. **(Optional)** If you want the worksheet/tier-classification flow, paste the task content into Claude Chat — the `bevco-task-intake` skill fills the diagnostic worksheet, classifies the tier, and checks in with you before drafting a deliverable
4. **(You, or Code)** If the deliverable requires actual Zoho writes, hand the spec to Claude Code to execute; if it's a document/diagram, it's already done

`new_task_alerts.md` is still written every run a new task is found — keep it as a fallback/manual visibility feed (glance at what's new without opening a workspace), but it is **not** the primary handoff mechanism anymore; the local workspace + `HANDOFF.md` is.

## Notes

- The poller now calls the Zoho Projects REST API directly (`fetch_zoho_tasks.py`), reusing the OAuth refresh credentials in `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/.env` — the same source the Cliq status poller and repo-lifecycle tool use. The previous `claude -p` MCP fetch was removed because it required an interactive Claude login and failed under cron.
- If the fetch starts failing, check `poll_error.log`; token refresh problems and HTTP errors are logged there. The access-token cache (`zoho_access_token_cache.json`, git-ignored) is local to this folder; the status poller's cache is read but never written.
- When a newly detected task carries the exact `repo-needed` tag, `run_poll.sh` prints an `[ACTION NEEDED]` line into `poll.log` with the exact repo-lifecycle dry-run/apply commands to run. Repo creation stays human-approved — the poller never creates repos itself.
- Tier framework lives in three places by design (this skill, your CLAUDE.md, and Claude's memory) — if you ever change your permission tiers, update all three.
