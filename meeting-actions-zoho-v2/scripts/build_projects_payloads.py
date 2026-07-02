#!/usr/bin/env python3
"""Build inert Zoho Projects task payload maps from parsed action-item maps.

This module is standard-library-only. It performs no HTTP requests, OAuth,
Zoho calls, file discovery, task creation, or external writes. Its only CLI
output is JSON written to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence


PORTAL_ID = "898600220"
PROJECT_ID = "2543412000001324010"
STATUS_NAME = "In Progress"
STATUS_ID = "2543412000000031001"
DIAGNOSTIC_PLACEHOLDER = "Not provided"

KNOWN_OWNER_IDS: Mapping[str, str] = MappingProxyType(
    {
        "Blake Allard": "2543412000001324206",
        "Bill Beverley": "2543412000000059003",
        "Bryan Ovalle": "2543412000000108001",
    }
)

KNOWN_TAG_IDS: Mapping[str, str] = MappingProxyType(
    {
        "automation": "2543412000001391053",
        "internal-work": "2543412000001391061",
    }
)

REQUIRED_TAG_NAMES = (
    "automation",
    "internal-work",
)

WORKFLOW_DIAGNOSTIC_FIELDS = (
    "Requested task",
    "Business problem",
    "Desired workflow",
    "Success criteria",
    "Current status",
    "Problem type",
    "Systems involved",
    "Data needed",
    "Access / approval needed",
    "Information between systems",
    "One-sentence diagnosis",
    "Next action",
)

ALLOWED_OWNER_RESOLUTIONS = {"matched", "missing", "unresolved", "multiple"}
KNOWN_OWNER_ID_VALUES = frozenset(KNOWN_OWNER_IDS.values())


@dataclass(frozen=True)
class ProjectsPayloadConfig:
    """Non-secret target configuration used only to construct payload maps."""

    portal_id: str = PORTAL_ID
    project_id: str = PROJECT_ID
    status_name: str = STATUS_NAME
    status_id: str = STATUS_ID
    task_name_max_length: int = 250

    def validate(self) -> None:
        if not self.portal_id or not self.project_id:
            raise ValueError("portal_id and project_id are required")
        if self.status_name != STATUS_NAME:
            raise ValueError(f"status_name must remain {STATUS_NAME!r}")
        if self.status_id != STATUS_ID:
            raise ValueError("status_id must be the verified In Progress ID")
        if self.task_name_max_length < 1:
            raise ValueError("task_name_max_length must be positive")


DEFAULT_CONFIG = ProjectsPayloadConfig()


def _required_text(item: Mapping[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"parsed item field {field!r} must be non-empty text")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional parsed text fields must be text or null")
    return value


def _format_detected_owners(value: Any) -> str:
    if value is None:
        return "None detected"
    if not isinstance(value, list):
        raise ValueError("detected_owners must be a list")
    if not value:
        return "None detected"

    formatted: list[str] = []
    for owner in value:
        if not isinstance(owner, Mapping):
            raise ValueError("each detected owner must be a map")
        name = owner.get("name")
        resolution = owner.get("resolution")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("each detected owner requires a name")
        if resolution not in {"matched", "unresolved"}:
            raise ValueError("detected owner resolution must be matched or unresolved")
        canonical_name = owner.get("canonical_name")
        owner_id = owner.get("owner_id")
        details = [f"resolution={resolution}"]
        if canonical_name:
            details.append(f"canonical_name={canonical_name}")
        if owner_id:
            details.append(f"owner_id={owner_id}")
        formatted.append(f"{name} ({'; '.join(details)})")
    return "; ".join(formatted)


def _build_description(item: Mapping[str, Any], meeting_name: str) -> str:
    action_text = _required_text(item, "action_text")
    source_file_name = _required_text(item, "source_file_name")
    action_hash = _required_text(item, "action_hash")
    owner_resolution = _required_text(item, "owner_resolution")
    owner_raw = _optional_text(item.get("owner_raw"))
    due_date_text = _optional_text(item.get("due_date_text"))
    detected_owners = _format_detected_owners(item.get("detected_owners"))
    source_file_id = _optional_text(item.get("source_file_id"))
    source_folder_path = _optional_text(item.get("source_folder_path"))
    original_source_text = _optional_text(item.get("original_source_text"))

    lines = [
        "Source: Zoho AI meeting summary",
        f"Summary file: {source_file_name}",
    ]
    if source_file_id is not None:
        lines.append(f"Source file ID: {source_file_id}")
    if source_folder_path is not None:
        lines.append(f"Source folder path: {source_folder_path}")
    lines.append(f"Meeting name: {meeting_name}")
    if original_source_text is not None:
        lines.append(f"Original source text: {original_source_text}")
    lines.extend([
        f"Original action text: {action_text}",
        f"Owner raw: {owner_raw if owner_raw is not None else 'Not provided'}",
        f"Owner resolution: {owner_resolution}",
        f"Detected owners: {detected_owners}",
        f"Due date text: {due_date_text if due_date_text is not None else 'Not provided'}",
        "Due date calculation: Not performed",
        f"Action hash: {action_hash}",
        "",
        "Workflow Diagnostic",
    ])
    lines.extend(
        f"{field}: {DIAGNOSTIC_PLACEHOLDER}"
        for field in WORKFLOW_DIAGNOSTIC_FIELDS
    )
    return "\n".join(lines)


def _task_name(meeting_name: str, action_text: str, max_length: int) -> str:
    name = f"{meeting_name} - {action_text}"
    return name[:max_length]


def build_task_payload(
    item: Mapping[str, Any],
    *,
    meeting_name: str,
    config: ProjectsPayloadConfig = DEFAULT_CONFIG,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Return one inert payload envelope for one parsed action item.

    ``meeting_name`` is required explicitly so the builder never guesses it
    from a filename. Live mode is intentionally unsupported.
    """

    if dry_run is not True:
        raise ValueError("live mode is unsupported; dry_run must remain true")
    config.validate()
    if not isinstance(item, Mapping):
        raise ValueError("parsed item must be a map")
    if not isinstance(meeting_name, str) or not meeting_name.strip():
        raise ValueError("meeting_name must be non-empty text")
    meeting_name = meeting_name.strip()

    action_text = _required_text(item, "action_text")
    owner_resolution = _required_text(item, "owner_resolution")
    if owner_resolution not in ALLOWED_OWNER_RESOLUTIONS:
        raise ValueError(f"unsupported owner_resolution: {owner_resolution!r}")

    owner_id = item.get("owner_id")
    if owner_resolution == "matched":
        if not isinstance(owner_id, str) or owner_id not in KNOWN_OWNER_ID_VALUES:
            raise ValueError("matched owner must use a configured known owner ID")

    task_parameters: dict[str, Any] = {
        "name": _task_name(meeting_name, action_text, config.task_name_max_length),
        "description": _build_description(item, meeting_name),
        "custom_status": config.status_id,
        "tagIds": list(KNOWN_TAG_IDS.values()),
    }
    if owner_resolution == "matched":
        task_parameters["person_responsible"] = owner_id

    configured_tags = [
        {"name": tag_name, "id": KNOWN_TAG_IDS.get(tag_name)}
        for tag_name in REQUIRED_TAG_NAMES
    ]
    missing_tag_ids = [tag["name"] for tag in configured_tags if tag["id"] is None]

    return {
        "dry_run": True,
        "portal_id": config.portal_id,
        "project_id": config.project_id,
        "status": {"name": config.status_name, "id": config.status_id, "verified": True},
        "tags": configured_tags,
        "task_parameters": task_parameters,
        "validation": {
            "ready_for_live": not missing_tag_ids,
            "missing_status_id": False,
            "missing_tag_ids": missing_tag_ids,
            "owner_assignment": "matched" if owner_resolution == "matched" else "unassigned",
        },
    }


def build_task_payloads(
    items: Sequence[Mapping[str, Any]],
    *,
    meeting_name: str,
    config: ProjectsPayloadConfig = DEFAULT_CONFIG,
    dry_run: bool = True,
) -> list[dict[str, Any]]:
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise ValueError("parsed items must be a sequence of maps")
    return [
        build_task_payload(
            item,
            meeting_name=meeting_name,
            config=config,
            dry_run=dry_run,
        )
        for item in items
    ]


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build dry-run Zoho Projects payload maps from parsed JSON."
    )
    parser.add_argument("parsed_json", type=Path, help="JSON file containing parsed item maps")
    parser.add_argument("--meeting-name", required=True, help="authoritative meeting name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    try:
        parsed = json.loads(args.parsed_json.read_text(encoding="utf-8"))
        payloads = build_task_payloads(parsed, meeting_name=args.meeting_name)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    json.dump(payloads, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
