# Duplicate and Idempotency Registry

## Scope

[`scripts/build_registry_report.py`](../scripts/build_registry_report.py) is a local, in-memory idempotency model and dry-run report generator. It consumes existing parser output and payload-builder output. It does not parse summaries, build task payloads, persist state, call Zoho, create tasks, authenticate, fetch WorkDrive files, or wire a Flow.

The registry input is treated as immutable. The report returns a `proposed_registry_state` to support repeatable local first-run/second-run tests, but `registry_persisted` is always false and the module never writes that state to disk.

## Local Registry Schema

```json
{
  "schema_version": 1,
  "files": [
    {
      "source_file_id": "workdrive-file-id-or-null",
      "source_file_name": "meeting_summary.txt",
      "processed_action_hashes": ["sha256-action-hash"]
    }
  ]
}
```

Sample fixtures:

- [`samples/registry/empty_registry.json`](../samples/registry/empty_registry.json)
- [`samples/registry/example_registry.json`](../samples/registry/example_registry.json)

`source_file_id` is authoritative when present. A filename is the fallback identity when no stable ID is available. A name-only record can be upgraded when the same file later supplies an ID, but records with two different non-null IDs are never merged solely because their filenames match.

## Evaluation Rules

For every parsed action and its aligned dry-run payload:

1. Validate that both lists have the same length.
2. Validate the source filename, optional source ID, action text, owner resolution, and action hash.
3. Confirm that the payload is dry-run and that its description contains the same action hash.
4. Check whether the action hash already exists in the supplied registry.
5. Check whether the same hash was already accepted earlier in the current batch.
6. Skip duplicates and do not include their payloads in `payloads_that_would_be_created`.
7. Accept a new action hash even when its file record already exists.
8. Add accepted hashes only to the returned proposed state.

The action hash is treated as the action-level idempotency key. The existing Python parser currently hashes normalized source filename plus normalized action text. When a stable WorkDrive file ID becomes available in a future integration phase, hash canonicalization should be re-evaluated so same-name files cannot collide. Until then, the registry retains both file identity and action hashes and reports both in every decision.

## Dry-Run Report

`build_processing_report` returns:

| Field | Meaning |
| --- | --- |
| `dry_run` | Always true |
| `summary` | Counts for received files, parsed actions, skipped duplicates, candidate payloads, and blockers |
| `received_files` | File IDs/names, identity keys, and whether each file was seen before |
| `parsed_actions` | Auditable action text, hash, source identity, and owner resolution |
| `skipped_duplicates` | Duplicate action details and either registry or same-batch reason |
| `payloads_that_would_be_created` | Only payloads for newly accepted hashes |
| `unresolved_blockers` | Nonmatched owners and unresolved payload configuration |
| `proposed_registry_state` | Simulated next state; never persisted |
| `registry_persisted` | Always false |

Blockers are reporting data, not inferred resolutions. Missing, unresolved, and multiple owners remain explicit. Missing status/tag IDs from the payload builder are consolidated into configuration blockers.

Example local report command:

```bash
python3 scripts/build_registry_report.py \
  samples/expected/multiple_unknown_summary.json \
  samples/payloads/unassigned_owner_payloads.json \
  samples/registry/empty_registry.json
```

The command reads three local JSON files and prints the report to stdout. It does not modify the registry fixture.

## Future Zoho-Native Registry Options

These options are design targets only. No connector, API, OAuth, `invokeURL`, Flow, or persistence implementation exists in this repository phase.

### Zoho Creator table — preferred

Use a parent file table plus child action rows, or one action-granular table with indexed identity fields.

Suggested file fields:

- `file_id`
- `file_name`
- `file_path`
- `meeting_name`
- `meeting_date`
- `source_hash`
- `status`
- `processed_at`
- `task_count`
- `error_message`

Suggested action fields:

- parent file reference;
- `action_hash`;
- original action text;
- owner resolution;
- processing status;
- resulting Projects task ID; and
- last error/retry metadata.

Creator is preferred because it can represent file/action relationships, validation states, and uniqueness checks more explicitly than a spreadsheet. The eventual implementation must prevent two concurrent events from both claiming the same action; a read-then-create sequence without an atomic uniqueness strategy is not sufficient.

### Zoho Sheet — validation-stage alternative

A Sheet can use one row per action with columns for file ID/name, action hash, status, task ID, timestamp, and error. It is easy to inspect manually and may be sufficient for a small controlled pilot.

Its tradeoffs are weaker concurrency control, less reliable uniqueness enforcement, schema drift from manual edits, and more difficult parent/child status handling. A Sheet implementation must still use the complete stable keys and must not rely on visual row filtering as duplicate prevention.

### Zoho Projects task-description search — fallback only

If the primary registry is unavailable, search existing task descriptions for exact traceability markers:

```text
Source file ID: <stable-id>
Action hash: <hash>
```

This is a defensive reconciliation fallback, not the preferred registry. It requires complete pagination, exact marker matching, and protection against the race where two runs search before either creates a task. It also cannot represent zero-action files, failed actions, or partial processing cleanly. Task-name matching alone is not acceptable.

## Future State Semantics

The local `proposed_registry_state` assumes all candidate payloads would eventually succeed; it exists only for deterministic tests. A live registry must record per-action outcomes and mark a file complete only after all intended actions reach a terminal outcome. Partial failures must remain retryable without recreating successful actions. Zero-action files need an explicit successful terminal record so repeated triggers do not loop forever.

No live state transition is implemented here.

## Tests

Run the full suite with:

```bash
python3 -m unittest discover -s tests -v
```

Registry tests cover:

- first-run payload candidates;
- second-run duplicate suppression;
- duplicate hashes within one batch;
- a new action in an already-seen file;
- stable file-ID matching after a rename; and
- confirmation that the returned registry state is not persisted.

