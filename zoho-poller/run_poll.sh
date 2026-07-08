#!/usr/bin/env bash
# run_poll.sh — wrapper for bevco_task_poller.py
#
# This calls Claude Code with a prompt instructing it to pull live Zoho
# task data via the ZohoMCP/Zoho Projects connector, save it as JSON,
# then run the diff/alert script against it.
#
# Schedule this with cron, e.g. every 30 min during work hours:
#   */30 9-18 * * 1-5  cd /Users/blakeallard/bevco-zoho-poller && ./run_poll.sh >> poll.log 2>&1
#
# Requires: claude CLI (Claude Code) authenticated with Zoho MCP access.

set -euo pipefail
export HOME="/Users/blakeallard"
export PATH="/Users/blakeallard/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")"

TASKS_JSON="tasks_latest.json"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pulling BE-9 tasks via Claude Code..."

/Users/blakeallard/.local/bin/claude -p "Use ToolSearch if needed to locate mcp__zoho__ZohoProjects_get_tasks_by_portal.
Call ZohoProjects_get_tasks_by_portal with portal_id 898600220,
per_page 50, sort_by DESC(last_modified_time). Output ONLY the raw JSON
response, nothing else — no commentary, no markdown formatting." \
  --allowedTools "ToolSearch" "mcp__zoho__ZohoProjects_get_tasks_by_portal" \
  --output-format json \
  --no-session-persistence > "${TASKS_JSON}.raw" 2>poll_error.log || {
    echo "Claude Code pull failed — see poll_error.log"
    exit 1
  }

# Extract the actual tool result from Claude Code's response wrapper.
# Handles both cases: result contains the Zoho JSON directly, or result
# contains a Claude tool-results .txt path when the payload was too large
# to inline.
python3 - <<'PY'
import json
import re
import sys
from pathlib import Path

raw_path = Path("tasks_latest.json.raw")
out_path = Path("tasks_latest.json")

try:
    raw = json.loads(raw_path.read_text())
except Exception as e:
    print(f"Could not parse Claude wrapper JSON from {raw_path}: {e}", file=sys.stderr)
    sys.exit(1)

text = raw.get("result") or raw.get("text") or ""

def try_parse_json(value: str):
    try:
        return json.loads(value)
    except Exception:
        return None

data = try_parse_json(text)

if data is None:
    match = re.search(r"(/Users/[^\s`]+/tool-results/[^\s`]+\.txt)", text)
    if not match:
        print("Could not parse Zoho JSON from Claude Code output and no tool-results path was found", file=sys.stderr)
        sys.exit(1)

    tool_result_path = Path(match.group(1))
    if not tool_result_path.exists():
        print(f"Claude tool-results file does not exist: {tool_result_path}", file=sys.stderr)
        sys.exit(1)

    tool_text = tool_result_path.read_text()
    data = try_parse_json(tool_text)

    if data is None:
        print(f"Could not parse JSON from Claude tool-results file: {tool_result_path}", file=sys.stderr)
        sys.exit(1)

out_path.write_text(json.dumps(data, indent=2))
PY

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Running diff against last_seen_tasks.json..."
python3 bevco_task_poller.py --input "${TASKS_JSON}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Syncing local task workspaces for new tasks..."
python3 sync_local_task_workspaces.py --input new_tasks.json || {
  echo "[WARN] Local task workspace sync failed — new tasks were still detected above. See output for details."
}

echo "Done."
