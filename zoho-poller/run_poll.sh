#!/usr/bin/env bash
# run_poll.sh — wrapper for bevco_task_poller.py
#
# Pulls live Zoho Projects task data directly via the Zoho REST API
# (fetch_zoho_tasks.py, using the shared OAuth refresh credentials),
# then runs the diff/alert script and the local workspace sync.
#
# The previous implementation fetched via `claude -p` + Zoho MCP; that
# required an interactive Claude Code login and failed under cron.
#
# Schedule with cron, e.g. every 30 min during work hours:
#   */30 9-18 * * 1-5  /Users/blakeallard/bevco/automations/bevco-zoho-poller/run_poll.sh >> poll.log 2>&1

set -euo pipefail
export HOME="/Users/blakeallard"
export PATH="/Users/blakeallard/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")"

TASKS_JSON="tasks_latest.json"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pulling BE-9 tasks via Zoho REST API..."

python3 fetch_zoho_tasks.py --out "${TASKS_JSON}" 2>poll_error.log || {
  echo "Zoho task fetch failed — see poll_error.log"
  exit 1
}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Running diff against last_seen_tasks.json..."
python3 bevco_task_poller.py --input "${TASKS_JSON}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Syncing local task workspaces for new tasks..."
python3 sync_local_task_workspaces.py --input new_tasks.json || {
  echo "[WARN] Local task workspace sync failed — new tasks were still detected above. See output for details."
}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Checking new tasks for repo-needed tag..."
python3 - <<'PY'
import json
from pathlib import Path

new_tasks = json.loads(Path("new_tasks.json").read_text()) if Path("new_tasks.json").exists() else []
tagged = [
    t for t in new_tasks
    if any((tag.get("name") if isinstance(tag, dict) else tag) == "repo-needed" for tag in (t.get("tags") or []))
]
for t in tagged:
    key = t.get("prefix") or t.get("key") or t.get("id")
    print(f"[ACTION NEEDED] {key} is tagged repo-needed — review with:")
    print("  cd /Users/blakeallard/bevco/automations/zoho-task-repo-lifecycle && python3 repo_lifecycle_dry_run.py")
    print(f"  then apply: python3 repo_lifecycle_dry_run.py --apply --task-key {key} --confirm-apply {key}")
if not tagged:
    print("[INFO] no new repo-needed tasks this run")
PY

echo "Done."
