# Final Lifecycle Implementation Plan

## [CURRENT STATE]

### What already works

- `repo_lifecycle_dry_run.py` is dry-run by default and can read Zoho Projects tasks from the configured summer project.
- The script detects tasks with the exact `repo-needed` tag.
- It derives a repo name from `BI1-T##` plus the task title slug.
- It performs duplicate/evidence checks across:
  - Zoho task metadata and comments
  - local repos under `/Users/blakeallard/bevco/repos`
  - approved mapping files, including local `task_repo_map.json`
  - GitHub repo existence via `gh repo view`
- It writes dated markdown reports under `reports/`.
- It already created and verified the private BI1-T71 GitHub repo and the corresponding local repo.
- It already pushed starter files for BI1-T71.
- It already wrote a mapping entry to `task_repo_map.json`.
- It already posted an idempotent Zoho comment for BI1-T71.

### What is dry-run only

- All default runs are read-only with respect to GitHub repos, git pushes, Zoho writes, local repo creation, and mapping writes.
- The dry-run path only writes the runtime report file.
- No GitHub Issue, GitHub Project item, kanban sync, notification, or scheduler behavior exists yet.

### What is apply-capable

- Apply mode exists behind `--apply --task-key BI1-T71 --confirm-apply BI1-T71`.
- Current apply mode can:
  - create or verify the local repo directory
  - generate starter files
  - initialize a git repo on `main`
  - create or verify a private GitHub repo
  - add and verify `origin`
  - commit and push starter files
  - atomically write `task_repo_map.json`
  - post one Zoho backlink comment if the exact comment is not already present

### What is hard-coded to BI1-T71

- `APPLY_TASK_KEY = "BI1-T71"` is enforced in argument gating and in `apply_one_task()`.
- Valid task-key parsing is effectively constrained to `BI1-T\d+`.
- The apply path refuses all tasks except BI1-T71, even if they are tagged `repo-needed`.
- The README explicitly documents apply as BI1-T71-only.

### What repo/template files are currently generated

Current generated starter set from `starter_file_contents()`:

- `README.md`
- `TASK.md`
- `CLAUDE.md`
- `AGENTS.md`
- `.gitignore`
- `docs/.gitkeep`
- `scripts/.gitkeep`
- `artifacts/.gitkeep`

Current generator does not create:

- `STATUS.md`
- `CODEX.md`
- `.github/ISSUE_TEMPLATE/zoho-task.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- a GitHub issue body
- any repo-level project or status-sync metadata file

### What mapping and Zoho comment behavior exists

- `task_repo_map.json` stores:
  - `task_id`
  - `task_key`
  - `title`
  - `repo_name`
  - `repo_url`
  - `local_path`
  - `created_at`
- Mapping writes are atomic via temp file + `os.replace()`.
- Mapping conflicts block apply instead of overwriting.
- Zoho comment behavior is idempotent only for a single exact message:
  - `GitHub repo created: <repo_url>`
- The script checks existing task comments and skips the write if that exact content already exists.
- There is no structured comment marker, no issue link, no project link, no local path, and no synced status in the current comment.

## [GAPS]

### Generalizing apply mode beyond BI1-T71

- Remove the single-task allowlist without removing safety.
- Replace the BI1-T71 hard gate with a confirmation gate tied to an eligible task key selected from the current dry-run decision set.
- Preserve conflict blocking for mismatched mappings, repo names, remotes, and task metadata.
- Keep dry-run as default and require explicit apply confirmation per task.

### Creating GitHub Issues

- No issue creation exists.
- No issue template population exists.
- No issue number or URL is stored in mapping state.
- No duplicate detection exists for “issue already created for this Zoho task.”

### Creating/updating GitHub Project items

- No GitHub Project integration exists.
- No project item creation exists.
- No project field lookup or field update exists.
- No project item ID is stored in state.

### Mirroring Zoho kanban status into GitHub Project status

- The script reads task status but does not persist or sync it anywhere in GitHub.
- No status mapping table exists.
- No unknown-status handling exists.
- No overwrite guard exists for project-field updates.

### Standardizing repo templates

- The current starter files are MVP-safe but below the BI1-T71 repo standard.
- Current generated repos do not include `STATUS.md`, `CODEX.md`, GitHub templates, or explicit workflow instructions for future agents.
- Template reuse is currently deferred instead of standardized.

### Agent notification/ping options

- No notification channel integration exists in this workflow.
- Existing env names suggest webhook-based options may already exist elsewhere, but the lifecycle script does not use them.
- There is no explicit “repo ready for Claude/Codex/Antigravity” notification step.

### Idempotency and duplicate handling

- Repo creation, mapping, and the simple Zoho comment are reasonably guarded.
- Issue creation, project item creation, and status sync have no idempotency design yet.
- There is no canonical marker format spanning repo, issue, project item, and Zoho comment.
- There is no persisted sync checkpoint such as “last mirrored Zoho status.”

### Scheduling/triggering strategy

- The script is run manually today.
- No poll scheduler, cron wrapper, launch agent, or CI trigger is defined.
- No lockfile or single-run coordination exists to prevent overlapping apply runs.

## [PROPOSED ARCHITECTURE]

### Final workflow

1. Poll Zoho Projects for current tasks.
2. Filter to tasks explicitly approved for repo creation.
3. Validate task metadata and compute deterministic repo slug.
4. Reconcile existing state across local repo, GitHub repo, issue, project item, mapping file, and Zoho comments.
5. In dry-run:
   - emit a full planned action report
   - do not write repo, issue, project, mapping, or Zoho comment changes
6. In apply:
   - create or verify private GitHub repo
   - create or verify local repo
   - populate standard AI-agent templates
   - commit and push
   - create or verify one GitHub Issue for the Zoho task
   - create or verify one GitHub Project item linked to that issue
   - mirror Zoho status into the GitHub Project status field
   - update mapping state atomically
   - post one structured, idempotent Zoho backlink comment
   - optionally send one notification

### Approval model

- Source-of-truth eligibility: Zoho task carries exact `repo-needed` tag.
- First version apply gate:
  - `--apply`
  - `--task-key <TASK_KEY>`
  - `--confirm-apply <TASK_KEY>`
- Optional future hardening:
  - require the selected task to appear as `would-create` or `existing-resume` in the same run
  - require an explicit `--approve-repo-worthy` flag only for non-tag-based approvals if that path is later added

### Data flow

- Zoho task data
  - inputs: task ID, task key, title, description, tags, status, owner, task URL/comments
  - outputs: repo slug, issue body content, Zoho backlink comment content, status mirror value
- GitHub repo
  - created/verifed before issue creation
  - contains standard files and templates for agent work
- GitHub Issue
  - one issue per Zoho task
  - linked from repo mapping state and Zoho comment
- GitHub Project item
  - one project item per GitHub issue
  - status field mirrored from Zoho status
- Zoho comment
  - one managed comment per task with deterministic marker content

### State files

Keep `task_repo_map.json` as the primary durable state file, but extend each mapping entry to include:

- `task_id`
- `task_key`
- `title`
- `repo_name`
- `repo_url`
- `local_path`
- `issue_number`
- `issue_url`
- `project_id`
- `project_item_id`
- `project_status_field_id`
- `project_status_option_id`
- `zoho_status_at_last_sync`
- `zoho_comment_marker`
- `zoho_comment_hash`
- `created_at`
- `updated_at`

Recommended rule:

- Keep one state file unless scale or concurrency forces separation.
- If later split is needed, introduce `sync_state.json` for volatile project/status sync data and leave `task_repo_map.json` as identity mapping only.

### Managed comment format

Use a stable marker so comments can be detected and safely updated idempotently:

```text
[bevco-repo-lifecycle]
Repo: <repo_url>
Issue: <issue_url>
Local repo: <local_path>
GitHub Project status: <status>
```

Recommended first version:

- Only create or replace the single managed comment owned by this automation.
- Never edit arbitrary user comments.

## [STATUS/KANBAN MIRRORING DESIGN]

### Source of truth

- Zoho Projects task status should be the source of truth in v1.
- The script already reads `custom_status` first and falls back to `status`; keep that precedence.

### GitHub mirror target

- Mirror into a single-select `Status` field on the target GitHub Project item.
- The GitHub Issue state (`open` / `closed`) should not be used as the primary kanban mirror in v1.

### Sync direction

- Recommended v1: one-way Zoho → GitHub only.
- Do not update Zoho status from GitHub in v1.

### Why one-way first

- Zoho is already the operational system of record for task intake.
- Two-way sync adds conflict resolution, race conditions, and accidental overwrite risk without immediate benefit.
- One-way sync is enough to make GitHub the execution workspace while preserving Zoho workflow ownership.

### Overwrite protection

- Only update the GitHub Project `Status` field when:
  - the task has a known mapped status
  - the mapped project item is the one recorded for this task
  - the new status differs from the last mirrored value or current project field value
- Never infer status from issue state, labels, or PR state in v1.
- Never write a fallback status silently if the Zoho status is unknown.

### Unknown statuses

- Maintain an explicit Zoho → GitHub status mapping table in config.
- If a Zoho status is unmapped:
  - dry-run: mark task as `[BLOCKED]` for status mirroring but do not block repo creation unless project sync is part of the requested apply scope
  - apply: block the project-status update and surface the exact unknown Zoho status
- Optional safe fallback after approval:
  - map unknowns to `Needs Triage`
  - only if explicitly configured

### Recommended mapping approach

Example initial table:

- `Open` / `Not Started` → `Backlog`
- `In Progress` → `In Progress`
- `On Hold` → `Blocked`
- `Closed` / `Completed` → `Done`

Exact values should be discovered from the live Zoho project and live GitHub Project field options during implementation.

## [REPO TEMPLATE STANDARD]

Use the BI1-T71 repo as the baseline standard for generated repositories. Generated files should be deterministic, task-specific, and safe by default.

### Exact generated files

- `README.md`
- `TASK.md`
- `STATUS.md`
- `AGENTS.md`
- `CLAUDE.md`
- `CODEX.md`
- `.gitignore`
- `.github/ISSUE_TEMPLATE/zoho-task.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `docs/.gitkeep`
- `scripts/.gitkeep`
- `artifacts/.gitkeep`

### Required content expectations

`README.md`

- Task title and key
- immutable Zoho task ID marker
- short purpose summary
- source-system metadata
- repo structure
- safety warning not to commit secrets or customer/private data

`TASK.md`

- task metadata snapshot
- sanitized Zoho payload snapshot
- task description
- tags, owner, status, task URL, generated timestamp

`STATUS.md`

- canonical current-state / handoff instructions
- what file is the deeper status source if one exists later
- current summary placeholder
- next decision points placeholder
- agent rule to read core files before work
- explicit “do not modify Zoho runtime systems unless approved”

`AGENTS.md`

- repo-scoped collaboration rules
- bounded-change rule
- verification and documentation expectations
- no-secret / no-destructive-change rules

`CLAUDE.md`

- repo-scoped instructions for Claude
- file reading order
- no direct runtime-system changes without approval
- folder usage rules

`CODEX.md`

- repo-scoped instructions for Codex
- file reading order
- preference for review/tests/validation/small diffs
- branch/PR preference when appropriate
- no runtime-system modifications without approval

`.github/ISSUE_TEMPLATE/zoho-task.md`

- Zoho metadata fields
- task summary
- requirements
- current state
- acceptance criteria
- agent notes
- deployment notes

`.github/PULL_REQUEST_TEMPLATE.md`

- summary
- Zoho task metadata
- changes
- validation
- deployment notes
- safety checklist

### Standardization method

- Prefer checked-in template source files inside the automation repo rather than assembling large strings inline in Python.
- Parameterize only task-specific fields.
- Keep templates versioned so future standard changes are explicit and reviewable.

## [IMPLEMENTATION PHASES]

### Phase 1: Audit/refactor current script without behavior change

Scope:

- Split the script into clear units:
  - Zoho client
  - GitHub client
  - repo templating
  - mapping/state management
  - report rendering
  - apply orchestration
- Preserve the current dry-run output shape and current BI1-T71-only apply behavior.
- Add tests around slug generation, mapping conflict detection, comment detection, and redaction behavior.

### Phase 2: Upgrade generated templates

Scope:

- Move starter templates into versioned template files in the automation repo.
- Generate `STATUS.md`, `CODEX.md`, and GitHub templates in addition to existing files.
- Make BI1-T71 repo standard the baseline for new repos.
- Keep generated placeholders generic where task-specific status content is unknown.

### Phase 3: Generalize apply mode from BI1-T71-only to any approved `repo-needed` task

Scope:

- Replace the BI1-T71 allowlist with deterministic eligibility based on:
  - exact `repo-needed` tag
  - valid task metadata
  - conflict-free duplicate checks
  - explicit CLI confirmation
- Keep private-only repo creation.
- Keep apply default-off.
- Keep conflict-first blocking semantics.

### Phase 4: Create GitHub Issue per Zoho task

Scope:

- Create or verify one issue per mapped task.
- Populate issue content from task metadata and the repo issue template.
- Store issue number and URL in mapping state.
- Detect duplicates by task ID/task key marker before creating a new issue.

### Phase 5: Add GitHub Project item/status mirroring

Scope:

- Create or verify one project item for the issue.
- Discover the configured project field IDs/options once per run.
- Mirror Zoho status into the GitHub Project `Status` field.
- Persist project identifiers and last mirrored status in state.

### Phase 6: Add notification/ping

Scope:

- Add an optional notifier after repo/issue/project creation succeeds.
- Keep notification disabled by default unless explicitly configured.
- Keep notifications informational only; they must not drive state.

### Phase 7: Optional scheduler integration

Scope:

- Add a safe poll wrapper for periodic dry-runs and explicit apply invocations.
- Prevent overlapping runs with a lockfile.
- Keep scheduler rollout separate from workflow correctness.

## [ACCEPTANCE CRITERIA]

### Phase 1

- Dry-run report output remains materially unchanged for current tasks.
- BI1-T71 apply still succeeds exactly as before.
- Unit coverage exists for slugging, redaction, conflict checks, and comment matching.

### Phase 2

- New repo generation includes `STATUS.md`, `CODEX.md`, and both GitHub templates.
- Generated files include the immutable Zoho task ID marker where applicable.
- Existing safety text against secrets/private data is preserved.

### Phase 3

- A tagged, valid non-BI1-T71 task can be selected with `--apply --task-key <TASK_KEY> --confirm-apply <TASK_KEY>`.
- An untagged task is not apply-eligible.
- A conflicting mapping, repo, or remote blocks apply with a clear report message.
- Repo creation remains private-only.

### Phase 4

- Applying an eligible task creates exactly one GitHub Issue.
- Re-running apply does not create a duplicate issue.
- Mapping state captures `issue_number` and `issue_url`.
- The Zoho backlink comment includes the issue link.

### Phase 5

- Applying an eligible task creates exactly one GitHub Project item.
- Re-running apply does not create a duplicate project item.
- Known Zoho statuses map to the configured GitHub Project status.
- Unknown Zoho statuses are surfaced explicitly and not silently rewritten.

### Phase 6

- Notification can be enabled or disabled by config.
- When enabled, one success notification is emitted per newly ready workspace.
- Re-runs do not spam duplicate notifications for unchanged state.

### Phase 7

- Scheduled runs can execute dry-run safely without creating repos/issues/project items.
- Overlapping runs are prevented.
- Reports clearly identify scheduled versus manual runs.

## [SAFETY CHECKS]

### dry-run output

- Dry-run must remain the default.
- Dry-run must never create repos, issues, project items, comments, mappings, commits, pushes, or notifications.
- Dry-run reports must explicitly confirm no-write behavior.

### no-write confirmation

- Apply must require explicit CLI confirmation tied to the selected task key.
- The script should print the planned actions before writes begin.

### secret redaction

- Continue redacting token-, secret-, password-, cookie-, webhook-, and query-string-like values in logs and reports.
- Never print env values or full auth headers.

### private repo enforcement

- Repo creation must always pass explicit private visibility.
- If an existing repo is public or visibility cannot be verified, block.

### idempotent Zoho comments

- Use one managed marker-based comment format.
- Re-runs should update or skip only the managed comment, never create duplicates.

### mapping conflict detection

- Block if the same task maps to a different repo.
- Block if the same repo maps to a different task.
- Block if stored repo, issue, or project identifiers disagree with live state.

### GitHub repo/issue/project duplicate detection

- Detect an existing repo by deterministic repo name and stored mapping.
- Detect an existing issue by stored mapping and by task marker in issue content.
- Detect an existing project item by stored mapping and linked issue ID.
- Never guess between multiple candidates; block and require manual resolution.

## [QUESTIONS / BLOCKERS]

- What is the target GitHub Project board ID/number that should mirror the Zoho summer project kanban?
- What are the exact GitHub Project `Status` field options that should receive the Zoho status mirror?
- What is the approved notification destination, if Phase 6 is enabled: Zoho Cliq webhook, GitHub issue/comment, or another agent channel?
- Should the structured Zoho backlink comment be updated in place when issue/project status changes, or should v1 only write it during repo creation and issue/project provisioning?
