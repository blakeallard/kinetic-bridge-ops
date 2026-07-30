#!/usr/bin/env python3
"""
parse_meeting_actions.py
Parse a Bevco meeting summary/notes file and extract action items assigned to known owners.
Supports two formats:
  1. WorkDrive summary: multi-line bullets with "- Owner: Name" sub-bullets
  2. Weekly notes: inline "— Owner: Name" at end of bullet

Usage:
    python3 parse_meeting_actions.py <file>              # basic parse
    python3 parse_meeting_actions.py <file> --worksheet  # fills BEVCO worksheet per task via Claude
"""

import json
import os
import re
import sys
from pathlib import Path

PORTAL_ID = "898600220"
PROJECT_ID = "2543412000001324010"

OWNER_MAP = {
    "blake": "2543412000001324206",
    "blake allard": "2543412000001324206",
    "bill": "2543412000000059003",
    "bill beverley": "2543412000000059003",
    "bryan": "2543412000000108001",
    "brian": "2543412000000108001",
    "bryan ovalle": "2543412000000108001",
}
DEFAULT_OWNER_ZPUID = "2543412000001324206"

TAGS = [
    {"id": "2543412000001391053", "name": "automation"},
    {"id": "2543412000001391061", "name": "internal-work"},
]


# ── Owner resolution ─────────────────────────────────────────────────────────

def resolve_owner(raw_owner: str) -> dict:
    first = re.split(r"[;(/]", raw_owner)[0].strip().rstrip(".")
    for candidate in [first] + first.split():
        zpuid = OWNER_MAP.get(candidate.lower())
        if zpuid is not None:
            return {"raw": raw_owner.strip(), "resolved_name": candidate, "zpuid": zpuid, "is_fallback": False}
    return {"raw": raw_owner.strip(), "resolved_name": first, "zpuid": DEFAULT_OWNER_ZPUID, "is_fallback": True}


# ── Section extraction ────────────────────────────────────────────────────────

def extract_action_items_section(text: str) -> str:
    match = re.search(
        r"(?:^|\n)(?:#{1,3}\s*)?Action Items[^\n]*\n(.*?)(?=\n#{1,3}\s+|\n(?:Notes|Next steps|If you want)\b|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    match = re.search(
        r"4\.\s+Action Items[^\n]*\n(.*?)(?=\n\d+\.\s+|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_workdrive_format(section_text: str, meeting_date: str) -> list[dict]:
    items = []
    blocks = re.split(r"\n(?=- )", "\n" + section_text)
    for block in blocks:
        block = block.strip()
        if not block.startswith("- "):
            continue
        lines = block.split("\n")
        task_text = lines[0].lstrip("- ").strip()
        if not task_text:
            continue
        owner_raw = "Unknown"
        for line in lines[1:]:
            m = re.match(r"\s+[-•]\s*Owner[s]?:\s*(.+)", line, re.IGNORECASE)
            if m:
                owner_raw = m.group(1).strip()
                break
        primary = re.split(r"\s+(?:and|&)\s+|/", owner_raw, maxsplit=1)[0].strip()
        owner = resolve_owner(primary)
        items.append(_make_item(task_text, owner, meeting_date, owner_raw))
    return items


def parse_inline_format(section_text: str, meeting_date: str) -> list[dict]:
    items = []
    for line in re.split(r"\n(?=[-•])", section_text):
        line = line.strip().lstrip("-•").strip()
        if not line:
            continue
        owner_match = re.search(r"\s*[—–-]{1,2}\s*Owner[s]?:\s*(.+)$", line, re.IGNORECASE)
        if owner_match:
            task_text = line[: owner_match.start()].strip()
            owner_raw = owner_match.group(1)
        else:
            # Positional format: "task — Name — due date/notes"
            parts = re.split(r"\s*[—–]\s*", line)
            if len(parts) >= 2:
                task_text = parts[0].strip()
                owner_raw = parts[1].strip()
            else:
                task_text = line
                owner_raw = "Unknown"
        owner = resolve_owner(owner_raw)
        items.append(_make_item(task_text, owner, meeting_date, owner_raw))
    return items


def _make_item(task_text: str, owner: dict, meeting_date: str, owner_raw: str) -> dict:
    return {
        "name": task_text[:250],
        "owner_zpuid": owner["zpuid"],
        "owner_display": owner["resolved_name"],
        "is_fallback": owner["is_fallback"],
        "owner_raw": owner_raw,
        "tags": TAGS,
        "portal_id": PORTAL_ID,
        "project_id": PROJECT_ID,
        "meeting_date": meeting_date,
        "description": None,  # filled later by worksheet step or basic fallback
    }


# ── Worksheet fill (Claude Haiku) ─────────────────────────────────────────────

WORKSHEET_PROMPT = """\
You are filling out the BEVCO Task/Workflow Diagnostic Worksheet for one action item extracted from a meeting.

--- MEETING CONTEXT ---
{meeting_text}
--- END CONTEXT ---

Action item: {action_item}
Assigned to: {owner}

Fill every field carefully using the meeting context above. Be specific — avoid generic placeholders.

Return ONLY a JSON object with these exact keys (no markdown, no extra text):
{{
  "requested_task": "clear restatement of what needs to be built or done",
  "business_problem": "the specific business pain or gap this solves",
  "how_should_work": "the desired end state or solution flow",
  "success_criteria": "specific, measurable definition of done",
  "current_status": "one of: No solution | Existing but inefficient | Broken | Manual | Not used",
  "problem_type": "one or more of: Slow | Duplicate entry | Missing info | Hard to report | Access blocker | Manual",
  "systems_involved": ["list", "from: Projects, People, Flow, CRM/Bigin, Books, Creator, WorkDrive, Email, Other"],
  "data_needed": "what data or inputs are required to complete this",
  "access_approval_needed": "any permissions, credentials, or approvals needed — or None",
  "info_between_systems": "what data needs to move between which systems",
  "one_sentence_diagnosis": "concise summary: problem + solution in one sentence",
  "next_action": "one of: Research | Access | Draft | Build/test | Document | Review"
}}"""


def fill_worksheet(item: dict, meeting_text: str) -> dict:
    """Call Claude via CLI subprocess to fill the BEVCO worksheet for one action item."""
    import subprocess
    claude_bin = os.path.expanduser("~/.local/bin/claude")
    prompt = WORKSHEET_PROMPT.format(
        meeting_text=meeting_text[:6000],
        action_item=item["name"],
        owner=item["owner_display"],
    )
    result = subprocess.run(
        [claude_bin, "-p", prompt, "--model", "claude-haiku-4-5-20251001",
         "--output-format", "json"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[:200])
    data = json.loads(result.stdout)
    raw = data.get("result", "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    return json.loads(raw)


def format_worksheet_html(ws: dict, item: dict) -> str:
    """Format the filled worksheet as HTML for the Zoho task description."""
    systems = ws.get("systems_involved", [])
    if isinstance(systems, list):
        systems_str = ", ".join(systems)
    else:
        systems_str = str(systems)

    return (
        f"<b>1. REQUEST + DESIRED WORKFLOW</b><br/>"
        f"<b>Requested task:</b> {ws.get('requested_task', item['name'])}<br/>"
        f"<b>Business problem:</b> {ws.get('business_problem', '')}<br/>"
        f"<br/>"
        f"<b>How should this work:</b> {ws.get('how_should_work', '')}<br/>"
        f"<b>Success / done criteria:</b> {ws.get('success_criteria', '')}<br/>"
        f"<br/>"
        f"<b>2. CURRENT SITUATION</b><br/>"
        f"<b>Current status:</b> {ws.get('current_status', '')}<br/>"
        f"<b>Problem type:</b> {ws.get('problem_type', '')}<br/>"
        f"<br/>"
        f"<b>3. SYSTEMS + INPUTS</b><br/>"
        f"<b>Systems involved:</b> {systems_str}<br/>"
        f"<b>Data needed:</b> {ws.get('data_needed', '')}<br/>"
        f"<b>Access / approval needed:</b> {ws.get('access_approval_needed', '')}<br/>"
        f"<br/>"
        f"<b>4. FOLLOW-UP QUESTIONS</b><br/>"
        f"<b>What info needs to move between systems:</b> {ws.get('info_between_systems', '')}<br/>"
        f"<br/>"
        f"<b>5. SUMMARY + NEXT ACTION</b><br/>"
        f"<b>Diagnosis:</b> {ws.get('one_sentence_diagnosis', '')}<br/>"
        f"<b>Next action:</b> {ws.get('next_action', '')}<br/>"
        f"<br/>"
        f"<i>From meeting: {item['meeting_date']} | Owner: {item['owner_display']}</i>"
    )


def basic_description(item: dict) -> str:
    return (
        f"<b>From meeting:</b> {item['meeting_date']}<br/>"
        f"<b>Original action:</b> {item['name']}<br/>"
        f"<b>Assigned to:</b> {item['owner_display']}"
    )


# ── File parsing ──────────────────────────────────────────────────────────────

def parse_file(path: Path, use_worksheet: bool = False, blake_only: bool = False) -> list[dict]:
    text = path.read_text(encoding="utf-8")

    # Derive meeting date from metadata.json or folder name
    stem_base = re.sub(r"_(transcript|summary)$", "", path.stem)
    meta = path.parent / (stem_base + "_metadata.json")
    meeting_date = None
    if meta.exists():
        try:
            data = json.loads(meta.read_text())
            meeting_date = data.get("date") or data.get("meeting_date")
        except Exception:
            pass

    if not meeting_date:
        parts = path.stem.split("_")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            m, d, y = parts
            meeting_date = f"20{y}-{m}-{d}"
        else:
            dm = re.match(r"(\d{2})-(\d{2})", path.parent.name)
            meeting_date = f"2026-{dm.group(1)}-{dm.group(2)}" if dm else path.stem

    section = extract_action_items_section(text)
    if not section:
        print(f"[warn] No 'Action Items' section found in {path.name}", file=sys.stderr)
        return []

    if re.search(r"\n\s+[-•]\s*Owner[s]?:", section, re.IGNORECASE):
        items = parse_workdrive_format(section, meeting_date)
    else:
        items = parse_inline_format(section, meeting_date)

    for item in items:
        owned_by_blake = item["owner_zpuid"] == OWNER_MAP["blake"]
        if blake_only and not owned_by_blake:
            item["description"] = basic_description(item)
            continue
        if use_worksheet and not item["is_fallback"]:
            print(f"  [worksheet] Filling: {item['name'][:60]}...", file=sys.stderr)
            try:
                ws = fill_worksheet(item, text)
                item["description"] = format_worksheet_html(ws, item)
                item["worksheet"] = ws
            except Exception as e:
                print(f"  [warn] Worksheet fill failed: {e}", file=sys.stderr)
                item["description"] = basic_description(item)
        else:
            item["description"] = basic_description(item)

    return items


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    use_worksheet = "--worksheet" in args
    blake_only = "--blake-only" in args
    files = [a for a in args if not a.startswith("--")]

    if not files:
        print(f"Usage: {sys.argv[0]} <notes_file> [--worksheet] [--blake-only]", file=sys.stderr)
        sys.exit(1)

    path = Path(files[0])
    if not path.exists():
        path = Path.home() / "Bevco/notes/meeting_notes/weekly" / files[0]
    if not path.exists():
        print(f"[error] File not found: {files[0]}", file=sys.stderr)
        sys.exit(1)

    items = parse_file(path, use_worksheet=use_worksheet, blake_only=blake_only)
    print(json.dumps(items, indent=2))


if __name__ == "__main__":
    main()
