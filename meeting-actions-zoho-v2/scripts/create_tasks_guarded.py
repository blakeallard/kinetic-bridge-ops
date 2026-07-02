#!/usr/bin/env python3
"""Guarded Zoho Projects create-task scaffold.

Default execution is dry-run and never invokes a client. Live execution needs
both ``--live`` and ``LIVE_ZOHO_TASK_CREATE=true``, then preflights the entire
batch before sending only each payload's ``task_parameters`` map.

This stage does not fetch/refresh OAuth tokens, wire Flow or WorkDrive, or
persist registry state.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


LIVE_UNLOCK_ENV = "LIVE_ZOHO_TASK_CREATE"
REQUIRED_STATUS_NAME = "In Progress"
REQUIRED_TAG_NAMES = {
    "automation",
    "internal-work",
    "meeting-action",
    "zoho-ai-generated",
}


class CreateTaskGuardError(RuntimeError):
    """Raised when live execution is not explicitly and completely unlocked."""


class PayloadValidationError(RuntimeError):
    """Raised when any payload fails all-batch live preflight."""


class TaskCreateClientError(RuntimeError):
    """Raised when the configured create-task transport fails."""


class TaskCreateClient(Protocol):
    """Transport boundary used by live execution and fake clients in tests."""

    def create_task(self, task_parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        """Create one task using only its validated task parameter map."""


def _required_environment(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if not isinstance(value, str) or not value.strip():
        raise CreateTaskGuardError(f"live mode requires environment variable {name}")
    return value.strip()


class ZohoProjectsHttpClient:
    """Minimal create-task HTTP client configured exclusively from environment.

    Instantiate only after the two-key guard and full payload preflight pass.
    The client accepts no envelope fields; its request body is exactly the
    validated ``task_parameters`` map after form serialization.
    """

    def __init__(
        self,
        *,
        api_domain: str,
        portal_id: str,
        project_id: str,
        access_token: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        parsed_domain = urllib.parse.urlparse(api_domain)
        if (
            parsed_domain.scheme != "https"
            or not parsed_domain.netloc
            or parsed_domain.username is not None
            or parsed_domain.password is not None
            or parsed_domain.path not in ("", "/")
            or parsed_domain.query
            or parsed_domain.fragment
        ):
            raise CreateTaskGuardError("ZOHO_PROJECTS_API_DOMAIN must be a plain HTTPS origin")
        if not re.fullmatch(r"[0-9]+", portal_id):
            raise CreateTaskGuardError("ZOHO_PROJECTS_PORTAL_ID must contain digits only")
        if not re.fullmatch(r"[0-9]+", project_id):
            raise CreateTaskGuardError("ZOHO_PROJECTS_PROJECT_ID must contain digits only")
        if not access_token:
            raise CreateTaskGuardError("ZOHO_PROJECTS_ACCESS_TOKEN is required")
        if timeout_seconds <= 0:
            raise CreateTaskGuardError("ZOHO_PROJECTS_TIMEOUT_SECONDS must be positive")

        self._api_domain = api_domain.rstrip("/")
        self._portal_id = portal_id
        self._project_id = project_id
        self._access_token = access_token
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
        *,
        expected_portal_id: str,
        expected_project_id: str,
    ) -> "ZohoProjectsHttpClient":
        api_domain = _required_environment(environ, "ZOHO_PROJECTS_API_DOMAIN")
        portal_id = _required_environment(environ, "ZOHO_PROJECTS_PORTAL_ID")
        project_id = _required_environment(environ, "ZOHO_PROJECTS_PROJECT_ID")
        access_token = _required_environment(environ, "ZOHO_PROJECTS_ACCESS_TOKEN")
        if portal_id != expected_portal_id:
            raise CreateTaskGuardError("payload portal_id does not match environment configuration")
        if project_id != expected_project_id:
            raise CreateTaskGuardError("payload project_id does not match environment configuration")
        timeout_raw = environ.get("ZOHO_PROJECTS_TIMEOUT_SECONDS", "30").strip()
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as error:
            raise CreateTaskGuardError(
                "ZOHO_PROJECTS_TIMEOUT_SECONDS must be numeric"
            ) from error
        return cls(
            api_domain=api_domain,
            portal_id=portal_id,
            project_id=project_id,
            access_token=access_token,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _form_value(value: Any) -> str:
        if isinstance(value, (list, dict)):
            return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            raise TaskCreateClientError("task_parameters cannot contain null values")
        return str(value)

    def create_task(self, task_parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        form_fields = {
            key: self._form_value(value) for key, value in task_parameters.items()
        }
        request_body = urllib.parse.urlencode(form_fields).encode("utf-8")
        url = (
            f"{self._api_domain}/restapi/portal/{self._portal_id}"
            f"/projects/{self._project_id}/tasks/"
        )
        request = urllib.request.Request(
            url,
            data=request_body,
            method="POST",
            headers={
                "Authorization": f"Zoho-oauthtoken {self._access_token}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                response_text = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            response_text = error.read().decode("utf-8", errors="replace")
            raise TaskCreateClientError(
                f"Zoho Projects create-task request failed with HTTP {error.code}: "
                f"{response_text[:1000]}"
            ) from error
        except urllib.error.URLError as error:
            raise TaskCreateClientError(
                f"Zoho Projects create-task transport failed: {error.reason}"
            ) from error

        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError as error:
            raise TaskCreateClientError(
                "Zoho Projects create-task response was not valid JSON"
            ) from error
        if not isinstance(parsed, Mapping):
            raise TaskCreateClientError("Zoho Projects create-task response must be a map")
        return dict(parsed)


def _payloads_from_report(registry_report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if not isinstance(registry_report, Mapping):
        raise PayloadValidationError("registry report must be a map")
    payloads = registry_report.get("payloads_that_would_be_created")
    if not isinstance(payloads, list):
        raise PayloadValidationError(
            "registry report payloads_that_would_be_created must be a list"
        )
    for payload in payloads:
        if not isinstance(payload, Mapping):
            raise PayloadValidationError("every task payload must be a map")
    return payloads


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _numeric_id(value: Any) -> bool:
    return _nonempty_text(value) and bool(re.fullmatch(r"[0-9]+", value.strip()))


def _payload_live_errors(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    validation = payload.get("validation")
    if not isinstance(validation, Mapping):
        return ["validation must be a map"]
    if validation.get("ready_for_live") is not True:
        errors.append("validation.ready_for_live must be true")
    if validation.get("missing_status_id") is not False:
        errors.append("validation.missing_status_id must be false")
    missing_tag_ids = validation.get("missing_tag_ids")
    if not isinstance(missing_tag_ids, list):
        errors.append("validation.missing_tag_ids must be a list")
    elif missing_tag_ids:
        errors.append("validation.missing_tag_ids must be empty")

    status = payload.get("status")
    status_id: str | None = None
    if not isinstance(status, Mapping):
        errors.append("status must be a map")
    else:
        if status.get("name") != REQUIRED_STATUS_NAME:
            errors.append(f"status.name must be {REQUIRED_STATUS_NAME}")
        if not _numeric_id(status.get("id")):
            errors.append("status.id must be a verified numeric ID")
        else:
            status_id = status["id"].strip()
        if status.get("verified") is not True:
            errors.append("status.verified must be true")

    tags = payload.get("tags")
    verified_tag_ids: list[str] = []
    tag_names: set[str] = set()
    if not isinstance(tags, list):
        errors.append("tags must be a list")
    else:
        for tag in tags:
            if not isinstance(tag, Mapping):
                errors.append("every tag must be a map")
                continue
            tag_name = tag.get("name")
            tag_id = tag.get("id")
            if _nonempty_text(tag_name):
                tag_names.add(tag_name.strip())
            if not _numeric_id(tag_id):
                errors.append(f"tag ID is missing for {tag_name!r}")
            else:
                verified_tag_ids.append(tag_id.strip())
        if tag_names != REQUIRED_TAG_NAMES:
            errors.append("tags must contain exactly the four required tag names")

    task_parameters = payload.get("task_parameters")
    if not isinstance(task_parameters, Mapping):
        errors.append("task_parameters must be a map")
    else:
        if not _nonempty_text(task_parameters.get("name")):
            errors.append("task_parameters.name must be present")
        if not _nonempty_text(task_parameters.get("description")):
            errors.append("task_parameters.description must be present")
        custom_status = task_parameters.get("custom_status")
        if status_id is None or str(custom_status).strip() != status_id:
            errors.append("task_parameters.custom_status must equal verified status.id")
        task_tag_ids = task_parameters.get("tagIds")
        if not isinstance(task_tag_ids, list) or any(
            not _nonempty_text(tag_id) for tag_id in task_tag_ids
        ):
            errors.append("task_parameters.tagIds must contain non-empty IDs")
        elif set(task_tag_ids) != set(verified_tag_ids):
            errors.append("task_parameters.tagIds must match the four verified tag IDs")

    if not _numeric_id(payload.get("portal_id")):
        errors.append("portal_id must be a numeric ID")
    if not _numeric_id(payload.get("project_id")):
        errors.append("project_id must be a numeric ID")
    return errors


def _preflight_payloads(
    payloads: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    validation_failures: list[dict[str, Any]] = []
    portal_ids: set[str] = set()
    project_ids: set[str] = set()
    task_parameters: list[dict[str, Any]] = []

    for index, payload in enumerate(payloads):
        errors = _payload_live_errors(payload)
        if errors:
            validation_failures.append({"index": index, "errors": errors})
            continue
        portal_ids.add(payload["portal_id"].strip())
        project_ids.add(payload["project_id"].strip())
        task_parameters.append(copy.deepcopy(dict(payload["task_parameters"])))

    if validation_failures:
        raise PayloadValidationError(
            "live payload preflight failed: "
            + json.dumps(validation_failures, separators=(",", ":"))
        )
    if len(portal_ids) > 1 or len(project_ids) > 1:
        raise PayloadValidationError("all live payloads must target one portal and project")
    portal_id = next(iter(portal_ids), None)
    project_id = next(iter(project_ids), None)
    return task_parameters, portal_id, project_id


def _dry_run_result(payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    blocked: list[dict[str, Any]] = []
    ready_count = 0
    for index, payload in enumerate(payloads):
        errors = _payload_live_errors(payload)
        if errors:
            blocked.append({"index": index, "errors": errors})
        else:
            ready_count += 1
    return {
        "mode": "dry-run",
        "payload_count": len(payloads),
        "live_ready_payload_count": ready_count,
        "blocked_payloads": blocked,
        "client_calls": 0,
        "registry_persisted": False,
    }


def execute_registry_report(
    registry_report: Mapping[str, Any],
    *,
    live: bool = False,
    environ: Mapping[str, str] | None = None,
    client: TaskCreateClient | None = None,
) -> dict[str, Any]:
    """Execute the guarded stage using a registry report.

    Dry-run never calls or constructs a client. Live mode checks both guard
    keys, validates every payload before the first call, and sends only copied
    ``task_parameters`` maps.
    """

    payloads = _payloads_from_report(registry_report)
    if not live:
        return _dry_run_result(payloads)

    runtime_env = os.environ if environ is None else environ
    if runtime_env.get(LIVE_UNLOCK_ENV, "").strip().lower() != "true":
        raise CreateTaskGuardError(
            f"live mode requires both --live and {LIVE_UNLOCK_ENV}=true"
        )

    parameters, portal_id, project_id = _preflight_payloads(payloads)
    if not parameters:
        return {
            "mode": "live",
            "payload_count": 0,
            "created_count": 0,
            "responses": [],
            "registry_persisted": False,
        }

    active_client = client
    if active_client is None:
        assert portal_id is not None and project_id is not None
        active_client = ZohoProjectsHttpClient.from_environment(
            runtime_env,
            expected_portal_id=portal_id,
            expected_project_id=project_id,
        )

    responses: list[dict[str, Any]] = []
    for task_parameters in parameters:
        response = active_client.create_task(task_parameters)
        if not isinstance(response, Mapping):
            raise TaskCreateClientError("create-task client response must be a map")
        responses.append(dict(response))

    return {
        "mode": "live",
        "payload_count": len(parameters),
        "created_count": len(responses),
        "responses": responses,
        "registry_persisted": False,
    }


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guarded Zoho Projects create-task scaffold (dry-run by default)."
    )
    parser.add_argument("registry_report", type=Path, help="local registry report JSON")
    parser.add_argument(
        "--live",
        action="store_true",
        help=f"request live creation; also requires {LIVE_UNLOCK_ENV}=true",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        registry_report = json.loads(args.registry_report.read_text(encoding="utf-8"))
        result = execute_registry_report(registry_report, live=args.live)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        CreateTaskGuardError,
        PayloadValidationError,
        TaskCreateClientError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
