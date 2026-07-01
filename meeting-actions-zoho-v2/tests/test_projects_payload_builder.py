#!/usr/bin/env python3
"""Tests for inert Zoho Projects task payload generation."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_projects_payloads.py"
SPEC = importlib.util.spec_from_file_location("build_projects_payloads", BUILDER_PATH)
assert SPEC is not None and SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILDER
SPEC.loader.exec_module(BUILDER)



def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class ProjectsPayloadBuilderTests(unittest.TestCase):
    def test_matched_owner_fixture(self) -> None:
        item = load_json(ROOT / "samples/expected/known_owner_summary.json")[0]
        expected = load_json(ROOT / "samples/payloads/known_owner_payload.json")
        actual = BUILDER.build_task_payload(item, meeting_name="Website Planning Meeting")
        self.assertEqual(actual, expected)
        self.assertEqual(
            actual["task_parameters"]["person_responsible"],
            "2543412000001324206",
        )

    def test_unassigned_owner_fixtures(self) -> None:
        items = load_json(ROOT / "samples/expected/multiple_unknown_summary.json")
        expected = load_json(ROOT / "samples/payloads/unassigned_owner_payloads.json")
        actual = BUILDER.build_task_payloads(
            items,
            meeting_name="Partner Automation Review",
        )
        self.assertEqual(actual, expected)
        for payload in actual:
            self.assertNotIn("person_responsible", payload["task_parameters"])
            self.assertEqual(payload["validation"]["owner_assignment"], "unassigned")

    def test_every_payload_is_needs_review_and_not_live_ready(self) -> None:
        items = load_json(ROOT / "samples/expected/multiple_unknown_summary.json")
        for payload in BUILDER.build_task_payloads(items, meeting_name="Review"):
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["status"], {"name": "Needs Review", "id": None})
            self.assertFalse(payload["validation"]["ready_for_live"])
            description = payload["task_parameters"]["description"]
            for field in BUILDER.WORKFLOW_DIAGNOSTIC_FIELDS:
                self.assertIn(f"{field}: Needs Review", description)

    def test_nonmatched_resolution_never_assigns_owner(self) -> None:
        item = load_json(ROOT / "samples/expected/multiple_unknown_summary.json")[1]
        item["owner_id"] = "2543412000001324206"
        payload = BUILDER.build_task_payload(item, meeting_name="Review")
        self.assertNotIn("person_responsible", payload["task_parameters"])

    def test_matched_resolution_rejects_unknown_owner_id(self) -> None:
        item = load_json(ROOT / "samples/expected/known_owner_summary.json")[0]
        item["owner_id"] = "not-configured"
        with self.assertRaisesRegex(ValueError, "configured known owner ID"):
            BUILDER.build_task_payload(item, meeting_name="Review")

    def test_live_mode_is_not_supported(self) -> None:
        item = load_json(ROOT / "samples/expected/known_owner_summary.json")[0]
        with self.assertRaisesRegex(ValueError, "live mode is unsupported"):
            BUILDER.build_task_payload(item, meeting_name="Review", dry_run=False)


if __name__ == "__main__":
    unittest.main()
