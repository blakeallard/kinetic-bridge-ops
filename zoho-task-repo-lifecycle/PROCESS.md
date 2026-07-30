# zoho-task-repo-lifecycle Runtime Process

**Purpose:** Dry-run by default; controlled apply mode creates GitHub repositories for Zoho tasks tagged `repo-needed`.

**Canonical Path:** `/Users/blakeallard/bevco/automations/zoho-task-repo-lifecycle`

---

## Entrypoint

**Primary:** `repo_lifecycle_dry_run.py` (Python script)

**Called by:** Manual invocation (human review + approval required before apply)

---

## Inputs

### Environment
- **Credentials source:** `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/.env`
  - `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`
  - `ZOHO_PROJECTS_PORTAL_ID`, `ZOHO_PROJECT_ID`
- **Token cache (read-only):** `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/zoho_access_token_cache.json`
- **GitHub org override:** `GITHUB_ORG` env var (defaults to `blake-bevco-tech`)

### Files
- **Task-repo mapping state:** `task_repo_map.json` (local state, git-ignored)
- **Mapping fallback locations:** (checked in order for multi-location support)
  - `./task_repo_map.json` (current automation folder)
  - `/Users/blakeallard/bevco/automation_state/task_repo_map.json`
  - `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/task_repo_map.json`

### Data Sources
- Zoho Projects REST API (read-only, or write during apply)
- GitHub API (read via `gh` CLI auth check, read-write during apply)
- Local `/Users/blakeallard/bevco/repos/` filesystem (read)

---

## Outputs

### Dry-run outputs (default)
1. **`reports/repo_lifecycle_dry_run_YYYY-MM-DD.md`** — Human-readable dry-run report
   - Lists `[INFO] would create repo`, `[SKIPPED]`, `[BLOCKED]` decisions for all tasks
   - Includes task metadata, duplicate check results, proposed repo name
   - No GitHub/Zoho/filesystem changes
2. **stdout** — Dry-run report printed to terminal

### Apply outputs (controlled mode, `--apply` flag)
1. **GitHub repository** — Private repo created in `blake-bevco-tech` org (or GITHUB_ORG override)
   - Name: Task key + slug (e.g., `bi1-t71-...`)
   - Visibility: Private
   - Starter files: README.md, TASK.md, AGENTS.md, `docs/CURRENT_HANDOFF.md`, `.gitignore`, `.github/ISSUE_TEMPLATE/zoho-task.md`, `.github/PULL_REQUEST_TEMPLATE.md`, plus empty `docs/`, `scripts/`, and `artifacts/` placeholders
2. **`task_repo_map.json`** — Updated local state mapping task → repo (atomically written)
3. **Zoho task comment** — Idempotent comment posted to task with GitHub repo link
4. **`reports/repo_lifecycle_apply_YYYY-MM-DD.md`** — Apply report

---

## Runtime Flow

```
repo_lifecycle_dry_run.py
  ├─ [Startup checks]
  │   ├─ Verify: .env credentials exist
  │   ├─ Load: ZOHO_* env vars, GitHub org
  │   ├─ Check: `gh auth status` (GitHub CLI authenticated)
  │   └─ Create: reports/ directory if missing
  │
  ├─ [Fetch data]
  │   ├─ Read: Zoho Projects task list (REST API)
  │   ├─ Tag-filter: Keep only tasks with exact "repo-needed" tag
  │   ├─ Load: task_repo_map.json (prior mappings)
  │   └─ Scan: /Users/blakeallard/bevco/repos/ (duplicate detection)
  │
  ├─ [Analyze each task]
  │   ├─ Decision: [INFO] would-create, [SKIPPED], or [BLOCKED]
  │   ├─ Checks:
  │   │   ├─ Is task tagged "repo-needed"?
  │   │   ├─ Does repo already exist (local or GitHub)?
  │   │   ├─ Is required metadata complete? (name, description)
  │   │   └─ Pass all safety checks?
  │   └─ Report: Task key, name, proposed repo name, checks summary
  │
  ├─ [DRY-RUN (default)]
  │   ├─ Write: reports/repo_lifecycle_dry_run_YYYY-MM-DD.md
  │   ├─ Print: Report to stdout
  │   └─ Exit: Code 0
  │
  └─ [APPLY (--apply + --task-key + --confirm-apply)]
      ├─ Verify: Task key appears in dry-run decisions as "would-create"
      ├─ Verify: Both confirmation args match task key
      ├─ Create: GitHub private repo in blake-bevco-tech org
      ├─ Clone: Repo locally to /Users/blakeallard/bevco/repos/
      ├─ Add: Minimal starter files (README.md, TASK.md, AGENTS.md, docs/CURRENT_HANDOFF.md, GitHub templates, and placeholders from templates/)
      ├─ Git: Commit + push (atomic)
      ├─ Update: task_repo_map.json (atomically)
      ├─ Post: Idempotent Zoho comment with GitHub link
      ├─ Write: Reports
      └─ Exit: Code 0 (or 1 if any step fails)
```

---

## Dry-Run / Apply Behavior

### Dry-run (default, `python3 repo_lifecycle_dry_run.py`)
- **Read-only on all external systems:**
  - Zoho: Reads only task list + tags
  - GitHub: Reads only via `gh repo view` (no writes)
  - Filesystem: Scans repos/ for duplicates (no writes)
- **Local writes:** None (except report file)
- **Idempotent:** Can be run repeatedly to preview decisions
- **Recommended:** Run dry-run first, review report, then run apply if satisfied

### Apply (controlled, `python3 repo_lifecycle_dry_run.py --apply --task-key <KEY> --confirm-apply <KEY>`)
- **Requires:**
  - `--apply` flag (must be explicit)
 - `--task-key <TASK_KEY>` (target task, must be in a current-run `would-create` or safe `existing` resume state)
  - `--confirm-apply <TASK_KEY>` (matching confirmation value, both must match)
- **Hard limits:**
  - Processes exactly one task per run
  - Task must be eligible in the same run's dry-run decisions
 - Applies only to `would-create` or verified safe `existing` resume decisions; conflicting state blocks execution
 - Existing repos may satisfy either the current minimal coordination-file set or the legacy larger coordination-file set
- **Writes:**
  - GitHub: Creates private repo
  - Local: Clones repo, commits starter files, pushes
  - State: Updates task_repo_map.json atomically
  - Zoho: Posts one idempotent comment
- **Rollback:** Not implemented; partial failures require manual verification, then a fresh dry-run and apply can resume only if the current run verifies a safe `existing` state

---

## Logs and Reports

| File | Source | Format | Lifecycle |
|------|--------|--------|-----------|
| `reports/repo_lifecycle_dry_run_YYYY-MM-DD.md` | Script | Markdown | One per run, uniquely named |
| `reports/repo_lifecycle_apply_YYYY-MM-DD.md` | Script | Markdown | One per apply run, uniquely named |
| stdout | Script | Text, human-readable | Printed during run |
| `.env` | (local) | Text (git-ignored) | Credential store (never printed) |
| `task_repo_map.json` | Script (apply only) | JSON (git-ignored) | Updated atomically on apply |

**Check for errors:**
- Dry-run: Read the `.md` report for `[BLOCKED]` items; apply only if all are `[INFO]`
- Apply: Read `reports/repo_lifecycle_apply_*.md` for `[BLOCKED]`, `[WARN]`, and apply-execution details

---

## Scheduling / LaunchD Integration

**Current scheduling:** Manual (no automation)

**Why:** This tool requires human review + explicit confirmation. Automate only after:
1. Multiple successful manual applies
2. Consensus on naming/template conventions
3. Documented approval process

**Manual invocation:**
```bash
# Step 1: Dry-run (review decisions)
cd /Users/blakeallard/bevco/automations/zoho-task-repo-lifecycle
python3 repo_lifecycle_dry_run.py
cat reports/repo_lifecycle_dry_run_*.md

# Step 2: Apply (if satisfied)
python3 repo_lifecycle_dry_run.py --apply --task-key BI1-T71 --confirm-apply BI1-T71
```

**LaunchD:** Not configured (intentional; would require approval workflow)

---

## Failure Modes

| Failure | Symptom | Root Cause Check | Recovery |
|---------|---------|------------------|----------|
| OAuth token expired | Zoho fetch fails in dry-run | Credentials stale or rotated | Update .env; retry dry-run |
| GitHub auth missing | `gh repo view` fails | GitHub CLI not authenticated | Run `gh auth login`; retry |
| Repo already exists | `[BLOCKED] repo already exists` | GitHub repo or local folder found | Use existing repo; don't create duplicate |
| Task metadata incomplete | `[BLOCKED] missing required metadata` | Task lacks name or description | Update task in Zoho; retry dry-run |
| Git push fails | Apply fails mid-push | Network/GitHub issue | Check GitHub status; retry apply |
| Partial apply (mid-create) | Repo exists but map not updated | Crash between GitHub create and map write | Manually verify repo state; delete repo if needed; retry |

---

## Recovery Steps

1. **After OAuth failure:**
   - Update `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/.env` with new credentials
   - Retry dry-run

2. **After GitHub auth failure:**
   - Run `gh auth status` to check login
   - Run `gh auth login` if needed
   - Retry dry-run

3. **After repo creation failure (apply):**
   - Check `reports/repo_lifecycle_apply_*.md` for error details
   - Manually verify GitHub repo state (may be partially created)
   - Delete repo if needed: `gh repo delete blake-bevco-tech/<repo-name> --confirm`
   - Fix the underlying issue (metadata, perms, etc.)
   - Retry dry-run + apply

4. **After partial apply (repo created but map not written):**
   - Manually verify the local repo path, GitHub repo, and current `task_repo_map.json` contents
   - Confirm the task still carries the exact `repo-needed` tag
   - Rerun dry-run, then rerun apply only if the current run reports a safe `existing` resume or `would-create` decision

---

## Validation Commands

```bash
# Dry-run to see what would happen
cd /Users/blakeallard/bevco/automations/zoho-task-repo-lifecycle
python3 repo_lifecycle_dry_run.py
cat reports/repo_lifecycle_dry_run_*.md

# Check GitHub auth
gh auth status

# Check existing mappings
cat task_repo_map.json

# Check Zoho task eligibility (manual)
# Log into Zoho, find task tagged "repo-needed"

# List existing repos
ls -la /Users/blakeallard/bevco/repos/ | head -20
gh repo list blake-bevco-tech
```

---

## Safety Boundaries

- **Dry-run only:** Default mode is read-only; apply requires explicit flags
- **One task per apply:** Can't bulk-create; reviewed individually
- **Private GitHub repos only:** No public visibility (override requires code change)
- **No delete/force-push:** Only create, commit, push; no destructive operations
- **Explicit confirmation:** `--confirm-apply` must match `--task-key` exactly
- **Secrets never printed:** No credentials, tokens, or secrets in reports or stdout
- **Template inheritance:** Conservative starter files generated in apply; shared template reuse deferred per architecture decision
- **Optional templates:** `docs/PROCESS.md` and `.github/copilot-instructions.md` templates are preserved in this repo for manual use, but no optional-generation switch is implemented today

---

## Important Notes

- **No scheduler:** This automation requires human approval. Do not add to cron/launchd without explicit permission.
- **Git-ignored state:** `task_repo_map.json` is not committed; it's local reconciliation cache. GitHub + Zoho are canonical sources of truth.
- **Idempotent Zoho comments:** Posting the same comment twice is safe (script prevents duplicate links).
- **Template deferral:** Shared template extraction from zoho-task-folder-sync is intentionally deferred. The current apply path generates a minimal default package instead.

---

## Related Repos / Files

- **Credential source:** `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/.env`
- **Token cache:** `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/zoho_access_token_cache.json` (read-only)
- **Mapping state:** `./task_repo_map.json` (local git-ignored)
- **Starter templates:** `./templates/repo/` (minimal defaults plus preserved optional/legacy templates)
- **Reports:** `./reports/` (dry-run + apply reports)
- **Local repos:** `/Users/blakeallard/bevco/repos/` (where cloned repos are stored)
- **Upstream:** `bevco-zoho-poller` (detects new tasks + repo-needed tag); this tool processes tagged tasks
- **Sibling:** `zoho-task-folder-sync` (mirrors tasks to WorkDrive; independent of repo creation)
- **Parent README:** See `README.md` in this folder for architectural overview
