# Architecture

## Objective and Constraints

The system tests whether deterministic parsing of Zoho AI/Zia summaries is sufficient to produce useful Zoho Projects tasks. It is not a general transcript-understanding system.

The architecture is constrained by these rules:

- Zoho AI/Zia summary text is the only semantic source.
- Parsing is deterministic and restricted to explicit action-item sections.
- No Claude, OpenAI, or other external LLM participates.
- Missing owners and dates are not inferred.
- Every task starts in `In Progress` and retains its source evidence.
- Processing is idempotent at both file and action level.
- Dry-run is the default and performs no external writes.
- v2 operates alongside v1 and has no control over v1 files or services.

## Preferred System Context

```text
Zoho Meeting / Zia
        |
        | writes _summary.txt
        v
Zoho WorkDrive
        |
        | new-file event and file metadata
        v
Zoho Flow
        |
        | fetch content + invoke function
        v
Custom Deluge function
   | parse and normalize
   | resolve owner/configuration
   | construct candidate + hashes
   v
Dry-run result / audit log -------------------------+
   |                                                |
   | explicit future live-mode gate                 |
   v                                                v
Zoho Projects                              Processed-file registry
In Progress tasks                         (Creator preferred; Sheet acceptable)
```

Zoho Flow is preferred because it makes trigger, content-fetch, error handling, and orchestration steps visible in one place. An acceptable alternate is a WorkDrive workflow rule invoking a WorkDrive custom function. Both paths must use the same parser contract, payload contract, safety gate, and idempotency rules.

## Logical Components

### 1. Trigger and intake

The trigger accepts a WorkDrive file event only when the file name ends in `_summary.txt`. It captures stable WorkDrive identity and metadata before parsing:

- `file_id` (authoritative identity);
- `file_name` and `file_path` (human traceability);
- content bytes/text;
- meeting name and date metadata when available; and
- event/run identifiers for diagnostics.

File names are display data, not the sole deduplication key. A rename must not cause a duplicate when the WorkDrive file ID is unchanged.

### 2. Normalization and parsing

Normalize line endings and insignificant whitespace without rewriting the original evidence. Search case-insensitively for these section headings only:

- `Action Items`
- `Action Item`
- `Next Actions`
- `Next Steps`

Stop the section when a new major heading begins, including `Summary`, `Notes`, `Decisions`, `Key Takeaways`, `Transcript`, or `Agenda`. Heading detection must support the actual plain-text and Markdown shapes found in fixtures.

Supported initial bullet shapes are:

```text
- Build website routing flow
  - Owner: Blake
  - Due: Friday

- Build website routing flow — Owner: Blake
- Review Zoho-only task pipeline — Bill
```

The parser emits only an explicit top-level bullet. It must not turn narrative sentences, decisions, headings, owner lines, due lines, or other metadata into tasks. Unrecognized or ambiguous text is retained in diagnostics and skipped rather than guessed.

### 3. Metadata resolution

Owner matching is case-insensitive against configured aliases:

| Alias | Zoho Projects user ID |
| --- | --- |
| Blake, Blake Allard | `2543412000001324206` |
| Bill, Bill Beverley | `2543412000000059003` |
| Bryan, Brian, Bryan Ovalle | `2543412000000108001` |

An unknown or absent owner remains unresolved. The live integration should create it unassigned if Zoho permits. If the target API requires an assignee, it may use Blake (`2543412000001324206`) only as a configured fallback, with `Owner resolution: fallback` in the description. Fallback assignment must never masquerade as a detected owner.

Due-date text is preserved verbatim. The initial version does not turn `Friday`, `next week`, or any other relative expression into a Zoho due date. An explicit ISO/calendar date may also remain descriptive until date handling is separately designed and approved.

Meeting name and meeting date should come from authoritative event/file metadata. A documented filename rule may be used when metadata is absent, but failure to determine a date must produce `unknown`, never a fabricated year.

### 4. Candidate task payload

The normalized internal candidate should include at least:

| Field | Rule |
| --- | --- |
| `task_name` | `[Meeting] - [Action Text]`, constrained safely to Zoho's verified limit |
| `status` | `In Progress` |
| `owner_raw` | Exact detected text or empty |
| `owner_id` | Mapped ID, null/unassigned, or explicit configured fallback |
| `owner_resolution` | `matched`, `unassigned`, or `fallback` |
| `due_date_raw` | Exact detected text or empty |
| `due_date` | Unset in the initial version |
| `tags` | Verified existing tags `automation` and `internal-work` |
| `source_file_id` | Stable WorkDrive file ID |
| `source_file_name` | Display and audit value |
| `source_hash` | Hash of normalized source content |
| `action_hash` | Deterministic hash of source identity plus normalized explicit action |
| `original_action_text` | Unmodified source bullet text |
| `diagnostic_placeholder` | `Not provided` for all workflow-diagnostic fields |

The description must render the source type (`Zoho AI meeting summary`), summary file identity, meeting name/date, owner detection/resolution, raw due text, original action text, file/action hashes, and Workflow Diagnostic fields. The diagnostic fields carried forward from v1 are requested task, business problem, how the workflow should work, success criteria, current status, problem type, systems involved, data needed, access/approval needed, information moving between systems, one-sentence diagnosis, and next action. The initial no-LLM version does not invent answers for these fields; each remains visibly `Not provided` for a human.

Portal `898600220`, project `2543412000001324010`, the known owner IDs, verified tag IDs, and verified `In Progress` status ID are configuration values. They are not secrets, but should not be scattered through implementation code. The pilot deliberately does not require `meeting-action` or `zoho-ai-generated` because those tags do not exist or cannot be discovered with current read-only permissions.

### 5. Idempotency and registry

The preferred registry is a Zoho Creator table named `Meeting_Action_Processed_Files`; a Zoho Sheet is an acceptable validation-stage alternative. Its file-level fields are:

- `file_id`, `file_name`, `file_path`;
- `meeting_name`, `meeting_date`;
- `processed_at`, `source_hash`;
- `task_count`, `status`, `error_message`.

The design must additionally retain action-level hashes and resulting task IDs, either in a child table or an equivalent structured field. File identity prevents repeated event delivery from reprocessing the same version; `source_hash` detects changed content; `action_hash` prevents retries or revised files from recreating unchanged actions.

The dry-run result reports the logical transition `received -> dry_run_validated` without persisting it. In a future live path, persisted transitions are `received -> processing -> completed` or `failed`. A file is `completed` only when every intended action has a recorded outcome. Partial success remains retryable and must not be recorded as fully processed.

As a defensive backup, the live path may search task descriptions for `Source file ID` and `Action hash`. Task-name matching alone is insufficient because two meetings can legitimately assign the same action.

Dry-run may read a registry in a later test phase, but it must not create or update registry records.

## Safety Gate

The execution mode is a fail-closed boundary:

- default or absent mode: dry-run;
- invalid mode: dry-run plus a configuration error;
- live mode: permitted only by an explicit setting added in a later approved phase.

Before any live write, the system must validate the target portal/project, status mapping, tag mapping, owner resolution, source identity, and idempotency key. Task creation and registry mutation are live writes and remain disabled during the current phase.

## Failure Handling and Observability

Each run should report a stable run ID, file identity, source hash, parser outcome, candidate count, skipped-item reasons, owner resolution, dedup decisions, intended payloads, and errors. Logs must never contain OAuth tokens or secrets.

No-action summaries are successful zero-candidate results, not parser failures. Missing content, malformed trigger data, ambiguous structure, unavailable configuration, or failed Zoho operations are explicit errors. Retries must be safe through deterministic hashes and per-action recorded outcomes.

## Security Boundaries

OAuth credentials belong in Zoho connection management or environment/secret configuration appropriate to the selected platform. They must not appear in source, documentation examples, logs, payload snapshots, or local absolute paths. The Deluge/Flow connection should receive only the minimum WorkDrive read, registry read/write, and Zoho Projects scopes required for the approved live design.
