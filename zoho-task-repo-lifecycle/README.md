# Zoho Task to GitHub Repo Lifecycle Dry-Run MVP

This project performs read-only reconciliation by default for Zoho tasks explicitly tagged `repo-needed`. A controlled apply path exists for one eligible `repo-needed` task per run and requires two matching command-line confirmation values naming that task key.

## Data sources

- Zoho credential names and values are loaded from `/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/.env`. Values are used in memory and never printed.
- A valid status-poller access-token cache may be reused read-only to avoid unnecessary OAuth refreshes.
- Zoho Projects task and tagged-task comment endpoints are read only.
- GitHub checks use only `gh auth status` and `gh repo view ... --json ...`.
- Local duplicate checks inspect `/Users/blakeallard/bevco/repos` and approved `task_repo_map.json` candidate paths.

## Run

```bash
cd /Users/blakeallard/bevco/automations/zoho-task-repo-lifecycle
python3 repo_lifecycle_dry_run.py
```

Dry-run remains the default. It performs no GitHub, Git, mapping, or Zoho writes.

## Controlled apply mode

Apply mode processes exactly one task per run: the task named by `--task-key` must appear as `would-create` (or safe existing-resume) in the same run's dry-run decisions, carry the exact `repo-needed` tag, pass all duplicate and metadata checks, and be confirmed a second time via `--confirm-apply`. (The original BI1-T71-only hard lock has been generalized; BI1-T71 below is an example.)

After reviewing a fresh dry-run, the separately approved command is:

```bash
python3 repo_lifecycle_dry_run.py \
  --apply \
  --task-key BI1-T71 \
  --confirm-apply BI1-T71
```

The apply path creates or verifies only the expected local repository, creates or verifies a private GitHub repository, commits and pushes starter files, atomically records `task_repo_map.json`, and posts one idempotent Zoho comment. Starter files include the core coordination set plus `docs/PROCESS.md`, `docs/CURRENT_HANDOFF.md`, and `.github/copilot-instructions.md`. Existing or partial state is verified before continuation; conflicting files, remotes, mappings, repository visibility, or task metadata block execution.

Shared `CLAUDE.md` and `AGENTS.md` template extraction from the active folder-sync automation is intentionally deferred. Apply mode generates conservative starter versions instead and reports the deferral.

The report is printed to the terminal and written to:

```text
/Users/blakeallard/bevco/automations/zoho-task-repo-lifecycle/reports/repo_lifecycle_dry_run_YYYY-MM-DD.md
```

## Decisions

- `[INFO] would create repo`: the exact `repo-needed` tag and required metadata are present, and available duplicate checks found no repository evidence.
- `[SKIPPED]`: the task is untagged or already has consistent repository evidence.
- `[BLOCKED]`: required metadata is missing, evidence conflicts, or an essential read-only duplicate check could not complete.

Tasks without the exact `repo-needed` tag are counted and skipped without per-task GitHub or Zoho-comment checks.

## Safety

- Dry-run reports are the only default runtime writes.
- Apply mode cannot process more than one task per run, only a task eligible in the same run's decisions, and cannot run without both matching confirmation arguments.
- GitHub repositories are created with explicit private visibility only.
- No delete, public-visibility, force-push, history-rewrite, scheduler, or service-control operation is implemented.
- Secrets and full environment values are never printed.
- The expected GitHub organization defaults to `blake-bevco-tech` and can be overridden with `GITHUB_ORG` for a future Kinetic Bridge organization.
- Generated reports, local `.env`, runtime mapping state, and Python caches are ignored by Git.

## task_repo_map.json

- `task_repo_map.json` is intentionally ignored by Git.
- It is local runtime state for this automation.
- It stores task-to-repo, task-to-issue, and task-to-project mappings along with local filesystem paths used for reconciliation.
- It should not be committed unless this project intentionally changes its state-management policy.
- The canonical GitHub/Zoho truth remains live Zoho plus live GitHub; `task_repo_map.json` is the local reconciliation cache.
