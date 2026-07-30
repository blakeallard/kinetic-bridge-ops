#!/usr/bin/env python3
"""Verify every sanitized sample against its checked-in expected JSON."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = ROOT / "scripts" / "parse_summary.py"
SPEC = importlib.util.spec_from_file_location("parse_summary", PARSER_PATH)
assert SPEC is not None and SPEC.loader is not None
PARSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARSER)


class SampleParityTests(unittest.TestCase):
    def test_samples_match_expected_json(self) -> None:
        inputs = sorted((ROOT / "samples").glob("*_summary.txt"))
        self.assertGreater(len(inputs), 0)
        for input_path in inputs:
            expected_path = ROOT / "samples" / "expected" / f"{input_path.stem}.json"
            with self.subTest(sample=input_path.name):
                expected = json.loads(expected_path.read_text(encoding="utf-8"))
                self.assertEqual(PARSER.parse_summary(input_path), expected)


if __name__ == "__main__":
    unittest.main()

