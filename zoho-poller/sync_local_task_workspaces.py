#!/usr/bin/env python3
"""
sync_local_task_workspaces.py

Creates or updates a local, plain-filesystem workspace folder for each
newly-detected Zoho Projects task, so Claude/Codex can `cd` into it and
start working immediately.

This is a pure local file transform: no Zoho API calls, no credentials,
no network access, no Cliq notifications. It only reads the JSON produced
by bevco_task_poller.py's --new-tasks-out (new_tasks.json) — the raw task
objects for tasks detected as new in the most recent poll.

Usage:
    python3 sync_local_task_workspaces.py --input new_tasks.json
    python3 sync_local_task_workspaces.py --input new_tasks.json --dry-run
    python3 sync_local_task_workspaces.py --input new_tasks.json \
        --workspace-root /custom/path

Idempotent: reruns update metadata in place and never duplicate a folder
for the same task_id. HANDOFF.md only has its auto-generated header block
replaced on resync — everything below the markers (manual agent notes) is
preserved verbatim.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_INPUT = "new_tasks.json"
DEFAULT_WORKSPACE_ROOT = "/Users/blakeallard/bevco/task-workspaces"

# Static portal context — this poller is scoped to a single portal/project.
PORTAL_ID = "898600220"
PORTAL_NAME = "bevcollc"

# Auto-generated block markers in HANDOFF.md. Everything between these is
# replaced on each sync; everything outside them is left untouched.
_HANDOFF_START = "<!-- zoho-sync:start -->"
_HANDOFF_END = "<!-- zoho-sync:end -->"

METADATA_FILENAME = ".zoho_task_metadata.json"
HANDOFF_FILENAME = "HANDOFF.md"


def strip_html(html: str) -> str:
    text = str(html or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(?:div|p|li|h\d)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def slugify(text: str) -> str:
    text = str(text or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80] or "untitled"


def extract_task_key(task: dict) -> str:
    candidates = [task.get("prefix"), task.get("key"), task.get("task_key"), task.get("id")]
    for value in candidates:
        if not value:
            continue
        value = str(value).strip()
        match = re.search(r"[A-Z]+[A-Z0-9]*-T\d+", value, re.IGNORECASE)
        if match:
            return match.group(0).upper()
    return str(task.get("id") or "unknown-task")


def task_owner(task: dict) -> str:
    owner = task.get("owner")
    if isinstance(owner, dict) and owner.get("name"):
        return str(owner["name"])
    created_by = task.get("created_by")
    if isinstance(created_by, dict) and created_by.get("name"):
        return str(created_by["name"])
    details = task.get("details")
    if isinstance(details, dict):
        owners = details.get("owners")
        if isinstance(owners, list) and owners:
            first = owners[0]
            if isinstance(first, dict) and first.get("name"):
                return str(first["name"])
    return "Not provided"


def build_task_url(task_id: str, project_id: str) -> str:
    if not task_id or not project_id:
        return ""
    return f"https://projects.zoho.com/portal/{PORTAL_NAME}/projects/{project_id}/#tasks:{task_id}"


def normalize_task(task: dict) -> dict:
    task_id = str(task.get("id") or "")
    task_key = extract_task_key(task)
    name = str(task.get("name") or "Untitled Task")

    project = task.get("project") or {}
    project_name = project.get("name") if isinstance(project, dict) else str(project or "")
    project_id = project.get("id") if isinstance(project, dict) else ""

    status = task.get("status") or {}
    status_name = status.get("name") if isinstance(status, dict) else str(status or "")

    return {
        "task_id": task_id,
        "task_key": task_key,
        "task_name": name,
        "project_id": str(project_id or ""),
        "project_name": str(project_name or ""),
        "portal_id": PORTAL_ID,
        "portal_name": PORTAL_NAME,
        "status": str(status_name or "Unknown"),
        "owner": task_owner(task),
        "created_time": str(task.get("created_time") or ""),
        "last_modified_time": str(task.get("last_modified_time") or ""),
        "description": strip_html(task.get("description") or ""),
        "zoho_url": build_task_url(task_id, str(project_id or "")),
    }


def find_existing_workspace_dir(workspace_root: Path, meta: dict):
    """Match by stored task_id first, then by task_key folder-name prefix."""
    if not workspace_root.exists():
        return None

    task_key = meta["task_key"]
    fallback = None

    for child in sorted(workspace_root.iterdir()):
        if not child.is_dir():
            continue

        metadata_file = child / METADATA_FILENAME
        if metadata_file.exists():
            try:
                existing = json.loads(metadata_file.read_text())
            except (json.JSONDecodeError, OSError):
                existing = {}
            if existing.get("task_id") == meta["task_id"]:
                return child

        if task_key != "unknown-task" and child.name.lower().startswith(task_key.lower()):
            fallback = fallback or child

    return fallback


def build_target_dir(workspace_root: Path, meta: dict) -> Path:
    folder_name = f"{meta['task_key'].lower()}-{slugify(meta['task_name'])}"
    return workspace_root / folder_name


def write_metadata_file(task_dir: Path, meta: dict, dry_run: bool) -> None:
    data = dict(meta)
    data["last_synced_at"] = datetime.now(timezone.utc).isoformat()
    metadata_file = task_dir / METADATA_FILENAME
    if dry_run:
        print(f"  [dry-run] would write {metadata_file}")
        return
    metadata_file.write_text(json.dumps(data, indent=2))


def build_handoff_header(meta: dict) -> str:
    description = meta["description"] or "(no description provided)"
    return f"""{_HANDOFF_START}
# {meta['task_key']} — {meta['task_name']}

## Task Context

| Field | Value |
|---|---|
| Task Key | {meta['task_key']} |
| Task ID | {meta['task_id']} |
| Project | {meta['project_name']} |
| Portal | {meta['portal_name']} ({meta['portal_id']}) |
| Status | {meta['status']} |
| Owner | {meta['owner']} |
| Created | {meta['created_time'] or '[Unknown]'} |
| Last Modified | {meta['last_modified_time'] or '[Unknown]'} |
| Zoho Link | {meta['zoho_url'] or '[Unavailable]'} |

## Description

{description}
{_HANDOFF_END}"""


def default_handoff_body() -> str:
    return """
## Working Notes

- (Add implementation notes, decisions, and assumptions here.)

## Next Steps

- [ ] Review task details above and confirm scope.
- [ ] Implement / draft the deliverable.
- [ ] Report back or update the Zoho task.

## Change Log

- Workspace created automatically from Zoho Projects task detection.
"""


def create_or_update_handoff(task_dir: Path, meta: dict, dry_run: bool) -> None:
    handoff_file = task_dir / HANDOFF_FILENAME
    header = build_handoff_header(meta)

    if not handoff_file.exists():
        if dry_run:
            print(f"  [dry-run] would create {handoff_file}")
            return
        handoff_file.write_text(header + "\n" + default_handoff_body())
        return

    existing = handoff_file.read_text()
    start_idx = existing.find(_HANDOFF_START)
    end_idx = existing.find(_HANDOFF_END)

    if start_idx != -1 and end_idx != -1:
        after_end = existing[end_idx + len(_HANDOFF_END):]
        new_content = header + "\n" + after_end.lstrip("\n")
        if dry_run:
            print(f"  [dry-run] would refresh header block in {handoff_file} (manual content below markers preserved)")
            return
        handoff_file.write_text(new_content)
        return

    # Legacy/manual file without markers — prepend the header, keep everything else.
    if dry_run:
        print(f"  [dry-run] would prepend header to {handoff_file} (no existing markers found)")
        return
    handoff_file.write_text(header + "\n\n---\n\n" + existing)


def sync_task(workspace_root: Path, task: dict, dry_run: bool) -> None:
    meta = normalize_task(task)

    existing_dir = find_existing_workspace_dir(workspace_root, meta)
    task_dir = existing_dir or build_target_dir(workspace_root, meta)

    action = "Updated" if existing_dir else "Created"
    print(f"{action}: {task_dir}")

    if not dry_run:
        task_dir.mkdir(parents=True, exist_ok=True)
    elif not task_dir.exists():
        print(f"  [dry-run] would create directory {task_dir}")

    write_metadata_file(task_dir, meta, dry_run)
    create_or_update_handoff(task_dir, meta, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create/update local task workspaces for newly-detected Zoho tasks"
    )
    parser.add_argument(
        "--input", default=DEFAULT_INPUT, help="Path to new_tasks.json (or '-' for stdin)"
    )
    parser.add_argument(
        "--workspace-root",
        default=DEFAULT_WORKSPACE_ROOT,
        help="Directory under which task workspace folders are created",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print planned actions without writing anything"
    )
    args = parser.parse_args()

    if args.input == "-":
        raw = json.load(sys.stdin)
    else:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"No input file at {input_path} — nothing to sync.", file=sys.stderr)
            return 0
        raw = json.loads(input_path.read_text())

    if not isinstance(raw, list):
        print(f"Expected a JSON list of tasks in {args.input}, got {type(raw).__name__}", file=sys.stderr)
        return 1

    if not raw:
        print("No new tasks to sync.")
        return 0

    workspace_root = Path(args.workspace_root)
    if not args.dry_run:
        workspace_root.mkdir(parents=True, exist_ok=True)

    failures = 0
    for task in raw:
        try:
            sync_task(workspace_root, task, args.dry_run)
        except Exception as e:
            failures += 1
            print(f"[WARN] Skipping task {task.get('id', '?')}: {e}", file=sys.stderr)

    print(f"Done. {len(raw) - failures}/{len(raw)} task workspace(s) synced.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
