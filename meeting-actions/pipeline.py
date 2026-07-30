#!/usr/bin/env python3
"""
pipeline.py
Core meeting-actions logic: worksheet-based task extraction with OpenAI
gpt-4o-mini, dedupe, and Zoho Projects task creation.

This replaces the Claude-CLI worksheet fill in parse_meeting_actions.py and
the Claude-CLI task creation in create_tasks.sh for the Railway deployment.
The BEVCO Task / Workflow Diagnostic Worksheet remains the qualification
filter: a task is created only when the summary describes a concrete
follow-up workflow with a requested task, business problem, systems, and a
clear next action.
"""

import html
import json
import logging
import os
import re
from pathlib import Path

from zoho_client import ZohoClient

logger = logging.getLogger("meeting-actions.pipeline")

# ── Defaults / config ─────────────────────────────────────────────────────────

DEFAULT_PORTAL_ID = os.environ.get("ZOHO_PORTAL_ID", "898600220")
DEFAULT_PROJECT_ID = os.environ.get("ZOHO_PROJECT_ID", "2543412000001324010")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
STATE_FILE = Path(os.environ.get("STATE_FILE", Path(__file__).parent / "processed_notes.json"))
ATTACH_WORKSHEET_HTML = os.environ.get("ATTACH_WORKSHEET_HTML", "0") == "1"

# Known portal/project owners (Zoho Projects ZPUIDs).
OWNER_MAP = {
    "blake": "2543412000001324206",
    "blake allard": "2543412000001324206",
    "bill": "2543412000000059003",
    "bill beverley": "2543412000000059003",
    "bryan": "2543412000000108001",
    "brian": "2543412000000108001",
    "bryan ovalle": "2543412000000108001",
}
BLAKE_ZPUID = OWNER_MAP["blake"]


def load_local_env(env_file: Path | None = None) -> None:
    """Load a .env file into os.environ for local runs (no-op if absent).

    Railway injects real env vars, so this only matters on a dev machine.
    Existing environment values are never overwritten.
    """
    candidates = [env_file] if env_file else [
        Path(__file__).parent / ".env",
        Path("/Users/blakeallard/bevco/automations/zoho-task-folder-sync/.env"),
    ]
    for path in candidates:
        if not path or not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        logger.info("Loaded local env from %s", path)
        return


# ── OpenAI extraction ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a workflow diagnostic and task extraction assistant for BEVCO/Kinetic Bridge.

Use the BEVCO Task / Workflow Diagnostic Worksheet as the filter for creating tasks.

Create a task only when the meeting summary describes a concrete follow-up workflow/problem that has:
- a requested task or workflow,
- a business/process problem,
- involved systems or inputs,
- and a clear next action such as Research, Access, Draft, Build/test, Document, or Review.

Do not create tasks from background notes, general discussion, vague monitoring items, duplicate items, or decisions with no follow-up work.
Do not assume ownership unless the summary explicitly names or strongly implies an owner.
Include tasks for any named person/team, not only Blake.
Merge overlapping items into one task when they belong to the same workflow/problem.
Prefer 3-7 high-value tasks over many tiny tasks.

Return ONLY raw valid JSON.
No markdown.
No code fences.

Return exactly:
{
  "tasks": [
    {
      "title": "Short imperative title, max 10 words",
      "description": "Concise task description",
      "assignee": "Person/team if stated, else null",
      "requested_task": "What work is being requested",
      "business_problem": "Why this matters",
      "problem_type": "No solution | Existing but inefficient | Broken | Manual | Not used | Access blocker | Slow | Duplicate entry | Missing info | Hard to report",
      "systems_involved": ["Projects", "People", "Flow", "CRM/Bigin", "Books", "Creator", "WorkDrive", "Email", "Other"],
      "data_needed": "Data/input needed, else null",
      "access_needed": "Access/approval needed, else null",
      "follow_up_questions": ["Question 1", "Question 2"],
      "diagnosis": "One-sentence diagnosis",
      "next_action": "Research | Access | Draft | Build/test | Document | Review",
      "dedupe_key": "stable-lowercase-hyphen-key",
      "create_task": true
    }
  ]
}

If there are no qualified tasks, return:
{"tasks":[]}"""


def build_worksheet_prompt(summary_text: str, meeting_name: str = "") -> str:
    """User-message half of the extraction prompt (system half is SYSTEM_PROMPT)."""
    header = f"Meeting: {meeting_name}\n\n" if meeting_name else ""
    return f"{header}--- MEETING SUMMARY ---\n{summary_text[:24000]}\n--- END SUMMARY ---"


def extract_tasks_from_summary(
    summary_text: str,
    summary_file_name: str,
    model: str = OPENAI_MODEL,
) -> list[dict]:
    """Run worksheet-based extraction with OpenAI; returns the tasks list."""
    from openai import OpenAI

    meeting_name = meeting_name_from_file(summary_file_name)
    client = OpenAI()  # reads OPENAI_API_KEY
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_worksheet_prompt(summary_text, meeting_name)},
        ],
    )
    raw = (resp.choices[0].message.content or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    data = json.loads(raw)
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError(f"Model returned non-list tasks: {type(tasks)}")
    logger.info("Extracted %d candidate tasks from %s", len(tasks), summary_file_name)
    return tasks


# ── Normalization / dedupe ────────────────────────────────────────────────────

def meeting_name_from_file(summary_file_name: str) -> str:
    name = Path(summary_file_name).stem
    name = re.sub(r"_summary$", "", name, flags=re.IGNORECASE)
    return re.sub(r"[_]+", " ", name).strip()


def normalize_task_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for title matching."""
    title = re.sub(r"[^\w\s]", "", (title or "").lower())
    return re.sub(r"\s+", " ", title).strip()


def make_dedupe_key(task: dict) -> str:
    """Stable key: model-provided dedupe_key, else derived from systems + request."""
    key = (task.get("dedupe_key") or "").strip().lower()
    if not key:
        systems = "-".join(sorted(s.lower() for s in task.get("systems_involved", [])))
        base = f"{systems}-{task.get('requested_task') or task.get('title', '')}"
        key = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return key[:120]


def resolve_owner_zpuid(assignee: str | None) -> str | None:
    if not assignee:
        return None
    first = re.split(r"[;(/,]", assignee)[0].strip().rstrip(".")
    for candidate in [first.lower()] + [w.lower() for w in first.split()]:
        if candidate in OWNER_MAP:
            return OWNER_MAP[candidate]
    return None


# ── Description formatting ────────────────────────────────────────────────────

def format_task_description(task: dict, meeting_name: str) -> str:
    """Clean plain-text task description (converted to HTML at create time)."""
    systems = task.get("systems_involved") or []
    systems_str = ", ".join(systems) if isinstance(systems, list) else str(systems)
    lines = [
        f"Source meeting: {meeting_name}",
        f"Assignee: {task.get('assignee') or 'Unassigned'}",
        f"Next action: {task.get('next_action') or ''}",
        f"Problem type: {task.get('problem_type') or ''}",
        f"Systems: {systems_str}",
        "",
        "Requested workflow:",
        task.get("requested_task") or "",
        "",
        "Business problem:",
        task.get("business_problem") or "",
        "",
        "Details:",
        task.get("description") or "",
    ]
    extras = []
    if task.get("data_needed"):
        extras.append(f"Data needed: {task['data_needed']}")
    if task.get("access_needed"):
        extras.append(f"Access needed: {task['access_needed']}")
    if extras:
        lines += ["", "Data/access needed:", *extras]
    lines += ["", f"Dedupe-key: {make_dedupe_key(task)}"]
    return "\n".join(lines)


def description_to_html(description: str) -> str:
    return description.replace("\n", "<br />")


def worksheet_html_page(task: dict, meeting_name: str) -> str:
    """Full worksheet as a standalone HTML page (optional task attachment)."""
    questions = "".join(f"<li>{q}</li>" for q in task.get("follow_up_questions") or [])
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>BEVCO Worksheet — {task.get('title', '')}</title>
<style>body{{font-family:Arial,sans-serif;max-width:780px;margin:40px auto;padding:0 20px;color:#222;line-height:1.6}}</style>
</head><body>
<h2>{task.get('title', '')}</h2>
<p>{description_to_html(format_task_description(task, meeting_name))}</p>
<p><b>Diagnosis:</b> {task.get('diagnosis') or ''}</p>
<b>Follow-up questions:</b><ul>{questions}</ul>
</body></html>"""


# ── Processed-state file ──────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("processed", [])
    state.setdefault("dedupe_keys", [])
    return state


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Main entrypoint ───────────────────────────────────────────────────────────

def process_summary(
    summary_text: str,
    summary_file_name: str,
    portal_id: str | None = None,
    project_id: str | None = None,
    dry_run: bool = False,
    blake_only: bool = False,
    force: bool = False,
    model: str = OPENAI_MODEL,
    zoho: ZohoClient | None = None,
) -> dict:
    """Extract → filter → dedupe → create Zoho tasks. Returns the API response dict."""
    portal_id = portal_id if (portal_id or "").isdigit() else DEFAULT_PORTAL_ID
    project_id = project_id if (project_id or "").isdigit() else DEFAULT_PROJECT_ID
    meeting_name = meeting_name_from_file(summary_file_name)
    zoho = zoho or ZohoClient()

    response: dict = {
        "summary_file_name": summary_file_name,
        "meeting_name": meeting_name,
        "created_count": 0,
        "skipped_count": 0,
        "tasks": [],
        "created_tasks": [],
        "skipped_tasks": [],
        "dry_run": dry_run,
        "force": force,
        "zoho_source_meeting_exists": False,
    }

    # File-level dedupe: never reprocess the same summary (dry-run is exempt
    # so it stays usable for testing; force bypasses ONLY this check — title
    # and dedupe-key checks below still apply).
    state = _load_state()
    if summary_file_name in state["processed"] and not dry_run and not force:
        logger.info("Skipping %s — already processed", summary_file_name)
        response["already_processed"] = True
        return response

    # 1. Worksheet-based extraction (gpt-4o-mini, temperature 0, strict JSON).
    tasks = extract_tasks_from_summary(summary_text, summary_file_name, model=model)
    response["tasks"] = tasks

    # 2. Qualification + optional owner filter.
    qualified = []
    for task in tasks:
        if not task.get("create_task", False) or not (task.get("title") or "").strip():
            response["skipped_tasks"].append({"title": task.get("title"), "reason": "not_qualified"})
            continue
        owner_zpuid = resolve_owner_zpuid(task.get("assignee"))
        if blake_only and owner_zpuid != BLAKE_ZPUID:
            response["skipped_tasks"].append({"title": task["title"], "reason": "not_blake"})
            continue
        qualified.append((task, owner_zpuid))

    # 3. Task-level dedupe against existing Zoho tasks (title + dedupe key in
    #    descriptions) and the local dedupe-key registry.
    existing_titles: set[str] = set()
    existing_desc_blob = ""
    if zoho.configured:
        try:
            existing = zoho.get_existing_tasks(portal_id, project_id)
            existing_titles = {normalize_task_title(t.get("name", "")) for t in existing}
            # Unescape HTML entities so "Blake&#39;s" matches "Blake's".
            existing_desc_blob = html.unescape(
                " ".join(t.get("description", "") or "" for t in existing)
            ).lower()
            logger.info("Loaded %d existing Zoho tasks for dedupe", len(existing))
        except Exception as e:
            logger.warning("Could not fetch existing Zoho tasks (%s) — title dedupe degraded", e)
    else:
        logger.warning("Zoho creds not configured — dedupe limited to local state")
    known_keys = set(state["dedupe_keys"])

    # Meeting-level dedupe: if any existing Zoho task already references this
    # source meeting, the whole meeting is represented — skip every candidate.
    # This is the primary guard against the model re-wording titles/dedupe
    # keys between runs, and it is NOT bypassed by force (force only skips
    # the processed_notes.json check).
    meeting_lc = meeting_name.lower()
    if meeting_lc and (
        f"source meeting: {meeting_lc}" in existing_desc_blob
        or f"meeting: {meeting_lc}" in existing_desc_blob
    ):
        response["zoho_source_meeting_exists"] = True
        logger.info("Source meeting '%s' already represented in Zoho — skipping all %d candidates",
                    meeting_name, len(qualified))
        for task, _ in qualified:
            response["skipped_tasks"].append(
                {"title": task["title"].strip(), "reason": "source_meeting_already_exists"}
            )
        qualified = []

    new_keys: list[str] = []
    for task, owner_zpuid in qualified:
        title = task["title"].strip()
        key = make_dedupe_key(task)
        if normalize_task_title(title) in existing_titles:
            response["skipped_tasks"].append({"title": title, "reason": "duplicate_title"})
            continue
        if key in known_keys or (key and key in existing_desc_blob):
            response["skipped_tasks"].append({"title": title, "reason": "duplicate_dedupe_key", "dedupe_key": key})
            continue
        known_keys.add(key)

        description = format_task_description(task, meeting_name)
        if dry_run:
            response["created_tasks"].append({
                "title": title, "assignee": task.get("assignee"),
                "owner_zpuid": owner_zpuid, "dedupe_key": key,
                "description": description, "dry_run": True,
            })
            continue

        # 4. Create the Zoho task.
        try:
            created = zoho.create_task(
                portal_id, project_id, title,
                description_to_html(description), owner_zpuid=owner_zpuid,
            )
            task_id = str(created.get("id_string") or created.get("id") or "")
            logger.info("Created task %s: %s", task_id, title)
            response["created_tasks"].append({
                "title": title, "task_id": task_id, "assignee": task.get("assignee"),
                "owner_zpuid": owner_zpuid, "dedupe_key": key,
            })
            new_keys.append(key)
            if ATTACH_WORKSHEET_HTML and task_id:
                try:
                    zoho.attach_html(
                        portal_id, project_id, task_id,
                        worksheet_html_page(task, meeting_name),
                        f"BEVCO_Worksheet_{task_id}.html",
                    )
                except Exception as e:  # portal upload setting may block this
                    logger.warning("Worksheet attach failed for %s: %s", task_id, e)
        except Exception as e:
            logger.error("Task creation failed for '%s': %s", title, e)
            response["skipped_tasks"].append({"title": title, "reason": f"create_failed: {e}"})

    response["created_count"] = len(response["created_tasks"])
    response["skipped_count"] = len(response["skipped_tasks"])

    # 5. Persist state (real runs only).
    if not dry_run:
        if summary_file_name not in state["processed"]:
            state["processed"].append(summary_file_name)
        state["dedupe_keys"].extend(k for k in new_keys if k not in state["dedupe_keys"])
        _save_state(state)

    return response
