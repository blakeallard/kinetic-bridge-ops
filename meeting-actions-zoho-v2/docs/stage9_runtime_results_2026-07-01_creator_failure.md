# Stage 9 Zoho Creator Runtime Validation — Parity Failure

## Disposition

**FAIL — the function compiled and executed, but returned zero actions instead of the expected parser/QC projection.**

This document records the supplied runtime evidence and the subsequent Stage 9E
classification fix. Runtime parity remains pending until the fixed function is
executed again in Creator.

## Runtime Context

| Field | Recorded value |
| --- | --- |
| Date | 2026-07-01 |
| Zoho product | Zoho Creator |
| Sandbox app | `Deluge Validation Sandbox` |
| Function | `stage9_parser_validation` |
| Function save/compile | Successful; no compile error reported |
| Parser version returned | `deluge-stage8-v2` |
| Repository baseline | `14baf3e` on `main` |

No Projects task creation, Flow/WorkDrive wiring, registry persistence, or external LLM behavior exists in the tested function source.

## Actual Runtime Return

```json
{
  "dry_run": true,
  "parser_version": "deluge-stage8-v2",
  "file_id": "dqftz0624072c37654c0ca469052b49bd0418",
  "file_name": "Zoho AI - Bevco <> MWS - LA Tech Week Weekly Tag-Up_summary.txt",
  "file_path": "06-30 - Blake's Weekly Catch-Up",
  "parsed_actions_raw": [],
  "raw_action_count": 0,
  "skipped_candidate_reviews": [],
  "skipped_candidate_count": 0,
  "parsed_actions_selected": [],
  "selected_action_count": 0,
  "payload_input_items": [],
  "items": [],
  "item_count": 0,
  "errors": []
}
```

## Expected Versus Actual

| Check | Expected | Actual | Result |
| --- | --- | --- | --- |
| `dry_run` | `true` | `true` | Pass |
| `parser_version` | `deluge-stage8-v2` | `deluge-stage8-v2` | Pass |
| `errors` | `[]` | `[]` | Pass |
| `raw_action_count` | `13` | `0` | Fail |
| `selected_action_count` | `8` | `0` | Fail |
| `skipped_candidate_count` | `5` | `0` | Fail |
| `item_count` | `8` | `0` | Fail |
| `payload_input_items == parsed_actions_selected` | `true` | `true` for two empty lists | Structurally pass; no parity value |
| `items == parsed_actions_selected` | `true` | `true` for two empty lists | Structurally pass; no parity value |

## Current Diagnosis

### Diagnostic retry result

The subsequent Creator diagnostic retry confirmed that `file_text` was present,
non-empty, normalized, and split into the expected lines. Creator nevertheless
returned:

```json
{
  "bullet_candidate_count": 0,
  "raw_action_count": 0,
  "selected_action_count": 0,
  "skipped_candidate_count": 0,
  "item_count": 0,
  "errors": []
}
```

The expected bullet count for the same input is `13`. This isolates the first
failure to Creator's runtime evaluation of the Deluge bullet `matches(...)`
expression; it is not an input-map, text-presence, newline-normalization, or
line-splitting failure.

Stage 9E replaces that expression at all three bullet-classification sites with
deterministic trimmed-string checks for `- `, `* `, `• `, `[digits]. `, and
`[digits]) `. Bullet prefix removal uses the same calculated string offset, so
it no longer depends on the equivalent regex. QC selection logic is unchanged.

The diagnostic return now also includes:

- `symbol_bullet_candidate_count` (expected `10`)
- `numbered_candidate_count` (expected `3`)
- `first_detected_bullet_line` (expected `1. The team reviewed an internal workflow and its current implementation.`)

### Superseded pre-diagnostic hypotheses

Before the diagnostic retry, the empty `errors` list proved only that
`flow_input.get("file_text")` returned a non-null value. It did **not** prove
that value was non-empty, contained the expected 1,287 characters, or contained
actual newline characters.

At that point, the zero raw-action result was consistent with several causes:

1. Creator supplied `file_text` as an empty string.
2. Creator supplied one string containing literal backslash-plus-`n` sequences instead of actual newlines, so `toList("\n")` produced one line.
3. Line splitting succeeded, but Creator's regex behavior detected zero bullet candidates.
4. Bullet detection succeeded, but a later embedded-action branch behaved differently in Creator.

The diagnostic retry eliminated causes 1, 2, and 4 at the first failing
boundary and confirmed cause 3. These hypotheses are retained only as the
investigation record.

Metadata fields being present does not distinguish these cases. Parser logic must not be changed until runtime diagnostics identify the first failing boundary.

## Diagnostic-Only Change

The parity-debug branch adds an opt-in `diagnostic_mode` return with:

- `file_text_present`
- `file_text_non_empty`
- `file_text_length`
- `normalized_text_length`
- `line_count`
- `actual_newline_count`
- `escaped_newline_sequence_count`
- `first_200_chars`
- `bullet_candidate_count`

The diagnostics do not convert escaped newlines and do not alter parser/QC selection.

For the correctly decoded sanitized fixture, expected diagnostics are recorded in `samples/deluge/stage9_expected_diagnostics.json`:

| Diagnostic | Expected |
| --- | --- |
| `file_text_present` | `true` |
| `file_text_non_empty` | `true` |
| `file_text_length` | `1287` |
| `normalized_text_length` | `1287` |
| `line_count` | `19` |
| `actual_newline_count` | `18` |
| `escaped_newline_sequence_count` | `0` |
| `bullet_candidate_count` | `13` |
| `symbol_bullet_candidate_count` | `10` |
| `numbered_candidate_count` | `3` |
| `first_detected_bullet_line` | `1. The team reviewed an internal workflow and its current implementation.` |

## Exact Next Retry

1. In the existing Creator sandbox function only, replace the function body with the diagnostic branch version of `deluge/parse_meeting_summary.deluge`. Do not attach it to any event or workflow.
2. Use `samples/deluge/stage9_diagnostic_flow_input.json` as the input map. It is identical to the Stage 8 fixture plus boolean `diagnostic_mode: true`.
3. Ensure `flow_input` is a Creator map/key-value argument. Its `file_text` value must be the fixture's multiline text value, not the entire JSON object serialized into one text field.
4. Execute the function once and capture the complete returned map.
5. Compare all diagnostic fields with `samples/deluge/stage9_expected_diagnostics.json` before evaluating parser counts.
6. Confirm `bullet_candidate_count=13`, with `10` symbol and `3` numbered bullets, before comparing the expected parser/QC counts (`13` raw, `8` selected, `5` skipped, `8` items).
7. Capture the complete returned map. Do not add the function to any event or workflow.

| Runtime observation | Isolated conclusion | Next action |
| --- | --- | --- |
| `file_text_present=false` | Creator map key/binding is wrong | Correct the map argument/key only |
| `file_text_non_empty=false` or length `0` | Creator passed an empty value | Correct the map value only |
| `line_count=1`, actual newlines `0`, escaped sequences `>0` | Literal `\n` encoding confirmed | Add and test a deterministic escaped-newline normalization fix in a follow-up commit |
| `line_count=19`, bullets `0` | The Stage 9E string classifier still differs in Creator | Capture the three new bullet diagnostics; do not change QC logic |
| `line_count=19`, bullets `13`, raw actions `0` | Failure occurs after line splitting/bullet recognition | Add branch counters for embedded phrase recognition in a follow-up diagnostic |
| Diagnostics match and raw count `13` | Input boundary works in diagnostic revision | Compare QC counts/order and record remaining differences |

If literal escaped newlines are confirmed, the fix must be narrowly scoped to converting literal `\r\n`, `\n`, and `\r` only when actual newline count is zero and escaped sequences are present. Do not apply that conversion speculatively before the diagnostic return is captured.

## Safety Result

The executed parser returned maps/lists only. No task/network/write operation is present in the function. Stage 9 remains failed/pending until a retry produces the expected projection or a narrower runtime difference is recorded.
