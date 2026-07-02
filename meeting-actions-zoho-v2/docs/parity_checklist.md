# Legacy v1 to Zoho-Only v2 Parity Checklist

## How to Use This Checklist

“Parity” means retaining an outcome that is still required, not copying v1 implementation. The project brief overrides legacy behavior. Items marked **Replace** or **Drop** are intentional changes required for safety or for the Zoho-only validation question.

| Area | Legacy v1 behavior | Zoho-only v2 requirement | Disposition | Validation |
| --- | --- | --- | --- | --- |
| Production isolation | Local scripts in the original meeting-actions folder | Independent repository and deployment; never modify or disable v1 | Preserve isolation | `git`/file review shows changes only in v2; v1 watcher remains untouched |
| Source | Local WorkDrive-synced `_summary.txt` | Zoho AI/Zia `_summary.txt` fetched from WorkDrive | Preserve source type, replace transport | Fixture and trigger metadata identify the Zia summary and stable file ID |
| Trigger | `launchd` runs a Mac watcher every 30 minutes | Zoho Flow new-file trigger preferred; WorkDrive workflow alternate | Replace | Repeated trigger events are captured without relying on a Mac |
| Availability | Depends on Blake's Mac and TrueSync | Zoho-hosted execution | Replace | Test event succeeds while local watcher is irrelevant |
| Intake restriction | Watcher accepts filenames containing `blake` and passes `--blake-only` | Start with a controlled Blake-only pilot, then expand after review | Preserve rollout guard, replace filename heuristic | Allowlisted test files only during pilot; nonpilot event safely skipped |
| Section names | Primarily `Action Items`; also numbered `4. Action Items` | `Action Items`, `Action Item`, `Next Actions`, `Next Steps` | Extend | Positive fixture for every heading |
| Section end | Stops at Markdown headings or selected text/numbered sections | Stop at any new major heading: Summary, Notes, Decisions, Key Takeaways, Transcript, Agenda | Tighten | Boundary fixtures do not emit later bullets |
| Bullet formats | Top-level hyphen bullets with nested owner; inline owner; positional em-dash form | Nested owner/due and inline owner/positional owner forms explicitly documented | Preserve with stricter grammar | Fixture coverage for supported hyphen, bullet, en dash, and em dash shapes |
| Explicit actions | All top-level bullets found inside extracted section become items | Preserve strict sections and add deterministic embedded future-work extraction for Zoho AI bullets; ambiguous/status/history prose is skipped | Extend conservatively | Real-format fixture yields expected candidates while negative history bullets yield none |
| LLM interpretation | Optional Claude worksheet generation from meeting context | No Claude/OpenAI/external LLM | Drop | Dependency and network review finds no external LLM path |
| Workflow worksheet | Claude may fill diagnostic fields; basic fallback has meeting/action/owner only | Retain diagnostic field names but set each to `Not provided` | Replace | Candidate description contains every agreed field without invented content |
| Owner aliases | Maps Blake, Bill, Bryan/Brian aliases to known Zoho IDs | Retain the documented alias map as configuration | Preserve | Case-insensitive alias tests return exact configured IDs |
| Multiple owners | v1 selects the first parsed owner | Do not silently discard ambiguity; preserve raw owner text and use only a clearly supported primary owner rule | Tighten / decision needed | Multiple-owner fixture is either explicitly resolved by approved rule or marked unresolved |
| Unknown owner parsing | Parser assigns Blake as fallback and marks `is_fallback` | Prefer unassigned; use configured Blake fallback only if Zoho mandates assignment, and label it | Replace | Unknown-owner dry run shows `unassigned`; fallback test is explicit and labeled |
| Unknown owner execution | Task creation skips all fallback/unresolved items | v2 may create an unassigned `In Progress` task when supported | Replace | Pilot verifies actual Zoho unassigned behavior before live use |
| Missing owner | Parsed as `Unknown`, then skipped by live v1 creator | Preserve unresolved state; never infer from meeting prose | Tighten | Missing-owner fixture contains no detected owner and no inferred ID |
| Due date | Positional trailing text is effectively discarded; no task due date is set | Preserve raw due text in description; do not calculate relative dates initially | Replace | `Friday` and explicit-date fixtures preserve exact text with no due-date payload |
| Meeting date | Uses sibling metadata, special filename patterns, parent folder, or even a hardcoded 2026 fallback | Prefer authoritative WorkDrive/event metadata; never fabricate a date | Replace | Missing-date fixture returns unknown rather than an invented year |
| Task name | Raw action, truncated to 250 characters | `[Meeting] - [Action Text]`, safely constrained to verified Zoho limits | Replace | Expected payload includes prefix and deterministic safe truncation behavior |
| Status | No explicit `In Progress` status in create prompt | Every task starts in `In Progress` | Add required behavior | Controlled pilot reads back exact status before rollout |
| Tags | Adds `automation` and `internal-work` by ID | Use those same two verified tags for the pilot; do not block on undiscoverable `meeting-action` or `zoho-ai-generated` tags | Preserve for pilot | Dry-run uses the two verified IDs; live pilot confirms readback |
| Task list | Creates `Meeting Actions – [date]`, then tasks; may fall back to General | Task-list policy is not specified by v2 requirements | Decision needed | Decide before payload implementation; absence must not weaken task traceability |
| Description | Basic source date/action/owner or LLM worksheet HTML | Full source, meeting, owner resolution, due text, original text, hashes, and diagnostic review fields | Extend | Snapshot test covers all required fields |
| Source traceability | Meeting date and original action; no stable WorkDrive file ID/action hash | Include source file ID/name/path, source hash, action hash, meeting name/date | Extend | Reviewer can trace every candidate back to one source bullet |
| File deduplication | `processed_notes.json` keyed only by basename | Creator/Sheet registry keyed by stable file ID and content hash | Replace | Same event and renamed-file replay create no duplicate candidate writes |
| Action deduplication | Fetches all tasks and compares lowercased task names | Deterministic action hash; description search is backup | Replace | Same action replay is skipped; same text from a distinct meeting remains distinguishable |
| Partial failure | Non-dry-run marks source processed even when some/all task creates fail | Mark completed only after every intended action has a recorded terminal outcome | Fix | Injected partial failure remains retryable without recreating successful actions |
| No-action file | Exits without marking file processed, so watcher can repeatedly retry it | Record a successful zero-action outcome in live registry; dry-run makes no mutation | Fix | Replay does not loop after an approved live zero-action processing result |
| Dry-run default | `--dry-run` is opt-in; watcher invokes live behavior | Dry-run is the fail-closed default everywhere | Replace | Omitted/invalid mode causes zero external writes |
| Dry-run side effects | Skips task/task-list creation and processed state update; may emit local visualizer events | No external object or registry writes; output intended payload and diagnostics only | Preserve and tighten | Side-effect audit shows no Zoho mutations |
| Live enablement | Normal path creates tasks via Claude tooling/direct OAuth reads | Future explicit live-mode gate using Zoho-native integration | Replace | Live path absent now; later requires deliberate positive setting and approval |
| Task creation | Claude CLI calls Zoho Projects MCP | Direct Zoho integration/Deluge, no Claude | Replace | Dependency review and controlled API readback |
| Zoho reads | Direct OAuth fetch of all tasks for name dedup | Minimized Zoho-native calls with least-privilege connection | Replace | Scope review and call inventory |
| Credentials | Reads a hardcoded personal `.env` path | Zoho connection/approved secret configuration; no committed credentials or local paths | Replace | Secret scan and configuration review pass |
| Configuration | Portal/project/user/tag IDs repeated in scripts | Central documented configuration; required IDs validated before live mode | Replace | One authoritative config source and startup validation |
| Attachments | HTML attachment helper exists but invocation is disabled | Attachments are not required for initial validation | Drop/defer | No attachment code in initial implementation |
| Observability | Optional localhost visualizer events and watcher log | Run/file IDs, counts, skip reasons, hashes, owner decisions, dedup outcomes, errors; no secrets | Replace | Dry-run output and test logs contain required audit data |
| Verification | Treats positive local success count as Zoho confirmation | In live pilot, read back created task fields or record API response evidence | Tighten | Pilot evidence verifies status, tags, owner, description, and IDs |
| Processed history | Legacy JSON contains many processed basenames | Reconcile cautiously; do not import as authoritative identity | Replace | Human-reviewed mapping from legacy name to stable file/action identity |

## Required Acceptance Checks Before Any Live Call

- [ ] Documentation decisions are reviewed and unresolved rows above are resolved.
- [ ] Default and invalid modes are proven to make zero external writes.
- [ ] Parser fixtures cover all approved headings, boundaries, bullet formats, and negative cases.
- [ ] Unknown, missing, and multiple-owner behavior is explicit and non-inferential.
- [ ] Raw due-date text is retained and no relative date is calculated.
- [ ] Task payloads include the verified `In Progress` ID, the two verified pilot tags, and complete source traceability.
- [ ] File and action hashes are deterministic across retries.
- [ ] Partial-failure and zero-action behavior is retry-safe.
- [ ] Exact Zoho status/tag mappings and unassigned-task support are verified under authorization.
- [ ] No secret, OAuth token, API key, or personal local path exists in new implementation/configuration.
- [ ] No Claude/OpenAI/external LLM dependency exists.
- [ ] The original v1 directory and working pipeline remain unchanged.
