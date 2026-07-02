#!/usr/bin/env python3
"""Tests for the sanitized real WorkDrive-file dry-run path."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_workdrive_dry_run as workdrive_dry_run


RESOURCE_ID = "dqftz0624072c37654c0ca469052b49bd0418"
SOURCE_FOLDER = "06-30 - Blake's Weekly Catch-Up"
INPUT_PATH = (
    ROOT
    / "samples"
    / "real_inputs"
    / "Zoho AI - Bevco <> MWS - LA Tech Week Weekly Tag-Up_summary.txt"
)


class WorkDriveRealFileDryRunTests(unittest.TestCase):
    def test_real_file_shape_runs_all_stages_without_task_creation(self) -> None:
        with patch("urllib.request.urlopen") as urlopen:
            result = workdrive_dry_run.run_workdrive_dry_run(
                INPUT_PATH,
                source_file_id=RESOURCE_ID,
                source_folder_path=SOURCE_FOLDER,
                meeting_name="Bevco <> MWS - LA Tech Week Weekly Tag-Up",
            )
            urlopen.assert_not_called()

        self.assertEqual(result["parsed_actions"], [])
        self.assertEqual(
            result["registry_report"]["summary"],
            {
                "received_file_count": 1,
                "parsed_action_count": 0,
                "skipped_duplicate_count": 0,
                "payload_candidate_count": 0,
                "unresolved_blocker_count": 0,
            },
        )
        self.assertEqual(
            result["registry_report"]["payloads_that_would_be_created"], []
        )
        self.assertEqual(result["create_guard_result"]["client_calls"], 0)
        self.assertEqual(result["network_task_creation_calls"], 0)
        self.assertFalse(result["registry_persisted"])

    def test_target_configuration_uses_only_verified_status_and_tags(self) -> None:
        result = workdrive_dry_run.run_workdrive_dry_run(
            INPUT_PATH,
            source_file_id=RESOURCE_ID,
            source_folder_path=SOURCE_FOLDER,
            meeting_name="Bevco <> MWS - LA Tech Week Weekly Tag-Up",
        )
        self.assertEqual(
            result["target_configuration"]["status"],
            {
                "name": "In Progress",
                "id": "2543412000000031001",
                "verified": True,
            },
        )
        self.assertEqual(
            result["target_configuration"]["tags"],
            [
                {"name": "automation", "id": "2543412000001391053"},
                {"name": "internal-work", "id": "2543412000001391061"},
            ],
        )

    def test_non_blake_file_and_path_are_rejected_before_parsing(self) -> None:
        with patch("run_workdrive_dry_run.parser.parse_summary") as parse_summary:
            with self.assertRaisesRegex(ValueError, "rejected non-target WorkDrive file"):
                workdrive_dry_run.run_workdrive_dry_run(
                    INPUT_PATH,
                    source_file_id=RESOURCE_ID,
                    source_folder_path="06-30 - Weekly Catch-Up",
                    meeting_name="Weekly Tag-Up",
                )
            parse_summary.assert_not_called()


if __name__ == "__main__":
    unittest.main()
