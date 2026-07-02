# Repository Instructions

## Scope

This repository is the independent Zoho-only v2 meeting-actions pipeline. Build and document it from scratch here.

- Never modify the original v1 `meeting-actions` repository identified in the project brief.
- Treat every `legacy_*` file in this repository as read-only reference material.
- Do not copy changes back to, replace, disable, or otherwise interfere with the working Claude/local v1 pipeline.
- Follow `CODEX_Zoho_Meeting_Actions_Project.md` as the project brief. If it conflicts with a legacy behavior, the project brief wins.

## Current Phase

The current phase includes the local parser, deterministic QC review, Stage 8 Deluge parser/QC draft, payload builder, in-memory duplicate registry, and guarded create-task scaffold. Do not add Flow/WorkDrive wiring, registry persistence, token refresh, or make a live Zoho call until separately requested. The pilot configuration uses the verified `In Progress` custom status ID and only the verified `automation` and `internal-work` tags. Live execution remains protected by the explicit two-key guard and payload validation.

## Safety Defaults

- Every future executable entry point and integration must default to dry-run.
- Dry-run must perform no external writes, create no Zoho objects, and make no processed-registry mutations.
- Do not make live Zoho API calls until the user explicitly authorizes the live integration phase.
- A live mode must require an explicit positive opt-in; an omitted, empty, or unrecognized setting must remain dry-run.
- Tasks eventually created by v2 must start in `In Progress` and retain source traceability.

## Secrets and Configuration

- Never commit secrets, OAuth tokens, refresh tokens, client secrets, API keys, or credentials.
- Never hardcode user-specific local paths.
- Keep environment-specific IDs and endpoints in documented configuration. The portal, project, owner, and tag IDs in the project brief are non-secret reference configuration, not credentials.
- Provide sanitized examples only. Keep real secret-bearing files ignored by Git when configuration files are introduced.

## Behavioral Rules

- Use the Zoho AI/Zia summary as the source document.
- Extract explicit action items from approved sections and conservative future-work phrases embedded in Zoho AI summary bullets; never promote pure status/history prose.
- Do not infer an owner or due date from surrounding prose.
- Preserve unknown owners as unresolved. Prefer an unassigned task; if Zoho requires an owner, use the documented Blake fallback and label the fallback in the description.
- Preserve relative or otherwise unparsed due-date text in the description; do not calculate it during the initial validation version.
- Include deterministic file- and action-level identifiers so retries cannot create duplicates.
- Do not add Claude, OpenAI, or another external LLM dependency to v2.

## Change Discipline

- Make changes only inside this repository.
- Do not edit or rename `legacy_*` files.
- Keep documentation aligned with the target architecture and record intentional differences from v1 in `docs/parity_checklist.md`.
- Avoid speculative features that do not answer the primary validation question.
- When implementation begins, add representative fixtures and expected dry-run outputs before enabling any live path.
- Do not claim Zoho behavior has been verified unless it was tested under explicit authorization and the result was recorded.
