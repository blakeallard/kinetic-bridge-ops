#!/usr/bin/env python3
"""Deterministically review parsed Zoho AI action candidates.

This module is local-only and standard-library-only. It groups overlapping
actions within one source summary, retains the most specific wording, and
records every skipped candidate with its reason. It performs no network calls,
task creation, registry persistence, or LLM interpretation.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any, Mapping, Sequence


ACTION_VERBS = {
    "conduct",
    "confirm",
    "evaluate",
    "fix",
    "implement",
    "mass",
    "refine",
    "test",
    "validate",
}

TOKEN_EQUIVALENTS = {
    "descriptions": "description",
    "fields": "field",
    "imports": "import",
    "imported": "import",
    "importing": "import",
    "lookups": "lookup",
    "tests": "test",
    "testing": "test",
    "updates": "import",
    "updating": "import",
    "validation": "validate",
    "validating": "validate",
}

SPECIFICITY_PHRASES = {
    "field population": 8,
    "pricing import": 7,
    "automated import": 5,
    "part number": 6,
    "duplicate routing": 7,
    "before launch": 4,
    "transcription accuracy": 5,
    "item master": 6,
    "data corruption": 3,
}


def _required_text(item: Mapping[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"candidate field {field!r} must be non-empty text")
    return value.strip()


def _tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    raw_tokens = re.findall(r"[a-z0-9]+", normalized)
    return [TOKEN_EQUIVALENTS.get(token, token) for token in raw_tokens]


def _canonical_signature(action_text: str) -> str:
    return " ".join(_tokens(action_text))


def _intent_group(action_text: str) -> str:
    tokens = set(_tokens(action_text))
    lowered = action_text.casefold()

    if lowered.startswith("mass import"):
        return "mass_import"
    if "transcription" in tokens and ("evaluate" in tokens or "test" in tokens):
        return "transcription_evaluation"
    if "routing" in tokens:
        if "conduct" in tokens or "test" in tokens:
            return "routing_test"
        if "fix" in tokens or "refine" in tokens:
            return "routing_remediation"
    if "lookup" in tokens:
        return "part_number_lookup"
    if "implement" in tokens and ("automated" in tokens or "import" in tokens):
        return "automated_import"
    data_quality_terms = {
        "accuracy",
        "corruption",
        "description",
        "field",
        "item",
        "master",
        "population",
    }
    if ("validate" in tokens or "test" in tokens) and tokens & data_quality_terms:
        return "field_data_validation"
    if "confirm" in tokens and "launch" in tokens:
        return "launch_confirmation"
    return f"exact:{_canonical_signature(action_text)}"


def _specificity_score(action_text: str) -> tuple[int, int, int]:
    lowered = action_text.casefold()
    tokens = _tokens(action_text)
    informative_tokens = [token for token in tokens if token not in ACTION_VERBS]
    phrase_score = sum(
        weight for phrase, weight in SPECIFICITY_PHRASES.items() if phrase in lowered
    )
    concrete_terms = len(set(informative_tokens))
    return phrase_score, concrete_terms, len(action_text)


def review_action_candidates(
    parsed_actions: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Return raw, selected, and reasoned skipped candidate rows."""

    if isinstance(parsed_actions, (str, bytes)) or not isinstance(parsed_actions, Sequence):
        raise ValueError("parsed_actions must be a sequence of maps")

    raw: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = {}
    for index, source_item in enumerate(parsed_actions):
        if not isinstance(source_item, Mapping):
            raise ValueError("each parsed action must be a map")
        item = copy.deepcopy(dict(source_item))
        action_text = _required_text(item, "action_text")
        source_file_name = _required_text(item, "source_file_name")
        _required_text(item, "action_hash")
        source_identity = item.get("source_file_id")
        if not isinstance(source_identity, str) or not source_identity.strip():
            source_identity = source_file_name
        group_key = _intent_group(action_text)
        groups.setdefault((source_identity, group_key), []).append((index, item))
        raw.append(copy.deepcopy(item))

    selected_by_index: dict[int, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    for (_, group_key), members in groups.items():
        selected_index, selected_item = max(
            members,
            key=lambda member: (_specificity_score(member[1]["action_text"]), -member[0]),
        )
        selected_copy = copy.deepcopy(selected_item)
        selected_copy["qc_review"] = {
            "group_key": group_key,
            "group_size": len(members),
            "selection_reason": (
                "unique_candidate"
                if len(members) == 1
                else "most_specific_deterministic_candidate"
            ),
        }
        selected_by_index[selected_index] = selected_copy

        selected_signature = _canonical_signature(selected_item["action_text"])
        for member_index, member in members:
            if member_index == selected_index:
                continue
            member_signature = _canonical_signature(member["action_text"])
            reason = (
                "repeated_summary_candidate"
                if member_signature == selected_signature
                else "overlap_superseded_by_specific_candidate"
            )
            skipped.append(
                {
                    "action_hash": member["action_hash"],
                    "action_text": member["action_text"],
                    "source_file_name": member["source_file_name"],
                    "source_file_id": member.get("source_file_id"),
                    "original_source_text": member.get("original_source_text"),
                    "reason": reason,
                    "group_key": group_key,
                    "selected_action_hash": selected_item["action_hash"],
                    "selected_action_text": selected_item["action_text"],
                }
            )

    selected = [selected_by_index[index] for index in sorted(selected_by_index)]
    skipped.sort(key=lambda row: next(
        index for index, item in enumerate(raw) if item["action_hash"] == row["action_hash"]
    ))
    return {
        "parsed_actions_raw": raw,
        "skipped_candidate_reviews": skipped,
        "parsed_actions_selected": selected,
    }
