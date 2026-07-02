#!/usr/bin/env bash
# create_tasks.sh
# Parse a meeting notes file and create Zoho Projects tasks for each action item.
# Follows the same claude -p pattern as bevco-zoho-poller.
#
# Usage:
#   ./create_tasks.sh <notes_file.txt> [--blake-only] [--worksheet] [--dry-run]
#   ./create_tasks.sh 06_01_26.txt --blake-only
#   VISUALIZER_EVENTS=1 ./create_tasks.sh 06_01_26.txt --blake-only --dry-run
#
# State is tracked in processed_notes.json — re-running on the same file is safe.
# --dry-run emits visualizer events but does not create/update Zoho tasks or mark
#   the file as processed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTES_DIR="$HOME/Bevco/notes/meeting_notes/weekly"
STATE_FILE="$SCRIPT_DIR/processed_notes.json"
CLAUDE_BIN="$HOME/.local/bin/claude"
PYTHON="python3.13"
VISUALIZER_DIR="$HOME/Dev/workflow-visualizer"
WORKFLOW_ID="meeting_actions"

# ── args ────────────────────────────────────────────────────────────────────
BLAKE_ONLY=false
WORKSHEET=false
DRY_RUN=false
POSITIONAL=()
for arg in "$@"; do
  case "$arg" in
    --blake-only) BLAKE_ONLY=true ;;
    --worksheet)  WORKSHEET=true ;;
    --dry-run)    DRY_RUN=true ;;
    *) POSITIONAL+=("$arg") ;;
  esac
done

if [[ ${#POSITIONAL[@]} -lt 1 ]]; then
  echo "Usage: $0 <notes_file.txt> [--blake-only] [--worksheet] [--dry-run]" >&2
  exit 1
fi

NOTES_FILE="${POSITIONAL[0]}"
[[ "$NOTES_FILE" != /* ]] && NOTES_FILE="$NOTES_DIR/$NOTES_FILE"

# ── temp files (safe even across set -e exits) ───────────────────────────────
ITEMS_FILE=$(mktemp /tmp/meeting_items_XXXXXX.json)
TASKS_TMPFILE=$(mktemp /tmp/meeting_actions_XXXXXX)
trap 'rm -f "$ITEMS_FILE" "$TASKS_TMPFILE"' EXIT

# ── event emitter ────────────────────────────────────────────────────────────
# Set VISUALIZER_EVENTS=1 to enable live event posting to the bridge at :8787.
# Uses curl for speed (no node.js startup per event).
RUN_ID="meeting_actions_$(date +%Y%m%d_%H%M%S)"

emit_event() {
  [[ "${VISUALIZER_EVENTS:-0}" != "1" ]] && return 0
  local node_id="$1" node_name="$2" status="$3"
  shift 3
  local input_json="{}" output_json="{}" error_val="null"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --input-json)  input_json="$2";  shift 2 ;;
      --output-json) output_json="$2"; shift 2 ;;
      --error)
        error_val=$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$2")
        shift 2 ;;
      *) shift ;;
    esac
  done
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
  curl -sf -X POST "http://localhost:8787/events" \
    -H "Content-Type: application/json" \
    -d "{\"workflow_id\":\"$WORKFLOW_ID\",\"run_id\":\"$RUN_ID\",\"node_id\":\"$node_id\",\"node_name\":\"$node_name\",\"status\":\"$status\",\"timestamp\":\"$ts\",\"input\":$input_json,\"output\":$output_json,\"error\":$error_val}" \
    > /dev/null 2>&1 || true
}

# ── detect meeting summary ───────────────────────────────────────────────────
emit_event "detect_meeting_summary" "Detect Meeting Summary" "running" \
  --input-json "{\"file\":\"$(basename "$NOTES_FILE")\"}"

if [[ ! -f "$NOTES_FILE" ]]; then
  emit_event "detect_meeting_summary" "Detect Meeting Summary" "failed" \
    --error "File not found: $(basename "$NOTES_FILE")"
  echo "[error] File not found: $NOTES_FILE" >&2
  exit 1
fi

BASENAME="$(basename "$NOTES_FILE")"

# ── deduplication check ─────────────────────────────────────────────────────
if [[ ! -f "$STATE_FILE" ]]; then
  echo '{"processed":[]}' > "$STATE_FILE"
fi

already=$(python3 -c "
import json, sys
state = json.load(open(sys.argv[1]))
print('yes' if sys.argv[2] in state['processed'] else 'no')
" "$STATE_FILE" "$BASENAME")

if [[ "$already" == "yes" ]]; then
  emit_event "detect_meeting_summary" "Detect Meeting Summary" "skipped" \
    --output-json "{\"reason\":\"already_processed\",\"file\":\"$BASENAME\"}"
  echo "[skip] $BASENAME already processed. Delete its entry from processed_notes.json to re-run."
  exit 0
fi

emit_event "detect_meeting_summary" "Detect Meeting Summary" "completed" \
  --output-json "{\"file\":\"$BASENAME\",\"dry_run\":$DRY_RUN,\"worksheet\":$WORKSHEET}"

# ── parse action items ───────────────────────────────────────────────────────
emit_event "parse_action_items" "Parse Action Items" "running" \
  --input-json "{\"file\":\"$BASENAME\",\"worksheet\":$WORKSHEET}"

echo "[parse] Extracting action items from $BASENAME ..."

# stdout → temp file; stderr (worksheet progress) → terminal as usual
# --blake-only is passed through here too, BEFORE the worksheet-fill step, so
# Claude is never called to fill out worksheets for other people's action
# items that get discarded later anyway.
PARSE_ARGS=("$NOTES_FILE")
[[ "$WORKSHEET" == "true" ]] && PARSE_ARGS+=("--worksheet")
[[ "$BLAKE_ONLY" == "true" ]] && PARSE_ARGS+=("--blake-only")

$PYTHON "$SCRIPT_DIR/parse_meeting_actions.py" "${PARSE_ARGS[@]}" > "$ITEMS_FILE" || {
  emit_event "parse_action_items" "Parse Action Items" "failed" --error "parse_meeting_actions.py exited non-zero"
  echo "[error] parse_meeting_actions.py failed." >&2
  exit 1
}

ITEM_COUNT=$(python3 -c "import json; print(len(json.load(open('$ITEMS_FILE'))))" 2>/dev/null || echo "0")
echo "[parse] Found $ITEM_COUNT action items."

if [[ "$ITEM_COUNT" -eq 0 ]]; then
  emit_event "parse_action_items" "Parse Action Items" "completed" \
    --output-json "{\"item_count\":0,\"warning\":\"no_action_items\"}"
  echo "[warn] No action items found — nothing to create."
  exit 0
fi

emit_event "parse_action_items" "Parse Action Items" "completed" \
  --output-json "{\"item_count\":$ITEM_COUNT,\"worksheet\":$WORKSHEET}"

# ── fill worksheets event (happened inside parse when --worksheet) ───────────
if [[ "$WORKSHEET" == "true" ]]; then
  emit_event "fill_worksheets" "Fill Worksheets" "completed" \
    --output-json "{\"item_count\":$ITEM_COUNT,\"note\":\"filled_during_parse\"}"
else
  emit_event "fill_worksheets" "Fill Worksheets" "skipped" \
    --output-json "{\"reason\":\"no_worksheet_flag\"}"
fi

# ── filter blake tasks ───────────────────────────────────────────────────────
BLAKE_ZPUID="2543412000001324206"

if [[ "$BLAKE_ONLY" == "true" ]]; then
  emit_event "filter_blake_tasks" "Filter Blake Tasks" "running" \
    --input-json "{\"item_count\":$ITEM_COUNT,\"filter\":\"blake_only\"}"

  FILTERED_COUNT=$(python3 -c "
import json
items = json.load(open('$ITEMS_FILE'))
count = sum(1 for i in items if not i.get('is_fallback', True) and i.get('owner_zpuid') == '$BLAKE_ZPUID')
print(count)
" 2>/dev/null || echo "0")

  emit_event "filter_blake_tasks" "Filter Blake Tasks" "completed" \
    --output-json "{\"in\":$ITEM_COUNT,\"out\":$FILTERED_COUNT,\"filter\":\"blake_only\"}"
  echo "[filter] $FILTERED_COUNT/$ITEM_COUNT tasks assigned to Blake."
else
  FILTERED_COUNT="$ITEM_COUNT"
  emit_event "filter_blake_tasks" "Filter Blake Tasks" "skipped" \
    --output-json "{\"reason\":\"all_owners\",\"item_count\":$ITEM_COUNT}"
fi

# ── create a tasklist for this meeting ──────────────────────────────────────
MEETING_DATE=$(python3 -c "
import json
items = json.load(open('$ITEMS_FILE'))
print(items[0]['meeting_date'] if items else 'unknown')
")
TASKLIST_NAME="Meeting Actions – $MEETING_DATE"
echo "[zoho] Creating tasklist: '$TASKLIST_NAME' ..."

TASKLIST_ID=""
if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] Skipping tasklist creation."
  TASKLIST_ID="dry_run_tasklist"
else
  TASKLIST_RESULT=$("$CLAUDE_BIN" -p \
    "Create a Zoho Projects tasklist named '$TASKLIST_NAME' in portal 898600220, project 2543412000001324010. Use mcp__claude_ai_Zoho_Projects__create_task_list. Return only the tasklist ID as a plain number, nothing else." \
    --allowedTools "mcp__claude_ai_Zoho_Projects__create_task_list" \
    --output-format json 2>/dev/null)

  TASKLIST_ID=$(echo "$TASKLIST_RESULT" | python3 -c "
import json, sys, re
data = json.load(sys.stdin)
result = data.get('result','')
match = re.search(r'\b(\d{10,})\b', result)
print(match.group(1) if match else '')
")
fi

if [[ -z "$TASKLIST_ID" ]]; then
  echo "[warn] Could not parse tasklist ID — tasks will fall back to General tasklist."
fi

# ── create tasks ─────────────────────────────────────────────────────────────
emit_event "create_zoho_tasks" "Create Zoho Tasks" "running" \
  --input-json "{\"task_count\":$FILTERED_COUNT,\"dry_run\":$DRY_RUN,\"tasklist\":\"${TASKLIST_ID:-none}\"}"

echo "[zoho] Creating $ITEM_COUNT tasks ..."

python3 - "$ITEMS_FILE" "$TASKLIST_ID" "$CLAUDE_BIN" "$BLAKE_ONLY" "$DRY_RUN" "$TASKS_TMPFILE" <<'PYEOF'
import json, re, subprocess, sys
from pathlib import Path

items_file, tasklist_id, claude, blake_only_str, dry_run_str, out_file = sys.argv[1:]
items = json.load(open(items_file))
tasklist_id = tasklist_id.strip()
dry_run = dry_run_str == "true"
blake_only = blake_only_str == "true"
successes = 0

BLAKE_ZPUID = "2543412000001324206"

# Fetch existing task names once so we can skip duplicates.
# Uses the Zoho API directly (paginated) to avoid Claude CLI truncation.
existing_names = set()
if not dry_run:
    import ssl, urllib.parse, urllib.request
    try:
        import certifi
        _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        _ssl_ctx = ssl.create_default_context()

    def _load_env(env_path):
        env = {}
        try:
            for line in open(env_path).read().splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass
        return env

    def _zoho_token(env):
        domain = env.get('ZOHO_ACCOUNTS_DOMAIN', 'https://accounts.zoho.com')
        data = urllib.parse.urlencode({
            'grant_type': 'refresh_token',
            'client_id': env['ZOHO_CLIENT_ID'],
            'client_secret': env['ZOHO_CLIENT_SECRET'],
            'refresh_token': env['ZOHO_REFRESH_TOKEN'],
        }).encode()
        req = urllib.request.Request(
            f'{domain}/oauth/v2/token', data=data, method='POST',
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx) as r:
            return json.loads(r.read())['access_token']

    print("[dedup] Fetching existing tasks from Zoho (all pages)...")
    ENV_FILE = '/Users/blakeallard/bevco/scripts/zoho_task_folder_sync/.env'
    env = _load_env(ENV_FILE)
    try:
        token = _zoho_token(env)
        api = env.get('ZOHO_PROJECTS_API_DOMAIN', 'https://projectsapi.zoho.com')
        index = 1
        page_size = 100
        while True:
            url = (f'{api}/restapi/portal/898600220/projects/2543412000001324010/tasks/'
                   f'?index={index}&range={page_size}')
            req = urllib.request.Request(url, headers={'Authorization': f'Zoho-oauthtoken {token}'})
            with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx) as r:
                tasks = json.loads(r.read()).get('tasks', [])
            for t in tasks:
                name = t.get('name', '').strip()
                if name:
                    existing_names.add(name.lower())
            if len(tasks) < page_size:
                break
            index += page_size
    except Exception as e:
        print(f"[dedup] Warning: could not fetch existing tasks ({e}) — skipping dedup.")
    print(f"[dedup] {len(existing_names)} existing task names loaded.")

for i, item in enumerate(items, 1):
    if item.get('is_fallback', True):
        print(f"  [{i}/{len(items)}] SKIP (unresolved owner: {item['owner_display']})")
        continue
    if blake_only and item['owner_zpuid'] != BLAKE_ZPUID:
        print(f"  [{i}/{len(items)}] SKIP (not Blake: {item['owner_display']})")
        continue
    if not dry_run and item['name'].strip().lower() in existing_names:
        print(f"  [{i}/{len(items)}] SKIP (duplicate: '{item['name'][:60]}' already exists in Zoho)")
        continue
    if dry_run:
        print(f"  [{i}/{len(items)}] DRY-RUN: {item['name'][:80]}")
        print(f"         owner: {item['owner_display']} | [no task created]")
        successes += 1
        continue
    use_tasklist = tasklist_id and not tasklist_id.startswith('dry_run')
    tasklist_clause = f" Put it in tasklist ID {tasklist_id}." if use_tasklist else ""
    prompt = (
        f"Create a Zoho Projects task in portal 898600220, project 2543412000001324010."
        f" Task name: {json.dumps(item['name'])}."
        f" Description (HTML): {json.dumps(item['description'])}."
        f" Assign owner zpuid: {item['owner_zpuid']}."
        f" Add tags with IDs: 2543412000001391053 (automation) and 2543412000001391061 (internal-work)."
        f"{tasklist_clause}"
        f" After creating the task, output only the task ID as a plain number on its own line."
    )
    print(f"  [{i}/{len(items)}] {item['name'][:80]}...")
    result = subprocess.run(
        [claude, "-p", prompt,
         "--allowedTools", "mcp__claude_ai_Zoho_Projects__create_a_task",
         "--output-format", "json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"         ✗ failed: {result.stderr[:120]}", file=sys.stderr)
        continue
    successes += 1
    raw = json.loads(result.stdout).get("result", "")
    m = re.search(r'\b(\d{13,})\b', raw)
    task_id = m.group(1) if m else None
    print(f"         ✓ owner: {item['owner_display']}", end="")
    if task_id:
        print(f" | task_id: {task_id}", end="")
        # Wire attachment here once upload rule is enabled (portal admin setting)
        # subprocess.run(["python3.13", str(Path(items_file).parent / "zoho_attach.py"), task_id, "--html", item["description"]])
    print()

print(f"\n[done] {successes}/{len(items)} tasks created.")
Path(out_file).write_text(str(successes))
PYEOF

CREATED_COUNT=$(cat "$TASKS_TMPFILE" 2>/dev/null || echo "0")

emit_event "create_zoho_tasks" "Create Zoho Tasks" "completed" \
  --output-json "{\"created\":${CREATED_COUNT:-0},\"total\":$ITEM_COUNT,\"dry_run\":$DRY_RUN}"

# ── verify zoho tasks ────────────────────────────────────────────────────────
emit_event "verify_zoho_tasks" "Verify Zoho Tasks" "running" \
  --input-json "{\"expected\":${CREATED_COUNT:-0},\"dry_run\":$DRY_RUN}"

if [[ "$DRY_RUN" == "true" ]]; then
  emit_event "verify_zoho_tasks" "Verify Zoho Tasks" "completed" \
    --output-json "{\"status\":\"dry_run_skipped\",\"simulated\":${CREATED_COUNT:-0}}"
  echo "[verify] Dry-run: ${CREATED_COUNT:-0} tasks would have been created."
elif [[ "${CREATED_COUNT:-0}" -gt 0 ]]; then
  emit_event "verify_zoho_tasks" "Verify Zoho Tasks" "completed" \
    --output-json "{\"status\":\"ok\",\"created\":${CREATED_COUNT:-0}}"
  echo "[verify] ${CREATED_COUNT:-0} tasks confirmed in Zoho Projects."
else
  emit_event "verify_zoho_tasks" "Verify Zoho Tasks" "failed" \
    --error "No tasks were successfully created"
  echo "[verify] Warning: no tasks were successfully created." >&2
fi

# ── mark as processed ────────────────────────────────────────────────────────
if [[ "$DRY_RUN" != "true" ]]; then
  python3 - "$STATE_FILE" "$BASENAME" <<'PYEOF'
import json, sys
state_file, basename = sys.argv[1], sys.argv[2]
state = json.load(open(state_file))
if basename not in state['processed']:
    state['processed'].append(basename)
json.dump(state, open(state_file, 'w'), indent=2)
print(f"[state] Marked {basename} as processed.")
PYEOF
else
  echo "[dry-run] Skipping state update (processed_notes.json unchanged)."
fi

# ── complete ─────────────────────────────────────────────────────────────────
emit_event "complete" "Workflow Complete" "completed" \
  --output-json "{\"file\":\"$BASENAME\",\"created\":${CREATED_COUNT:-0},\"dry_run\":$DRY_RUN}"

echo "[complete] Done."
