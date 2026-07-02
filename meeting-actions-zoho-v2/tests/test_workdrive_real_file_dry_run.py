#!/usr/bin/env python3
"""Tests for the sanitized real WorkDrive-file dry-run path."""

from __future__ import annotations

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_workdrive_dry_run as workdrive_dry_run
import parse_summary
import review_action_candidates


RESOURCE_ID = "dqftz0624072c37654c0ca469052b49bd0418"
SOURCE_FOLDER = "06-30 - Blake's Weekly Catch-Up"
INPUT_PATH = (
    ROOT
    / "samples"
    / "real_inputs"
    / "Zoho AI - Bevco <> MWS - LA Tech Week Weekly Tag-Up_summary.txt"
)
EXPECTED_RAW_PATH = ROOT / "samples" / "expected" / "workdrive_blake_zoho_ai_summary.json"
EXPECTED_QC_PATH = ROOT / "samples" / "expected" / "workdrive_blake_zoho_ai_qc.json"


class WorkDriveRealFileDryRunTests(unittest.TestCase):
    def test_sanitized_real_summary_matches_expected_embedded_actions(self) -> None:
        expected = json.loads(EXPECTED_RAW_PATH.read_text(encoding="utf-8"))
        self.assertEqual(parse_summary.parse_summary(INPUT_PATH), expected)

    def test_qc_selection_matches_expected_review(self) -> None:
        result = workdrive_dry_run.run_workdrive_dry_run(
            INPUT_PATH,
            source_file_id=RESOURCE_ID,
            source_folder_path=SOURCE_FOLDER,
            meeting_name="Bevco <> MWS - LA Tech Week Weekly Tag-Up",
        )
        expected = json.loads(EXPECTED_QC_PATH.read_text(encoding="utf-8"))
        actual = {
            "raw_action_count": len(result["parsed_actions_raw"]),
            "selected_action_texts": [
                action["action_text"] for action in result["parsed_actions_selected"]
            ],
            "skipped_candidate_reviews": [
                {
                    "action_text": review["action_text"],
                    "reason": review["reason"],
                    "selected_action_text": review["selected_action_text"],
                }
                for review in result["skipped_candidate_reviews"]
            ],
        }
        self.assertEqual(actual, expected)
        self.assertLess(
            len(result["parsed_actions_selected"]),
            len(result["parsed_actions_raw"]),
        )

    def test_qc_records_exact_repeated_summary_candidate(self) -> None:
        raw = json.loads(EXPECTED_RAW_PATH.read_text(encoding="utf-8"))
        duplicate = deepcopy(raw[0])
        review = review_action_candidates.review_action_candidates([raw[0], duplicate])
        self.assertEqual(len(review["parsed_actions_selected"]), 1)
        self.assertEqual(
            review["skipped_candidate_reviews"][0]["reason"],
            "repeated_summary_candidate",
        )

    def test_real_file_shape_runs_all_stages_without_task_creation(self) -> None:
        with patch("urllib.request.urlopen") as urlopen:
            result = workdrive_dry_run.run_workdrive_dry_run(
                INPUT_PATH,
                source_file_id=RESOURCE_ID,
                source_folder_path=SOURCE_FOLDER,
                meeting_name="Bevco <> MWS - LA Tech Week Weekly Tag-Up",
            )
            urlopen.assert_not_called()

        self.assertEqual(len(result["parsed_actions_raw"]), 13)
        self.assertEqual(len(result["parsed_actions_selected"]), 8)
        self.assertEqual(len(result["skipped_candidate_reviews"]), 5)
        self.assertTrue(all(review["reason"] for review in result["skipped_candidate_reviews"]))
        self.assertEqual(
            result["registry_report"]["summary"],
            {
                "received_file_count": 1,
                "parsed_action_count": 8,
                "skipped_duplicate_count": 0,
                "payload_candidate_count": 8,
                "unresolved_blocker_count": 6,
            },
        )
        payloads = result["registry_report"]["payloads_that_would_be_created"]
        self.assertEqual(len(payloads), 8)
        for action in result["parsed_actions_raw"]:
            self.assertEqual(action["source_file_id"], RESOURCE_ID)
            self.assertEqual(action["source_folder_path"], SOURCE_FOLDER)
            self.assertEqual(action["extraction_mode"], "embedded_zoho_ai")
            self.assertTrue(action["original_source_text"])
        self.assertEqual(
            sum(
                action["owner_resolution"] == "matched"
                for action in result["parsed_actions_selected"]
            ),
            2,
        )
        self.assertEqual(
            {
                action["action_text"]
                for action in result["parsed_actions_selected"]
                if action["owner_resolution"] == "matched"
            },
            {"Conduct routing tests", "Evaluate transcription accuracy"},
        )
        self.assertEqual(
            [
                (action["action_text"], action["due_date_text"])
                for action in result["parsed_actions_selected"]
                if action["due_date_text"] is not None
            ],
            [("Confirm launch readiness with stakeholders", "Friday")],
        )
        self.assertFalse(
            any(
                "earlier prototype" in action["action_text"]
                for action in result["parsed_actions_raw"]
            )
        )
        selected_hashes = {
            action["action_hash"] for action in result["parsed_actions_selected"]
        }
        skipped_hashes = {
            review["action_hash"] for review in result["skipped_candidate_reviews"]
        }
        for payload in payloads:
            self.assertEqual(payload["status"]["id"], "2543412000000031001")
            self.assertEqual(
                [tag["name"] for tag in payload["tags"]],
                ["automation", "internal-work"],
            )
            self.assertIn("Original source text:", payload["task_parameters"]["description"])
            self.assertTrue(
                any(
                    f"Action hash: {action_hash}" in payload["task_parameters"]["description"]
                    for action_hash in selected_hashes
                )
            )
            self.assertFalse(
                any(
                    f"Action hash: {action_hash}" in payload["task_parameters"]["description"]
                    for action_hash in skipped_hashes
                )
            )
        self.assertEqual(result["create_guard_result"]["client_calls"], 0)
        self.assertEqual(result["create_guard_result"]["payload_count"], 8)
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
