#!/usr/bin/env python3
"""Run the local WorkDrive-file pipeline without network calls or persistence.

The caller must provide an already-downloaded ``*_summary.txt`` file plus its
authoritative WorkDrive resource ID and meeting name. This script performs no
WorkDrive fetch itself and exposes no live task-creation option.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import build_projects_payloads as payload_builder
import build_registry_report as registry
import create_tasks_guarded as create_guard
import parse_summary as parser
import review_action_candidates as candidate_review


EMPTY_REGISTRY: Mapping[str, Any] = {"schema_version": 1, "files": []}


def run_workdrive_dry_run(
    input_path: Path,
    *,
    source_file_id: str,
    source_folder_path: str = "",
    meeting_name: str,
    registry_data: Mapping[str, Any] = EMPTY_REGISTRY,
) -> dict[str, Any]:
    """Run parser -> QC review -> payload builder -> registry -> guard locally."""

    if not isinstance(source_file_id, str) or not source_file_id.strip():
        raise ValueError("source_file_id must be non-empty text")
    if not isinstance(meeting_name, str) or not meeting_name.strip():
        raise ValueError("meeting_name must be non-empty text")
    if not isinstance(source_folder_path, str):
        raise ValueError("source_folder_path must be text")
    if "blake" not in input_path.name.casefold() and "blake" not in source_folder_path.casefold():
        raise ValueError(
            "rejected non-target WorkDrive file: file name or folder path must contain Blake"
        )

    raw_actions = parser.parse_summary(input_path)
    for action in raw_actions:
        action["source_file_id"] = source_file_id.strip()
        action["source_folder_path"] = source_folder_path.strip()

    review = candidate_review.review_action_candidates(raw_actions)
    selected_actions = review["parsed_actions_selected"]

    payloads = payload_builder.build_task_payloads(
        selected_actions,
        meeting_name=meeting_name.strip(),
    )
    report = registry.build_processing_report(
        selected_actions,
        payloads,
        registry_data,
        received_files=[
            {
                "source_file_id": source_file_id.strip(),
                "source_file_name": input_path.name,
            }
        ],
    )
    guard_result = create_guard.execute_registry_report(report)

    return {
        "mode": "dry-run",
        "source": {
            "app": "Zoho WorkDrive",
            "source_file_id": source_file_id.strip(),
            "source_file_name": input_path.name,
            "source_folder_path": source_folder_path.strip(),
            "blake_target_verified": True,
        },
        "target_configuration": {
            "portal_id": payload_builder.PORTAL_ID,
            "project_id": payload_builder.PROJECT_ID,
            "status": {
                "name": payload_builder.STATUS_NAME,
                "id": payload_builder.STATUS_ID,
                "verified": True,
            },
            "tags": [
                {"name": name, "id": tag_id}
                for name, tag_id in payload_builder.KNOWN_TAG_IDS.items()
            ],
        },
        "parsed_actions_raw": review["parsed_actions_raw"],
        "skipped_candidate_reviews": review["skipped_candidate_reviews"],
        "parsed_actions_selected": selected_actions,
        "registry_report": report,
        "create_guard_result": guard_result,
        "network_task_creation_calls": 0,
        "registry_persisted": False,
    }


def _argument_parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(
        description="Run an already-downloaded WorkDrive summary through the local dry-run pipeline."
    )
    argument_parser.add_argument("input_file", type=Path)
    argument_parser.add_argument("--source-file-id", required=True)
    argument_parser.add_argument(
        "--source-folder-path",
        default="",
        help="authoritative WorkDrive folder path; required when the file name lacks Blake",
    )
    argument_parser.add_argument("--meeting-name", required=True)
    argument_parser.add_argument(
        "--registry-json",
        type=Path,
        help="optional local registry fixture; omitted means an empty in-memory registry",
    )
    return argument_parser


def main(argv: list[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        registry_data = EMPTY_REGISTRY
        if args.registry_json is not None:
            registry_data = json.loads(args.registry_json.read_text(encoding="utf-8"))
        result = run_workdrive_dry_run(
            args.input_file,
            source_file_id=args.source_file_id,
            source_folder_path=args.source_folder_path,
            meeting_name=args.meeting_name,
            registry_data=registry_data,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
