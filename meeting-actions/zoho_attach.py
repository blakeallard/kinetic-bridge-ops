#!/usr/bin/env python3
"""
zoho_attach.py
Upload a worksheet HTML file as an attachment to a Zoho Projects task.

Usage:
    python3 zoho_attach.py <task_id> <html_file>
    python3 zoho_attach.py <task_id> --html "<raw html string>"
"""

import json
import os
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import certifi
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

ENV_FILE = Path("/Users/blakeallard/bevco/automations/zoho-task-folder-sync/.env")

PORTAL_ID = "898600220"
PROJECT_ID = "2543412000001324010"


def load_env() -> None:
    if not ENV_FILE.exists():
        raise FileNotFoundError(f"Missing .env: {ENV_FILE}")
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def get_access_token() -> str:
    accounts_domain = os.environ.get("ZOHO_ACCOUNTS_DOMAIN", "https://accounts.zoho.com")
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": os.environ["ZOHO_CLIENT_ID"],
        "client_secret": os.environ["ZOHO_CLIENT_SECRET"],
        "refresh_token": os.environ["ZOHO_REFRESH_TOKEN"],
    }).encode()
    req = urllib.request.Request(
        f"{accounts_domain}/oauth/v2/token",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        result = json.loads(resp.read())
    token = result.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {json.dumps(result)}")
    return token


def attach_file(task_id: str, file_path: Path, filename: str, access_token: str) -> dict:
    api_domain = os.environ.get("ZOHO_PROJECTS_API_DOMAIN", "https://projectsapi.zoho.com")
    url = (
        f"{api_domain}/restapi/portal/{PORTAL_ID}/projects/{PROJECT_ID}"
        f"/tasks/{task_id}/attachments/"
    )

    content = file_path.read_bytes()
    boundary = f"----ZohoBoundary{uuid.uuid4().hex}"

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/html; charset=utf-8\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_str = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body_str}")


def worksheet_html_page(description_html: str, task_name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BEVCO Worksheet — {task_name}</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 780px; margin: 40px auto; padding: 0 20px; color: #222; line-height: 1.6; }}
  b {{ color: #1a1a1a; }}
  i {{ color: #666; font-size: 0.9em; }}
</style>
</head>
<body>
{description_html}
</body>
</html>"""


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        print("Usage: zoho_attach.py <task_id> <html_file>", file=sys.stderr)
        print("       zoho_attach.py <task_id> --html '<html string>'", file=sys.stderr)
        sys.exit(1)

    task_id = args[0]
    load_env()
    token = get_access_token()

    if args[1] == "--html":
        raw_html = args[2] if len(args) > 2 else ""
        full_html = worksheet_html_page(raw_html, f"Task {task_id}")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        ) as f:
            f.write(full_html)
            tmp = Path(f.name)
        filename = f"BEVCO_Worksheet_{task_id}.html"
        try:
            result = attach_file(task_id, tmp, filename, token)
        finally:
            tmp.unlink(missing_ok=True)
    else:
        file_path = Path(args[1])
        if not file_path.exists():
            print(f"[error] File not found: {file_path}", file=sys.stderr)
            sys.exit(1)
        filename = file_path.name
        result = attach_file(task_id, file_path, filename, token)

    status = result.get("status", "?")
    if status == "success":
        doc = result.get("data", {})
        print(f"[ok] Attached: {doc.get('file_name', filename)} (id={doc.get('id', '?')})")
    else:
        print(f"[error] {json.dumps(result)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
