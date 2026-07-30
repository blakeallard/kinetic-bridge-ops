#!/usr/bin/env python3
"""
fetch_zoho_tasks.py

Fetches the current task list for the configured Zoho Projects project
directly via the Zoho Projects REST API and writes it to tasks_latest.json
in the shape bevco_task_poller.py expects ({"tasks": [...]}).

This replaces the previous `claude -p` MCP fetch, which required an
interactive Claude Code login and therefore failed under cron.

Credentials: reuses the existing OAuth client + refresh token from
/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/.env (same source
as status_poller.py and the repo-lifecycle tool). No secrets are printed.

Token cache: reads the status poller's cache read-only if fresh; refreshed
tokens are written only to this folder's own cache file to avoid two
writers on the shared cache.

Usage:
  python3 fetch_zoho_tasks.py                  # writes tasks_latest.json
  python3 fetch_zoho_tasks.py --out other.json
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_PATH = Path("/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/.env")
SHARED_TOKEN_CACHE = Path(
    "/Users/blakeallard/bevco/scripts/zoho_projects_to_cliq/zoho_access_token_cache.json"
)
LOCAL_TOKEN_CACHE = SCRIPT_DIR / "zoho_access_token_cache.json"
TOKEN_EXPIRY_SKEW_SECONDS = 120
PAGE_SIZE = 100

# SSL: use certifi bundle if available (fixes Python 3.13 macOS cert issue)
import ssl as _ssl

try:
    import certifi as _certifi

    _https_handler = urllib.request.HTTPSHandler(
        context=_ssl.create_default_context(cafile=_certifi.where())
    )
    urllib.request.install_opener(urllib.request.build_opener(_https_handler))
except ImportError:
    pass


def load_dotenv(path: Path) -> None:
    if not path.exists():
        print(f"[ERROR] env file not found: {path}", file=sys.stderr)
        sys.exit(1)
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def read_cached_token(path: Path) -> str | None:
    try:
        cache = json.loads(path.read_text())
        token = cache.get("access_token")
        expires_at = float(cache.get("expires_at", 0))
    except (OSError, ValueError, TypeError):
        return None
    if not token or time.time() >= expires_at - TOKEN_EXPIRY_SKEW_SECONDS:
        return None
    return token


def refresh_access_token() -> str:
    url = "https://accounts.zoho.com/oauth/v2/token"
    params = {
        "refresh_token": os.environ["ZOHO_REFRESH_TOKEN"],
        "client_id": os.environ["ZOHO_CLIENT_ID"],
        "client_secret": os.environ["ZOHO_CLIENT_SECRET"],
        "grant_type": "refresh_token",
    }
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(params).encode(), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"[ERROR] Zoho token refresh failed: {e}", file=sys.stderr)
        sys.exit(1)
    if "access_token" not in result:
        detail = result.get("error_description") or result.get("error") or "no access_token"
        print(f"[ERROR] Zoho token refresh failed: {detail}", file=sys.stderr)
        sys.exit(1)
    try:
        expires_in = int(result.get("expires_in_sec", result.get("expires_in", 3600)))
    except (TypeError, ValueError):
        expires_in = 3600
    try:
        LOCAL_TOKEN_CACHE.write_text(
            json.dumps({"access_token": result["access_token"], "expires_at": time.time() + expires_in})
        )
        LOCAL_TOKEN_CACHE.chmod(0o600)
    except OSError as e:
        print(f"[WARN] could not write local token cache: {e}", file=sys.stderr)
    print("[INFO] Refreshed Zoho access token")
    return result["access_token"]


def get_access_token() -> str:
    for cache in (LOCAL_TOKEN_CACHE, SHARED_TOKEN_CACHE):
        token = read_cached_token(cache)
        if token:
            print(f"[INFO] Reusing cached Zoho access token ({cache.name})")
            return token
    return refresh_access_token()


def fetch_all_tasks(token: str) -> list[dict]:
    portal_id = urllib.parse.quote(os.environ["ZOHO_PROJECTS_PORTAL_ID"], safe="")
    project_id = urllib.parse.quote(os.environ["ZOHO_PROJECT_ID"], safe="")
    tasks: list[dict] = []
    index = 1
    while True:
        url = (
            f"https://projectsapi.zoho.com/restapi/portal/{portal_id}"
            f"/projects/{project_id}/tasks/?index={index}&range={PAGE_SIZE}"
        )
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Zoho-oauthtoken {token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 204:
                break  # no (more) content
            print(f"[ERROR] Zoho task fetch failed: HTTP {e.code}", file=sys.stderr)
            sys.exit(1)
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"[ERROR] Zoho task fetch failed: {e}", file=sys.stderr)
            sys.exit(1)
        if not body.strip():
            break
        page = json.loads(body).get("tasks", [])
        if not page:
            break
        tasks.extend(page)
        if len(page) < PAGE_SIZE:
            break
        index += PAGE_SIZE
    return tasks


def normalize(task: dict) -> dict:
    # Downstream diffing compares string task IDs (MCP shape used strings);
    # the raw REST API returns numeric id plus id_string.
    task_id = task.get("id_string") or task.get("id")
    task["id"] = str(task_id)
    # MCP payloads carried `prefix` (task key) and dict-shaped created_by;
    # mirror those so downstream formatting keeps working with either source.
    if not task.get("prefix") and task.get("key"):
        task["prefix"] = task["key"]
    created_by = task.get("created_by")
    if not task.get("last_modified_time") and task.get("last_updated_time"):
        task["last_modified_time"] = task["last_updated_time"]
    if isinstance(created_by, str):
        task["created_by"] = {
            "name": task.get("created_person") or created_by,
            "id": created_by,
        }
    return task


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Zoho Projects tasks to JSON")
    parser.add_argument("--out", default=str(SCRIPT_DIR / "tasks_latest.json"))
    args = parser.parse_args()

    load_dotenv(ENV_PATH)
    for var in ("ZOHO_REFRESH_TOKEN", "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET",
                "ZOHO_PROJECTS_PORTAL_ID", "ZOHO_PROJECT_ID"):
        if not os.environ.get(var):
            print(f"[ERROR] missing required env var: {var}", file=sys.stderr)
            return 1

    tasks = [normalize(t) for t in fetch_all_tasks(get_access_token())]
    Path(args.out).write_text(json.dumps({"tasks": tasks}, indent=2))
    print(f"[INFO] wrote {len(tasks)} task(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
