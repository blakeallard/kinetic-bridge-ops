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

## Source Validation Result

The downloaded file contained no standalone approved action heading:

- `Action Items`
- `Action Item`
- `Next Actions`
- `Next Steps`

It did contain phrases such as “key next steps” inside numbered prose and bullets. The parser correctly rejected those phrases because v2 extracts actions only from an explicit approved section. Therefore this real source produces zero parsed actions and zero task payload candidates. This is a source-format validation result, not a parser failure.

The sanitized fixture preserves that boundary behavior:

```text
samples/real_inputs/Zoho AI - Bevco <> MWS - LA Tech Week Weekly Tag-Up_summary.txt
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
parsed actions:                 0
skipped duplicates:             0
payloads that would be created: 0
unresolved blockers:            0
task-creation client calls:      0
registry persisted:              false
```

`payloads_that_would_be_created` is an empty list. No tasks would be created from this source because it lacks an approved action section.

The dry-run output also records the downstream target configuration that would apply if explicit actions were present:

- status: `In Progress`, ID `2543412000000031001`, verified;
- tag: `automation`, ID `2543412000001391053`;
- tag: `internal-work`, ID `2543412000001391061`.

No other tags are configured. No Projects network request occurred.

## Test

The sanitized-fixture tests verify Blake-target enforcement before parsing, the zero-action boundary, one received WorkDrive file, empty payload candidate list, exact status/tag configuration, zero URL opens, zero task-client calls, and no registry persistence:

```bash
python3 -m unittest tests.test_workdrive_real_file_dry_run -v
```
