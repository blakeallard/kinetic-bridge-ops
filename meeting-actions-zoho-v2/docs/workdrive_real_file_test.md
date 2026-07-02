# WorkDrive Real-File Dry-Run Test

## Scope

Stage 7 validates the local pipeline against one WorkDrive source file selected only after read-only candidate discovery:

```text
https://workdrive.zoho.com/file/dqftz0624072c37654c0ca469052b49bd0418
```

WorkDrive is the source of truth. This path does not access Zoho Meeting, create or update Zoho data, create Projects tasks, persist registry state, or expose a live execution option.

## Blake-Only Selection Rule

Before downloading or parsing content, at least one authoritative WorkDrive value must contain `Blake` case-insensitively:

- file name;
- folder name; or
- folder path.

A file with no `Blake` match is a rejected non-target. The local runner enforces the same rule before opening the input file. Supplying a file ID is not sufficient evidence by itself.

The previous sanitized fixture's file name does not contain `Blake`. Read-only metadata now verifies that its direct parent folder is `06-30 - Blake's Weekly Catch-Up`, so it is an eligible target only when that folder evidence is supplied. Without that verified folder path, the fixture is rejected.

## Candidate Discovery

Candidate discovery occurred before the revised dry-run:

1. `ZohoWorkdrive_getFileOrFolderDetails` verified parent folder `dqftz8a3fe44dff574df684aa2649bc0aa1ce` is named `06-30 - Blake's Weekly Catch-Up`.
2. `ZohoWorkdrive_getFolderFiles` listed the folder contents read-only.
3. Summary candidates were filtered locally; transcript, metadata, and video files were excluded.

| Candidate file | Resource ID | Blake match | Decision |
| --- | --- | --- | --- |
| `Blake's Weekly Catch-Up_summary.txt` | `dqftz6ef834d940e5439ab1709f03a78d5f1c` | File and folder name | Eligible, not selected |
| `Zoho AI - Bevco <> MWS - LA Tech Week Weekly Tag-Up_summary.txt` | `dqftz0624072c37654c0ca469052b49bd0418` | Parent folder name | Selected; explicit Zoho AI summary |

Only the selected eligible file was used for the revised dry-run.

## Read-Only Fetch Procedure

The file resource ID is the final URL segment: `dqftz0624072c37654c0ca469052b49bd0418`.

Using the `zoho_all` MCP connection:

1. Call the read-only `ZohoWorkdrive_getFileOrFolderDetails` tool with that resource ID.
2. Verify the returned resource is a readable, downloadable text file whose name ends in `_summary.txt`.
3. Call the read-only `ZohoWorkdrive_downloadWorkDriveFile` tool with the same resource ID.
4. Read the returned `mime_type` and base64-encoded `content` fields.
5. Base64-decode `content` as UTF-8 text.
6. If retaining a local test input, place it only under `samples/real_inputs/` and sanitize confidential meeting prose while preserving the parser-relevant structure.

The Stage 7 read returned:

- MIME type: `text/plain`;
- source name: `Zoho AI - Bevco <> MWS - LA Tech Week Weekly Tag-Up_summary.txt`;
- source size: 16,492 bytes; and
- readable/downloadable metadata.

No WorkDrive write tool was called. The retained fixture is a sanitized structural derivative, not a verbatim archive of the meeting summary.

## Parser Format Fix

The downloaded file contained no standalone approved action heading:

- `Action Items`
- `Action Item`
- `Next Actions`
- `Next Steps`

The original strict parser accepted only those headings, so its first real-file run safely returned zero actions. That behavior remains intact for clean action sections, but it was insufficient for real Zoho AI output because Zoho commonly embeds future work inside ordinary summary bullets.

The deterministic parser now performs a second, conservative Zoho AI embedded-action pass over bullets outside strict action sections. It recognizes explicit future-work forms such as:

- `next steps include` and `next steps:`;
- `plans to` and `is planned to`;
- `requires validation`, `requiring validation`, and `needs validation`;
- direct or listed actions beginning with `implement`, `refine`, `test`, `validate`, `fix`, `evaluate`, `confirm`, `conduct`, or `mass import`.

Compound next-step lists are split into individual imperative candidates. Past-tense status/history statements remain excluded unless they contain an explicit future-work construction. Every embedded candidate retains its original source bullet in `original_source_text` and is labeled `extraction_mode: embedded_zoho_ai`.

Blake is assigned only when `Blake` or `Blake Allard` appears in that candidate's source sentence. A Blake folder name or meeting context never assigns ownership. Other candidates remain unassigned. Due text remains unset unless the same bullet has explicit labeled due metadata, such as `Due: Friday`; the parser preserves that text without calculating a date.

The sanitized fixture preserves representative structures from the real summary and includes rejected history/status bullets:

```text
samples/real_inputs/Zoho AI - Bevco <> MWS - LA Tech Week Weekly Tag-Up_summary.txt
```

Its deterministic expected candidates are checked in at `samples/expected/workdrive_blake_zoho_ai_summary.json`.

## Stage 7B Deterministic QC Review

Raw extraction is intentionally diagnostic and can contain overlapping wording from repeated Zoho AI summary sections. Before payload generation, `scripts/review_action_candidates.py` groups candidates only within the same source file and selects the most specific candidate in each deterministic intent group.

The QC stage uses normalized tokens, a fixed intent taxonomy, and explicit specificity weights. It does not call an LLM or infer new work. Retained candidates preserve the parser's source file metadata, original source bullet, owner decision, due text, and action hash. Skipped candidates remain visible with:

- the skipped action and source evidence;
- `reason` (`repeated_summary_candidate` or `overlap_superseded_by_specific_candidate`);
- the QC group; and
- the selected replacement action/hash.

For the sanitized real-format fixture, QC reduces 13 raw actions to these eight selected candidates:

1. `Test field population accuracy`
2. `Refine the part number lookup functionality`
3. `Implement automated pricing imports`
4. `Conduct routing tests`
5. `Evaluate transcription accuracy`
6. `Mass import from the sanitized pricing matrix to populate the full item master`
7. `Fix duplicate routing before launch`
8. `Confirm launch readiness with stakeholders`

The five overlapping candidates are retained in `skipped_candidate_reviews` with their selected replacements. The expected QC decision is checked in at `samples/expected/workdrive_blake_zoho_ai_qc.json`.

The runner's relevant output contract is:

```text
parsed_actions_raw           all deterministic parser results
skipped_candidate_reviews    reasoned QC exclusions
parsed_actions_selected      manager-usable retained candidates
registry_report.payloads_that_would_be_created
                             payloads for selected candidates only
```

## End-to-End Local Command

Run the already-downloaded file through the parser, payload builder, in-memory duplicate registry, and guarded create-task dry-run:

```bash
python3 scripts/run_workdrive_dry_run.py \
  'samples/real_inputs/Zoho AI - Bevco <> MWS - LA Tech Week Weekly Tag-Up_summary.txt' \
  --source-file-id dqftz0624072c37654c0ca469052b49bd0418 \
  --source-folder-path "06-30 - Blake's Weekly Catch-Up" \
  --meeting-name 'Bevco <> MWS - LA Tech Week Weekly Tag-Up'
```

The command has no `--live` option. It invokes the existing create-task guard without live mode, so the guard cannot construct or call the HTTP client.

## Observed Dry-Run Result

```text
received files:                 1
raw parsed actions:            13
QC selected actions:            8
QC skipped reviews:             5
skipped duplicates:             0
payloads that would be created: 8
unresolved owner reviews:        6
task-creation client calls:      0
registry persisted:              false
```

`payloads_that_would_be_created` contains only the eight QC-selected candidates. Two actions are assigned to Blake because he is explicit in their shared source sentence. The other six remain unassigned and appear as owner-review diagnostics. No candidate is assigned from folder or meeting context.

Every generated payload uses the verified downstream target configuration:

- status: `In Progress`, ID `2543412000000031001`, verified;
- tag: `automation`, ID `2543412000001391053`;
- tag: `internal-work`, ID `2543412000001391061`.

No other tags are configured. The descriptions preserve WorkDrive file ID, filename, folder path, original source bullet, normalized task text, owner decision, raw due text, and action hash. No Projects network request occurred.

## Deluge Production Direction

Python remains local proof and fixture generation only. Stage 8 now includes a Deluge draft of both parser passes and the deterministic QC review for the future Zoho Flow/WorkDrive workflow. Its local projection matches the checked-in Python parser/QC fixtures, but actual Zoho Deluge runtime parity must still be recorded before workflow wiring or any live task creation. No OpenAI, Claude, or other external LLM interpretation is part of this design.

## Test

The sanitized-fixture tests verify Blake-target enforcement, unchanged raw parser output, a smaller expected QC selection, reasoned skips, payload generation only for selected hashes, explicit-only Blake ownership, source traceability, exact status/tag configuration, zero URL opens, zero task-client calls, and no registry persistence:

```bash
python3 -m unittest tests.test_workdrive_real_file_dry_run -v
```
