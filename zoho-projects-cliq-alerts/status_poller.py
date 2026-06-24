#!/usr/bin/env python3
"""
status_poller.py

Polls Zoho Projects every minute (via cron) for tasks that have moved to
Blocker or Needs Approval, then fires a Zoho Cliq channel notification.

Replaces the Enterprise-only Zoho Flow "Task Updated" trigger passively —
you move the task in the UI, this script detects the change and notifies Cliq
within one cron cycle (~1 min).

State file: status_poller_state.json (task ID → last known status name)
When Claude moves a task directly, it writes to this state file so the poller
doesn't double-fire.

Usage (manual):
  python status_poller.py

Cron (every minute, Mon–Fri 8am–7pm):
  * 8-19 * * 1-5 cd /Users/blakeallard/bevco/scripts/zoho_projects_to_cliq && /usr/bin/python3 status_poller.py >> poller.log 2>&1

Requires .env with the same credentials as update_task_status_and_alert.py.
"""

import os
import re
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

# ── Load .env ────────────────────────────────────────────────────────────────
def load_dotenv(path=".env"):
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

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

# ── Config ───────────────────────────────────────────────────────────────────
REQUIRED_VARS = [
    "ZOHO_CLIENT_ID",
    "ZOHO_CLIENT_SECRET",
    "ZOHO_REFRESH_TOKEN",
    "ZOHO_PROJECTS_PORTAL_ID",
    "ZOHO_PROJECT_ID",
    "CLIQ_CHANNEL_WEBHOOK_URL_BLOCKER",
    "CLIQ_CHANNEL_WEBHOOK_URL_NEEDS_APPROVAL",
]

ALERT_STATUSES = {
    "blocker":        "CLIQ_CHANNEL_WEBHOOK_URL_BLOCKER",
    "needs approval": "CLIQ_CHANNEL_WEBHOOK_URL_NEEDS_APPROVAL",
}

STATE_FILE = os.path.join(SCRIPT_DIR, "status_poller_state.json")

# ── State helpers ─────────────────────────────────────────────────────────────
def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE) as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ── Zoho OAuth ────────────────────────────────────────────────────────────────
def get_access_token():
    url = "https://accounts.zoho.com/oauth/v2/token"
    params = {
        "refresh_token": os.environ["ZOHO_REFRESH_TOKEN"],
        "client_id":     os.environ["ZOHO_CLIENT_ID"],
        "client_secret": os.environ["ZOHO_CLIENT_SECRET"],
        "grant_type":    "refresh_token",
    }
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[ERROR] Token refresh {e.code}: {e.read().decode()}")
        sys.exit(1)
    if "access_token" not in result:
        print(f"[ERROR] Token refresh failed: {result}")
        sys.exit(1)
    return result["access_token"]

# ── Zoho Projects API ─────────────────────────────────────────────────────────
def get_tasks(portal_id, project_id, token):
    url = (
        f"https://projectsapi.zoho.com/restapi/portal/{portal_id}"
        f"/projects/{project_id}/tasks/"
    )
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Zoho-oauthtoken {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[ERROR] Get tasks {e.code}: {e.read().decode()}")
        sys.exit(1)
    return result.get("tasks", [])

def _strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()

def get_latest_comment(portal_id, project_id, task_id, token):
    url = (
        f"https://projectsapi.zoho.com/restapi/portal/{portal_id}"
        f"/projects/{project_id}/tasks/{task_id}/comments/"
    )
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Zoho-oauthtoken {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            result = json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        print(f"[WARN] Could not fetch comments for {task_id}: {e.code}")
        return ""
    comments = result.get("comments", [])
    if not comments:
        return ""
    latest = max(comments, key=lambda c: c.get("created_time_long", 0))
    return _strip_html(latest.get("content", ""))

# ── Cliq notification ─────────────────────────────────────────────────────────
def post_cliq_message(webhook_url, task_name, task_key, status_name, comment, task_url):
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
        f"*Time:* {timestamp}"
        f"{comment_line}"
    )

    payload = {
        "text": message_text,
        "card": {
            "title": card_display_title,
            "theme": "modern-inline",
        },
        "buttons": [
            {
                "label": "Open Task",
                "type": "+",
                "action": {
                    "type": "open.url",
                    "data": {"web": task_url},
                },
            }
        ],
    }

    data = json.dumps(payload).encode()
    req = urllib.request.Request(webhook_url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        print(f"[OK] Cliq notified: {card_title}")
    except urllib.error.HTTPError as e:
        print(f"[WARN] Cliq POST {e.code}: {e.read().decode()}")

def build_task_url(project_id, task_id):
    return f"https://projects.zoho.com/portal/bevcollc/projects/{project_id}/#tasks:{task_id}"

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        print(f"[ERROR] Missing env vars: {missing}")
        sys.exit(1)

    portal_id  = os.environ["ZOHO_PROJECTS_PORTAL_ID"]
    project_id = os.environ["ZOHO_PROJECT_ID"]

    state = load_state()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Polling tasks...")
    token = get_access_token()
    tasks = get_tasks(portal_id, project_id, token)

    new_state = {}
    for task in tasks:
        task_id     = str(task.get("id", ""))
        task_name   = task.get("name", f"Task {task_id}")
        task_key    = task.get("key", task_id)
        status_name = (task.get("custom_status", {}) or {}).get("name", "") or task.get("status", {}).get("name", "")

        new_state[task_id] = status_name

        prev_status = state.get(task_id, "")
        if prev_status == status_name:
            continue  # no change

        status_lower = status_name.lower()
        if status_lower not in ALERT_STATUSES:
            continue  # changed to something we don't alert on

        print(f"[!] {task_key} moved to '{status_name}' (was '{prev_status}')")

        comment  = get_latest_comment(portal_id, project_id, task_id, token)
        task_url = build_task_url(project_id, task_id)
        webhook_url = os.environ[ALERT_STATUSES[status_lower]]

        post_cliq_message(
            webhook_url=webhook_url,
            task_name=task_name,
            task_key=task_key,
            status_name=status_name,
            comment=comment,
            task_url=task_url,
        )

    save_state(new_state)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Done. {len(tasks)} tasks checked.")

if __name__ == "__main__":
    main()
