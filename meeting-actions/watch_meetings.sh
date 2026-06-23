#!/usr/bin/env bash
# watch_meetings.sh
# Scans WorkDrive for new meeting summary files and runs create_tasks.sh on each.
# Run by launchd every 30 minutes. Exits immediately if nothing new.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDRIVE="$HOME/Library/CloudStorage/ZohoWorkDriveTrueSync-BEVCO/Org Meeting Recordings/Meeting Recordings"
STATE_FILE="$SCRIPT_DIR/processed_notes.json"
LOG="$SCRIPT_DIR/watcher.log"
PYTHON="python3.13"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

if [[ ! -f "$STATE_FILE" ]]; then
  echo '{"processed":[]}' > "$STATE_FILE"
fi

# Find unprocessed summary files
NEW_FILES=$($PYTHON - <<PYEOF
import json, os
from pathlib import Path

workdrive = Path(os.path.expanduser("$WORKDRIVE"))
state = json.load(open("$STATE_FILE"))
processed = set(state.get("processed", []))

new = []
for f in sorted(workdrive.rglob("*_summary.txt")):
    if f.name not in processed:
        new.append(str(f))

print("\n".join(new))
PYEOF
)

if [[ -z "$NEW_FILES" ]]; then
  exit 0
fi

log "=== Meeting watcher triggered ==="
while IFS= read -r filepath; do
    [[ -z "$filepath" ]] && continue
    log "Processing: $(basename "$filepath")"
    if "$SCRIPT_DIR/create_tasks.sh" "$filepath" --worksheet --blake-only >> "$LOG" 2>&1; then
        log "Done: $(basename "$filepath")"
    else
        log "FAILED: $(basename "$filepath") (exit $?)"
    fi
done <<< "$NEW_FILES"
log "=== Done ==="
