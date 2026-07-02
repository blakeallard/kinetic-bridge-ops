#!/usr/bin/env python3
"""Parse explicit meeting-summary action items and print dry-run JSON.

This module is intentionally local-only and standard-library-only. It reads files
provided on the command line and writes the parsed representation to stdout. It
has no network, Zoho, LLM, registry, or task-creation behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Iterable


OWNER_MAP = {
    "blake": ("Blake Allard", "2543412000001324206"),
    "blake allard": ("Blake Allard", "2543412000001324206"),
    "bill": ("Bill Beverley", "2543412000000059003"),
    "bill beverley": ("Bill Beverley", "2543412000000059003"),
    "bryan": ("Bryan Ovalle", "2543412000000108001"),
    "brian": ("Bryan Ovalle", "2543412000000108001"),
    "bryan ovalle": ("Bryan Ovalle", "2543412000000108001"),
}

SECTION_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:Action Items?|Next Actions|Next Steps)\s*:?\s*$",
    re.IGNORECASE,
)

MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")

MAJOR_HEADING_RE = re.compile(
    r"^\s*(?:\d+[.)]\s+)?(?:"
    r"Summary|Meeting Summary|Notes|Decisions|Key Takeaways|Transcript|Agenda"
    r")\s*:?\s*$",
    re.IGNORECASE,
)

HEADING_CONNECTORS = {"and", "or", "of", "the", "to", "for", "in", "on", "&"}

BULLET_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-*•]|\d+[.)])\s+(?P<body>\S.*)$"
)

METADATA_RE = re.compile(
    r"^(?P<label>Owners?|Assignees?|Due(?:\s+Date)?)\s*:\s*(?P<value>.*)$",
    re.IGNORECASE,
)

INLINE_SEPARATOR_RE = re.compile(r"\s+(?:—|–)\s+|\s+-\s+(?=(?:Owners?|Assignees?|Due(?:\s+Date)?)\s*:)", re.IGNORECASE)

OWNER_SPLIT_RE = re.compile(r"\s*(?:,|;|/|&|\+|\band\b)\s*", re.IGNORECASE)

EMBEDDED_ACTION_FORMS = {
    "conduct": "Conduct",
    "conducting": "Conduct",
    "confirm": "Confirm",
    "confirming": "Confirm",
    "evaluate": "Evaluate",
    "evaluating": "Evaluate",
    "fix": "Fix",
    "fixing": "Fix",
    "implement": "Implement",
    "implementing": "Implement",
    "mass import": "Mass import",
    "mass importing": "Mass import",
    "refine": "Refine",
    "refining": "Refine",
    "test": "Test",
    "testing": "Test",
    "validate": "Validate",
    "validating": "Validate",
}

_EMBEDDED_FORMS_PATTERN = "|".join(
    sorted((re.escape(value) for value in EMBEDDED_ACTION_FORMS), key=len, reverse=True)
)
EMBEDDED_ACTION_START_RE = re.compile(
    rf"^(?:to\s+)?(?:{_EMBEDDED_FORMS_PATTERN})\b",
    re.IGNORECASE,
)
NEXT_STEPS_RE = re.compile(
    r"\b(?:key\s+)?next steps\s*(?:include|are|:)\s*(?P<actions>.+)$",
    re.IGNORECASE,
)
PLANS_TO_RE = re.compile(r"\bplans to\s+(?P<actions>.+)$", re.IGNORECASE)
IS_PLANNED_TO_RE = re.compile(
    r"^(?P<subject>.+?)\s+is planned to\s+(?P<actions>.+)$",
    re.IGNORECASE,
)
FUTURE_ACTION_RE = re.compile(
    r"\b(?:will|must|should|need to|needs to)\s+(?P<actions>.+)$",
    re.IGNORECASE,
)
NEEDS_VALIDATION_RE = re.compile(
    r"^(?P<subject>.+?)\s+(?:requires?|requiring|needs?)\s+(?:further\s+)?validation\b",
    re.IGNORECASE,
)
EXPLICIT_BLAKE_RE = re.compile(r"\bBlake(?:\s+Allard)?\b", re.IGNORECASE)
EMBEDDED_DUE_RE = re.compile(
    r"\s+(?:[—–-]\s*)?Due(?:\s+Date)?\s*:\s*(?P<due>.+)$",
    re.IGNORECASE,
)


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _action_hash(source_file_name: str, action_text: str) -> str:
    identity = f"{_normalized_text(source_file_name)}\n{_normalized_text(action_text)}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _is_major_heading(line: str) -> bool:
    if MARKDOWN_HEADING_RE.match(line) or MAJOR_HEADING_RE.match(line):
        return True

    # Zia plain-text summaries can use unmarked headings. Restrict generic
    # detection to short, unindented title-style lines so prose is not treated
    # as a boundary. Bulleted lines are excluded by the section scanner.
    if line != line.lstrip() or len(line.strip()) > 80:
        return False
    candidate = re.sub(r"^\d+[.)]\s+", "", line.strip().rstrip(":"))
    if not candidate or candidate.endswith((".", "?", "!")):
        return False
    words = candidate.split()
    if not 1 <= len(words) <= 8:
        return False
    return all(
        word.casefold() in HEADING_CONNECTORS
        or word[:1].isupper()
        or word.isupper()
        for word in words
    )


def _action_sections(text: str) -> list[list[str]]:
    sections: list[list[str]] = []
    current: list[str] | None = None

    for line in text.splitlines():
        if SECTION_HEADING_RE.match(line):
            current = []
            sections.append(current)
            continue
        if current is not None and not BULLET_RE.match(line) and _is_major_heading(line):
            current = None
            continue
        if current is not None:
            current.append(line)

    return sections


def _metadata_from_line(line: str) -> tuple[str, str] | None:
    candidate = line.strip()
    bullet = BULLET_RE.match(candidate)
    if bullet:
        candidate = bullet.group("body").strip()
    match = METADATA_RE.match(candidate)
    if not match:
        return None
    label = match.group("label").casefold()
    kind = "due" if label.startswith("due") else "owner"
    return kind, match.group("value").strip()


def _split_inline_metadata(body: str) -> tuple[str, list[str], list[str]]:
    parts = [part.strip() for part in INLINE_SEPARATOR_RE.split(body) if part.strip()]
    if not parts:
        return body.strip(), [], []

    action_parts = [parts[0]]
    owner_values: list[str] = []
    due_values: list[str] = []
    unlabeled: list[str] = []

    for part in parts[1:]:
        metadata = METADATA_RE.match(part)
        if metadata:
            label = metadata.group("label").casefold()
            value = metadata.group("value").strip()
            (due_values if label.startswith("due") else owner_values).append(value)
        else:
            unlabeled.append(part)

    # The brief explicitly supports "Action — Bill". Positional owner matching
    # is limited to known aliases so arbitrary action text is never inferred to
    # be a person. A following positional segment is retained as raw due text.
    if not owner_values and unlabeled:
        owner_tokens = _split_owner_tokens(unlabeled[0])
        if owner_tokens and all(_owner_key(token) in OWNER_MAP for token in owner_tokens):
            owner_values.append(unlabeled.pop(0))
            if unlabeled and not due_values:
                due_values.append(unlabeled.pop(0))

    if unlabeled:
        action_parts.extend(unlabeled)

    return " — ".join(action_parts).strip(), owner_values, due_values


def _owner_key(owner: str) -> str:
    return _normalized_text(owner).strip(" .")


def _split_owner_tokens(raw_owner: str) -> list[str]:
    return [token.strip() for token in OWNER_SPLIT_RE.split(raw_owner) if token.strip()]


def _resolve_owners(owner_values: Iterable[str]) -> tuple[str | None, str, list[dict[str, str | None]], str | None]:
    raw_values = [value.strip() for value in owner_values if value.strip()]
    tokens: list[str] = []
    for raw_value in raw_values:
        tokens.extend(_split_owner_tokens(raw_value))

    detected: list[dict[str, str | None]] = []
    seen_identities: set[str] = set()
    for token in tokens:
        known = OWNER_MAP.get(_owner_key(token))
        canonical_name, owner_id = known if known else (token, None)
        identity = f"id:{owner_id}" if owner_id else f"unknown:{_owner_key(token)}"
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        detected.append(
            {
                "name": token,
                "canonical_name": canonical_name if known else None,
                "owner_id": owner_id,
                "resolution": "matched" if known else "unresolved",
            }
        )

    owner_raw = "; ".join(raw_values) or None
    if not detected:
        return owner_raw, "missing", detected, None
    if len(detected) > 1:
        return owner_raw, "multiple", detected, None
    if detected[0]["owner_id"] is None:
        return owner_raw, "unresolved", detected, None
    return owner_raw, "matched", detected, detected[0]["owner_id"]


def _combine_raw(values: Iterable[str]) -> str | None:
    unique: list[str] = []
    for value in values:
        clean = value.strip()
        if clean and clean not in unique:
            unique.append(clean)
    return "; ".join(unique) or None


def _make_item(
    source_file_name: str,
    body: str,
    nested_owner_values: list[str],
    nested_due_values: list[str],
) -> dict[str, object] | None:
    action_text, inline_owner_values, inline_due_values = _split_inline_metadata(body)
    if not action_text:
        return None

    owner_raw, owner_resolution, detected_owners, owner_id = _resolve_owners(
        [*inline_owner_values, *nested_owner_values]
    )
    due_date_text = _combine_raw([*inline_due_values, *nested_due_values])

    return {
        "action_text": action_text,
        "owner_raw": owner_raw,
        "owner_resolution": owner_resolution,
        "owner_id": owner_id,
        "detected_owners": detected_owners,
        "due_date_text": due_date_text,
        "source_file_name": source_file_name,
        "action_hash": _action_hash(source_file_name, action_text),
    }


def _parse_section(lines: list[str], source_file_name: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    current_body: list[str] = []
    current_indent: int | None = None
    owner_values: list[str] = []
    due_values: list[str] = []

    def flush() -> None:
        nonlocal current_body, current_indent, owner_values, due_values
        if current_body:
            item = _make_item(
                source_file_name,
                " ".join(current_body).strip(),
                owner_values,
                due_values,
            )
            if item is not None:
                items.append(item)
        current_body = []
        current_indent = None
        owner_values = []
        due_values = []

    for line in lines:
        bullet = BULLET_RE.match(line)
        if bullet:
            indent = len(bullet.group("indent").expandtabs(4))
            body = bullet.group("body").strip()
            metadata = _metadata_from_line(body)
            if metadata and current_body:
                kind, value = metadata
                (due_values if kind == "due" else owner_values).append(value)
                continue
            if metadata:
                # A metadata bullet without a preceding action is not itself an
                # explicit action item.
                continue
            if current_body and current_indent is not None and indent > current_indent:
                # Nested non-metadata bullets are context, not top-level actions.
                continue
            flush()
            current_body = [body]
            current_indent = indent
            continue

        if not current_body or not line.strip():
            continue

        metadata = _metadata_from_line(line)
        if metadata:
            kind, value = metadata
            (due_values if kind == "due" else owner_values).append(value)
        elif line[:1].isspace():
            # Retain wrapped action text, but never promote unbulleted prose to
            # a new action item.
            current_body.append(line.strip())

    flush()
    return items


def _clean_embedded_clause(clause: str) -> str | None:
    clean = clause.strip().strip("-–—• ").rstrip(". ;:")
    clean = re.sub(r"^(?:and\s+|to\s+)", "", clean, flags=re.IGNORECASE)
    if not clean:
        return None

    lowered = clean.casefold()
    for form in sorted(EMBEDDED_ACTION_FORMS, key=len, reverse=True):
        if lowered == form or lowered.startswith(f"{form} "):
            remainder = clean[len(form):]
            return f"{EMBEDDED_ACTION_FORMS[form]}{remainder}".strip()
    return None


def _split_embedded_actions(value: str) -> list[str]:
    parts = re.split(
        rf"\s*;\s*|\s*,\s*(?:and\s+)?|\s+and\s+(?=(?:to\s+)?(?:{_EMBEDDED_FORMS_PATTERN})\b)",
        value,
        flags=re.IGNORECASE,
    )
    actions: list[str] = []
    for part in parts:
        action = _clean_embedded_clause(part)
        if action and action not in actions:
            actions.append(action)
    return actions


def _generic_planned_action(value: str) -> str | None:
    clean = value.strip().rstrip(". ;:")
    clean = re.sub(r"^to\s+", "", clean, flags=re.IGNORECASE)
    if not clean:
        return None
    return clean[:1].upper() + clean[1:]


def _embedded_action_texts(body: str) -> list[str]:
    candidate = body.strip()
    next_steps = NEXT_STEPS_RE.search(candidate)
    if next_steps:
        return _split_embedded_actions(next_steps.group("actions"))

    plans_to = PLANS_TO_RE.search(candidate)
    if plans_to:
        action_value = plans_to.group("actions")
        actions = _split_embedded_actions(action_value)
        if actions:
            return actions
        fallback = _generic_planned_action(action_value)
        return [fallback] if fallback else []

    planned = IS_PLANNED_TO_RE.match(candidate.rstrip(". "))
    if planned:
        subject = planned.group("subject").strip()
        planned_value = planned.group("actions").strip().rstrip(". ;:")
        actions = _split_embedded_actions(planned_value)
        if subject.casefold().startswith(("a mass import", "the mass import", "mass import")):
            mass_import = re.sub(r"^(?:a|the)\s+", "", subject, flags=re.IGNORECASE)
            planned_value = planned_value[:1].lower() + planned_value[1:]
            return [f"Mass import{mass_import[len('mass import'):]} to {planned_value}"]
        if not actions:
            fallback = _generic_planned_action(planned_value)
            return [fallback] if fallback else []
        return actions

    validation = NEEDS_VALIDATION_RE.match(candidate.rstrip(". "))
    if validation:
        subject = validation.group("subject").strip().strip("-–—• ").rstrip(",")
        remains_in = re.match(r"(?P<issue>.+?)\s+remains in\s+(?P<target>.+)$", subject, re.IGNORECASE)
        if remains_in:
            issue = remains_in.group("issue").strip().lower()
            target = remains_in.group("target").strip().lower()
            return [f"Validate {target} for {issue}"]
        if not subject.isupper():
            subject = subject[:1].lower() + subject[1:]
        return [f"Validate {subject}"]

    future = FUTURE_ACTION_RE.search(candidate)
    if future:
        return _split_embedded_actions(future.group("actions"))

    if EMBEDDED_ACTION_START_RE.match(candidate):
        action = _clean_embedded_clause(candidate)
        return [action] if action else []
    return []


def _make_embedded_item(
    source_file_name: str,
    action_text: str,
    original_source_text: str,
    due_date_text: str | None,
) -> dict[str, object]:
    explicit_blake = EXPLICIT_BLAKE_RE.search(original_source_text)
    detected_owners: list[dict[str, str | None]] = []
    owner_raw: str | None = None
    owner_id: str | None = None
    owner_resolution = "missing"
    if explicit_blake:
        owner_raw = explicit_blake.group(0)
        owner_id = OWNER_MAP["blake"][1]
        owner_resolution = "matched"
        detected_owners = [
            {
                "name": owner_raw,
                "canonical_name": "Blake Allard",
                "owner_id": owner_id,
                "resolution": "matched",
            }
        ]

    return {
        "action_text": action_text,
        "owner_raw": owner_raw,
        "owner_resolution": owner_resolution,
        "owner_id": owner_id,
        "detected_owners": detected_owners,
        "due_date_text": due_date_text,
        "source_file_name": source_file_name,
        "original_source_text": original_source_text,
        "extraction_mode": "embedded_zoho_ai",
        "action_hash": _action_hash(source_file_name, action_text),
    }


def _parse_embedded_actions(text: str, source_file_name: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    inside_strict_section = False
    seen_hashes: set[str] = set()

    for line in text.splitlines():
        if SECTION_HEADING_RE.match(line):
            inside_strict_section = True
            continue
        if inside_strict_section:
            if not BULLET_RE.match(line) and _is_major_heading(line):
                inside_strict_section = False
            else:
                continue

        bullet = BULLET_RE.match(line)
        if not bullet:
            continue
        body = bullet.group("body").strip()
        original_source_text = line.strip()
        due_match = EMBEDDED_DUE_RE.search(body)
        due_date_text = None
        if due_match:
            due_date_text = due_match.group("due").strip().rstrip(".") or None
            body = body[:due_match.start()].rstrip()
        for action_text in _embedded_action_texts(body):
            item = _make_embedded_item(
                source_file_name,
                action_text,
                original_source_text,
                due_date_text,
            )
            action_hash = str(item["action_hash"])
            if action_hash not in seen_hashes:
                items.append(item)
                seen_hashes.add(action_hash)
    return items


def parse_summary(path: Path) -> list[dict[str, object]]:
    if not path.name.endswith("_summary.txt"):
        raise ValueError(f"expected an _summary.txt file: {path}")
    if not path.is_file():
        raise ValueError(f"file not found: {path}")

    text = path.read_text(encoding="utf-8")
    items: list[dict[str, object]] = []
    for section in _action_sections(text):
        items.extend(_parse_section(section, path.name))
    items.extend(_parse_embedded_actions(text, path.name))
    return items


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse explicit action items from local Zoho summary files."
    )
    parser.add_argument("files", nargs="+", type=Path, help="local *_summary.txt files")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    output: list[dict[str, object]] = []
    try:
        for path in args.files:
            output.extend(parse_summary(path))
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    json.dump(output, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
