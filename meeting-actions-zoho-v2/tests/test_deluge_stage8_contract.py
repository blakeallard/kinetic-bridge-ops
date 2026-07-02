#!/usr/bin/env python3
"""Local structural/parity harness for the Stage 8 Deluge draft."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import parse_summary
import review_action_candidates


DELUGE_PATH = ROOT / "deluge" / "parse_meeting_summary.deluge"
REAL_INPUT_PATH = (
    ROOT
    / "samples"
    / "real_inputs"
    / "Zoho AI - Bevco <> MWS - LA Tech Week Weekly Tag-Up_summary.txt"
)
FLOW_INPUT_PATH = ROOT / "samples" / "deluge" / "stage8_workdrive_flow_input.json"
EXPECTED_PATH = ROOT / "samples" / "deluge" / "stage8_expected_projection.json"


class DelugeStage8ContractTests(unittest.TestCase):
    def test_flow_input_fixture_tracks_sanitized_real_input(self) -> None:
        flow_input = json.loads(FLOW_INPUT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(flow_input["file_text"], REAL_INPUT_PATH.read_text(encoding="utf-8"))
        self.assertTrue(flow_input["file_name"].endswith("_summary.txt"))
        self.assertIn("Blake", flow_input["file_path"])

    def test_expected_projection_matches_python_source_of_truth(self) -> None:
        flow_input = json.loads(FLOW_INPUT_PATH.read_text(encoding="utf-8"))
        raw = parse_summary.parse_summary(REAL_INPUT_PATH)
        for action in raw:
            action["source_file_id"] = flow_input["file_id"]
            action["source_folder_path"] = flow_input["file_path"]
        review = review_action_candidates.review_action_candidates(raw)
        projection = {
            "parser_version": "deluge-stage8-v2",
            "raw_action_count": len(review["parsed_actions_raw"]),
            "selected_action_count": len(review["parsed_actions_selected"]),
            "skipped_candidate_count": len(review["skipped_candidate_reviews"]),
            "selected_action_texts": [
                action["action_text"] for action in review["parsed_actions_selected"]
            ],
            "skipped_candidate_reviews": [
                {
                    "action_text": skipped["action_text"],
                    "reason": skipped["reason"],
                    "selected_action_text": skipped["selected_action_text"],
                }
                for skipped in review["skipped_candidate_reviews"]
            ],
            "payload_input_equals_selected": True,
        }
        expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
        self.assertEqual(projection, expected)

    def test_deluge_source_exposes_stage8_contract_and_no_live_operations(self) -> None:
        source = DELUGE_PATH.read_text(encoding="utf-8")
        required_fragments = (
            'result.put("parser_version", "deluge-stage8-v2")',
            'result.put("parsed_actions_raw", items)',
            'result.put("skipped_candidate_reviews", skipped_candidate_reviews)',
            'result.put("parsed_actions_selected", selected_items)',
            'result.put("payload_input_items", selected_items)',
            'result.put("items", selected_items)',
            '"embedded_zoho_ai"',
            '"next steps include"',
            '"plans to"',
            '" is planned to "',
            '"field_data_validation"',
            '"automated_import"',
            '"routing_remediation"',
            '"repeated_summary_candidate"',
            '"overlap_superseded_by_specific_candidate"',
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

        executable_source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL).casefold()
        for forbidden in ("invokeurl", "zoho.projects", "openai", "claude", "create_task"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, executable_source)
        self.assertEqual(source.count("{"), source.count("}"))


if __name__ == "__main__":
    unittest.main()
