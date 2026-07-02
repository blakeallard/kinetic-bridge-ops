# Agent Handoff State

Repo:
- https://github.com/blake-bevco-tech/meeting-actions-zoho-v2

Current baseline:
- origin/main at b77da95 Add shared agent handoff state
- active branch: stage-9-runtime-validation

Current stage:
- Stage 9: Zoho Deluge runtime validation
- Status: blocked/pending because no MCP-accessible Zoho Deluge/Flow/custom-function execution surface is available

Completed:
- Stage 8 Deluge parser/QC draft committed
- Stage 7B deterministic QC committed
- Local tests pass: 29 tests

Hard rules:
- Dry-run only
- No Zoho Projects task creation
- No Zoho data modification
- No Flow/WorkDrive wiring yet
- No registry persistence
- No OpenAI/Claude/external LLM calls inside the pipeline
- Do not modify legacy_* files
- Do not push directly to main from agent branches

Next allowed work:
- Documentation and setup for manual Zoho runtime validation
- Branch workflow setup for Codex/Claude coordination
- No live task creation

Manual validation package:
- docs/stage9_manual_validation_checklist.md
- docs/stage9_runtime_results_template.md
- docs/zoho_deluge_parser.md (existing blocker and parser contract)
- samples/deluge/stage8_workdrive_flow_input.json
- samples/deluge/stage8_expected_projection.json
