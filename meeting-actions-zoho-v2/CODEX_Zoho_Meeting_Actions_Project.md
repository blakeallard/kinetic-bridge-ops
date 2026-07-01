# Codex Project Brief — Zoho-Only Meeting Summary to Zoho Projects Tasks

## Goal

Build a separate Zoho-only v2 of the existing meeting-actions pipeline.

Do not modify the existing production folder:

/Users/blakeallard/Dev/bevco/meeting-actions

This new repo is:

/Users/blakeallard/Dev/bevco/meeting-actions-zoho-v2

## Current v1 Pipeline

Zoho Meeting recording
→ transcript/summary generated
→ summary saved to WorkDrive
→ local Mac watcher scans `_summary.txt`
→ Python parser extracts action items
→ Claude fills BEVCO workflow worksheet
→ Claude/Zoho tooling creates Zoho Projects tasks
→ `processed_notes.json` prevents duplicate processing

## Target v2 Pipeline

Zoho Meeting recording
→ Zoho AI/Zia summary saved to WorkDrive
→ WorkDrive workflow or Zoho Flow trigger detects new `_summary.txt`
→ Deluge parser extracts explicit action items
→ Zoho Projects task created through Zoho API / Deluge integration
→ task status = Needs Review
→ human validates task quality

## Primary Validation Question

Can Zoho-generated meeting summaries produce usable Zoho Projects tasks without Claude/OpenAI interpreting the transcript?

## Hard Requirements

1. Build in this new folder only.
2. Treat all legacy files as read-only references.
3. Do not modify `/Users/blakeallard/Dev/bevco/meeting-actions`.
4. Use Zoho-native infrastructure where possible.
5. Do not call Claude, OpenAI, or external LLMs in v1.
6. Use the Zoho AI/Zia summary text as the source document.
7. Only create tasks from explicit action items.
8. Do not infer owners unless clearly stated.
9. Do not infer due dates unless explicitly stated.
10. All created tasks must start in Needs Review.
11. Preserve source file traceability in task descriptions.
12. Prevent duplicate processing.
13. Default everything to dry-run.
14. Do not hardcode secrets, OAuth tokens, API keys, or local Mac paths.

## Existing Constants From Legacy Pipeline

PORTAL_ID = "898600220"
PROJECT_ID = "2543412000001324010"

Known owner map:

blake = 2543412000001324206
blake allard = 2543412000001324206
bill = 2543412000000059003
bill beverley = 2543412000000059003
bryan = 2543412000000108001
brian = 2543412000000108001
bryan ovalle = 2543412000000108001

Known tags:

automation = 2543412000001391053
internal-work = 2543412000001391061

## Files Copied From v1

legacy_CLAUDE.md
legacy_parse_meeting_actions.py
legacy_create_tasks.sh
legacy_watch_meetings.sh
legacy_processed_notes.json
legacy_zoho_attach.py

## v2 Architecture

Preferred:

WorkDrive `_summary.txt` uploaded
→ Zoho Flow trigger
→ Fetch file content
→ Custom Deluge function parses action items
→ Create Zoho Projects tasks
→ Log processed file

Alternate:

WorkDrive workflow rule
→ WorkDrive custom function
→ Fetch file content
→ Parse
→ Create Zoho Projects tasks
→ Log processed file

## Parser Rules

Extract only sections named:

Action Items
Action Item
Next Actions
Next Steps

Stop parsing when a new major heading starts:

Summary
Notes
Decisions
Key Takeaways
Transcript
Agenda

Support bullets like:

- Build website routing flow
  - Owner: Blake
  - Due: Friday

And inline forms like:

- Build website routing flow — Owner: Blake
- Review Zoho-only task pipeline — Bill

Unknown owner rule:

If owner is unknown, create unassigned if possible. If Zoho requires assignment, assign to Blake as fallback and mark the description with `Owner resolution: fallback`.

Due date rule:

Do not calculate relative dates in v1. Preserve raw due date text in the task description.

## Task Format

Task name:

[Meeting] - [Action Text]

Status:

Needs Review

Tags:

automation
internal-work
meeting-action
zoho-ai-generated
needs-review

Description must include:

Source: Zoho AI meeting summary
Summary file
Meeting name
Meeting date
Owner detected
Owner resolution
Due date text
Original action text
Workflow Diagnostic fields marked Needs Review

## Duplicate Prevention

Preferred registry:

Zoho Creator table or Zoho Sheet:

Meeting_Action_Processed_Files

Fields:

file_id
file_name
file_path
meeting_name
meeting_date
processed_at
source_hash
task_count
status
error_message

Backup:

Search existing Zoho Projects task descriptions for:

Source file ID
Action hash

## First Deliverables

Do not write implementation code first.

Create:

AGENTS.md
README.md
docs/architecture.md
docs/migration_plan.md
docs/parity_checklist.md

Then stop and ask for review.

## Build Order

1. Create repo instructions and docs.
2. Build local dry-run parser.
3. Add sample summaries and expected JSON outputs.
4. Draft Deluge parser.
5. Build Zoho Projects task payload generator.
6. Add duplicate registry design.
7. Add live task creation behind LIVE_MODE=false default.
8. Add Zoho Flow or WorkDrive setup docs.
9. Test one Blake-only summary.
10. Test three real summaries.
11. Remove Blake-only restriction only after review.
