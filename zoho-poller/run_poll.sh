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
export PATH="/Users/blakeallard/.local/bin:$PATH"
cd "$(dirname "$0")"

TASKS_JSON="tasks_latest.json"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pulling BE-9 tasks via Claude Code..."

claude -p "Call ZohoProjects_get_tasks_by_portal with portal_id 898600220,
per_page 50, sort_by DESC(last_modified_time). Output ONLY the raw JSON
response, nothing else — no commentary, no markdown formatting." \
  --allowedTools "mcp__zoho__ZohoProjects_get_tasks_by_portal" \
  --output-format json > "${TASKS_JSON}.raw" 2>poll_error.log || {
    echo "Claude Code pull failed — see poll_error.log"
    exit 1
  }

# Extract the actual tool result from Claude Code's response wrapper.
# Adjust this jq filter if Claude Code's --output-format json shape changes.
python3 -c "
import json, sys
with open('${TASKS_JSON}.raw') as f:
    raw = json.load(f)
# Claude Code json output typically nests the final message text;
# the Zoho tool result should be embedded as JSON text within it.
text = raw.get('result', raw.get('text', ''))
try:
    data = json.loads(text)
except Exception:
    print('Could not parse Zoho JSON from Claude Code output', file=sys.stderr)
    sys.exit(1)
with open('${TASKS_JSON}', 'w') as out:
    json.dump(data, out)
"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Running diff against last_seen_tasks.json..."
python3 bevco_task_poller.py --input "${TASKS_JSON}"

echo "Done."
