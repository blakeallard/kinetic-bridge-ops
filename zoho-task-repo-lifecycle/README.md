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

The apply path creates or verifies the expected local repository and private GitHub repository, renders the complete template-driven agent scaffold, validates it before Git, commits and pushes, creates or verifies Issue #1, adds it to the configured GitHub Project with initial status, atomically records `task_repo_map.json`, and posts one idempotent Zoho completion comment. The scaffold includes `README.md`, `TASK.md`, `STATUS.md`, `AGENTS.md`, `CLAUDE.md`, `CODEX.md`, GitHub templates, eight maintenance workflows, the generated Zoho task mapping and commit-sync client, and the required `docs/`, `scripts/`, and `artifacts/` directories. Existing partial repositories are repaired by generating missing files while preserving existing work; conflicting files, remotes, mappings, repository visibility, or task metadata block execution.

## Generated GitHub Actions

- `agent-readiness.yml` protects the required AI-agent files and directories.
- `python-quality.yml` installs optional requirements, compiles Python, runs Ruff, and runs pytest when tests exist.
- `repository-validation.yml` protects lifecycle v2 ownership and task metadata across every generated file.
- `claude-context-check.yml` verifies that task, status, Claude, and shared-agent context remains actionable.
- `issue-development.yml` labels implementation issues, creates a deterministic development branch, and comments the prepared metadata without opening or merging a PR.
- `pr-validation.yml` checks the PR requirements/validation contract, status and documentation updates, applicable Python tests, and lifecycle-file preservation.
- `security.yml` runs weekly and on changes, auditing Python dependencies and checking for tracked sensitive files or private keys.
- `sync-commits-to-zoho.yml` sends each pushed branch commit to the matching Zoho Projects task through a permanent Zoho Flow webhook. Flow must verify that the live task still carries the exact `repo-needed` tag before adding the comment.

The webhook URL is an organization Actions secret named `ZOHO_COMMIT_SYNC_WEBHOOK_URL`, granted only to lifecycle-managed private repositories. It is never generated into repository content.

Optional/manual add-ons such as `docs/PROCESS.md` and `.github/copilot-instructions.md` have preserved templates in this repo, but the automation does not generate them by default and does not expose a configuration switch for them today.

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
- Resume validation remains compatible with older repos that still use the larger legacy coordination-file set.

## task_repo_map.json

- `task_repo_map.json` is intentionally ignored by Git.
- It is local runtime state for this automation.
- It stores task-to-repo, task-to-issue, and task-to-project mappings along with local filesystem paths used for reconciliation.
- It should not be committed unless this project intentionally changes its state-management policy.
- The canonical GitHub/Zoho truth remains live Zoho plus live GitHub; `task_repo_map.json` is the local reconciliation cache.
