# Zoho/Deluge Parser and QC Draft

## Scope

[`deluge/parse_meeting_summary.deluge`](../deluge/parse_meeting_summary.deluge) is the Stage 8 dry-run port of the validated local parser and deterministic candidate-quality review. It accepts caller-fetched WorkDrive text and returns maps/lists only.

It contains no file download, `invokeurl`, OAuth, Zoho Projects operation, task creation, registry mutation, OpenAI, Claude, or other external LLM dependency.

The Python implementations remain the executable source of truth:

- [`scripts/parse_summary.py`](../scripts/parse_summary.py)
- [`scripts/review_action_candidates.py`](../scripts/review_action_candidates.py)

The Deluge draft is structurally compared with local fixtures but has not been executed in a Zoho Flow or WorkDrive Deluge runtime. Product-runtime parity must be verified before workflow wiring or live task creation.

## Input Contract

The function receives one `flow_input` map:

| Key | Required | Meaning |
| --- | --- | --- |
| `file_id` | Preferred | Stable WorkDrive resource ID |
| `file_name` | Yes | Source name ending in `_summary.txt` |
| `file_path` | No | WorkDrive folder/display path |
| `file_text` | Yes | UTF-8 Zoho AI summary text fetched by the caller |

Expected editor configuration:

```text
name: parse_meeting_summary
argument: flow_input (KEY-VALUE / MAP)
return type: KEY-VALUE / MAP
```

Some Zoho editors provide the outer signature; in that case paste only the function body.

## Output Contract

```text
{
  dry_run: true,
  parser_version: "deluge-stage8-v2",
  file_id: "...",
  file_name: "..._summary.txt",
  file_path: "...",
  parsed_actions_raw: [...],
  raw_action_count: 13,
  skipped_candidate_reviews: [...],
  skipped_candidate_count: 5,
  parsed_actions_selected: [...],
  selected_action_count: 8,
  payload_input_items: [...],
  items: [...],
  item_count: 8,
  errors: []
}
```

`payload_input_items` and the backward-compatible `items` field both reference selected actions only. Future Deluge payload construction must consume one of those selected lists, never `parsed_actions_raw`.

## Parsing Passes

### Strict section pass

The original behavior remains:

1. Enter only `Action Items`, `Action Item`, `Next Actions`, or `Next Steps` sections.
2. Stop at Markdown, known major, or conservative plain Title Case headings.
3. Accept top-level dash, star, bullet, or numbered actions.
4. Preserve nested/inline owner and due metadata.
5. Ignore nested contextual bullets and metadata without a preceding action.
6. Resolve configured aliases while retaining unknown and multiple-owner evidence.

### Embedded Zoho AI pass

Outside strict sections, the port scans only numbered or bulleted summary lines. It recognizes the same deterministic future-work families as Python:

- `next steps include`, `next steps are`, and `next steps:`;
- `plans to` and `is planned to`;
- `will`, `must`, `should`, `need to`, and `needs to` followed by allowed action wording;
- `require(s) validation`, `requiring validation`, `need(s) validation`;
- direct `conduct`, `confirm`, `evaluate`, `fix`, `implement`, `mass import`, `refine`, `test`, or `validate` forms, including supported gerunds.

Delimited compound actions are split and normalized to imperative wording. Pure history/status bullets remain excluded. Each embedded action preserves `original_source_text` and `extraction_mode: embedded_zoho_ai`.

Embedded ownership is conservative: Blake is assigned only when Blake is named in the source action sentence. Folder and meeting context do not assign an owner. Explicit labeled due text is retained but never calculated.

## Deterministic QC Port

The QC pass mirrors the Python constants and decision order:

- token equivalences for common plural/gerund/update forms;
- source-scoped intent groups such as `field_data_validation`, `automated_import`, `part_number_lookup`, `routing_test`, `routing_remediation`, `transcription_evaluation`, `mass_import`, and `launch_confirmation`;
- fixed specificity weights for phrases such as `field population`, `pricing import`, `part number`, `duplicate routing`, and `item master`;
- deterministic tie-breaking by concrete-token count, text length, then original order.

Every retained item receives:

```text
qc_review: {
  group_key: "...",
  group_size: N,
  selection_reason: "unique_candidate" | "most_specific_deterministic_candidate"
}
```

Every excluded candidate is retained in `skipped_candidate_reviews` with source evidence, reason, group, and selected replacement. Reasons are:

- `repeated_summary_candidate`
- `overlap_superseded_by_specific_candidate`

## Item and Idempotency Fields

Raw and selected actions preserve:

- action text;
- raw/resolved/detected owner data;
- raw due text;
- WorkDrive file ID, filename, and folder path;
- original source text and extraction mode for embedded actions;
- action hash; and
- `fallback_idempotency_key`.

The primary hash input remains:

```text
normalized(file_name) + "\n" + normalized(action_text)
```

The draft uses `zoho.encryption.sha256`. If that function is unavailable in the chosen Deluge runtime, set `action_hash` to null during the runtime adaptation and use the complete fallback key:

```text
(file_id when present, otherwise normalized file_name) + "::" + normalized action_text
```

Do not shorten the fallback or use task-name matching.

## Runtime Parity Risks

Deluge does not expose Python's Unicode NFKC normalization through the same text API. The draft uses lowercase conversion and whitespace collapse, which matches the current ASCII-oriented action/hash fixtures; non-ASCII hashes require explicit sandbox comparison. Regex word-boundary behavior, `subString` indexing, map/list ordering, and availability of `zoho.encryption.sha256` must also be checked in the selected Zoho product runtime. A local structural pass is not evidence that Zoho accepted or executed the function.

## Local Parity Harness

The local harness cannot execute Deluge syntax. It verifies that:

- the Deluge source exposes both parser passes, QC groups/reasons, and selected-only payload input;
- no executable live/LLM operation appears;
- the sanitized Flow input matches the real-input fixture; and
- the expected Stage 8 projection is regenerated from the Python source of truth.

Fixtures:

- [`samples/deluge/stage8_workdrive_flow_input.json`](../samples/deluge/stage8_workdrive_flow_input.json)
- [`samples/deluge/stage8_expected_projection.json`](../samples/deluge/stage8_expected_projection.json)
- [`samples/expected/workdrive_blake_zoho_ai_summary.json`](../samples/expected/workdrive_blake_zoho_ai_summary.json)
- [`samples/expected/workdrive_blake_zoho_ai_qc.json`](../samples/expected/workdrive_blake_zoho_ai_qc.json)

Run locally:

```bash
python3 -m unittest tests.test_deluge_stage8_contract -v
python3 -m unittest discover -s tests -v
```

## Required Zoho Runtime Validation

Before Flow/WorkDrive wiring:

1. Paste the draft into an inert sandbox/editor function.
2. Pass `stage8_workdrive_flow_input.json` as the map input.
3. Compare raw action text/hash/owner/due/source fields to the Python raw fixture.
4. Compare selected action text, skip reasons, replacement hashes, and counts to `stage8_expected_projection.json`.
5. Confirm `payload_input_items` and `items` exactly equal `parsed_actions_selected`.
6. Record any regex, list-order, substring, Unicode, or hash difference before changing the Python source of truth.

No WorkDrive fetch, registry write, Projects call, or task creation is part of that validation.
