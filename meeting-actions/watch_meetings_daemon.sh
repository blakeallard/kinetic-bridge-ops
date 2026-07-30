#!/usr/bin/env bash
# watch_meetings_daemon.sh
# Event-driven replacement for the old 30-minute launchd poll. Runs as a
# persistent fswatch daemon (launchd KeepAlive) and fires watch_meetings.sh's
# scan immediately when a new file lands in the WorkDrive recordings folder,
# instead of waiting for the next timer tick.
#
# watch_meetings.sh itself is idempotent (gated by processed_notes.json), so
# it's safe to re-trigger it on every fs event — it's a no-op when there's
# nothing new.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDRIVE="$HOME/Library/CloudStorage/ZohoWorkDriveTrueSync-KineticBridge/Org Meeting Recordings/Meeting Recordings"
LOG="$SCRIPT_DIR/watcher.log"
FSWATCH="$(command -v fswatch || echo /opt/homebrew/bin/fswatch)"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

log "=== fswatch daemon started (watching: $WORKDRIVE) ==="

"$FSWATCH" -0 -r \
  --event Created --event Renamed --event MovedTo --event Updated \
  "$WORKDRIVE" | \
while IFS= read -r -d '' path; do
  case "$path" in
    *_summary.txt) ;;
    *) continue ;;
  esac
  log "fs event: $(basename "$path")"
  # WorkDrive's sync client can fire multiple events while writing a file;
  # give it a few seconds to settle before scanning.
  sleep 5
  "$SCRIPT_DIR/watch_meetings.sh"
done
