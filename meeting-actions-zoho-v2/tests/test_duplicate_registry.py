#!/usr/bin/env python3
"""Tests for local dry-run file/action idempotency reporting."""

from __future__ import annotations

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_registry_report as registry_module


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class DuplicateRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actions = load_json(ROOT / "samples/expected/known_owner_summary.json")
        first_payload = load_json(ROOT / "samples/payloads/known_owner_payload.json")
        all_payloads = load_json(ROOT / "samples/payloads/unassigned_owner_payloads.json")
        # Build the second known-owner payload through the existing fixture's
        # schema without introducing task-generation behavior into this layer.
        import build_projects_payloads as payload_builder

        second_payload = payload_builder.build_task_payload(
            self.actions[1], meeting_name="Website Planning Meeting"
        )
        self.payloads = [first_payload, second_payload]
        self.unassigned_payloads = all_payloads
        self.empty_registry = load_json(ROOT / "samples/registry/empty_registry.json")

    def test_first_run_creates_payload_candidates(self) -> None:
        report = registry_module.build_processing_report(
            self.actions,
            self.payloads,
            self.empty_registry,
        )
        self.assertEqual(report["summary"]["payload_candidate_count"], 2)
        self.assertEqual(report["summary"]["skipped_duplicate_count"], 0)
        self.assertEqual(len(report["payloads_that_would_be_created"]), 2)
        self.assertFalse(report["registry_persisted"])

    def test_second_run_skips_duplicates(self) -> None:
        first = registry_module.build_processing_report(
            self.actions,
            self.payloads,
            self.empty_registry,
        )
        second = registry_module.build_processing_report(
            self.actions,
            self.payloads,
            first["proposed_registry_state"],
        )
        self.assertEqual(second["summary"]["payload_candidate_count"], 0)
        self.assertEqual(second["summary"]["skipped_duplicate_count"], 2)
        self.assertEqual(second["payloads_that_would_be_created"], [])

    def test_duplicate_action_hash_in_batch_is_skipped(self) -> None:
        duplicate_actions = [deepcopy(self.actions[0]), deepcopy(self.actions[0])]
        duplicate_payloads = [deepcopy(self.payloads[0]), deepcopy(self.payloads[0])]
        report = registry_module.build_processing_report(
            duplicate_actions,
            duplicate_payloads,
            self.empty_registry,
        )
        self.assertEqual(report["summary"]["payload_candidate_count"], 1)
        self.assertEqual(report["summary"]["skipped_duplicate_count"], 1)
        self.assertEqual(
            report["skipped_duplicates"][0]["reason"],
            "duplicate_action_hash_in_batch",
        )

    def test_new_action_in_same_file_is_processed(self) -> None:
        existing = load_json(ROOT / "samples/registry/example_registry.json")
        report = registry_module.build_processing_report(
            self.actions,
            self.payloads,
            existing,
        )
        self.assertEqual(report["received_files"][0]["seen_before"], True)
        self.assertEqual(report["summary"]["skipped_duplicate_count"], 1)
        self.assertEqual(report["summary"]["payload_candidate_count"], 1)
        self.assertEqual(
            report["payloads_that_would_be_created"][0]["task_parameters"]["name"],
            "Website Planning Meeting - Review Zoho-only task pipeline",
        )

    def test_file_id_matches_across_a_rename(self) -> None:
        existing = load_json(ROOT / "samples/registry/example_registry.json")
        renamed_action = deepcopy(self.actions[0])
        renamed_action["source_file_name"] = "renamed_summary.txt"
        renamed_action["source_file_id"] = "workdrive-sample-file-001"
        report = registry_module.build_processing_report(
            [renamed_action],
            [self.payloads[0]],
            existing,
        )
        self.assertTrue(report["received_files"][0]["seen_before"])
        self.assertEqual(report["summary"]["skipped_duplicate_count"], 1)


if __name__ == "__main__":
    unittest.main()

