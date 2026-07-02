# Migration Plan

## Migration Principle

This is a parallel validation and rollout, not an in-place migration. The Claude/local v1 pipeline remains the production path until v2 passes explicit review gates. v2 must never edit v1 code, state, launchd configuration, credentials, or WorkDrive watcher behavior.

## Phase 0 — Documentation and Decisions

Deliver and review:

- repository operating rules;
- target architecture and data contracts;
- this staged rollout plan; and
- the v1/v2 parity checklist.

Exit gate: stakeholders approve the parsing boundary, unknown-owner policy, due-date policy, task description contract, duplicate strategy, and preferred Zoho trigger/registry choices.

No implementation or Zoho calls occur in this phase.

## Phase 1 — Local Deterministic Dry Run

Build a parser and payload generator from scratch in this repository. Use sanitized fixtures representing Zia summary formats, including positive, negative, malformed, unknown-owner, repeated-action, and no-action cases.

Required properties:

- dry-run is the default and only available execution mode;
- no network or Zoho writes;
- stable normalized JSON output;
- explicit skip reasons instead of inference;
- deterministic source and action hashes; and
- tests that assert expected candidates and rejected text.

Exit gate: fixtures demonstrate the agreed parser and task contract with no false task creation from non-action sections.

## Phase 2 — Deluge Parity Draft

Translate the validated rules into a Deluge custom function. Keep local fixture tests as the behavioral specification and compare Deluge outputs to the same expected results.

Exit gate: local and Deluge dry-run outputs match for all agreed fixtures, or every platform-driven difference is documented and approved.

## Phase 3 — Zoho Configuration Discovery

Under explicit authorization, inspect configuration without creating tasks:

- confirm portal and project IDs;
- identify the exact `In Progress` status/status ID;
- confirm existing tag IDs and create/identify IDs for `meeting-action` and `zoho-ai-generated` only with separate approval;
- verify whether a task may be unassigned;
- verify field lengths and accepted description format;
- select Creator or Sheet for the registry; and
- establish least-privilege Zoho connections.

Store configuration through Zoho connections, environment variables, or another approved secret/configuration facility. Do not introduce personal paths or committed credentials.

Exit gate: all payload fields and permissions are known, and the dry-run output can be validated against actual Zoho constraints without writes.

## Phase 4 — Trigger and Registry in Shadow Mode

Configure the preferred WorkDrive-to-Flow trigger, content fetch, Deluge invocation, and registry design. Keep task creation and registry mutation disabled. Capture dry-run outcomes in an approved non-production audit mechanism that does not mark files processed.

Initially restrict intake to a single Blake-hosted/test summary using stable metadata or an explicit allowlist; do not rely solely on a substring in the file name.

Exit gate: repeated and out-of-order trigger events yield identical candidates, duplicate decisions are correct, and v1 continues operating normally.

## Phase 5 — Controlled Live Pilot

Add task and registry writes behind a fail-closed live-mode switch. Live mode requires explicit approval at this phase and remains disabled by default.

Pilot sequence:

1. Review a dry-run payload for one Blake-only summary.
2. Enable one controlled live execution.
3. Confirm task name, `In Progress` status, tags, owner handling, empty due date, source fields, and registry/action hashes.
4. Replay the event and confirm that zero duplicate tasks are created.
5. Compare v2 candidates with the source summary and any v1 result; do not route the same event to two live task creators unless duplicate isolation is proven.

Exit gate: the one-file pilot is accurate, traceable, idempotent, and leaves v1 unaffected.

## Phase 6 — Representative Validation

Run dry-run review followed by separately approved live validation on three representative real summaries: known owner, unknown/multiple owner, and mixed or absent due-date text. Record false positives, false negatives, metadata quality, assignment decisions, and reviewer corrections.

Exit gate: agreed task-quality thresholds are met and all failures remain safely in `In Progress` or are skipped with a clear reason.

## Phase 7 — Limited Rollout

Remove the Blake-only restriction only after human approval. Expand gradually by meeting cohort while monitoring duplicate rate, parser misses, owner fallbacks, and corrections. v1 remains available until an explicit retirement decision outside this plan.

## Legacy State and Duplicate Strategy

Do not import `legacy_processed_notes.json` blindly. It contains file names rather than stable WorkDrive IDs and cannot prove that a particular action task exists. Before any overlapping live processing:

1. map candidate WorkDrive files to stable file IDs;
2. preserve the legacy file name as audit metadata;
3. search existing Zoho task descriptions/names only as a one-time reconciliation aid;
4. record reconciled source/action hashes in the new registry; and
5. require human review for ambiguous matches.

This avoids treating same-name files as identical and avoids recreating tasks from previously handled meetings.

## Rollback and Containment

The immediate containment action is to disable the v2 Flow/workflow or its live-mode setting. Because v1 is never modified, it requires no restoration. Preserve registry and run logs for diagnosis; do not delete created tasks automatically. Any cleanup, task deletion, or registry correction requires a reviewed plan and explicit authorization.

## Go/No-Go Evidence

Each promotion decision should include:

- fixture and parity results;
- reviewed dry-run payloads;
- false-positive and false-negative counts;
- unknown/fallback owner counts;
- duplicate replay results;
- source-to-task traceability checks;
- confirmation that all tasks begin in `In Progress`; and
- confirmation that v1 behavior and files are unchanged.
