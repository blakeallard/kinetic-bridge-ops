#!/usr/bin/env python3
"""
bevco_task_poller.py

Polls Zoho Projects (BE-9 / Blake Internship, portal bevcollc) for new tasks
since the last run, and writes an alert file when new tasks are found.

This script does NOT call the Zoho API directly — it's meant to be invoked
by Claude Code, which has live MCP access to ZohoProjects_get_tasks_by_portal.
The intended usage pattern (see README.md in this folder) is:

    claude -p "Run bevco_task_poller.py workflow: pull tasks via
    ZohoProjects_get_tasks_by_portal (portal_id 898600220), diff against
    last_seen_tasks.json, and report any new task IDs."

This script handles the LOCAL side: diffing, state tracking, and alert
formatting. Claude Code (or a wrapper script) handles the actual Zoho call
and feeds the JSON result into this script via stdin or a file argument.

Usage:
    python bevco_task_poller.py --input tasks.json
    python bevco_task_poller.py --input tasks.json --state last_seen_tasks.json

Recommended scheduling: cron every 30-60 min during work hours, e.g.
    */30 9-18 * * 1-5  cd ~/bevco-zoho-poller && ./run_poll.sh
(run_poll.sh would be a small wrapper that calls `claude -p` to fetch tasks,
then pipes the result into this script.)
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STATE_FILE = "last_seen_tasks.json"
DEFAULT_ALERT_FILE = "new_task_alerts.md"


def load_state(state_path: Path) -> dict:
    if state_path.exists():
        with open(state_path, "r") as f:
            return json.load(f)
    return {"seen_task_ids": [], "last_run": None}


def save_state(state_path: Path, seen_ids: set):
    with open(state_path, "w") as f:
        json.dump(
            {
                "seen_task_ids": sorted(seen_ids),
                "last_run": datetime.now(timezone.utc).isoformat(),
            },
            f,
            indent=2,
        )


def strip_html(text: str) -> str:
    """Very light HTML stripping for Zoho's description field."""
    import re
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_tasks(raw_json: dict) -> list:
    """
    Expects the shape returned by ZohoProjects_get_tasks_by_portal:
    { "data": { "tasks": [ {...}, {...} ] } }
    Adjust here if the MCP tool's response shape changes.
    """
    tasks = raw_json.get("data", {}).get("tasks", raw_json.get("tasks", []))
    return tasks


def format_alert(new_tasks: list) -> str:
    lines = [
        "# New BE-9 Tasks Detected",
        "",
        f"_Checked: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        f"{len(new_tasks)} new task(s) found since last check.",
        "",
    ]
    for t in new_tasks:
        prefix = t.get("prefix", "?")
        name = t.get("name", "(no title)")
        desc = strip_html(t.get("description", ""))
        status = t.get("status", {}).get("name", "Unknown")
        created_by = t.get("created_by", {}).get("name", "Unknown")
        task_id = t.get("id", "")

        lines.append(f"## {prefix} — {name}")
        lines.append(f"- **Status:** {status}")
        lines.append(f"- **Created by:** {created_by}")
        lines.append(f"- **Task ID:** `{task_id}`")
        lines.append(f"- **Description:** {desc[:500] or '(none)'}")
        lines.append("")
        lines.append(
            "> Next: paste this task into Claude Chat — the "
            "`bevco-task-intake` skill will auto-fill the diagnostic "
            "worksheet, classify the tier, and propose a deliverable."
        )
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Detect new Bevco BE-9 tasks")
    parser.add_argument(
        "--input", required=True, help="Path to JSON file with task list (or '-' for stdin)"
    )
    parser.add_argument(
        "--state", default=DEFAULT_STATE_FILE, help="Path to state file tracking seen task IDs"
    )
    parser.add_argument(
        "--alert-out", default=DEFAULT_ALERT_FILE, help="Path to write the alert markdown file"
    )
    args = parser.parse_args()

    if args.input == "-":
        raw = json.load(sys.stdin)
    else:
        with open(args.input, "r") as f:
            raw = json.load(f)

    tasks = extract_tasks(raw)
    if not tasks:
        print("No tasks found in input — check the JSON shape.", file=sys.stderr)
        sys.exit(1)

    state_path = Path(args.state)
    state = load_state(state_path)
    seen_ids = set(state["seen_task_ids"])

    current_ids = {t.get("id") for t in tasks if t.get("id")}
    new_ids = current_ids - seen_ids
    new_tasks = [t for t in tasks if t.get("id") in new_ids]

    if new_tasks:
        alert_md = format_alert(new_tasks)
        Path(args.alert_out).write_text(alert_md)
        print(f"ALERT: {len(new_tasks)} new task(s). Written to {args.alert_out}")
        print(alert_md)
    else:
        print("No new tasks since last check.")

    save_state(state_path, current_ids | seen_ids)


if __name__ == "__main__":
    main()
