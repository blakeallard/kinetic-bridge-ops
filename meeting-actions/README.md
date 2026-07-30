# Bevco Meeting Actions

Extracts qualified action items from meeting summaries using the BEVCO
Task / Workflow Diagnostic Worksheet as the filter, and creates Zoho Projects
tasks for them.

Two pipelines live in this repo:

| Pipeline | Files | Status |
|---|---|---|
| **Railway service (OpenAI gpt-4o-mini)** | `main.py`, `pipeline.py`, `zoho_client.py`, `cli.py` | Current — cloud, no Claude CLI dependency |
| Legacy local Mac watcher (Claude CLI) | `watch_meetings.sh`, `create_tasks.sh`, `parse_meeting_actions.py`, `zoho_attach.py` | Kept for local fallback; depends on Blake's Mac + Claude CLI |

---

# Railway OpenAI Deployment

## Architecture

```
Meeting ends → MP4 in WorkDrive
  → Zoho Flow (trigger 1) → Railway transcriber        → _summary.txt in WorkDrive
  → Zoho Flow (trigger 2, new _summary.txt file)
      → POST summary text + filename + portal/project metadata
        to this service's /process_summary
  → worksheet-based extraction (OpenAI gpt-4o-mini, temperature 0, strict JSON)
  → dedupe (filename, normalized title vs existing Zoho tasks, dedupe_key)
  → Zoho Projects tasks created via direct REST API (OAuth refresh token)
```

A task is created only when the summary describes a concrete follow-up
workflow with a requested task, a business problem, involved systems, and a
clear next action (Research / Access / Draft / Build|test / Document /
Review). Background notes, vague monitoring items, and decisions with no
follow-up work are filtered out. All owners are supported; `blake_only` is an
optional flag, not a default.

## Endpoints

- `GET /health` → `{"ok": true}`
- `POST /process_summary` — see payload below

## Required environment variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Worksheet extraction (`gpt-4o-mini`) |
| `ZOHO_CLIENT_ID` | Zoho self-client OAuth |
| `ZOHO_CLIENT_SECRET` | Zoho self-client OAuth |
| `ZOHO_REFRESH_TOKEN` | Zoho self-client OAuth — see required scopes below |
| `ZOHO_PORTAL_ID` | Default portal (898600220) when payload has no numeric id |
| `ZOHO_PROJECT_ID` | Default project (2543412000001324010) |
| `PORT` | Injected by Railway |

Optional: `OPENAI_MODEL`, `ZOHO_ACCOUNTS_BASE_URL`, `ZOHO_PROJECTS_API_BASE`,
`ATTACH_WORKSHEET_HTML=1` (attach full worksheet HTML to each task),
`STATE_FILE` (point at a Railway volume path for durable dedupe state),
`LOG_LEVEL`. See `.env.example`.

### Required Zoho OAuth scopes

The refresh token must be minted (self-client → Generate Code) with Zoho
Projects scopes — a token that authenticates fine but lacks these returns
**403** on the tasks endpoints:

- **Required minimum:**
  `ZohoProjects.portals.READ,ZohoProjects.projects.READ,ZohoProjects.tasks.READ,ZohoProjects.tasks.CREATE`
- **Preferred:**
  `ZohoProjects.portals.READ,ZohoProjects.projects.READ,ZohoProjects.tasks.ALL`
- **Optional (worksheet HTML attachments, `ATTACH_WORKSHEET_HTML=1`):**
  `ZohoProjects.attachments.ALL`

Symptom map: `tasks.READ` missing → 403 on the dedupe fetch
(`GET .../tasks/`); `tasks.CREATE` missing → 403 on task creation. Changing
scopes requires generating a new grant code and re-exchanging it for a new
refresh token — scopes on an existing refresh token cannot be widened.

## Zoho Flow webhook payload

Configure the Flow's webhook action to POST JSON to
`https://<railway-app>.up.railway.app/process_summary`:

```json
{
  "summary_text": "<full text of the _summary.txt file>",
  "summary_file_name": "Blake's Weekly Catch-Up_summary.txt",
  "portal_id": "bevcollc",
  "project_id": "2543412000001324010",
  "dry_run": false
}
```

`portal_id` may be the portal name or numeric id — non-numeric values fall
back to `ZOHO_PORTAL_ID`. Optional field: `blake_only` (boolean).

Response:

```json
{
  "summary_file_name": "...",
  "meeting_name": "...",
  "created_count": 2,
  "skipped_count": 1,
  "tasks": [ ...raw worksheet extraction... ],
  "created_tasks": [ {"title": "...", "task_id": "...", "dedupe_key": "..."} ],
  "skipped_tasks": [ {"title": "...", "reason": "duplicate_title"} ]
}
```

## Local run

```bash
cd ~/Dev/bevco/meeting-actions
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in real values

# Dry-run one summary (extracts + dedupes, creates nothing):
python3 cli.py "Blake's Weekly Catch-Up_summary.txt" --blake-only

# Real run (creates Zoho tasks):
python3 cli.py "Blake's Weekly Catch-Up_summary.txt" --apply

# Or run the API itself:
uvicorn main:app --port 8000
curl -X POST localhost:8000/process_summary -H 'Content-Type: application/json' \
  -d '{"summary_text":"...","summary_file_name":"test_summary.txt","dry_run":true}'
```

## Railway deploy

1. Push this repo to GitHub (`railway.json` and `requirements.txt` drive the
   Nixpacks build; start command is `uvicorn main:app`).
2. Railway → New Service → Deploy from this repo.
3. Set the env vars above (same Zoho creds as bevco-meeting-transcriber).
4. Verify `GET /health` returns `{"ok": true}`.
5. Point the Zoho Flow webhook at `/process_summary` with `"dry_run": true`
   first; flip to `false` once the extracted tasks look right.

## Dedupe behavior

1. **File level** — a `summary_file_name` already recorded in
   `processed_notes.json` is never reprocessed (dry-run is exempt).
2. **Title level** — existing tasks in the target project are fetched
   (paginated) and any candidate whose normalized title matches is skipped.
3. **dedupe_key** — each task gets a stable key (model-generated, fallback:
   systems + requested workflow). The key is embedded in the task description
   (`Dedupe-key: ...`) so future runs can match it in existing Zoho task
   descriptions; keys are also stored in local state.

## Known limitations

- **Ephemeral state on Railway**: `processed_notes.json` resets on redeploy.
  The durable dedupe layers are the Zoho title/description checks; for
  durable file-level dedupe, mount a Railway volume and set
  `STATE_FILE=/data/processed_notes.json`.
- **Tags are not applied** by the Railway path — the legacy pipeline set the
  `automation`/`internal-work` tags via Claude MCP; the v1 REST create-task
  endpoint doesn't take tags. Add a tag-association call later if needed.
- **Tasks go to the General tasklist** — the legacy per-meeting tasklist
  creation was Claude-CLI-based and is not ported yet.
- **Synchronous processing**: extraction of a typical summary takes a few
  seconds with gpt-4o-mini; if Zoho Flow webhook timeouts become an issue,
  move `process_summary` into a FastAPI background task.
- **Owner resolution** maps names to ZPUIDs for Blake/Bill/Bryan only;
  unmatched assignees create unassigned tasks (assignee is still recorded in
  the description).
- `GET /process_summary` (dedupe fetch) reads the *description* field only if
  Zoho returns it in the task list response; the local dedupe-key registry
  covers the gap.

## Legacy local pipeline (unchanged)

`watch_meetings.sh` (launchd, every 30 min) → `create_tasks.sh <file>
--worksheet --blake-only` → Claude CLI worksheet fill + MCP task creation.
See `CLAUDE.md` for details. This path still requires Blake's Mac to be awake
and the Claude CLI to be installed; it is superseded by the Railway service.
