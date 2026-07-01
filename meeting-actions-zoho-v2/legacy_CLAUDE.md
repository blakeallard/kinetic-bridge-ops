# Meeting Actions — Context & Roadmap

## What this is
Local pipeline that watches WorkDrive for new meeting summary files and automatically creates Zoho Projects tasks for action items extracted from the summary.

## Current setup (local Mac)
- `watch_meetings.sh` — launchd job, runs every 30 min, scans WorkDrive for new `_summary.txt` files
- `create_tasks.sh` — parses a summary file and creates Zoho tasks; supports `--blake-only`, `--worksheet`, `--dry-run`
- `parse_meeting_actions.py` — extracts action items, resolves owners, fills BEVCO diagnostic worksheets via Claude
- `zoho_attach.py` — attaches worksheet HTML to a Zoho task (wired but not yet enabled)
- `processed_notes.json` — tracks which files have already been processed (prevents re-runs)

## Watcher is currently Blake-only
`watch_meetings.sh` passes `--blake-only` until the pipeline is confirmed accurate for all owners.
Remove `--blake-only` from line 46 of `watch_meetings.sh` when ready to open up to Bill and Bryan.

## Full automation chain
```
Meeting ends → MP4 saved to WorkDrive
    → Zoho Flow → Railway transcriber (bevco-meeting-transcriber)
    → _summary.txt saved to WorkDrive
    → ZohoWorkDriveTrueSync syncs to Mac
    → watch_meetings.sh picks it up → creates Zoho tasks
```
Weak link: depends on Blake's Mac being awake.

---

## Planned: Port to Railway (do this when manager gets his Railway)

Replace the local Mac watcher with a cloud Railway service so it's always-on.

### Target architecture
```
MP4 uploaded to WorkDrive
    → Zoho Flow (trigger 1) → Railway transcriber       → _summary.txt saved
    → Zoho Flow (trigger 2) → Railway meeting-actions   → Zoho tasks created
```

### Steps to implement
1. Create a new FastAPI app (same pattern as `bevco-meeting-transcriber/main.py`)
   - `POST /process_summary` — receives summary file content from Zoho Flow webhook
   - Runs `parse_meeting_actions` logic in a background task
   - Creates Zoho tasks via direct API (no Claude CLI dependency)
2. Deploy as a separate Railway service under manager's Railway account
3. Add a new Zoho Flow:
   - Trigger: new `_summary.txt` file uploaded to WorkDrive
   - Action: POST file content + metadata to the Railway webhook
4. Set env vars on Railway (same Zoho OAuth creds as transcriber)
5. Remove `--blake-only` restriction once confirmed accurate

### Files to port
- `parse_meeting_actions.py` — core parsing logic, bring as-is
- Task creation logic from `create_tasks.sh` — rewrite in Python (remove Claude CLI dependency, call Zoho API directly)
- Dedup logic — already uses direct Zoho API, easy to port

### Reference
- Transcriber pattern: `~/Dev/web/bevco-meeting-transcriber/main.py`
- Zoho OAuth helper: `zoho_attach.py` → `get_access_token()`
