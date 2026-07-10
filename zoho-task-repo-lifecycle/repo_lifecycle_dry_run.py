#!/usr/bin/env python3
"""Zoho task to GitHub repository lifecycle; dry-run by default."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import ssl
import stat
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


LABELS = ("SUCCESS", "WARN", "ERROR", "INFO", "SKIPPED", "BLOCKED")
HOME = Path("/Users/blakeallard")
PROJECT_DIR = Path(__file__).resolve().parent
REPORT_DIR = PROJECT_DIR / "reports"
TEMPLATE_DIR = PROJECT_DIR / "templates/repo"
SOURCE_ENV_FILE = HOME / "bevco/scripts/zoho_projects_to_cliq/.env"
SOURCE_TOKEN_CACHE = HOME / "bevco/scripts/zoho_projects_to_cliq/zoho_access_token_cache.json"
LOCAL_REPO_ROOT = HOME / "bevco/repos"
GITHUB_ORG = os.environ.get("GITHUB_ORG", "blake-bevco-tech")
APPROVAL_TAG = "repo-needed"
REQUIRED_ENV_NAMES = {
    "ZOHO_CLIENT_ID",
    "ZOHO_CLIENT_SECRET",
    "ZOHO_REFRESH_TOKEN",
    "ZOHO_PROJECTS_PORTAL_ID",
    "ZOHO_PROJECT_ID",
}
MAPPING_PATHS = (
    PROJECT_DIR / "task_repo_map.json",
    HOME / "bevco/automation_state/task_repo_map.json",
    HOME / "bevco/scripts/zoho_projects_to_cliq/task_repo_map.json",
)
GITHUB_URL_PATTERN = re.compile(
    r"https://github\.com/(?P<org>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
SENSITIVE_HEADER_PATTERN = re.compile(r"(?i)\b(authorization|cookie|set-cookie)\s*:\s*[^\r\n]+")
BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
SECRET_PATTERN = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|client[_-]?secret|secret|password|zapikey|webhook)[A-Za-z0-9_-]*[\"']?\s*[:=]\s*)"
    r"(?:[\"'][^\"']*[\"']|[^\s,;]+)"
)
ISSUE_TASK_ID_MARKER = "<!-- zoho-task-id: {task_id} -->"
ISSUE_TASK_KEY_MARKER = "<!-- zoho-task-key: {task_key} -->"
PROJECT_OWNER = "blake-bevco-tech"
PROJECT_NUMBER = 1
PROJECT_ID = "PVT_kwHOEZB-V84BcWRd"
PROJECT_NAME = "BEVCO Summer AI Execution"
PROJECT_URL = "https://github.com/users/blake-bevco-tech/projects/1"
PROJECT_STATUS_FIELD_NAME = "Status"
PROJECT_STATUS_FIELD_ID = "PVTSSF_lAHOEZB-V84BcWRdzhW_yOs"
PROJECT_STATUS_OPTIONS = {
    "In Progress": "f75ad846",
    "Backlog": "47fc9ee4",
    "Needs Approval": "e5a27284",
    "Blocker": "ba2eeecb",
    "Closed": "e7c555c4",
}
MINIMAL_REQUIRED_COORDINATION_FILES = (
    "README.md",
    "TASK.md",
    "AGENTS.md",
    "docs/CURRENT_HANDOFF.md",
    ".github/ISSUE_TEMPLATE/zoho-task.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
)
LEGACY_REQUIRED_COORDINATION_FILES = (
    "README.md",
    "TASK.md",
    "STATUS.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
    ".github/ISSUE_TEMPLATE/zoho-task.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
)


@dataclass
class Finding:
    label: str
    section: str
    message: str


@dataclass
class Decision:
    task_id: str
    task_key: str
    title: str
    repo_name: str
    action: str
    reason: str
    missing_metadata: list[str] = field(default_factory=list)


@dataclass
class IssueRecord:
    number: str
    url: str
    title: str
    body: str


@dataclass
class ProjectItemRecord:
    item_id: str
    issue_node_id: str
    issue_number: str
    issue_url: str
    status_name: str
    status_option_id: str


@dataclass
class ZohoReadResult:
    env: dict[str, str]
    env_names: set[str]
    findings: list[tuple[str, str]]
    total_tasks: int = 0
    tagged_tasks: list[dict[str, Any]] = field(default_factory=list)
    untagged_count: int = 0
    token: str | None = None
    comments_checked: int = 0


@dataclass
class GitHubReadResult:
    findings: list[tuple[str, str]]
    state: str
    github_checks: int = 0


@dataclass
class MappingReadResult:
    entries: list[dict[str, str]]
    findings: list[tuple[str, str]]


@dataclass
class DecisionGroups:
    would_create: list[Decision]
    existing: list[Decision]
    blocked: list[Decision]
    missing_metadata: list[Decision]


class Report:
    def __init__(self, mode: str = "dry-run") -> None:
        self.timestamp = datetime.now().astimezone()
        self.started = time.monotonic()
        self.mode = mode
        self.findings: list[Finding] = []

    def add(self, label: str, section: str, message: str) -> None:
        if label not in LABELS:
            raise ValueError(f"unsupported label: {label}")
        self.findings.append(Finding(label, section, redact(message)))

    def lines(self, report_path: Path | None = None) -> list[str]:
        lines = [
            f"[INFO] Zoho Task to GitHub Repo Lifecycle — {self.timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"[INFO] Mode: {self.mode}; duration: {time.monotonic() - self.started:.2f}s",
        ]
        if report_path is not None:
            lines.append(f"[INFO] Report path: {report_path}")
        section = None
        for finding in self.findings:
            if finding.section != section:
                section = finding.section
                lines.append(f"[INFO] {section}")
            lines.append(f"[{finding.label}] {finding.message}")
        return lines

    def exit_code(self) -> int:
        labels = {finding.label for finding in self.findings}
        if "BLOCKED" in labels:
            return 2
        if "ERROR" in labels:
            return 1
        return 0


def redact(value: Any) -> str:
    text = str(value)
    text = SENSITIVE_HEADER_PATTERN.sub(r"\1: [REDACTED]", text)
    text = BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    text = SECRET_PATTERN.sub(r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(https?://[^\s?]+)\?[^\s]+", r"\1?[REDACTED]", text)
    return text.replace("\n", " ").replace("\r", " ")[:600]


def install_tls_context() -> None:
    try:
        import certifi  # type: ignore

        context = ssl.create_default_context(cafile=certifi.where())
        urllib.request.install_opener(
            urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
        )
    except ImportError:
        return


def load_env_file(path: Path) -> tuple[dict[str, str], set[str]]:
    values: dict[str, str] = {}
    names: set[str] = set()
    with path.open() as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                continue
            names.add(name)
            values[name] = value.strip().strip('"').strip("'")
    for name in names:
        if name in os.environ:
            values[name] = os.environ[name]
    return values, names


def safe_json_error(body: str, fallback: str) -> str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return fallback
    if not isinstance(data, dict):
        return fallback
    return str(data.get("error_description") or data.get("message") or data.get("error") or fallback)


def cached_access_token() -> str | None:
    if not SOURCE_TOKEN_CACHE.is_file():
        return None
    try:
        with SOURCE_TOKEN_CACHE.open() as handle:
            cache = json.load(handle)
        token = cache.get("access_token")
        expires_at = float(cache.get("expires_at", 0))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(token, str) or not token or expires_at - time.time() <= 300:
        return None
    return token


def refresh_access_token(env: dict[str, str]) -> str:
    data = urllib.parse.urlencode(
        {
            "refresh_token": env["ZOHO_REFRESH_TOKEN"],
            "client_id": env["ZOHO_CLIENT_ID"],
            "client_secret": env["ZOHO_CLIENT_SECRET"],
            "grant_type": "refresh_token",
        }
    ).encode()
    request = urllib.request.Request(
        "https://accounts.zoho.com/oauth/v2/token",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Zoho token refresh HTTP {exc.code}: {safe_json_error(body, 'request failed')}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Zoho token refresh failed: {exc}") from None
    token = result.get("access_token") if isinstance(result, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("Zoho token refresh response did not contain an access token")
    return token


def zoho_get_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(url)
    request.add_header("Authorization", f"Zoho-oauthtoken {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Zoho read HTTP {exc.code}: {safe_json_error(body, 'request failed')}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Zoho read failed: {exc}") from None
    if not isinstance(result, dict):
        raise RuntimeError("Zoho read returned an unexpected response shape")
    return result


def fetch_tasks(env: dict[str, str], token: str) -> list[dict[str, Any]]:
    portal_id = urllib.parse.quote(env["ZOHO_PROJECTS_PORTAL_ID"], safe="")
    project_id = urllib.parse.quote(env["ZOHO_PROJECT_ID"], safe="")
    base = f"https://projectsapi.zoho.com/restapi/portal/{portal_id}/projects/{project_id}/tasks/"
    tasks: list[dict[str, Any]] = []
    start = 1
    for _ in range(10):
        result = zoho_get_json(f"{base}?range=100&start={start}", token)
        page = result.get("tasks", [])
        if not isinstance(page, list):
            raise RuntimeError("Zoho task response does not contain a task list")
        tasks.extend(task for task in page if isinstance(task, dict))
        if len(page) < 100:
            break
        start += 100
    return tasks


def fetch_comments(env: dict[str, str], token: str, task_id: str) -> list[dict[str, Any]]:
    portal_id = urllib.parse.quote(env["ZOHO_PROJECTS_PORTAL_ID"], safe="")
    project_id = urllib.parse.quote(env["ZOHO_PROJECT_ID"], safe="")
    safe_task_id = urllib.parse.quote(task_id, safe="")
    url = (
        f"https://projectsapi.zoho.com/restapi/portal/{portal_id}/projects/{project_id}"
        f"/tasks/{safe_task_id}/comments/"
    )
    result = zoho_get_json(url, token)
    comments = result.get("comments", [])
    return [comment for comment in comments if isinstance(comment, dict)] if isinstance(comments, list) else []


def extract_tags(task: dict[str, Any]) -> list[str]:
    raw_tags = task.get("tags", [])
    if not isinstance(raw_tags, list):
        return []
    tags: list[str] = []
    for tag in raw_tags:
        if isinstance(tag, dict):
            name = tag.get("name") or tag.get("tag_name")
        else:
            name = tag
        if isinstance(name, str) and name.strip():
            tags.append(name.strip())
    return tags


def extract_task_key(task: dict[str, Any]) -> str:
    for field_name in ("key", "task_key", "task_number", "prefix", "id_string"):
        value = task.get(field_name)
        if value is None:
            continue
        match = re.search(r"\bBI1-T\d+\b", str(value), re.IGNORECASE)
        if match:
            return match.group(0).upper()
    return ""


def slugify(title: str, max_length: int = 80) -> str:
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug[:max_length].rstrip("-")


def expected_repo_name(task_key: str, title: str) -> str:
    prefix = task_key.lower()
    available = max(1, 100 - len(prefix) - 1)
    return f"{prefix}-{slugify(title, available)}"


def github_urls_from_text(text: str) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    for match in GITHUB_URL_PATTERN.finditer(text or ""):
        org = match.group("org")
        repo = match.group("repo").removesuffix(".git")
        results.append((org, repo, f"https://github.com/{org}/{repo}"))
    return results


def local_repo_index() -> dict[str, Path]:
    if not LOCAL_REPO_ROOT.is_dir():
        return {}
    index: dict[str, Path] = {}
    for entry in os.scandir(LOCAL_REPO_ROOT):
        if entry.is_symlink():
            continue
        if entry.is_dir(follow_symlinks=False):
            index[entry.name.lower()] = Path(entry.path)
    return index


def mapping_entries() -> tuple[list[dict[str, str]], list[Path]]:
    entries: list[dict[str, str]] = []
    sources: list[Path] = []
    for path in MAPPING_PATHS:
        if not path.is_file():
            continue
        sources.append(path)
        try:
            with path.open() as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"mapping file is unreadable: {path}: {exc}") from None
        raw_entries: list[tuple[str, Any]]
        if isinstance(data, dict) and isinstance(data.get("mappings"), list):
            raw_entries = [("", item) for item in data["mappings"]]
        elif isinstance(data, dict):
            raw_entries = list(data.items())
        elif isinstance(data, list):
            raw_entries = [("", item) for item in data]
        else:
            raise RuntimeError(f"mapping file has unsupported structure: {path}")
        for key, value in raw_entries:
            if isinstance(value, dict):
                entry = {str(k): str(v) for k, v in value.items() if v is not None}
                entry.setdefault("task_id", str(key))
            else:
                entry = {"task_id": str(key), "repo_url": str(value)}
            repo_url = entry.get("repo_url", "")
            urls = github_urls_from_text(repo_url)
            if urls and not entry.get("repo_name"):
                entry["repo_name"] = urls[0][1]
            entries.append(entry)
    return entries, sources


def run_gh(arguments: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["gh", *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env={**os.environ, "GH_PROMPT_DISABLED": "1"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def github_auth_state() -> tuple[str, str]:
    if shutil.which("gh") is None:
        return "unavailable", "GitHub CLI is not installed"
    result = run_gh(["auth", "status"])
    if result is None:
        return "blocked", "gh auth status could not complete"
    if result.returncode == 0:
        return "ready", "GitHub CLI authenticated"
    first_line = (result.stderr or result.stdout).strip().splitlines()
    reason = first_line[0] if first_line else f"exit {result.returncode}"
    return "blocked", f"GitHub CLI authentication unavailable: {reason}"


def github_repo_state(repo_name: str) -> tuple[str, str]:
    result = run_gh(["repo", "view", f"{GITHUB_ORG}/{repo_name}", "--json", "name,url,isPrivate"])
    if result is None:
        return "blocked", "gh repo view did not complete"
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            found_name = str(data.get("name") or repo_name)
        except json.JSONDecodeError:
            found_name = repo_name
        return "exists", f"GitHub repository exists: {GITHUB_ORG}/{found_name}"
    combined = f"{result.stderr}\n{result.stdout}".lower()
    if "could not resolve to a repository" in combined or "not found" in combined or "could not resolve" in combined:
        return "absent", f"GitHub repository not found: {GITHUB_ORG}/{repo_name}"
    return "blocked", "gh repo view returned an unclassified read error"


def mapping_evidence(entries: list[dict[str, str]], task_id: str, task_key: str, repo_name: str) -> tuple[list[str], list[str]]:
    matching: list[str] = []
    conflicts: list[str] = []
    for entry in entries:
        entry_id = entry.get("task_id", "")
        entry_key = entry.get("task_key", "")
        entry_repo = entry.get("repo_name", "")
        same_task = entry_id == task_id or entry_key.upper() == task_key.upper()
        same_repo = entry_repo.lower() == repo_name.lower() if entry_repo else False
        if same_task and entry_repo and not same_repo:
            conflicts.append(f"task mapping points to {entry_repo}")
        elif same_repo and entry_id and entry_id != task_id:
            conflicts.append(f"repository name maps to task ID {entry_id}")
        elif same_task or same_repo:
            matching.append("task_repo_map.json")
    return matching, conflicts


def mapping_entry_for_task(
    entries: list[dict[str, str]],
    task_id: str,
    task_key: str,
    repo_name: str,
) -> dict[str, str] | None:
    for entry in entries:
        entry_id = entry.get("task_id", "")
        entry_key = entry.get("task_key", "")
        entry_repo = entry.get("repo_name", "")
        same_task = entry_id == task_id or entry_key.upper() == task_key.upper()
        same_repo = entry_repo.lower() == repo_name.lower() if entry_repo else False
        if same_task or same_repo:
            return entry
    return None


class ApplyBlocked(RuntimeError):
    """A safety or idempotency check refused an apply step."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run by default; apply is confirmation-gated per eligible repo-needed task."
    )
    parser.add_argument("--apply", action="store_true", help="Enable the controlled one-task apply path")
    parser.add_argument("--task-key", help="Required task key for apply mode")
    parser.add_argument(
        "--confirm-apply",
        metavar="TASK_KEY",
        help="Second explicit confirmation token; must exactly match --task-key",
    )
    return parser.parse_args()


def validate_apply_gate(args: argparse.Namespace) -> str:
    if not args.apply:
        return ""
    if not args.task_key:
        return "apply mode requires --task-key"
    if args.confirm_apply != args.task_key:
        return f"apply mode requires --confirm-apply {args.task_key}"
    return ""


def named_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("display_name") or value.get("full_name") or "").strip()
    return str(value or "").strip()


def task_status(task: dict[str, Any]) -> str:
    return named_value(task.get("custom_status")) or named_value(task.get("status")) or "Unknown"


def task_owner(task: dict[str, Any]) -> str:
    for field_name in ("owner", "created_by"):
        value = named_value(task.get(field_name))
        if value:
            return value
    details = task.get("details")
    if isinstance(details, dict):
        owners = details.get("owners")
        if isinstance(owners, list) and owners:
            value = named_value(owners[0])
            if value:
                return value
    return "Not provided"


def plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def sanitize_metadata(value: Any, key_name: str = "") -> Any:
    if re.search(r"(?i)(token|secret|password|authorization|cookie|webhook|zapikey|api[_-]?key)", key_name):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(key): sanitize_metadata(item, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_metadata(item, key_name) for item in value]
    if isinstance(value, str):
        text = SENSITIVE_HEADER_PATTERN.sub(r"\1: [REDACTED]", value)
        text = BEARER_PATTERN.sub("Bearer [REDACTED]", text)
        text = SECRET_PATTERN.sub(r"\1[REDACTED]", text)
        return re.sub(r"(?i)(https?://[^\s?]+)\?[^\s]+", r"\1?[REDACTED]", text)
    return value


def issue_task_id_marker(task_id: str) -> str:
    return ISSUE_TASK_ID_MARKER.format(task_id=task_id)


def issue_task_key_marker(task_key: str) -> str:
    return ISSUE_TASK_KEY_MARKER.format(task_key=task_key)


def build_issue_title(decision: Decision) -> str:
    return f"[{decision.task_key}] {decision.title}"


def task_web_url(task: dict[str, Any]) -> str:
    direct = str(task.get("url") or task.get("web_url") or task.get("task_url") or "").strip()
    if direct:
        return direct
    link = task.get("link")
    if isinstance(link, dict):
        web = link.get("web")
        if isinstance(web, dict):
            value = str(web.get("url") or "").strip()
            if value:
                return value
    return ""


def build_issue_body(
    task: dict[str, Any],
    decision: Decision,
    env: dict[str, str],
    repo_url: str,
    local_path: Path,
) -> str:
    description = plain_text(str(sanitize_metadata(str(task.get("description") or "")))) or "No task description was provided."
    status = task_status(task)
    task_url = task_web_url(task) or "Not provided"
    return "\n".join(
        [
            issue_task_id_marker(decision.task_id),
            issue_task_key_marker(decision.task_key),
            "",
            "## Zoho Metadata",
            "",
            f"- Zoho Project ID: {env.get('ZOHO_PROJECT_ID', 'Not provided')}",
            f"- Zoho Task ID: {decision.task_id}",
            f"- Zoho Task Key: {decision.task_key}",
            f"- Zoho Task Title: {decision.title}",
            f"- Zoho URL: {task_url}",
            "",
            "## Workspace",
            "",
            f"- GitHub Repo URL: {repo_url}",
            f"- Local Repo Path: {local_path}",
            f"- Current Zoho Status: {status}",
            "",
            "## Task Description",
            "",
            description,
            "",
            "## Acceptance Criteria",
            "",
            "- [ ] Acceptance criteria to be confirmed",
            "",
            "## Agent Notes",
            "",
            "- Add implementation notes, assumptions, and validation details here.",
            "",
            "## Deployment Notes",
            "",
            "- [ ] No deployment required yet",
            "- [ ] Deployment approach to be confirmed",
            "",
        ]
    )


def parse_issue_record(data: dict[str, Any]) -> IssueRecord:
    return IssueRecord(
        number=str(data.get("number") or ""),
        url=str(data.get("url") or ""),
        title=str(data.get("title") or ""),
        body=str(data.get("body") or ""),
    )


def issue_markers_match(issue: IssueRecord, task_id: str, task_key: str) -> bool:
    return issue_task_id_marker(task_id) in issue.body and issue_task_key_marker(task_key) in issue.body


def get_project_config() -> dict[str, Any]:
    return {
        "owner": PROJECT_OWNER,
        "number": PROJECT_NUMBER,
        "id": PROJECT_ID,
        "name": PROJECT_NAME,
        "url": PROJECT_URL,
        "status_field_name": PROJECT_STATUS_FIELD_NAME,
        "status_field_id": PROJECT_STATUS_FIELD_ID,
        "status_options": dict(PROJECT_STATUS_OPTIONS),
    }


def load_template(relative_name: str) -> str:
    path = TEMPLATE_DIR / relative_name
    try:
        return path.read_text()
    except OSError as exc:
        raise ApplyBlocked(f"starter template is unreadable: {path}: {exc}") from None


def render_template(relative_name: str, context: dict[str, str]) -> str:
    content = load_template(relative_name)
    for key, value in context.items():
        content = content.replace(f"{{{{{key}}}}}", value)
    return content


def starter_template_context(task: dict[str, Any], decision: Decision, repo_url: str) -> dict[str, str]:
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    description_html = str(task.get("description") or "")
    description = plain_text(description_html) or "No task description was provided."
    status = task_status(task)
    owner = task_owner(task)
    tags = extract_tags(task)
    task_url = str(task.get("url") or task.get("web_url") or task.get("task_url") or "")
    purpose = description[:800]
    marker = f"Zoho Task ID: {decision.task_id}"
    return {
        "TASK_KEY": decision.task_key,
        "TASK_TITLE": decision.title,
        "TASK_ID": decision.task_id,
        "TASK_MARKER": marker,
        "PURPOSE": purpose,
        "TASK_STATUS": status,
        "TASK_OWNER": owner,
        "TASK_TAGS": ", ".join(tags) if tags else "None",
        "TASK_URL": task_url or "Not provided",
        "REPO_URL": repo_url,
        "CANONICAL_REPO_PATH": str(LOCAL_REPO_ROOT / decision.repo_name),
        "GENERATED_AT": generated_at,
        "DESCRIPTION": description,
        "SANITIZED_METADATA_JSON": json.dumps(
            sanitize_metadata(task), indent=2, ensure_ascii=False
        ),
    }


def starter_file_contents(task: dict[str, Any], decision: Decision, repo_url: str) -> dict[str, str]:
    context = starter_template_context(task, decision, repo_url)
    return {
        "README.md": render_template("README.md.tmpl", context),
        "TASK.md": render_template("TASK.md.tmpl", context),
        "AGENTS.md": render_template("AGENTS.md.tmpl", context),
        "docs/CURRENT_HANDOFF.md": render_template("docs/CURRENT_HANDOFF.md.tmpl", context),
        ".gitignore": load_template(".gitignore.tmpl"),
        ".github/ISSUE_TEMPLATE/zoho-task.md": render_template(
            ".github/ISSUE_TEMPLATE/zoho-task.md.tmpl", context
        ),
        ".github/PULL_REQUEST_TEMPLATE.md": render_template(
            ".github/PULL_REQUEST_TEMPLATE.md.tmpl", context
        ),
        "docs/.gitkeep": "",
        "scripts/.gitkeep": "",
        "artifacts/.gitkeep": "",
    }


def run_process(command: list[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env={**os.environ, "GH_PROMPT_DISABLED": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ApplyBlocked(f"command could not complete: {command[0]}: {exc}") from None


def require_command_success(result: subprocess.CompletedProcess[str], operation: str) -> None:
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout).strip().splitlines()
    reason = detail[-1] if detail else f"exit {result.returncode}"
    raise ApplyBlocked(f"{operation} failed: {redact(reason)}")


def run_gh_json(arguments: list[str], operation: str, timeout: int = 30) -> list[dict[str, Any]] | dict[str, Any]:
    result = run_gh(arguments, timeout=timeout)
    if result is None:
        raise ApplyBlocked(f"{operation} did not complete")
    require_command_success(result, operation)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ApplyBlocked(f"{operation} returned invalid JSON") from None
    if not isinstance(data, (list, dict)):
        raise ApplyBlocked(f"{operation} returned an unexpected response")
    return data


def list_repo_issues(repo_name: str) -> list[IssueRecord]:
    data = run_gh_json(
        [
            "issue",
            "list",
            "--repo",
            f"{GITHUB_ORG}/{repo_name}",
            "--state",
            "all",
            "--limit",
            "200",
            "--json",
            "number,title,url,body",
        ],
        "GitHub issue list",
        timeout=60,
    )
    if not isinstance(data, list):
        raise ApplyBlocked("GitHub issue list returned an unexpected response")
    return [parse_issue_record(item) for item in data if isinstance(item, dict)]


def view_repo_issue(repo_name: str, issue_number: str) -> IssueRecord:
    data = run_gh_json(
        [
            "issue",
            "view",
            issue_number,
            "--repo",
            f"{GITHUB_ORG}/{repo_name}",
            "--json",
            "number,title,url,body",
        ],
        "GitHub issue view",
    )
    if not isinstance(data, dict):
        raise ApplyBlocked("GitHub issue view returned an unexpected response")
    return parse_issue_record(data)


def find_existing_issue_by_marker(repo_name: str, task_id: str, task_key: str, issue_title: str) -> IssueRecord | None:
    issues = list_repo_issues(repo_name)
    partial_marker_matches = [
        issue
        for issue in issues
        if (issue_task_id_marker(task_id) in issue.body) != (issue_task_key_marker(task_key) in issue.body)
    ]
    if partial_marker_matches:
        raise ApplyBlocked(
            f"GitHub issue marker is incomplete for {task_key}: #{partial_marker_matches[0].number}"
        )
    marker_matches = [issue for issue in issues if issue_markers_match(issue, task_id, task_key)]
    if len(marker_matches) > 1:
        raise ApplyBlocked(f"multiple GitHub issues match Zoho task marker for {task_key}")
    conflicting_title_matches = [
        issue
        for issue in issues
        if issue.title == issue_title and not issue_markers_match(issue, task_id, task_key)
    ]
    if conflicting_title_matches:
        raise ApplyBlocked(
            f"GitHub issue title already exists with a different Zoho marker: #{conflicting_title_matches[0].number}"
        )
    return marker_matches[0] if marker_matches else None


def verify_mapped_issue(
    repo_name: str,
    task_id: str,
    task_key: str,
    entry: dict[str, str],
    issue_title: str,
) -> IssueRecord:
    issue_number = entry.get("issue_number", "").strip()
    issue_url = entry.get("issue_url", "").strip()
    if not issue_number or not issue_url:
        raise ApplyBlocked("mapping entry has incomplete GitHub issue metadata")
    issue = view_repo_issue(repo_name, issue_number)
    if issue.url != issue_url:
        raise ApplyBlocked("mapped GitHub issue URL does not match the live issue")
    if issue.title != issue_title:
        raise ApplyBlocked("mapped GitHub issue title does not match the expected Zoho task title")
    if not issue_markers_match(issue, task_id, task_key):
        raise ApplyBlocked("mapped GitHub issue marker does not match the Zoho task")
    return issue


def create_github_issue(repo_name: str, title: str, body: str) -> None:
    result = run_gh(
        [
            "issue",
            "create",
            "--repo",
            f"{GITHUB_ORG}/{repo_name}",
            "--title",
            title,
            "--body",
            body,
        ],
        timeout=60,
    )
    if result is None:
        raise ApplyBlocked("GitHub issue creation did not complete")
    require_command_success(result, "GitHub issue creation")


def create_or_verify_issue(
    *,
    task: dict[str, Any],
    decision: Decision,
    env: dict[str, str],
    repo_url: str,
    local_path: Path,
    mapping_entry: dict[str, str] | None,
    allow_create: bool,
) -> tuple[str, IssueRecord | None]:
    issue_title = build_issue_title(decision)
    if mapping_entry and (mapping_entry.get("issue_number") or mapping_entry.get("issue_url")):
        issue = verify_mapped_issue(
            repo_name=decision.repo_name,
            task_id=decision.task_id,
            task_key=decision.task_key,
            entry=mapping_entry,
            issue_title=issue_title,
        )
        return "issue already mapped", issue
    issue = find_existing_issue_by_marker(decision.repo_name, decision.task_id, decision.task_key, issue_title)
    if issue is not None:
        if issue.title != issue_title:
            raise ApplyBlocked("GitHub issue marker exists but the issue title does not match the expected Zoho task title")
        return "issue found by marker", issue
    if not allow_create:
        return "would create issue", None
    issue_body = build_issue_body(task, decision, env, repo_url, local_path)
    create_github_issue(decision.repo_name, issue_title, issue_body)
    issue = find_existing_issue_by_marker(decision.repo_name, decision.task_id, decision.task_key, issue_title)
    if issue is None:
        raise ApplyBlocked("GitHub issue was not found after creation")
    return "issue created", issue


def map_zoho_status_to_project_option(status_name: str) -> tuple[str, str]:
    option_id = PROJECT_STATUS_OPTIONS.get(status_name)
    if not option_id:
        raise ApplyBlocked(f"Zoho status is unmapped for GitHub Project Status: {status_name}")
    return status_name, option_id


def get_issue_node_id(repo_name: str, issue_number: str) -> str:
    data = run_gh_json(
        [
            "issue",
            "view",
            issue_number,
            "--repo",
            f"{GITHUB_ORG}/{repo_name}",
            "--json",
            "id",
        ],
        "GitHub issue node ID lookup",
    )
    if not isinstance(data, dict):
        raise ApplyBlocked("GitHub issue node ID lookup returned an unexpected response")
    issue_node_id = str(data.get("id") or "")
    if not issue_node_id:
        raise ApplyBlocked("GitHub issue node ID lookup returned an empty issue ID")
    return issue_node_id


def parse_project_item_record(node: dict[str, Any]) -> ProjectItemRecord | None:
    content = node.get("content")
    if not isinstance(content, dict):
        return None
    issue_node_id = str(content.get("id") or "")
    issue_number = str(content.get("number") or "")
    issue_url = str(content.get("url") or "")
    field_value = node.get("fieldValueByName")
    status_name = ""
    status_option_id = ""
    if isinstance(field_value, dict):
        status_name = str(field_value.get("name") or "")
        status_option_id = str(field_value.get("optionId") or "")
    return ProjectItemRecord(
        item_id=str(node.get("id") or ""),
        issue_node_id=issue_node_id,
        issue_number=issue_number,
        issue_url=issue_url,
        status_name=status_name,
        status_option_id=status_option_id,
    )


def list_project_items() -> list[ProjectItemRecord]:
    items: list[ProjectItemRecord] = []
    cursor: str | None = None
    while True:
        query = """
query($projectId: ID!, $cursor: String) {
  node(id: $projectId) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        nodes {
          id
          fieldValueByName(name: "Status") {
            ... on ProjectV2ItemFieldSingleSelectValue {
              name
              optionId
            }
          }
          content {
            ... on Issue {
              id
              number
              url
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
""".strip()
        arguments = ["api", "graphql", "-f", f"query={query}", "-F", f"projectId={PROJECT_ID}"]
        if cursor:
            arguments.extend(["-F", f"cursor={cursor}"])
        data = run_gh_json(arguments, "GitHub Project item list", timeout=60)
        if not isinstance(data, dict):
            raise ApplyBlocked("GitHub Project item list returned an unexpected response")
        node = data.get("data", {}).get("node") if isinstance(data.get("data"), dict) else None
        if not isinstance(node, dict):
            raise ApplyBlocked("GitHub Project item list did not return the target project")
        items_data = node.get("items")
        if not isinstance(items_data, dict):
            raise ApplyBlocked("GitHub Project item list did not return project items")
        for item_node in items_data.get("nodes", []):
            if isinstance(item_node, dict):
                record = parse_project_item_record(item_node)
                if record is not None:
                    items.append(record)
        page_info = items_data.get("pageInfo")
        if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
            break
        cursor = str(page_info.get("endCursor") or "")
        if not cursor:
            break
    return items


def find_project_item_for_issue(issue_node_id: str) -> ProjectItemRecord | None:
    matches = [item for item in list_project_items() if item.issue_node_id == issue_node_id]
    if len(matches) > 1:
        raise ApplyBlocked("multiple GitHub Project items match the GitHub issue")
    return matches[0] if matches else None


def add_issue_to_project(issue_node_id: str) -> str:
    query = """
mutation($projectId: ID!, $contentId: ID!) {
  addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
    item {
      id
    }
  }
}
""".strip()
    data = run_gh_json(
        [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"projectId={PROJECT_ID}",
            "-F",
            f"contentId={issue_node_id}",
        ],
        "GitHub Project item creation",
        timeout=60,
    )
    if not isinstance(data, dict):
        raise ApplyBlocked("GitHub Project item creation returned an unexpected response")
    item = (
        data.get("data", {})
        .get("addProjectV2ItemById", {})
        .get("item")
        if isinstance(data.get("data"), dict)
        else None
    )
    if not isinstance(item, dict):
        raise ApplyBlocked("GitHub Project item creation did not return a project item")
    item_id = str(item.get("id") or "")
    if not item_id:
        raise ApplyBlocked("GitHub Project item creation returned an empty item ID")
    return item_id


def set_project_status(item_id: str, option_id: str) -> bool:
    existing = next((item for item in list_project_items() if item.item_id == item_id), None)
    if existing is not None and existing.status_option_id == option_id:
        return False
    query = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(
    input: {
      projectId: $projectId
      itemId: $itemId
      fieldId: $fieldId
      value: { singleSelectOptionId: $optionId }
    }
  ) {
    projectV2Item {
      id
    }
  }
}
""".strip()
    run_gh_json(
        [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"projectId={PROJECT_ID}",
            "-F",
            f"itemId={item_id}",
            "-F",
            f"fieldId={PROJECT_STATUS_FIELD_ID}",
            "-F",
            f"optionId={option_id}",
        ],
        "GitHub Project status update",
        timeout=60,
    )
    return True


def github_repo_details(repo_name: str) -> dict[str, Any] | None:
    result = run_gh(["repo", "view", f"{GITHUB_ORG}/{repo_name}", "--json", "name,url,isPrivate"])
    if result is None:
        raise ApplyBlocked("GitHub repository verification did not complete")
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise ApplyBlocked("GitHub repository verification returned invalid JSON") from None
        if not isinstance(data, dict):
            raise ApplyBlocked("GitHub repository verification returned an unexpected response")
        return data
    combined = f"{result.stderr}\n{result.stdout}".lower()
    if "could not resolve to a repository" in combined or "not found" in combined or "could not resolve" in combined:
        return None
    raise ApplyBlocked("GitHub repository verification returned an unclassified error")


def verify_private_repo(repo_name: str) -> tuple[bool, str]:
    details = github_repo_details(repo_name)
    if details is None:
        return False, ""
    if details.get("isPrivate") is not True:
        raise ApplyBlocked(f"existing GitHub repository is not private: {GITHUB_ORG}/{repo_name}")
    found_name = str(details.get("name") or "")
    if found_name.lower() != repo_name.lower():
        raise ApplyBlocked(f"GitHub repository name mismatch: expected {repo_name}, found {found_name}")
    repo_url = str(details.get("url") or f"https://github.com/{GITHUB_ORG}/{repo_name}")
    return True, repo_url


def verify_resume_candidate(task: dict[str, Any], decision: Decision) -> None:
    local_path = LOCAL_REPO_ROOT / decision.repo_name
    if local_path.exists():
        if local_path.is_symlink() or not local_path.is_dir():
            raise ApplyBlocked(f"local repository path is not a safe directory: {local_path}")
        identity_files = (local_path / "TASK.md", local_path / "README.md")
        if not any(path.is_file() and decision.task_id in path.read_text(errors="replace") for path in identity_files):
            raise ApplyBlocked("existing local repository cannot be verified as the approved Zoho task")
    exists, _ = verify_private_repo(decision.repo_name)
    if not local_path.exists() and not exists:
        raise ApplyBlocked("existing-state decision has no verifiable local or GitHub repository")
    if APPROVAL_TAG not in extract_tags(task):
        raise ApplyBlocked(f"task no longer has required tag {APPROVAL_TAG}")


def classify_existing_apply_state(task: dict[str, Any], decision: Decision) -> str:
    verify_resume_candidate(task, decision)
    return "resume"


def verify_existing_repo_files(local_path: Path) -> None:
    minimal_missing = [
        relative_name
        for relative_name in MINIMAL_REQUIRED_COORDINATION_FILES
        if not (local_path / relative_name).is_file()
    ]
    if not minimal_missing:
        return
    legacy_missing = [
        relative_name
        for relative_name in LEGACY_REQUIRED_COORDINATION_FILES
        if not (local_path / relative_name).is_file()
    ]
    if not legacy_missing:
        return
    raise ApplyBlocked(
        "existing repository is missing required AI coordination files for both the minimal and legacy starter packages: "
        + "minimal missing ["
        + ", ".join(minimal_missing)
        + "]; legacy missing ["
        + ", ".join(legacy_missing)
        + "]"
    )


def ensure_local_files(local_path: Path, task: dict[str, Any], decision: Decision, repo_url: str) -> None:
    if local_path.exists() and (local_path.is_symlink() or not local_path.is_dir()):
        raise ApplyBlocked(f"refusing unsafe local repository path: {local_path}")
    local_path.mkdir(mode=0o700, parents=False, exist_ok=True)
    contents = starter_file_contents(task, decision, repo_url)
    preserve_if_present = {
        ".github/ISSUE_TEMPLATE/zoho-task.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
    }
    for relative_name, content in contents.items():
        path = local_path / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise ApplyBlocked(f"refusing to replace non-regular file: {path}")
            existing = path.read_text(errors="replace")
            if relative_name == ".gitignore":
                if existing != content:
                    raise ApplyBlocked(f"existing file differs; refusing overwrite: {path}")
            elif relative_name.endswith(".gitkeep"):
                continue
            elif relative_name in preserve_if_present:
                continue
            elif decision.task_id not in existing:
                raise ApplyBlocked(f"existing file lacks approved task identity; refusing overwrite: {path}")
            continue
        path.write_text(content)


def ensure_git_repository(local_path: Path) -> None:
    git_dir = local_path / ".git"
    if git_dir.exists() and (git_dir.is_symlink() or not git_dir.is_dir()):
        raise ApplyBlocked("existing .git path is unsafe")
    if not git_dir.exists():
        result = run_process(["git", "init", "-b", "main"], local_path)
        require_command_success(result, "git init")
    result = run_process(["git", "branch", "-M", "main"], local_path)
    require_command_success(result, "set main branch")


def ensure_github_repository(repo_name: str) -> str:
    exists, repo_url = verify_private_repo(repo_name)
    if not exists:
        result = run_gh(["repo", "create", f"{GITHUB_ORG}/{repo_name}", "--private"], timeout=60)
        if result is None:
            raise ApplyBlocked("GitHub repository creation did not complete")
        require_command_success(result, "private GitHub repository creation")
        exists, repo_url = verify_private_repo(repo_name)
        if not exists:
            raise ApplyBlocked("GitHub repository was not found after creation")
    return repo_url


def normalize_remote_url(value: str) -> str:
    normalized = value.strip().removesuffix(".git").lower()
    normalized = normalized.replace("git@github.com:", "https://github.com/")
    return normalized


def ensure_origin(local_path: Path, repo_name: str) -> None:
    expected = f"https://github.com/{GITHUB_ORG}/{repo_name}.git"
    current = run_process(["git", "remote", "get-url", "origin"], local_path)
    if current.returncode == 0:
        if normalize_remote_url(current.stdout) != normalize_remote_url(expected):
            raise ApplyBlocked("existing origin remote does not match the approved repository")
        return
    result = run_process(["git", "remote", "add", "origin", expected], local_path)
    require_command_success(result, "add origin remote")


def commit_and_push(local_path: Path, task_key: str) -> None:
    paths = [
        "README.md",
        "TASK.md",
        "STATUS.md",
        "AGENTS.md",
        "CLAUDE.md",
        "CODEX.md",
        ".gitignore",
        ".github",
        "docs",
        "scripts",
        "artifacts",
    ]
    result = run_process(["git", "add", "--", *paths], local_path)
    require_command_success(result, "git add starter files")
    staged = run_process(["git", "diff", "--cached", "--quiet"], local_path)
    if staged.returncode not in (0, 1):
        require_command_success(staged, "inspect staged changes")
    if staged.returncode == 1:
        result = run_process(["git", "commit", "-m", f"Initialize repository for {task_key}"], local_path)
        require_command_success(result, "initial commit")
    result = run_process(["git", "push", "-u", "origin", "main"], local_path, timeout=120)
    require_command_success(result, "initial push")


def write_task_mapping(task: dict[str, Any], decision: Decision, repo_url: str, local_path: Path) -> bool:
    mapping_path = PROJECT_DIR / "task_repo_map.json"
    if mapping_path.exists():
        try:
            with mapping_path.open() as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ApplyBlocked(f"task_repo_map.json is unreadable: {exc}") from None
    else:
        data = {"mappings": []}
    if not isinstance(data, dict) or not isinstance(data.get("mappings"), list):
        raise ApplyBlocked("task_repo_map.json has an unsupported structure")
    mappings = data["mappings"]
    expected = {
        "task_id": decision.task_id,
        "task_key": decision.task_key,
        "title": decision.title,
        "repo_name": decision.repo_name,
        "repo_url": repo_url,
        "local_path": str(local_path),
    }
    for entry in mappings:
        if not isinstance(entry, dict):
            continue
        same_task = str(entry.get("task_id") or "") == decision.task_id or str(entry.get("task_key") or "").upper() == decision.task_key
        same_repo = str(entry.get("repo_name") or "").lower() == decision.repo_name.lower()
        if same_task or same_repo:
            for key, value in expected.items():
                if str(entry.get(key) or "") != value:
                    raise ApplyBlocked(f"existing task_repo_map.json entry conflicts on {key}")
            return False
    mappings.append({**expected, "created_at": datetime.now().astimezone().isoformat(timespec="seconds")})
    temporary = mapping_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, mapping_path)
    return True


def update_mapping_with_issue(
    task: dict[str, Any],
    decision: Decision,
    repo_url: str,
    local_path: Path,
    issue: IssueRecord,
) -> bool:
    mapping_path = PROJECT_DIR / "task_repo_map.json"
    if not mapping_path.exists():
        raise ApplyBlocked("task_repo_map.json is missing before GitHub issue update")
    try:
        with mapping_path.open() as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ApplyBlocked(f"task_repo_map.json is unreadable: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("mappings"), list):
        raise ApplyBlocked("task_repo_map.json has an unsupported structure")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    expected = {
        "task_id": decision.task_id,
        "task_key": decision.task_key,
        "title": decision.title,
        "repo_name": decision.repo_name,
        "repo_url": repo_url,
        "local_path": str(local_path),
    }
    for entry in data["mappings"]:
        if not isinstance(entry, dict):
            continue
        same_task = str(entry.get("task_id") or "") == decision.task_id or str(entry.get("task_key") or "").upper() == decision.task_key
        same_repo = str(entry.get("repo_name") or "").lower() == decision.repo_name.lower()
        if not (same_task or same_repo):
            continue
        for key, value in expected.items():
            if str(entry.get(key) or "") != value:
                raise ApplyBlocked(f"existing task_repo_map.json entry conflicts on {key}")
        existing_number = str(entry.get("issue_number") or "")
        existing_url = str(entry.get("issue_url") or "")
        if existing_number and existing_number != issue.number:
            raise ApplyBlocked("existing task_repo_map.json issue_number conflicts with the verified GitHub issue")
        if existing_url and existing_url != issue.url:
            raise ApplyBlocked("existing task_repo_map.json issue_url conflicts with the verified GitHub issue")
        changed = existing_number != issue.number or existing_url != issue.url
        entry["issue_number"] = issue.number
        entry["issue_url"] = issue.url
        if not str(entry.get("issue_created_at") or ""):
            entry["issue_created_at"] = now
        else:
            entry["issue_updated_at"] = now
        temporary = mapping_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, mapping_path)
        return changed
    raise ApplyBlocked("task_repo_map.json entry was not found for GitHub issue update")


def update_mapping_with_project(
    task: dict[str, Any],
    decision: Decision,
    repo_url: str,
    local_path: Path,
    issue: IssueRecord,
    project_item: ProjectItemRecord,
) -> bool:
    mapping_path = PROJECT_DIR / "task_repo_map.json"
    if not mapping_path.exists():
        raise ApplyBlocked("task_repo_map.json is missing before GitHub Project update")
    try:
        with mapping_path.open() as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ApplyBlocked(f"task_repo_map.json is unreadable: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("mappings"), list):
        raise ApplyBlocked("task_repo_map.json has an unsupported structure")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    zoho_status = task_status(task)
    _, option_id = map_zoho_status_to_project_option(zoho_status)
    expected = {
        "task_id": decision.task_id,
        "task_key": decision.task_key,
        "title": decision.title,
        "repo_name": decision.repo_name,
        "repo_url": repo_url,
        "local_path": str(local_path),
        "issue_number": issue.number,
        "issue_url": issue.url,
    }
    for entry in data["mappings"]:
        if not isinstance(entry, dict):
            continue
        same_task = str(entry.get("task_id") or "") == decision.task_id or str(entry.get("task_key") or "").upper() == decision.task_key
        same_repo = str(entry.get("repo_name") or "").lower() == decision.repo_name.lower()
        if not (same_task or same_repo):
            continue
        for key, value in expected.items():
            if str(entry.get(key) or "") != value:
                raise ApplyBlocked(f"existing task_repo_map.json entry conflicts on {key}")
        if str(entry.get("project_id") or "") and str(entry.get("project_id")) != PROJECT_ID:
            raise ApplyBlocked("existing task_repo_map.json project_id conflicts with the configured GitHub Project")
        if str(entry.get("project_item_id") or "") and str(entry.get("project_item_id")) != project_item.item_id:
            raise ApplyBlocked("existing task_repo_map.json project_item_id conflicts with the verified GitHub Project item")
        changed = any(
            [
                str(entry.get("project_id") or "") != PROJECT_ID,
                str(entry.get("project_number") or "") != str(PROJECT_NUMBER),
                str(entry.get("project_url") or "") != PROJECT_URL,
                str(entry.get("project_item_id") or "") != project_item.item_id,
                str(entry.get("project_status_field_id") or "") != PROJECT_STATUS_FIELD_ID,
                str(entry.get("project_status_option_id") or "") != option_id,
                str(entry.get("zoho_status_at_last_sync") or "") != zoho_status,
            ]
        )
        entry["project_id"] = PROJECT_ID
        entry["project_number"] = str(PROJECT_NUMBER)
        entry["project_url"] = PROJECT_URL
        entry["project_item_id"] = project_item.item_id
        entry["project_status_field_id"] = PROJECT_STATUS_FIELD_ID
        entry["project_status_option_id"] = option_id
        entry["zoho_status_at_last_sync"] = zoho_status
        entry["project_synced_at"] = now
        temporary = mapping_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, mapping_path)
        return changed
    raise ApplyBlocked("task_repo_map.json entry was not found for GitHub Project update")


def create_or_verify_project_item(
    *,
    task: dict[str, Any],
    decision: Decision,
    issue: IssueRecord,
    mapping_entry: dict[str, str] | None,
    allow_create: bool,
) -> tuple[str, str, ProjectItemRecord | None]:
    project_config = get_project_config()
    zoho_status = task_status(task)
    _, option_id = map_zoho_status_to_project_option(zoho_status)
    issue_node_id = get_issue_node_id(decision.repo_name, issue.number)
    if mapping_entry and mapping_entry.get("project_item_id"):
        project_item = find_project_item_for_issue(issue_node_id)
        if project_item is None:
            raise ApplyBlocked("mapped GitHub Project item was not found for the verified GitHub issue")
        if project_item.item_id != str(mapping_entry.get("project_item_id") or ""):
            raise ApplyBlocked("mapped GitHub Project item ID does not match the verified project item")
        if str(mapping_entry.get("project_id") or project_config["id"]) != project_config["id"]:
            raise ApplyBlocked("mapped GitHub Project ID does not match the configured project")
        if str(mapping_entry.get("project_number") or project_config["number"]) != str(project_config["number"]):
            raise ApplyBlocked("mapped GitHub Project number does not match the configured project")
        status_action = "would set/update status"
        if project_item.status_option_id == option_id:
            status_action = "project status already matched"
        return "project item already mapped", status_action, project_item
    project_item = find_project_item_for_issue(issue_node_id)
    if project_item is not None:
        status_action = "would set/update status"
        if project_item.status_option_id == option_id:
            status_action = "project status already matched"
        return "project item found/verified", status_action, project_item
    if not allow_create:
        return "would add issue to project", "would set/update status", None
    item_id = add_issue_to_project(issue_node_id)
    project_item = find_project_item_for_issue(issue_node_id)
    if project_item is None:
        project_item = ProjectItemRecord(
            item_id=item_id,
            issue_node_id=issue_node_id,
            issue_number=issue.number,
            issue_url=issue.url,
            status_name="",
            status_option_id="",
        )
    return "project item created", "would set/update status", project_item


def post_zoho_comment(env: dict[str, str], token: str, task_id: str, repo_url: str) -> bool:
    comment = f"GitHub repo created: {repo_url}"
    existing = fetch_comments(env, token, task_id)
    if any(comment in plain_text(str(item.get("content") or "")) for item in existing):
        return False
    portal_id = urllib.parse.quote(env["ZOHO_PROJECTS_PORTAL_ID"], safe="")
    project_id = urllib.parse.quote(env["ZOHO_PROJECT_ID"], safe="")
    safe_task_id = urllib.parse.quote(task_id, safe="")
    url = (
        f"https://projectsapi.zoho.com/restapi/portal/{portal_id}/projects/{project_id}"
        f"/tasks/{safe_task_id}/comments/"
    )
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode({"content": comment}).encode(),
        method="POST",
    )
    request.add_header("Authorization", f"Zoho-oauthtoken {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise ApplyBlocked(f"Zoho comment write HTTP {exc.code}: {safe_json_error(body, 'request failed')}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApplyBlocked(f"Zoho comment write failed: {exc}") from None
    return True


def apply_one_task(
    report: Report,
    env: dict[str, str],
    token: str,
    task: dict[str, Any],
    decision: Decision,
) -> None:
    if APPROVAL_TAG not in extract_tags(task):
        raise ApplyBlocked(f"task no longer has exact tag {APPROVAL_TAG}")
    if decision.action == "blocked":
        raise ApplyBlocked(f"dry-run eligibility is blocked: {decision.reason}")
    local_path = LOCAL_REPO_ROOT / decision.repo_name
    provisional_url = f"https://github.com/{GITHUB_ORG}/{decision.repo_name}"
    if decision.action == "existing":
        classify_existing_apply_state(task, decision)
        verify_existing_repo_files(local_path)
        report.add("WARN", "M. Apply execution", "verified partial existing state; continuing idempotent resume")
        report.add("SUCCESS", "M. Apply execution", f"existing coordination files verified at {local_path}")
    elif decision.action != "would-create":
        raise ApplyBlocked(f"unsupported apply decision: {decision.action}")
    else:
        ensure_local_files(local_path, task, decision, provisional_url)
        report.add("SUCCESS", "M. Apply execution", f"local starter files verified at {local_path}")
    ensure_git_repository(local_path)
    report.add("SUCCESS", "M. Apply execution", "local Git repository initialized or verified on main")
    repo_url = ensure_github_repository(decision.repo_name)
    report.add("SUCCESS", "M. Apply execution", f"private GitHub repository verified: {repo_url}")
    ensure_origin(local_path, decision.repo_name)
    report.add("SUCCESS", "M. Apply execution", "origin remote verified")
    commit_and_push(local_path, decision.task_key)
    report.add("SUCCESS", "M. Apply execution", "starter files committed and main pushed")
    mapping_written = write_task_mapping(task, decision, repo_url, local_path)
    mapping_action = "written" if mapping_written else "already present and verified"
    report.add("SUCCESS", "M. Apply execution", f"task_repo_map.json {mapping_action}")
    mapping_entry = mapping_entry_for_task(mapping_entries()[0], decision.task_id, decision.task_key, decision.repo_name)
    issue_action, issue = create_or_verify_issue(
        task=task,
        decision=decision,
        env=env,
        repo_url=repo_url,
        local_path=local_path,
        mapping_entry=mapping_entry,
        allow_create=True,
    )
    if issue is None:
        raise ApplyBlocked("GitHub issue verification did not produce issue metadata")
    issue_mapping_written = update_mapping_with_issue(task, decision, repo_url, local_path, issue)
    issue_mapping_action = "updated" if issue_mapping_written else "already present and verified"
    report.add("SUCCESS", "M. Apply execution", f"{issue_action}: {issue.url}")
    report.add("SUCCESS", "M. Apply execution", f"task_repo_map.json issue metadata {issue_mapping_action}")
    mapping_entry = mapping_entry_for_task(mapping_entries()[0], decision.task_id, decision.task_key, decision.repo_name)
    project_item_action, project_status_action, project_item = create_or_verify_project_item(
        task=task,
        decision=decision,
        issue=issue,
        mapping_entry=mapping_entry,
        allow_create=True,
    )
    if project_item is None:
        raise ApplyBlocked("GitHub Project verification did not produce project item metadata")
    _, option_id = map_zoho_status_to_project_option(task_status(task))
    project_status_updated = set_project_status(project_item.item_id, option_id)
    project_mapping_written = update_mapping_with_project(
        task,
        decision,
        repo_url,
        local_path,
        issue,
        project_item,
    )
    project_mapping_action = "updated" if project_mapping_written else "already present and verified"
    status_result = "updated" if project_status_updated else "already matched"
    report.add("SUCCESS", "M. Apply execution", f"{project_item_action}: {PROJECT_URL}")
    report.add("SUCCESS", "M. Apply execution", f"{project_status_action}: {task_status(task)} ({status_result})")
    report.add("SUCCESS", "M. Apply execution", f"task_repo_map.json project metadata {project_mapping_action}")
    comment_written = post_zoho_comment(env, token, decision.task_id, repo_url)
    comment_action = "written" if comment_written else "already present and verified"
    report.add("SUCCESS", "M. Apply execution", f"Zoho repository comment {comment_action}")


def write_report(report: Report) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_kind = "apply" if report.mode == "apply" else "dry_run"
    path = REPORT_DIR / f"repo_lifecycle_{report_kind}_{report.timestamp.strftime('%Y-%m-%d')}.md"
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text("\n".join(report.lines(path)) + "\n")
    os.replace(temporary, path)
    return path


def load_zoho_read_result() -> ZohoReadResult:
    findings: list[tuple[str, str]] = []
    try:
        env, env_names = load_env_file(SOURCE_ENV_FILE)
    except OSError as exc:
        findings.append(("ERROR", f"could not read source env file: {exc}"))
        env = {}
        env_names = set()
    findings.append(
        (
            "INFO",
            f"source env variable names present: {', '.join(sorted(env_names)) or 'none'}; values not printed",
        )
    )
    missing_env = sorted(name for name in REQUIRED_ENV_NAMES if not env.get(name))
    if missing_env:
        findings.append(
            ("ERROR", f"missing required env variable names or values: {', '.join(missing_env)}")
        )
        return ZohoReadResult(env=env, env_names=env_names, findings=findings)

    try:
        token = cached_access_token()
        token_source = "existing status-poller cache" if token else "OAuth refresh response held in memory only"
        if token is None:
            token = refresh_access_token(env)
        tasks = fetch_tasks(env, token)
        total_tasks = len(tasks)
        tagged_tasks = [task for task in tasks if APPROVAL_TAG in extract_tags(task)]
        untagged_count = total_tasks - len(tagged_tasks)
        findings.append(
            ("SUCCESS", f"Zoho read succeeded using {token_source}; {total_tasks} task(s) returned")
        )
        return ZohoReadResult(
            env=env,
            env_names=env_names,
            findings=findings,
            total_tasks=total_tasks,
            tagged_tasks=tagged_tasks,
            untagged_count=untagged_count,
            token=token,
        )
    except RuntimeError as exc:
        findings.append(("ERROR", str(exc)))
        return ZohoReadResult(env=env, env_names=env_names, findings=findings)


def load_github_read_result() -> GitHubReadResult:
    gh_state, gh_reason = github_auth_state()
    gh_label = "SUCCESS" if gh_state == "ready" else ("SKIPPED" if gh_state == "unavailable" else "BLOCKED")
    return GitHubReadResult(findings=[(gh_label, gh_reason)], state=gh_state)


def load_mapping_read_result() -> MappingReadResult:
    findings: list[tuple[str, str]] = []
    try:
        mappings, mapping_sources = mapping_entries()
        if mapping_sources:
            findings.append(
                (
                    "INFO",
                    f"loaded mapping evidence from: {', '.join(str(path) for path in mapping_sources)}",
                )
            )
        else:
            findings.append(("INFO", "no task_repo_map.json exists in the approved candidate locations"))
        return MappingReadResult(entries=mappings, findings=findings)
    except RuntimeError as exc:
        findings.append(("BLOCKED", str(exc)))
        return MappingReadResult(entries=[], findings=findings)


def evaluate_task_decision(
    task: dict[str, Any],
    mappings: list[dict[str, str]],
    local_repos: dict[str, Path],
    github_state: str,
    env: dict[str, str],
    token: str | None,
) -> tuple[Decision, int]:
    task_id = str(task.get("id") or task.get("id_string") or "").strip()
    task_key = extract_task_key(task)
    title = str(task.get("name") or task.get("title") or "").strip()
    missing: list[str] = []
    if not re.fullmatch(r"BI1-T\d+", task_key):
        missing.append("valid task key")
    if not title or title.lower() == "untitled zoho task":
        missing.append("title")
    if not task_id or not task_id.isdigit():
        missing.append("immutable Zoho task ID")
    repo_name = expected_repo_name(task_key, title) if not missing else ""
    if missing:
        return (
            Decision(
                task_id=task_id,
                task_key=task_key,
                title=title,
                repo_name=repo_name,
                action="blocked",
                reason="missing required metadata",
                missing_metadata=missing,
            ),
            0,
        )

    evidence: list[str] = []
    conflicts: list[str] = []
    local = local_repos.get(repo_name.lower())
    if local:
        evidence.append(f"local path {local}")

    mapped, mapping_conflicts = mapping_evidence(mappings, task_id, task_key, repo_name)
    evidence.extend(mapped)
    conflicts.extend(mapping_conflicts)

    text_sources = [str(task.get("description") or "")]
    try:
        comments = fetch_comments(env, token, task_id)
        text_sources.extend(str(comment.get("content") or "") for comment in comments)
    except RuntimeError as exc:
        return (
            Decision(
                task_id=task_id,
                task_key=task_key,
                title=title,
                repo_name=repo_name,
                action="blocked",
                reason=f"Zoho comments could not be checked: {exc}",
            ),
            0,
        )
    zoho_urls = [url for text in text_sources for url in github_urls_from_text(text)]
    for org, found_repo, url in zoho_urls:
        if org.lower() == GITHUB_ORG.lower() and found_repo.lower() == repo_name.lower():
            evidence.append(f"Zoho task repository URL {url}")
        else:
            conflicts.append(f"Zoho task references {url}")

    if github_state == "ready":
        repo_state, repo_reason = github_repo_state(repo_name)
        if repo_state == "exists":
            evidence.append(repo_reason)
        elif repo_state == "blocked":
            return (
                Decision(
                    task_id=task_id,
                    task_key=task_key,
                    title=title,
                    repo_name=repo_name,
                    action="blocked",
                    reason=repo_reason,
                ),
                1,
            )
        github_checks = 1
    elif github_state == "blocked":
        return (
            Decision(
                task_id=task_id,
                task_key=task_key,
                title=title,
                repo_name=repo_name,
                action="blocked",
                reason="GitHub existence check could not run",
            ),
            0,
        )
    else:
        github_checks = 0

    if conflicts:
        return (
            Decision(
                task_id=task_id,
                task_key=task_key,
                title=title,
                repo_name=repo_name,
                action="blocked",
                reason="; ".join(conflicts),
            ),
            github_checks,
        )
    if evidence:
        return (
            Decision(
                task_id=task_id,
                task_key=task_key,
                title=title,
                repo_name=repo_name,
                action="existing",
                reason="; ".join(evidence),
            ),
            github_checks,
        )
    return (
        Decision(
            task_id=task_id,
            task_key=task_key,
            title=title,
            repo_name=repo_name,
            action="would-create",
            reason="all available duplicate checks are clear",
        ),
        github_checks,
    )


def build_decisions(
    tagged_tasks: list[dict[str, Any]],
    mappings: list[dict[str, str]],
    local_repos: dict[str, Path],
    github_state: str,
    env: dict[str, str],
    token: str | None,
) -> tuple[list[Decision], int, int]:
    decisions: list[Decision] = []
    comments_checked = 0
    github_checks = 0
    for task in tagged_tasks:
        decision, task_github_checks = evaluate_task_decision(
            task=task,
            mappings=mappings,
            local_repos=local_repos,
            github_state=github_state,
            env=env,
            token=token,
        )
        decisions.append(decision)
        github_checks += task_github_checks
        if not decision.reason.startswith("Zoho comments could not be checked:"):
            comments_checked += 1
    return decisions, comments_checked, github_checks


def group_decisions(decisions: list[Decision]) -> DecisionGroups:
    would_create = [decision for decision in decisions if decision.action == "would-create"]
    existing = [decision for decision in decisions if decision.action == "existing"]
    blocked = [decision for decision in decisions if decision.action == "blocked"]
    missing_metadata = [decision for decision in blocked if decision.missing_metadata]
    return DecisionGroups(
        would_create=would_create,
        existing=existing,
        blocked=blocked,
        missing_metadata=missing_metadata,
    )


def evaluate_issue_actions(
    tagged_tasks: list[dict[str, Any]],
    decisions: list[Decision],
    mappings: list[dict[str, str]],
    env: dict[str, str],
    github_state: str,
) -> list[tuple[str, str]]:
    issue_findings: list[tuple[str, str]] = []
    task_by_key = {extract_task_key(task): task for task in tagged_tasks if extract_task_key(task)}
    for decision in decisions:
        task = task_by_key.get(decision.task_key)
        if task is None:
            issue_findings.append(("BLOCKED", f"{decision.task_key or decision.task_id}: missing Zoho task data for issue planning"))
            continue
        if decision.action == "blocked":
            issue_findings.append(("BLOCKED", f"{decision.task_key}: issue planning blocked because repo preflight is blocked: {decision.reason}"))
            continue
        if decision.action == "would-create":
            issue_findings.append(("INFO", f"{decision.task_key}: would create issue {build_issue_title(decision)} after private repo creation"))
            continue
        if github_state != "ready":
            issue_findings.append(("BLOCKED", f"{decision.task_key}: GitHub issue verification requires authenticated GitHub CLI access"))
            continue
        mapping_entry = mapping_entry_for_task(mappings, decision.task_id, decision.task_key, decision.repo_name)
        repo_url = (
            mapping_entry.get("repo_url", "").strip()
            if mapping_entry is not None
            else f"https://github.com/{GITHUB_ORG}/{decision.repo_name}"
        )
        local_path = Path(
            mapping_entry.get("local_path", str(LOCAL_REPO_ROOT / decision.repo_name))
            if mapping_entry is not None
            else str(LOCAL_REPO_ROOT / decision.repo_name)
        )
        try:
            issue_action, issue = create_or_verify_issue(
                task=task,
                decision=decision,
                env=env,
                repo_url=repo_url,
                local_path=local_path,
                mapping_entry=mapping_entry,
                allow_create=False,
            )
        except ApplyBlocked as exc:
            issue_findings.append(("BLOCKED", f"{decision.task_key}: {exc}"))
            continue
        if issue is None:
            issue_findings.append(("INFO", f"{decision.task_key}: {issue_action}"))
        else:
            label = "SKIPPED" if issue_action == "issue already mapped" else "INFO"
            issue_findings.append((label, f"{decision.task_key}: {issue_action}; {issue.url}"))
    return issue_findings


def evaluate_project_actions(
    tagged_tasks: list[dict[str, Any]],
    decisions: list[Decision],
    mappings: list[dict[str, str]],
    env: dict[str, str],
    github_state: str,
) -> list[tuple[str, str]]:
    project_findings: list[tuple[str, str]] = []
    task_by_key = {extract_task_key(task): task for task in tagged_tasks if extract_task_key(task)}
    for decision in decisions:
        task = task_by_key.get(decision.task_key)
        if task is None:
            project_findings.append(("BLOCKED", f"{decision.task_key or decision.task_id}: missing Zoho task data for project planning"))
            continue
        if decision.action == "blocked":
            project_findings.append(("BLOCKED", f"{decision.task_key}: project planning blocked because repo preflight is blocked: {decision.reason}"))
            continue
        try:
            zoho_status, option_id = map_zoho_status_to_project_option(task_status(task))
        except ApplyBlocked as exc:
            project_findings.append(("BLOCKED", f"{decision.task_key}: {exc}"))
            continue
        if decision.action == "would-create":
            project_findings.append(("INFO", f"{decision.task_key}: would add issue to project {PROJECT_NAME} after GitHub issue creation"))
            project_findings.append(("INFO", f"{decision.task_key}: would set/update status to {zoho_status} ({option_id})"))
            continue
        if github_state != "ready":
            project_findings.append(("BLOCKED", f"{decision.task_key}: GitHub Project planning requires authenticated GitHub CLI access"))
            continue
        mapping_entry = mapping_entry_for_task(mappings, decision.task_id, decision.task_key, decision.repo_name)
        repo_url = (
            mapping_entry.get("repo_url", "").strip()
            if mapping_entry is not None
            else f"https://github.com/{GITHUB_ORG}/{decision.repo_name}"
        )
        local_path = Path(
            mapping_entry.get("local_path", str(LOCAL_REPO_ROOT / decision.repo_name))
            if mapping_entry is not None
            else str(LOCAL_REPO_ROOT / decision.repo_name)
        )
        try:
            issue_action, issue = create_or_verify_issue(
                task=task,
                decision=decision,
                env=env,
                repo_url=repo_url,
                local_path=local_path,
                mapping_entry=mapping_entry,
                allow_create=False,
            )
        except ApplyBlocked as exc:
            project_findings.append(("BLOCKED", f"{decision.task_key}: project planning depends on issue verification: {exc}"))
            continue
        if issue is None:
            project_findings.append(("INFO", f"{decision.task_key}: would add issue to project {PROJECT_NAME} after issue provisioning"))
            project_findings.append(("INFO", f"{decision.task_key}: would set/update status to {zoho_status} ({option_id})"))
            continue
        if mapping_entry and mapping_entry.get("project_item_id"):
            project_findings.append(("SKIPPED", f"{decision.task_key}: project item already mapped; {PROJECT_URL}"))
            project_findings.append(("INFO", f"{decision.task_key}: would set/update status to {zoho_status} ({option_id})"))
            continue
        project_findings.append(("INFO", f"{decision.task_key}: would add issue to project {PROJECT_NAME}"))
        project_findings.append(("INFO", f"{decision.task_key}: would set/update status to {zoho_status} ({option_id})"))
    return project_findings


def find_selected_task_decision(
    tagged_tasks: list[dict[str, Any]],
    decisions: list[Decision],
    selected_task_key: str,
) -> tuple[dict[str, Any] | None, Decision | None]:
    normalized = selected_task_key.upper()
    selected_task = next(
        (task for task in tagged_tasks if extract_task_key(task) == normalized),
        None,
    )
    selected_decision = next(
        (decision for decision in decisions if decision.task_key == normalized),
        None,
    )
    return selected_task, selected_decision


def validate_apply_eligibility(
    *,
    selected_task: dict[str, Any] | None,
    selected_decision: Decision | None,
    selected_task_key: str,
) -> None:
    if selected_task is None:
        raise ApplyBlocked(f"{selected_task_key} is not currently tagged {APPROVAL_TAG}")
    if selected_decision is None:
        raise ApplyBlocked(f"no dry-run decision exists for {selected_task_key}")
    if selected_decision.action == "blocked":
        raise ApplyBlocked(f"dry-run preflight is blocked: {selected_decision.reason}")
    if selected_decision.action == "existing":
        classify_existing_apply_state(selected_task, selected_decision)
        return
    if selected_decision.action != "would-create":
        raise ApplyBlocked(f"apply supports only would-create or safe existing-resume decisions; got {selected_decision.action}")


def add_summary_sections(
    report: Report,
    *,
    total_tasks: int,
    tagged_tasks: list[dict[str, Any]],
    untagged_count: int,
    decision_groups: DecisionGroups,
    mapping_findings: list[tuple[str, str]],
    issue_findings: list[tuple[str, str]],
    project_findings: list[tuple[str, str]],
) -> None:
    report.add("INFO", "A. Summary counts", f"total Zoho tasks: {total_tasks}")
    report.add("INFO", "A. Summary counts", f"tagged repo-needed: {len(tagged_tasks)}")
    report.add("INFO", "A. Summary counts", f"untagged skipped: {untagged_count}")
    report.add(
        "INFO",
        "A. Summary counts",
        f"would create: {len(decision_groups.would_create)}; existing or mapped: {len(decision_groups.existing)}; blocked: {len(decision_groups.blocked)}; missing metadata: {len(decision_groups.missing_metadata)}",
    )

    if tagged_tasks:
        for task in tagged_tasks:
            key = extract_task_key(task) or "missing-key"
            title = str(task.get("name") or task.get("title") or "missing-title").strip()
            report.add("SUCCESS", "B. Tagged repo-needed tasks found", f"{key}: {title}")
    else:
        report.add("INFO", "B. Tagged repo-needed tasks found", "no tasks carry the exact repo-needed tag")

    report.add(
        "SKIPPED",
        "C. Skipped untagged task count",
        f"{untagged_count} task(s) skipped because the exact repo-needed tag is absent",
    )

    if decision_groups.would_create:
        for decision in decision_groups.would_create:
            report.add(
                "INFO",
                "D. Would-create repositories",
                f"would create private repo {GITHUB_ORG}/{decision.repo_name} for {decision.task_key}; dry-run performed no write",
            )
    else:
        report.add("INFO", "D. Would-create repositories", "no repositories would be created by this run")

    if decision_groups.existing:
        for label, message in mapping_findings:
            report.add(label, "E. Existing or mapped repositories", message)
        for decision in decision_groups.existing:
            report.add(
                "SKIPPED",
                "E. Existing or mapped repositories",
                f"{decision.task_key} {decision.repo_name}: repo already exists or is mapped; {decision.reason}",
            )
    else:
        for label, message in mapping_findings:
            report.add(label, "E. Existing or mapped repositories", message)
        report.add(
            "INFO",
            "E. Existing or mapped repositories",
            "no tagged task resolved to existing or mapped repository evidence",
        )

    if issue_findings:
        for label, message in issue_findings:
            report.add(label, "F. GitHub issue actions", message)
    else:
        report.add("INFO", "F. GitHub issue actions", "no GitHub issue actions are applicable for this run")

    if project_findings:
        for label, message in project_findings:
            report.add(label, "G. GitHub Project actions", message)
    else:
        report.add("INFO", "G. GitHub Project actions", "no GitHub Project actions are applicable for this run")

    if decision_groups.blocked:
        for decision in decision_groups.blocked:
            identity = decision.task_key or decision.task_id or "unknown-task"
            report.add("BLOCKED", "H. Blocked tasks", f"{identity}: {decision.reason}")
    else:
        report.add("SUCCESS", "H. Blocked tasks", "no tagged tasks are blocked")

    if decision_groups.missing_metadata:
        for decision in decision_groups.missing_metadata:
            identity = decision.task_key or decision.task_id or "unknown-task"
            report.add("BLOCKED", "I. Missing metadata", f"{identity} missing: {', '.join(decision.missing_metadata)}")
    else:
        report.add(
            "SUCCESS",
            "I. Missing metadata",
            "no tagged tasks are missing required key, title, or immutable ID",
        )


def add_integration_sections(
    report: Report,
    *,
    args: argparse.Namespace,
    github_findings: list[tuple[str, str]],
    github_checks: int,
    zoho_findings: list[tuple[str, str]],
    total_tasks: int,
    comments_checked: int,
) -> None:
    for label, message in github_findings:
        report.add(label, "J. GitHub read-only check result", message)
    github_mode_note = "dry-run used no GitHub write commands" if not args.apply else "apply writes remain confirmation-gated"
    report.add(
        "INFO",
        "J. GitHub read-only check result",
        f"GitHub organization: {GITHUB_ORG}; repo view checks executed: {github_checks}; {github_mode_note}",
    )

    for label, message in zoho_findings:
        report.add(label, "K. Zoho read-only check result", message)
    zoho_mode_note = "no task updates or comments were written" if not args.apply else "write-back remains confirmation-gated"
    report.add(
        "INFO",
        "K. Zoho read-only check result",
        f"task-list reads: {1 if total_tasks else 0}; tagged-task comment reads: {comments_checked}; {zoho_mode_note}",
    )


def execute_apply_mode(
    report: Report,
    *,
    args: argparse.Namespace,
    apply_gate_error: str,
    token: str | None,
    tagged_tasks: list[dict[str, Any]],
    decisions: list[Decision],
    env: dict[str, str],
) -> None:
    report.add(
        "INFO",
        "L. Apply safety",
        "apply mode requires matching --task-key and --confirm-apply values for one eligible repo-needed task from the current Zoho read",
    )
    if apply_gate_error:
        report.add("BLOCKED", "M. Apply execution", apply_gate_error)
        return
    if token is None:
        report.add(
            "BLOCKED",
            "M. Apply execution",
            "Zoho authentication/read preflight did not produce a usable access token",
        )
        return

    selected_task, selected_decision = find_selected_task_decision(
        tagged_tasks=tagged_tasks,
        decisions=decisions,
        selected_task_key=args.task_key,
    )
    try:
        validate_apply_eligibility(
            selected_task=selected_task,
            selected_decision=selected_decision,
            selected_task_key=args.task_key,
        )
    except ApplyBlocked as exc:
        report.add("BLOCKED", "M. Apply execution", str(exc))
        return

    assert selected_decision is not None
    local_path = LOCAL_REPO_ROOT / selected_decision.repo_name
    plan_messages = (
        f"apply plan: create or verify local path {local_path}",
        f"apply plan: create or verify private GitHub repo {GITHUB_ORG}/{selected_decision.repo_name}",
        "apply plan: generate starter files, commit, push, atomically map, then idempotently comment on the Zoho task",
        "shared CLAUDE.md and AGENTS.md template reuse is deferred; safe starter templates will be generated",
    )
    for index, message in enumerate(plan_messages):
        label = "WARN" if index == 3 else "INFO"
        report.add(label, "M. Apply plan", message)
        print(f"[{label}] {message}")
    print(f"[INFO] explicit apply confirmation accepted for {args.task_key}")
    try:
        assert selected_task is not None
        apply_one_task(report, env, token, selected_task, selected_decision)
        report.add("SUCCESS", "M. Apply execution", f"controlled apply completed for {args.task_key}")
    except ApplyBlocked as exc:
        report.add("BLOCKED", "M. Apply execution", str(exc))


def main() -> int:
    args = parse_args()
    install_tls_context()
    report = Report(mode="apply" if args.apply else "dry-run")
    apply_gate_error = validate_apply_gate(args)

    zoho_result = load_zoho_read_result()
    github_result = load_github_read_result()
    mapping_result = load_mapping_read_result()
    local_repos = local_repo_index()

    decisions, comments_checked, github_checks = build_decisions(
        tagged_tasks=zoho_result.tagged_tasks,
        mappings=mapping_result.entries,
        local_repos=local_repos,
        github_state=github_result.state,
        env=zoho_result.env,
        token=zoho_result.token,
    )
    decision_groups = group_decisions(decisions)
    issue_findings = evaluate_issue_actions(
        tagged_tasks=zoho_result.tagged_tasks,
        decisions=decisions,
        mappings=mapping_result.entries,
        env=zoho_result.env,
        github_state=github_result.state,
    )
    project_findings = evaluate_project_actions(
        tagged_tasks=zoho_result.tagged_tasks,
        decisions=decisions,
        mappings=mapping_result.entries,
        env=zoho_result.env,
        github_state=github_result.state,
    )

    add_summary_sections(
        report,
        total_tasks=zoho_result.total_tasks,
        tagged_tasks=zoho_result.tagged_tasks,
        untagged_count=zoho_result.untagged_count,
        decision_groups=decision_groups,
        mapping_findings=mapping_result.findings,
        issue_findings=issue_findings,
        project_findings=project_findings,
    )
    add_integration_sections(
        report,
        args=args,
        github_findings=github_result.findings,
        github_checks=github_checks,
        zoho_findings=zoho_result.findings,
        total_tasks=zoho_result.total_tasks,
        comments_checked=comments_checked,
    )
    if not args.apply:
        report.add("INFO", "L. No-write confirmation", "dry-run mode executed no GitHub create, Git push, Zoho write-back, repository initialization, scheduler edit, or service-control action")
        report.add("SUCCESS", "L. No-write confirmation", "no GitHub repositories, commits, pushes, Zoho comments, Zoho task updates, local repositories, mappings, or scheduler changes were created")
    else:
        execute_apply_mode(
            report,
            args=args,
            apply_gate_error=apply_gate_error,
            token=zoho_result.token,
            tagged_tasks=zoho_result.tagged_tasks,
            decisions=decisions,
            env=zoho_result.env,
        )

    try:
        report_path = write_report(report)
    except OSError as exc:
        report.add("ERROR", "J. No-write confirmation", f"dry-run report could not be written: {exc}")
        for line in report.lines():
            print(line)
        return 3
    for line in report.lines(report_path):
        print(line)
    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main())
