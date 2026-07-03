# Phase 5 Project Mirroring Discovery

## [CURRENT SCRIPT STATE]

- `repo_lifecycle_dry_run.py` remains dry-run by default.
- Apply is confirmation-gated and currently handles:
  - Zoho task discovery
  - private GitHub repo creation/verification
  - local repo creation/verification
  - versioned template population
  - GitHub Issue creation/verification
  - atomic `task_repo_map.json` writes
  - idempotent Zoho backlink comment
- No GitHub Project logic exists yet.
- No Zoho status mirroring exists yet.
- Current status helper in the script is:
  - `task_status(task) = custom_status -> status -> "Unknown"`
- Phase 5 should extend this model rather than replace it.

## [ZOHO STATUS FIELD DISCOVERY]

### Recommended Zoho status source

Recommended source of truth for Phase 5B:

- Primary: `status`
- Fallback order to preserve in code:
  - `custom_status`
  - `status`
  - `status_name` if it ever appears later

Why:

- Live task read shows `custom_status` is currently absent on all sampled and enumerated tasks.
- `status_name` is also absent on all enumerated tasks.
- `status` is populated consistently and already contains:
  - human-readable name
  - stable Zoho status ID
  - open/closed type
  - color code

### Live field usage summary

- Total tasks inspected: `32`
- `custom_status` populated: `0`
- `status_name` populated: `0`
- `custom_fields` relevant to status: none observed in current task payloads
- `tasklist` is populated, but it appears to represent intake grouping, not kanban state
- `milestone_id` is populated, but it appears to represent project grouping, not kanban state

### Live Zoho status values observed

- `Backlog`
  - id: `2543412000000441313`
  - type: `open`
  - color: `transparent`
- `In Progress`
  - id: `2543412000000031001`
  - type: `open`
  - color: `#f56b62`
- `Needs Approval`
  - id: `2543412000001349031`
  - type: `open`
  - color: `#EFB116`
- `Closed`
  - id: `2543412000000016071`
  - type: `closed`
  - color: `#74cb80`

### Redacted sample task status payloads

Sample 1:

```json
{
  "task_key": "BI1-T95",
  "task_id": "2543412000001511001",
  "title": "OpenAI vs. Zoho AI Transcriptions/Summary Comparisons",
  "custom_status": null,
  "status": {
    "name": "Needs Approval",
    "id": "2543412000001349031",
    "type": "open",
    "color_code": "#EFB116"
  },
  "status_name": null,
  "tasklist": {
    "name": "Meeting Actions – 2026-06-24",
    "id_string": "2543412000001493006",
    "id": "2543412000001493006"
  },
  "milestone_id": "2543412000000000073",
  "milestone": null,
  "custom_fields": []
}
```

Sample 2:

```json
{
  "task_key": "BI1-T94",
  "task_id": "2543412000001485016",
  "title": "Implement Local LLM with All Zoho Documentation",
  "custom_status": null,
  "status": {
    "name": "Closed",
    "id": "2543412000000016071",
    "type": "closed",
    "color_code": "#74cb80"
  },
  "status_name": null,
  "tasklist": {
    "name": "Meeting Actions – 2026-06-23",
    "id_string": "2543412000001491018",
    "id": "2543412000001491018"
  },
  "milestone_id": "2543412000000000073",
  "milestone": null,
  "custom_fields": []
}
```

Sample 3:

```json
{
  "task_key": "BI1-T93",
  "task_id": "2543412000001493001",
  "title": "Implement sequential document-numbering/log applet for SOWs and Quotes (store history and return next available ID)",
  "custom_status": null,
  "status": {
    "name": "In Progress",
    "id": "2543412000000031001",
    "type": "open",
    "color_code": "#f56b62"
  },
  "status_name": null,
  "tasklist": {
    "name": "Meeting Actions – 2026-06-23",
    "id_string": "2543412000001491014",
    "id": "2543412000001491014"
  },
  "milestone_id": "2543412000000000073",
  "milestone": null,
  "custom_fields": []
}
```

## [GITHUB PROJECT DISCOVERY]

### Discovery result

GitHub Project discovery via `gh project` is currently blocked.

Observed read-only CLI result:

- `gh project list --owner blake-bevco-tech --format json`
- returned:
  - authentication token missing required scope `read:project`

Additional auth check in the restricted shell also indicated the local `gh` token state is not currently healthy there.

### What this means

- I could not determine from live GitHub data whether a suitable org-level Project already exists.
- I could not discover any Project number, Project node ID, field list, field IDs, or status option IDs.
- Phase 5B implementation should not start until GitHub Project read access is repaired.

## [RECOMMENDED PROJECT TARGET]

If no suitable GitHub Project already exists once `read:project` access is restored, create this org-level Project manually:

- `BEVCO Summer AI Execution`

Recommended characteristics:

- Owner: `blake-bevco-tech`
- Project type: GitHub Project (Projects v2)
- Purpose: mirror Zoho task execution state for repo-backed AI workspaces

Recommended minimum fields:

- `Title`
- `Status`
- `Repository` or linked issue context through the Project item
- Optional later:
  - `Zoho Task Key`
  - `Zoho Task ID`
  - `Local Repo Path`

## [PROPOSED STATUS MAPPING]

Recommended first-pass one-way mapping:

- Zoho `Backlog` -> GitHub Project `Backlog`
- Zoho `In Progress` -> GitHub Project `In Progress`
- Zoho `Needs Approval` -> GitHub Project `Needs Approval`
- Zoho `Closed` -> GitHub Project `Done`

Alternative if the target Project only has GitHub default options:

- Zoho `Backlog` -> GitHub `Todo`
- Zoho `In Progress` -> GitHub `In Progress`
- Zoho `Needs Approval` -> GitHub `In Review`
- Zoho `Closed` -> GitHub `Done`

Recommendation:

- Prefer creating explicit Project status options that match Zoho names exactly:
  - `Backlog`
  - `In Progress`
  - `Needs Approval`
  - `Done`

That will minimize translation logic and reduce accidental overwrite risk.

## [REQUIRED CONFIG]

### Already known

- GitHub owner/org: `blake-bevco-tech`
- Zoho project ID for issue metadata: present in runtime env and already used by the script
- Zoho source status field: `status`

### Still required from GitHub Project discovery

- GitHub Project number
- GitHub Project node ID, if needed by the chosen CLI/API call path
- Exact Project name
- `Status` field name
- `Status` field ID
- Available status option names
- Available status option IDs

### Likely state additions for Phase 5B

`task_repo_map.json` will probably need:

- `project_number`
- `project_item_id`
- `project_status_field_id`
- `project_status_option_id`
- `zoho_status_at_last_sync`

## [IMPLEMENTATION RISKS]

- GitHub Project discovery is currently blocked by missing `read:project` scope.
- If multiple GitHub Projects have similar names, project targeting must be explicit by number/ID.
- If the Project `Status` field options do not match Zoho naming, the mapping table must be explicit and versioned.
- If GitHub Project status is edited manually, one-way Zoho -> GitHub sync will overwrite it unless a guard is added.
- Unknown future Zoho statuses must block or route to a configured fallback rather than guessing.
- Project item creation will need to decide whether to key items by:
  - issue URL
  - issue number
  - Project item ID
- Project APIs can differ between `gh project` and lower-level GraphQL access; implementation should choose one path and keep it consistent.

## [PHASE 5B IMPLEMENTATION PLAN]

1. Restore GitHub Project read access with `read:project`.
2. Discover and document the target Project number/ID and `Status` field options.
3. Add read-only Project discovery helpers to the script:
   - find target Project
   - fetch fields/options
   - map Zoho status name -> GitHub option ID
4. Extend dry-run reporting to include Project planning:
   - would create/find Project item
   - would set Project status
   - blocked due to unknown status or missing Project config
5. In apply mode only, after repo + issue verification:
   - create or verify the Project item linked to the issue
   - set the `Status` field one-way from Zoho
6. Extend `task_repo_map.json` atomically with Project metadata.
7. Preserve conflict-first behavior:
   - multiple Project item matches -> block
   - unknown Zoho status -> block
   - missing Status field/option -> block

## [BLOCKERS]

- GitHub CLI token for the current environment lacks `read:project`, so live Project discovery could not complete.
- Because Project discovery is blocked, the following implementation inputs remain unknown:
  - whether a suitable Project already exists
  - Project number/ID
  - field names/IDs
  - status option names/IDs
