#!/usr/bin/env python3
"""Evaluate local file/action idempotency and print a dry-run report.

The registry is an in-memory model loaded from caller-provided data. This module
does not persist registry state, call a network service, or create tasks. It
returns a proposed registry state solely for repeatable local simulations.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text or null")
    return value.strip() or None


class LocalRegistry:
    """In-memory registry indexed by file identity and action hash."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        if not isinstance(data, Mapping):
            raise ValueError("registry data must be a map")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"registry schema_version must be {SCHEMA_VERSION}")
        raw_files = data.get("files")
        if not isinstance(raw_files, list):
            raise ValueError("registry files must be a list")

        self._records: list[dict[str, Any]] = []
        self._persisted_hashes: set[str] = set()
        self._accepted_this_run: set[str] = set()
        for raw_record in raw_files:
            if not isinstance(raw_record, Mapping):
                raise ValueError("each registry file record must be a map")
            file_name = _required_text(raw_record.get("source_file_name"), "source_file_name")
            file_id = _optional_text(raw_record.get("source_file_id"), "source_file_id")
            raw_hashes = raw_record.get("processed_action_hashes")
            if not isinstance(raw_hashes, list):
                raise ValueError("processed_action_hashes must be a list")
            hashes: list[str] = []
            for raw_hash in raw_hashes:
                action_hash = _required_text(raw_hash, "action_hash")
                if action_hash not in hashes:
                    hashes.append(action_hash)
                    self._persisted_hashes.add(action_hash)
            self._records.append(
                {
                    "source_file_id": file_id,
                    "source_file_name": file_name,
                    "processed_action_hashes": hashes,
                }
            )

    def _find_record(self, file_name: str, file_id: str | None) -> dict[str, Any] | None:
        if file_id is not None:
            for record in self._records:
                if record["source_file_id"] == file_id:
                    return record
            # Permit a name-only legacy/local record to be upgraded with its
            # stable ID, but never merge two different non-null IDs merely
            # because their display filenames match.
            for record in self._records:
                if record["source_file_id"] is None and record["source_file_name"] == file_name:
                    return record
            return None
        for record in self._records:
            if record["source_file_name"] == file_name:
                return record
        return None

    def file_seen(self, file_name: str, file_id: str | None) -> bool:
        return self._find_record(file_name, file_id) is not None

    def duplicate_reason(self, action_hash: str) -> str | None:
        if action_hash in self._persisted_hashes:
            return "action_hash_already_processed"
        if action_hash in self._accepted_this_run:
            return "duplicate_action_hash_in_batch"
        return None

    def accept(self, file_name: str, file_id: str | None, action_hash: str) -> None:
        record = self._find_record(file_name, file_id)
        if record is None:
            record = {
                "source_file_id": file_id,
                "source_file_name": file_name,
                "processed_action_hashes": [],
            }
            self._records.append(record)
        else:
            if record["source_file_id"] is None and file_id is not None:
                record["source_file_id"] = file_id
            record["source_file_name"] = file_name

        if action_hash not in record["processed_action_hashes"]:
            record["processed_action_hashes"].append(action_hash)
        self._accepted_this_run.add(action_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "files": copy.deepcopy(self._records),
        }


def _validate_inputs(
    parsed_actions: Sequence[Mapping[str, Any]],
    payloads: Sequence[Mapping[str, Any]],
) -> None:
    if isinstance(parsed_actions, (str, bytes)) or not isinstance(parsed_actions, Sequence):
        raise ValueError("parsed_actions must be a sequence of maps")
    if isinstance(payloads, (str, bytes)) or not isinstance(payloads, Sequence):
        raise ValueError("payloads must be a sequence of maps")
    if len(parsed_actions) != len(payloads):
        raise ValueError("parsed_actions and payloads must have the same length")


def _file_identity(action: Mapping[str, Any]) -> tuple[str, str | None]:
    return (
        _required_text(action.get("source_file_name"), "source_file_name"),
        _optional_text(action.get("source_file_id"), "source_file_id"),
    )


def _payload_matches_action(payload: Mapping[str, Any], action_hash: str) -> None:
    if not isinstance(payload, Mapping) or payload.get("dry_run") is not True:
        raise ValueError("each payload must be a dry-run payload map")
    task_parameters = payload.get("task_parameters")
    if not isinstance(task_parameters, Mapping):
        raise ValueError("each payload requires task_parameters")
    description = task_parameters.get("description")
    if not isinstance(description, str) or f"Action hash: {action_hash}" not in description:
        raise ValueError("payload/action alignment failed for action_hash")


def _received_file_rows(
    actions: Sequence[Mapping[str, Any]],
    registry: LocalRegistry,
    explicit_received_files: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    raw_files: list[Mapping[str, Any]]
    if explicit_received_files is None:
        raw_files = [
            {
                "source_file_name": _file_identity(action)[0],
                "source_file_id": _file_identity(action)[1],
            }
            for action in actions
        ]
    else:
        if isinstance(explicit_received_files, (str, bytes)) or not isinstance(
            explicit_received_files, Sequence
        ):
            raise ValueError("received_files must be a sequence of maps")
        raw_files = list(explicit_received_files)

    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for raw_file in raw_files:
        if not isinstance(raw_file, Mapping):
            raise ValueError("each received file must be a map")
        file_name = _required_text(raw_file.get("source_file_name"), "source_file_name")
        file_id = _optional_text(raw_file.get("source_file_id"), "source_file_id")
        identity_key = f"id:{file_id}" if file_id else f"name:{file_name}"
        if identity_key in seen_keys:
            continue
        seen_keys.add(identity_key)
        rows.append(
            {
                "source_file_id": file_id,
                "source_file_name": file_name,
                "identity_key": identity_key,
                "seen_before": registry.file_seen(file_name, file_id),
            }
        )
    return rows


def build_processing_report(
    parsed_actions: Sequence[Mapping[str, Any]],
    payloads: Sequence[Mapping[str, Any]],
    registry_data: Mapping[str, Any],
    *,
    received_files: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Filter duplicate action payloads and return a dry-run report.

    The returned ``proposed_registry_state`` simulates the state after all
    payload candidates succeed. It is never persisted by this function.
    """

    _validate_inputs(parsed_actions, payloads)
    registry = LocalRegistry(copy.deepcopy(registry_data))
    received_file_rows = _received_file_rows(parsed_actions, registry, received_files)

    parsed_action_rows: list[dict[str, Any]] = []
    skipped_duplicates: list[dict[str, Any]] = []
    payload_candidates: list[dict[str, Any]] = []
    unresolved_blockers: list[dict[str, Any]] = []
    configuration_blocker_codes: set[str] = set()

    for action, payload in zip(parsed_actions, payloads, strict=True):
        if not isinstance(action, Mapping):
            raise ValueError("each parsed action must be a map")
        file_name, file_id = _file_identity(action)
        action_hash = _required_text(action.get("action_hash"), "action_hash")
        action_text = _required_text(action.get("action_text"), "action_text")
        owner_resolution = _required_text(action.get("owner_resolution"), "owner_resolution")
        _payload_matches_action(payload, action_hash)

        parsed_action_rows.append(
            {
                "source_file_id": file_id,
                "source_file_name": file_name,
                "action_hash": action_hash,
                "action_text": action_text,
                "owner_resolution": owner_resolution,
            }
        )

        duplicate_reason = registry.duplicate_reason(action_hash)
        if duplicate_reason is not None:
            skipped_duplicates.append(
                {
                    "source_file_id": file_id,
                    "source_file_name": file_name,
                    "action_hash": action_hash,
                    "action_text": action_text,
                    "reason": duplicate_reason,
                }
            )
            continue

        registry.accept(file_name, file_id, action_hash)
        payload_candidates.append(copy.deepcopy(dict(payload)))

        if owner_resolution != "matched":
            unresolved_blockers.append(
                {
                    "type": "owner_resolution",
                    "action_hash": action_hash,
                    "action_text": action_text,
                    "owner_resolution": owner_resolution,
                    "owner_raw": action.get("owner_raw"),
                }
            )

        validation = payload.get("validation")
        if isinstance(validation, Mapping):
            if validation.get("missing_status_id") is True:
                configuration_blocker_codes.add("missing_status_id")
            missing_tag_ids = validation.get("missing_tag_ids")
            if isinstance(missing_tag_ids, list) and missing_tag_ids:
                configuration_blocker_codes.add("missing_tag_ids")

    if "missing_status_id" in configuration_blocker_codes:
        unresolved_blockers.append(
            {
                "type": "configuration",
                "code": "missing_status_id",
                "details": "Needs Review status ID has not been verified",
            }
        )
    if "missing_tag_ids" in configuration_blocker_codes:
        missing_names: list[str] = []
        for payload in payload_candidates:
            validation = payload.get("validation", {})
            for tag_name in validation.get("missing_tag_ids", []):
                if tag_name not in missing_names:
                    missing_names.append(tag_name)
        unresolved_blockers.append(
            {
                "type": "configuration",
                "code": "missing_tag_ids",
                "tag_names": missing_names,
            }
        )

    return {
        "dry_run": True,
        "summary": {
            "received_file_count": len(received_file_rows),
            "parsed_action_count": len(parsed_action_rows),
            "skipped_duplicate_count": len(skipped_duplicates),
            "payload_candidate_count": len(payload_candidates),
            "unresolved_blocker_count": len(unresolved_blockers),
        },
        "received_files": received_file_rows,
        "parsed_actions": parsed_action_rows,
        "skipped_duplicates": skipped_duplicates,
        "payloads_that_would_be_created": payload_candidates,
        "unresolved_blockers": unresolved_blockers,
        "proposed_registry_state": registry.to_dict(),
        "registry_persisted": False,
    }


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a local dry-run duplicate registry report."
    )
    parser.add_argument("parsed_json", type=Path, help="parsed action-item JSON list")
    parser.add_argument("payload_json", type=Path, help="dry-run payload JSON list")
    parser.add_argument("registry_json", type=Path, help="local registry fixture JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        parsed_actions = json.loads(args.parsed_json.read_text(encoding="utf-8"))
        payloads = json.loads(args.payload_json.read_text(encoding="utf-8"))
        registry_data = json.loads(args.registry_json.read_text(encoding="utf-8"))
        report = build_processing_report(parsed_actions, payloads, registry_data)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
