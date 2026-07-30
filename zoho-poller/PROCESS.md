# bevco-zoho-poller Runtime Process

**Purpose:** Poll Zoho Projects (BE-9) for new tasks, diff against prior state, alert on changes, and sync new tasks to local workspaces.

**Canonical Path:** `/Users/blakeallard/bevco/automations/bevco-zoho-poller`

---

## Entrypoint

**Primary:** `run_poll.sh` (shell wrapper)  
**Called by:** cron, launchd, or manual invocation

**Secondary entry points (called by run_poll.sh):**
- `fetch_zoho_tasks.py` — Fetch live task list via Zoho REST API
- `bevco_task_poller.py` — Diff new tasks against last_seen_tasks.json
- `sync_local_task_workspaces.py` — Create/update local workspace folders

---

## Inputs

### Environment
- **Credentials source:** `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/.env`
  - `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`
  - `ZOHO_PROJECTS_PORTAL_ID`, `ZOHO_PROJECT_ID`
- **Token cache (read):** `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/zoho_access_token_cache.json`
- **Token cache (write):** `./zoho_access_token_cache.json` (local, avoids writer contention)

### Files (from run_poll.sh context)
- `tasks_latest.json` — Latest complete task list (written by fetch_zoho_tasks.py)
- `last_seen_tasks.json` — Previous run's task list (state file)
- `new_tasks.json` — Tasks detected as new this run (written by bevco_task_poller.py)

### State
- Zoho Projects REST API (read-only via fetch_zoho_tasks.py)
- Local task state files

---

## Outputs

1. **`tasks_latest.json`** — Complete task list from Zoho (raw shape: `{"data": {"tasks": [...]}}`), written by fetch_zoho_tasks.py
2. **`last_seen_tasks.json`** — State file tracking seen task IDs + last run timestamp, updated by bevco_task_poller.py
3. **`new_tasks.json`** — Array of raw Zoho task objects detected as new in this run, written by bevco_task_poller.py (empty `[]` if no new tasks)
4. **`new_task_alerts.md`** — Human-readable alert file when new tasks found, written by bevco_task_poller.py (overwritten each run)
5. **`poll.log`** — Timestamped log of all script output (appended by run_poll.sh via cron redirect)
6. **`poll_error.log`** — Errors from fetch_zoho_tasks.py only (written by fetch_zoho_tasks.py, may be empty)
7. **Local workspace folders** — Created/updated under `/Users/blakeallard/bevco/task-workspaces/<task-key>-<slug>/` for each new task
   - `.zoho_task_metadata.json` — Immutable task metadata snapshot
   - `HANDOFF.md` — Auto-generated header + manual notes area

---

## Runtime Flow

```
run_poll.sh (orchestrator)
  ├─ [Step 1] fetch_zoho_tasks.py
  │   ├─ Read: .env (credentials)
  │   ├─ Read: shared token cache (if fresh)
  │   ├─ Call: Zoho REST API → fetch task list
  │   ├─ Write: tasks_latest.json (complete list)
  │   └─ Write: ./zoho_access_token_cache.json (if refreshed)
  │
  ├─ [Step 2] bevco_task_poller.py
  │   ├─ Read: tasks_latest.json (from step 1)
  │   ├─ Read: last_seen_tasks.json (previous state)
  │   ├─ Diff: Find new task IDs
  │   ├─ Write: new_tasks.json (raw Zoho task objects, [] if none)
  │   ├─ Write: new_task_alerts.md (human alert, if tasks found)
  │   └─ Write: last_seen_tasks.json (updated state)
  │
  ├─ [Step 3] sync_local_task_workspaces.py
  │   ├─ Read: new_tasks.json
  │   ├─ For each task:
  │   │   ├─ Create: /Users/blakeallard/bevco/task-workspaces/<task-key>-<slug>/
  │   │   ├─ Write: .zoho_task_metadata.json (static snapshot)
  │   │   └─ Write/refresh: HANDOFF.md (auto-header + manual area)
  │   └─ (If no new tasks, this step is idempotent no-op)
  │
  └─ [Step 4] Embedded Python (repo-needed tag check)
      ├─ Read: new_tasks.json
      ├─ Find: Tasks with exact "repo-needed" tag
      └─ Print: ACTION NEEDED messages to stdout
```

---

## Dry-Run / Apply Behavior

**Dry-run (default):**
- All steps read-only except for state file updates (last_seen_tasks.json)
- No API writes to Zoho
- No GitHub operations
- Intended usage: run manually to preview new tasks before workspace sync

**Apply (full run):**
- fetch_zoho_tasks.py: Writes token cache if refreshed (normal)
- bevco_task_poller.py: Updates state (last_seen_tasks.json, new_task_alerts.md)
- sync_local_task_workspaces.py: Creates/updates workspace folders + HANDOFF.md
- No destructive operations (folders never auto-deleted)

**Idempotent:** Rerunning against same Zoho state produces identical outputs.

---

## Logs and Reports

| File | Writer | Format | Lifecycle |
|------|--------|--------|-----------|
| `poll.log` | run_poll.sh | Text, timestamped | Appended (cron redirect) |
| `poll_error.log` | fetch_zoho_tasks.py | Text | Overwritten each run |
| `new_task_alerts.md` | bevco_task_poller.py | Markdown | Overwritten each run |
| `last_seen_tasks.json` | bevco_task_poller.py | JSON | Overwritten each run |
| `tasks_latest.json` | fetch_zoho_tasks.py | JSON | Overwritten each run |

**Check for errors:**
- `poll_error.log` — OAuth/HTTP issues from Zoho fetch
- `poll.log` → Look for `[WARN]` or `[ERROR]` lines if workspace sync failed
- Script exits with code 1 if fetch_zoho_tasks.py fails; sync failures are logged but don't stop the run

---

## Scheduling / LaunchD Integration

**Current scheduling:** cron (manual setup in crontab)

**Recommended cron entry:**
```bash
*/30 9-18 * * 1-5  cd /Users/blakeallard/bevco/automations/bevco-zoho-poller && ./run_poll.sh >> poll.log 2>&1
```
- Every 30 minutes, 9am–6pm, Monday–Friday
- Appends stdout + stderr to poll.log

**LaunchD:** Not currently managed by launchd (uses cron instead)

**Manual test:**
```bash
cd /Users/blakeallard/bevco/automations/bevco-zoho-poller
./run_poll.sh
cat new_task_alerts.md      # see new tasks
cat poll.log                # see trace
cat poll_error.log          # see fetch errors if any
```

---

## Failure Modes

| Failure | Symptom | Root Cause Check | Recovery |
|---------|---------|------------------|----------|
| OAuth token expired | `poll_error.log` has HTTP 401 | Credentials stale or rotated | Refresh OAuth token in .env, delete token caches |
| Zoho API unreachable | `poll_error.log` has connection error | Network/Zoho downtime | Retry after Zoho is back online; log won't block next run |
| Workspace sync fails | `[WARN] Local task workspace sync failed` in poll.log | Permission/disk issue, TrueSync lock contention | Check workspace folder perms, retry after TrueSync syncs |
| run_poll.sh exits 1 | Task fetch failed entirely | Check poll_error.log | Fix OAuth or network, retry manually |

---

## Recovery Steps

1. **After OAuth failure:**
   - Check credentials in `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/.env`
   - Delete `/Users/blakeallard/bevco/automations/bevco-zoho-poller/zoho_access_token_cache.json` to force re-auth
   - Run `./run_poll.sh` manually

2. **After workspace sync failure:**
   - Rerun `./run_poll.sh` (sync is idempotent; same input produces same output)
   - Check folder permissions under `/Users/blakeallard/bevco/task-workspaces/`
   - If `HANDOFF.md` is corrupted, delete it and rerun to regenerate

3. **To manually process a new task without waiting for cron:**
   - Edit `new_tasks.json` to add/modify the task object
   - Run `python3 sync_local_task_workspaces.py --input new_tasks.json`

---

## Validation Commands

```bash
# Verify fetch works
python3 fetch_zoho_tasks.py --out /tmp/test_tasks.json

# Verify diff works
python3 bevco_task_poller.py --input /tmp/test_tasks.json --state last_seen_tasks.json

# Verify workspace sync works (dry-run)
python3 sync_local_task_workspaces.py --input new_tasks.json --dry-run

# Full end-to-end
./run_poll.sh
tail -20 poll.log
ls -la /Users/blakeallard/bevco/task-workspaces/
```

---

## Safety Boundaries

- **No Zoho writes:** Fetch and diff only; no task updates, status changes, or tag modifications
- **No GitHub operations:** Repo-needed tags are detected and logged; actual repo creation is handled by separate `zoho-task-repo-lifecycle` automation (requires manual approval)
- **Idempotent workspace sync:** Folders are never auto-deleted; reruns safely update metadata
- **State isolation:** Token caches are local; no writer contention with other tools
- **Error-tolerant:** Workspace sync failures don't block task detection; errors are logged and reported

---

## Related Repos / Files

- **Credential source:** `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/.env`
- **Token cache (shared):** `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/zoho_access_token_cache.json`
- **Workspace output:** `/Users/blakeallard/bevco/task-workspaces/`
- **Downstream:** `zoho-task-folder-sync` (mirrors to WorkDrive), `zoho-task-repo-lifecycle` (creates GitHub repos)
- **Parent README:** See `README.md` in this folder for architectural overview
