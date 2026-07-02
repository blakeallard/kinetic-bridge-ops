#!/usr/bin/env python3
"""Tests for the two-key Zoho Projects live-create guard."""

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

import create_tasks_guarded as guarded


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class FakeTaskCreateClient:
    def __init__(self) -> None:
        self.calls = []

    def create_task(self, task_parameters):
        self.calls.append(deepcopy(dict(task_parameters)))
        return {"tasks": [{"id": f"fake-{len(self.calls)}"}]}


def registry_report(payloads):
    return {"payloads_that_would_be_created": payloads}


def live_ready_payload():
    payload = load_json(ROOT / "samples/payloads/known_owner_payload.json")
    status_id = "2543412000000031001"
    tag_ids = {
        "automation": "2543412000001391053",
        "internal-work": "2543412000001391061",
    }
    payload["status"] = {
        "name": "In Progress",
        "id": status_id,
        "verified": True,
    }
    payload["tags"] = [
        {"name": name, "id": tag_id} for name, tag_id in tag_ids.items()
    ]
    payload["task_parameters"]["custom_status"] = status_id
    payload["task_parameters"]["tagIds"] = list(tag_ids.values())
    payload["validation"] = {
        "ready_for_live": True,
        "missing_status_id": False,
        "missing_tag_ids": [],
        "owner_assignment": "matched",
    }
    return payload


class LiveCreateTaskGuardTests(unittest.TestCase):
    def test_dry_run_makes_zero_client_calls(self) -> None:
        client = FakeTaskCreateClient()
        with patch.object(guarded.urllib.request, "urlopen") as urlopen:
            result = guarded.execute_registry_report(
                registry_report([live_ready_payload()]),
                client=client,
                environ={},
            )
            urlopen.assert_not_called()
        self.assertEqual(client.calls, [])
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(result["client_calls"], 0)

    def test_live_mode_without_unlock_environment_fails(self) -> None:
        client = FakeTaskCreateClient()
        with self.assertRaisesRegex(
            guarded.CreateTaskGuardError,
            "LIVE_ZOHO_TASK_CREATE=true",
        ):
            guarded.execute_registry_report(
                registry_report([live_ready_payload()]),
                live=True,
                environ={},
                client=client,
            )
        self.assertEqual(client.calls, [])

    def test_payload_marked_not_live_ready_is_rejected(self) -> None:
        client = FakeTaskCreateClient()
        blocked_payload = live_ready_payload()
        blocked_payload["validation"]["ready_for_live"] = False
        with self.assertRaisesRegex(
            guarded.PayloadValidationError,
            "ready_for_live must be true",
        ):
            guarded.execute_registry_report(
                registry_report([blocked_payload]),
                live=True,
                environ={"LIVE_ZOHO_TASK_CREATE": "true"},
                client=client,
            )
        self.assertEqual(client.calls, [])

    def test_any_other_status_name_is_rejected(self) -> None:
        client = FakeTaskCreateClient()
        payload = live_ready_payload()
        payload["status"]["name"] = "Open"
        with self.assertRaisesRegex(
            guarded.PayloadValidationError,
            "status.name must be In Progress",
        ):
            guarded.execute_registry_report(
                registry_report([payload]),
                live=True,
                environ={"LIVE_ZOHO_TASK_CREATE": "true"},
                client=client,
            )
        self.assertEqual(client.calls, [])

    def test_each_status_and_tag_blocker_prevents_all_calls(self) -> None:
        mutations = (
            ("missing status flag", lambda payload: payload["validation"].update(missing_status_id=True)),
            ("missing status ID", lambda payload: payload["status"].update(id=None)),
            ("wrong status ID", lambda payload: payload["status"].update(id="2543412000001999001")),
            ("unverified status", lambda payload: payload["status"].update(verified=False)),
            (
                "missing custom status parameter",
                lambda payload: payload["task_parameters"].pop("custom_status"),
            ),
            (
                "missing tag IDs",
                lambda payload: payload["validation"].update(
                    missing_tag_ids=["automation"]
                ),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(blocker=label):
                client = FakeTaskCreateClient()
                payload = live_ready_payload()
                mutate(payload)
                with self.assertRaises(guarded.PayloadValidationError):
                    guarded.execute_registry_report(
                        registry_report([payload]),
                        live=True,
                        environ={"LIVE_ZOHO_TASK_CREATE": "true"},
                        client=client,
                    )
                self.assertEqual(client.calls, [])

    def test_fake_client_receives_only_validated_task_parameters(self) -> None:
        client = FakeTaskCreateClient()
        payload = live_ready_payload()
        expected = deepcopy(payload["task_parameters"])
        result = guarded.execute_registry_report(
            registry_report([payload]),
            live=True,
            environ={"LIVE_ZOHO_TASK_CREATE": "true"},
            client=client,
        )
        self.assertEqual(client.calls, [expected])
        self.assertNotIn("portal_id", client.calls[0])
        self.assertNotIn("validation", client.calls[0])
        self.assertEqual(result["created_count"], 1)

    def test_registry_report_with_no_payloads_creates_no_tasks(self) -> None:
        client = FakeTaskCreateClient()
        result = guarded.execute_registry_report(
            registry_report([]),
            live=True,
            environ={"LIVE_ZOHO_TASK_CREATE": "true"},
            client=client,
        )
        self.assertEqual(client.calls, [])
        self.assertEqual(result["created_count"], 0)

    def test_entire_batch_is_validated_before_first_client_call(self) -> None:
        client = FakeTaskCreateClient()
        blocked = live_ready_payload()
        blocked["validation"]["missing_tag_ids"] = ["automation"]
        with self.assertRaises(guarded.PayloadValidationError):
            guarded.execute_registry_report(
                registry_report([live_ready_payload(), blocked]),
                live=True,
                environ={"LIVE_ZOHO_TASK_CREATE": "true"},
                client=client,
            )
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
