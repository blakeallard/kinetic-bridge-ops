#!/usr/bin/env python3
"""
update_task_status_and_alert.py

Replaces the Enterprise-only Zoho Flow "Task Updated" trigger.
Performs two atomic actions:
  1. Updates a Zoho Projects task status via REST API
  2. Posts an immediate formatted message to a Zoho Cliq channel

Usage:
  python update_task_status_and_alert.py --task-id 2543412000001324999 \
      --status "Blocker" --comment "Blocked waiting on vendor response"

Requires .env file with credentials (see .env.example).
Never commit secrets. All credentials are loaded from environment only.

Sources:
  Zoho Projects Tasks API: https://www.zoho.com/projects/help/rest-api/tasks-api.html
  Zoho Cliq Webhook Tokens: https://www.zoho.com/cliq/help/platform/webhook-tokens.html
"""

import argparse
import os
import re
import sys
import time
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

# ── Load .env if present ────────────────────────────────────────────────────
def load_dotenv(path=".env"):
    """Minimal .env loader — no external dependencies required."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val

load_dotenv()

# ── SSL: use certifi bundle if available (fixes Python 3.13 macOS cert issue) ─
import ssl as _ssl
try:
    import certifi as _certifi
    _https_handler = urllib.request.HTTPSHandler(
        context=_ssl.create_default_context(cafile=_certifi.where())
    )
    urllib.request.install_opener(urllib.request.build_opener(_https_handler))
except ImportError:
    pass

# ── Config from environment ──────────────────────────────────────────────────
REQUIRED_VARS = [
    "ZOHO_CLIENT_ID",
    "ZOHO_CLIENT_SECRET",
    "ZOHO_REFRESH_TOKEN",
    "ZOHO_PROJECTS_PORTAL_ID",
    "ZOHO_PROJECT_ID",
    "CLIQ_CHANNEL_WEBHOOK_URL_BLOCKER",
    "CLIQ_CHANNEL_WEBHOOK_URL_NEEDS_APPROVAL",
]

WEBHOOK_BY_STATUS = {
    "blocker":        "CLIQ_CHANNEL_WEBHOOK_URL_BLOCKER",
    "needs approval": "CLIQ_CHANNEL_WEBHOOK_URL_NEEDS_APPROVAL",
}

VALID_ALERT_STATUSES = {"blocker", "needs approval"}

# Known status IDs for the BE-9 (Blake Internship) project.
# These are checked first to avoid an unreliable /tasks/statuses/ API call.
KNOWN_STATUS_IDS = {
    "open":             "2543412000000016068",
    "in progress":      "2543412000000031001",
    "backlog":          "2543412000000441313",
    "blocker":          "2543412000001400019",
    "needs approval":   "2543412000001349031",
    "closed":           "2543412000000016071",
}

# ── OAuth Token Refresh ───────────────────────────────────────────────────────
def get_access_token():
    """
    Exchange refresh token for a new access token.
    Zoho OAuth endpoint: https://accounts.zoho.com/oauth/v2/token
    """
    url = "https://accounts.zoho.com/oauth/v2/token"
    params = {
        "refresh_token": os.environ["ZOHO_REFRESH_TOKEN"],
        "client_id": os.environ["ZOHO_CLIENT_ID"],
        "client_secret": os.environ["ZOHO_CLIENT_SECRET"],
        "grant_type": "refresh_token",
    }
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[ERROR] Token refresh HTTP error {e.code}: {e.read().decode()}")
        sys.exit(1)

    if "access_token" not in result:
        print(f"[ERROR] Token refresh failed: {result}")
        sys.exit(1)

    return result["access_token"]

# ── Get Task Details ──────────────────────────────────────────────────────────
def get_task(portal_id, project_id, task_id, access_token):
    """
    Fetch current task details (name, current status, assignee, key).
    GET /restapi/portal/{portal_id}/projects/{project_id}/tasks/{task_id}/
    """
    url = (
        f"https://projectsapi.zoho.com/restapi/portal/{portal_id}"
        f"/projects/{project_id}/tasks/{task_id}/"
    )
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Zoho-oauthtoken {access_token}")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[ERROR] Get task HTTP {e.code}: {body}")
        sys.exit(1)

    tasks = result.get("tasks", [])
    if not tasks:
        print(f"[ERROR] Task {task_id} not found or no access.")
        sys.exit(1)
    return tasks[0]

# ── Get Custom Status ID ──────────────────────────────────────────────────────
def get_status_id(portal_id, project_id, status_name, access_token):
    """
    Resolve a status name (e.g. 'Blocker') to its custom_status ID.
    Checks KNOWN_STATUS_IDS first; falls back to the API if not found.
    """
    name_lower = status_name.lower()
    if name_lower in KNOWN_STATUS_IDS:
        return KNOWN_STATUS_IDS[name_lower]

    url = (
        f"https://projectsapi.zoho.com/restapi/portal/{portal_id}"
        f"/projects/{project_id}/tasks/statuses/"
    )
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Zoho-oauthtoken {access_token}")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[ERROR] Get statuses HTTP {e.code}: {body}")
        sys.exit(1)

    statuses = result.get("statuses", [])
    for s in statuses:
        if s.get("name", "").lower() == name_lower:
            return s["id"]

    print(f"[ERROR] Status '{status_name}' not found in project.")
    print(f"        Available statuses: {[s.get('name') for s in statuses]}")
    sys.exit(1)

# ── Update Task Status ────────────────────────────────────────────────────────
def update_task_status(portal_id, project_id, task_id, status_id, access_token):
    """
    Update task custom_status via POST (Zoho Projects v2 API uses POST for updates).
    POST /restapi/portal/{portal_id}/projects/{project_id}/tasks/{task_id}/
    """
    url = (
        f"https://projectsapi.zoho.com/restapi/portal/{portal_id}"
        f"/projects/{project_id}/tasks/{task_id}/"
    )
    params = {"custom_status": status_id}
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Zoho-oauthtoken {access_token}")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[ERROR] Update task HTTP {e.code}: {body}")
        sys.exit(1)

    updated_tasks = result.get("tasks", [])
    if not updated_tasks:
        print(f"[ERROR] Task update response did not return tasks: {result}")
        sys.exit(1)
    return updated_tasks[0]

# ── Add Comment to Task ───────────────────────────────────────────────────────
def add_comment(portal_id, project_id, task_id, comment, access_token):
    """
    POST /restapi/portal/{portal_id}/projects/{project_id}/tasks/{task_id}/notes/
    """
    if not comment:
        return
    url = (
        f"https://projectsapi.zoho.com/restapi/portal/{portal_id}"
        f"/projects/{project_id}/tasks/{task_id}/comments/"
    )
    params = {"content": comment}
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Zoho-oauthtoken {access_token}")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        print(f"[OK] Comment added to task.")
    except urllib.error.HTTPError as e:
        # Non-fatal — log but continue
        print(f"[WARN] Comment POST HTTP {e.code}: {e.read().decode()}")

# ── Build Task URL ────────────────────────────────────────────────────────────
def build_task_url(portal_id, project_id, task_id):
    return f"https://projects.zoho.com/portal/{portal_id}/projects/{project_id}/#tasks:{task_id}"

# ── Get Latest Task Comment ───────────────────────────────────────────────────
def _strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()

def get_latest_comment(portal_id, project_id, task_id, access_token):
    """
    Fetch the most recent comment on a task.
    GET /restapi/portal/{portal_id}/projects/{project_id}/tasks/{task_id}/comments/
    """
    url = (
        f"https://projectsapi.zoho.com/restapi/portal/{portal_id}"
        f"/projects/{project_id}/tasks/{task_id}/comments/"
    )
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Zoho-oauthtoken {access_token}")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            result = json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        print(f"[WARN] Could not fetch task comments: {e.code}")
        return ""

    comments = result.get("comments", [])
    if not comments:
        return ""
    latest = max(comments, key=lambda c: c.get("created_time_long", 0))
    return _strip_html(latest.get("content", ""))

# ── Post Cliq Channel Message ─────────────────────────────────────────────────
def post_cliq_message(webhook_url, task_name, task_key, status_name, comment, updated_by, task_url):
    """
    POST to Cliq channel using webhook token URL.
    Endpoint format: https://cliq.zoho.com/api/v2/channelsbyname/{channel}/message?zapikey={token}
    Source: https://www.zoho.com/cliq/help/platform/webhook-tokens.html
    """
    if "blocker" in status_name.lower():
        icon = "🚫"
        title_phrase = "has a blocker"
    else:
        icon = "⚠️"
        title_phrase = "needs approval"

    timestamp = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    card_title = f"Task {task_name} ({task_key}) {title_phrase}"
    comment_line = f"\n*Comment:* {comment}" if comment else ""

    card_display_title = f"{icon} {card_title}"
    if len(card_display_title) > 100:
        card_display_title = card_display_title[:97] + "..."

    message_text = (
        f"{icon} *{card_title}*\n\n"
        f"*Updated by:* {updated_by}\n"
        f"*Time:* {timestamp}"
        f"{comment_line}"
    )

    payload = {
        "text": message_text,
        "card": {
            "title": card_display_title,
            "theme": "modern-inline"
        },
        "buttons": [
            {
                "label": "Open Task",
                "type": "+",
                "action": {
                    "type": "open.url",
                    "data": {"web": task_url}
                }
            }
        ]
    }

    data = json.dumps(payload).encode()
    req = urllib.request.Request(webhook_url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        print(f"[OK] Cliq message posted to channel.")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[ERROR] Cliq POST HTTP {e.code}: {body}")
        sys.exit(1)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Update Zoho Projects task status and post Cliq alert immediately."
    )
    parser.add_argument("--task-id", required=True, help="Zoho Projects task ID (numeric)")
    parser.add_argument(
        "--status", required=True,
        help='Target status name. Must match exactly: "Blocker" or "Needs Approval"'
    )
    parser.add_argument("--comment", default="", help="Optional comment to add to the task")
    parser.add_argument("--updated-by", default="Blake", help="Name to show in Cliq message (default: Blake)")
    args = parser.parse_args()

    # Validate status
    if args.status.lower() not in VALID_ALERT_STATUSES:
        print(f"[ERROR] --status must be one of: {list(VALID_ALERT_STATUSES)}")
        print(f"        Got: '{args.status}'")
        sys.exit(1)

    # Check required env vars
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        print(f"[ERROR] Missing required environment variables: {missing}")
        print("        Copy .env.example to .env and fill in all values.")
        sys.exit(1)

    portal_id  = os.environ["ZOHO_PROJECTS_PORTAL_ID"]
    project_id = os.environ["ZOHO_PROJECT_ID"]
    task_id    = args.task_id
    status_name = args.status

    print(f"[...] Refreshing Zoho access token...")
    token = get_access_token()

    print(f"[...] Fetching task {task_id}...")
    task = get_task(portal_id, project_id, task_id, token)
    task_name = task.get("name", f"Task {task_id}")
    task_key  = task.get("key", task_id)

    print(f"[...] Resolving status ID for '{status_name}'...")
    status_id = get_status_id(portal_id, project_id, status_name, token)

    print(f"[...] Updating task status to '{status_name}'...")
    update_task_status(portal_id, project_id, task_id, status_id, token)
    print(f"[OK] Task '{task_name}' status updated to '{status_name}'.")

    if args.comment:
        print(f"[...] Adding comment to task...")
        add_comment(portal_id, project_id, task_id, args.comment, token)

    print(f"[...] Fetching latest task comment...")
    latest_comment = get_latest_comment(portal_id, project_id, task_id, token)

    task_url = build_task_url(portal_id, project_id, task_id)

    webhook_var = WEBHOOK_BY_STATUS[status_name.lower()]
    webhook_url = os.environ[webhook_var]

    print(f"[...] Posting Cliq channel message...")
    post_cliq_message(
        webhook_url=webhook_url,
        task_name=task_name,
        task_key=task_key,
        status_name=status_name,
        comment=latest_comment,
        updated_by=args.updated_by,
        task_url=task_url,
    )

    print(f"\n✅ Done. Task '{task_name}' → {status_name}. Cliq notified.")

if __name__ == "__main__":
    main()
