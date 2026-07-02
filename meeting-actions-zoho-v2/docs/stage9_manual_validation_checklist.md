# Stage 9 Manual Deluge Runtime Validation Checklist

Use this checklist to execute the existing Stage 8 Deluge parser/QC draft once in an authorized inert Zoho test surface. This is runtime validation only. Do not attach the function to Flow, WorkDrive, Projects, a schedule, a button, or any data event.

The Stage 9 blocker and parser contract remain documented in [`docs/zoho_deluge_parser.md`](zoho_deluge_parser.md). Record the run using [`docs/stage9_runtime_results_template.md`](stage9_runtime_results_template.md).

## 1. Verify Exact Artifacts

Use the files from commit `b77da95` or a descendant that has not changed these artifacts.

| Artifact | SHA-256 at `b77da95` |
| --- | --- |
| `deluge/parse_meeting_summary.deluge` | `476037f7368ef0516b89810e6f4e26ff8aff681099de8d37f77b6cf424e419f4` |
| `samples/deluge/stage8_workdrive_flow_input.json` | `013822ae92d93ce955a87a9617e6bbde9accf338b8f4a91c5dfc58097c42b8b5` |
| `samples/deluge/stage8_expected_projection.json` | `c7833f7721d3a2a55bf0f12fcd9017402dc2697689a94b78fb7c9577705ee41f` |

Optional local verification:

```bash
shasum -a 256 \
  deluge/parse_meeting_summary.deluge \
  samples/deluge/stage8_workdrive_flow_input.json \
  samples/deluge/stage8_expected_projection.json
```

Do not continue with unexplained checksum differences.

## 2. Confirm the Test Surface Is Inert

- [ ] The tester is explicitly authorized to use this Zoho editor/runtime.
- [ ] The function is not connected to a Flow, WorkDrive workflow, Projects action, schedule, webhook, button, or record event.
- [ ] The test surface can execute supplied input and display the returned map without creating or updating Zoho data.
- [ ] No connection, OAuth credential, `invokeurl`, or Projects operation is added.
- [ ] No registry or processed-file persistence is added.
- [ ] The test uses only the sanitized checked-in input fixture.

If execution requires saving, deploying, publishing, or attaching the function, stop. Obtain explicit authorization for that configuration change before proceeding.

## 3. Apply Only Necessary Signature Adaptation

Record which editor behavior applies:

- [ ] The editor accepts the complete declaration. Paste all of `deluge/parse_meeting_summary.deluge`.
- [ ] The editor configures function metadata separately. Configure one map input named `flow_input` and a map/key-value return, then paste only the statements inside the outermost braces.

Do not change inner parser or QC logic to address an assumed syntax requirement. If compilation fails, record the exact product, editor, line, and message before proposing a parity fix.

## 4. Load the Sanitized Input

Use the editor's map-input test UI to load the complete object from:

```text
samples/deluge/stage8_workdrive_flow_input.json
```

The input map must contain exactly the fixture's `file_id`, `file_name`, `file_path`, and `file_text`. Do not fetch WorkDrive content and do not invent a Deluge wrapper expression if the editor does not accept raw map input.

## 5. Execute One Function Test

- [ ] Execute only the parser/QC function test.
- [ ] Capture the complete returned map or the complete compiler/runtime error.
- [ ] Do not retry with logic edits during the evidence-capture run.

## 6. Compare the Required Projection

Compare against `samples/deluge/stage8_expected_projection.json`.

| Check | Expected |
| --- | --- |
| `dry_run` | `true` |
| `parser_version` | `deluge-stage8-v2` |
| `errors` | `[]` |
| `raw_action_count` | `13` |
| `selected_action_count` | `8` |
| `skipped_candidate_count` | `5` |
| `item_count` | `8` |
| `payload_input_items` | Deep-equal to `parsed_actions_selected` |
| `items` | Deep-equal to `parsed_actions_selected` |

Then verify:

- [ ] Selected action text and order match `selected_action_texts` in the expected projection.
- [ ] Each skipped action text, reason, and selected replacement match `skipped_candidate_reviews` in the expected projection.
- [ ] Raw action text, owner resolution, due text, source evidence, and action hash match `samples/expected/workdrive_blake_zoho_ai_summary.json`.
- [ ] Selected QC metadata and ordering match `samples/expected/workdrive_blake_zoho_ai_qc.json`.
- [ ] `fallback_idempotency_key` is present on Deluge items; ignore it only when comparing against Python-only fixtures.

Do not treat reordered lists, different hashes, or missing fields as success. Record them as runtime differences.

## 7. Confirm Safety Evidence

- [ ] No Zoho Projects task or other object was created.
- [ ] No Zoho data or configuration was modified.
- [ ] No network request or connector call occurred.
- [ ] No Flow/WorkDrive wiring was created.
- [ ] No registry state was persisted.

## 8. Record the Outcome

Copy [`docs/stage9_runtime_results_template.md`](stage9_runtime_results_template.md) to a dated results document only after a test is authorized. Record pass, fail, or blocked without overstating what was verified.

Stage 9 passes only when the runtime accepts the function and the returned projection matches all required checks. Compiler failure, required deployment, unavailable test input, or output mismatch leaves Stage 9 pending.
