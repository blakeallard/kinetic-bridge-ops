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
import time
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
TOKEN_CACHE_FILE = os.path.join(SCRIPT_DIR, "zoho_access_token_cache.json")
TOKEN_EXPIRY_SKEW_SECONDS = 5 * 60

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
def load_cached_access_token():
    if not os.path.exists(TOKEN_CACHE_FILE):
        return None
    try:
        with open(TOKEN_CACHE_FILE) as f:
            cache = json.load(f)
        token = cache.get("access_token")
        expires_at = float(cache.get("expires_at", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
        print(f"[WARN] Ignoring invalid Zoho token cache: {e}")
        return None

    if not token or time.time() >= expires_at - TOKEN_EXPIRY_SKEW_SECONDS:
        return None

    print("[INFO] Reusing cached Zoho access token")
    return token


def save_access_token_cache(token, expires_at):
    cache = {
        "access_token": token,
        "expires_at": expires_at,
    }
    temp_path = f"{TOKEN_CACHE_FILE}.tmp"
    try:
        with open(temp_path, "w") as f:
            json.dump(cache, f, indent=2)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, TOKEN_CACHE_FILE)
    except OSError as e:
        print(f"[WARN] Could not write Zoho token cache: {e}")


def _token_refresh_error_message(result):
    if not isinstance(result, dict):
        return "unexpected response"
    return result.get("error_description") or result.get("error") or "access token missing from response"


def get_access_token(force_refresh=False):
    if not force_refresh:
        cached_token = load_cached_access_token()
        if cached_token:
            return cached_token

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
        body = e.read().decode(errors="replace")
        try:
            detail = _token_refresh_error_message(json.loads(body))
        except json.JSONDecodeError:
            detail = f"HTTP {e.code}"
        print(f"[ERROR] Token refresh failed: HTTP {e.code}: {detail}")
        sys.exit(1)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"[ERROR] Token refresh failed: {e}")
        sys.exit(1)
    if "access_token" not in result:
        print(f"[ERROR] Token refresh failed: {_token_refresh_error_message(result)}")
        sys.exit(1)

    try:
        expires_in = int(result.get("expires_in_sec", result.get("expires_in", 3600)))
    except (TypeError, ValueError):
        expires_in = 3600
    expires_at = time.time() + expires_in
    save_access_token_cache(result["access_token"], expires_at)
    print("[INFO] Refreshed Zoho access token")
    return result["access_token"]

# ── Zoho Projects API ─────────────────────────────────────────────────────────
def _is_auth_error(status_code, body):
    normalized = body.lower().replace("-", "_").replace(" ", "_")
    return status_code == 401 or any(marker in normalized for marker in (
        "invalid_token",
        "invalid_oauthtoken",
        "invalid_oauth_token",
    ))


def _authorized_get_json(url, token, error_context, warn_only=False):
    current_token = token
    for attempt in range(2):
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Zoho-oauthtoken {current_token}")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read()
                return (json.loads(body) if body.strip() else {}), current_token
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if attempt == 0 and _is_auth_error(e.code, body):
                print("[INFO] Cached Zoho access token was rejected; refreshing and retrying")
                current_token = get_access_token(force_refresh=True)
                continue
            if warn_only:
                print(f"[WARN] {error_context}: HTTP {e.code}")
                return {}, current_token
            print(f"[ERROR] {error_context}: HTTP {e.code}: {body}")
            sys.exit(1)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if warn_only:
                print(f"[WARN] {error_context}: {e}")
                return {}, current_token
            print(f"[ERROR] {error_context}: {e}")
            sys.exit(1)

    raise RuntimeError("unreachable")


def get_tasks(portal_id, project_id, token):
    url = (
        f"https://projectsapi.zoho.com/restapi/portal/{portal_id}"
        f"/projects/{project_id}/tasks/"
    )
    result, token = _authorized_get_json(url, token, "Get tasks failed")
    return result.get("tasks", []), token

def _strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()

def get_latest_comment(portal_id, project_id, task_id, token):
    url = (
        f"https://projectsapi.zoho.com/restapi/portal/{portal_id}"
        f"/projects/{project_id}/tasks/{task_id}/comments/"
    )
    result, token = _authorized_get_json(
        url,
        token,
        f"Could not fetch comments for {task_id}",
        warn_only=True,
    )
    comments = result.get("comments", [])
    if not comments:
        return "", token
    latest = max(comments, key=lambda c: c.get("created_time_long", 0))
    return _strip_html(latest.get("content", "")), token

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
    tasks, token = get_tasks(portal_id, project_id, token)

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

        comment, token = get_latest_comment(portal_id, project_id, task_id, token)
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
