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

### Confirmed Zoho kanban columns

The live API sample only observed statuses currently assigned to tasks, but the actual Zoho Projects kanban columns are:

- `In Progress`
- `Backlog`
- `Needs Approval`
- `Blocker`
- `Closed`

Important note:

- `Blocker` is a real Zoho kanban status even though the current API sample showed `0` tasks in that column at discovery time.
- Phase 5B must include `Blocker` in the mirror design and must not assume the observed sample is the complete status set.

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

Confirmed GitHub Project target:

- Owner: `blake-bevco-tech`
- Project number: `1`
- Project ID: `PVT_kwHOEZB-V84BcWRd`
- Project URL: `https://github.com/users/blake-bevco-tech/projects/1`

Confirmed Status field:

- Name: `Status`
- Field ID: `PVTSSF_lAHOEZB-V84BcWRdzhW_yOs`
- Type: `ProjectV2SingleSelectField`

Confirmed current Status options:

- `Todo` -> `f75ad846`
- `In Progress` -> `47fc9ee4`
- `Done` -> `98236657`

### What this means

- A suitable GitHub Project already exists and should be treated as the Phase 5 target.
- The minimum Project identifiers required for implementation are now known.
- Phase 5B still should not start until the Status option gap for `Needs Approval` is resolved.

## [RECOMMENDED PROJECT TARGET]

Use the existing Project:

- `BEVCO Summer AI Execution` is no longer a recommendation to create by default if Project `1` is the intended board.

Current target:

- Owner: `blake-bevco-tech`
- Project number: `1`
- Project ID: `PVT_kwHOEZB-V84BcWRd`
- Project URL: `https://github.com/users/blake-bevco-tech/projects/1`

Recommended confirmation before Phase 5B:

- Verify that Project `1` is intended to mirror the Zoho summer execution workflow.
- Add a `Needs Approval` single-select option before implementation begins.

## [PROPOSED STATUS MAPPING]

Recommended true-mirror target:

GitHub Project `Status` options should exactly mirror Zoho:

- `Backlog`
- `In Progress`
- `Needs Approval`
- `Blocker`
- `Closed`

Recommended v1 one-way mapping:

- Zoho `Backlog` -> GitHub `Backlog`
- Zoho `In Progress` -> GitHub `In Progress`
- Zoho `Needs Approval` -> GitHub `Needs Approval`
- Zoho `Blocker` -> GitHub `Blocker`
- Zoho `Closed` -> GitHub `Closed`

Important rule:

- Do not map Zoho `Backlog` to GitHub `Todo` if the goal is a true mirror.
- Do not map Zoho `Closed` to GitHub `Done` if the goal is a true mirror.

Recommendation:

- Update the GitHub Project `Status` field options to match Zoho exactly before Phase 5B implementation.
- Prefer exact-name matching over a translation table when the goal is a kanban mirror.

## [REQUIRED CONFIG]

### Already known

- GitHub owner/org: `blake-bevco-tech`
- GitHub Project number: `1`
- GitHub Project ID: `PVT_kwHOEZB-V84BcWRd`
- GitHub Project URL: `https://github.com/users/blake-bevco-tech/projects/1`
- GitHub Status field name: `Status`
- GitHub Status field ID: `PVTSSF_lAHOEZB-V84BcWRdzhW_yOs`
- GitHub Status field type: `ProjectV2SingleSelectField`
- GitHub Status option `Todo`: `f75ad846`
- GitHub Status option `In Progress`: `47fc9ee4`
- GitHub Status option `Done`: `98236657`
- Zoho project ID for issue metadata: present in runtime env and already used by the script
- Zoho source status field: `status`
- Confirmed Zoho kanban columns:
  - `Backlog`
  - `In Progress`
  - `Needs Approval`
  - `Blocker`
  - `Closed`

### Still required before Phase 5B implementation

- Confirmed Project display name if it should be referenced in code/comments/docs
- A GitHub Status option for `Backlog`
- A GitHub Status option for `Needs Approval`
- A GitHub Status option for `Blocker`
- A GitHub Status option for `Closed`
- The option IDs for all mirror-aligned Status options once they are added or renamed

### Likely state additions for Phase 5B

`task_repo_map.json` will probably need:

- `project_number`
- `project_item_id`
- `project_status_field_id`
- `project_status_option_id`
- `zoho_status_at_last_sync`

## [IMPLEMENTATION RISKS]

- GitHub Project currently does not exactly mirror the Zoho kanban column set.
- If the mirror requirement remains strict, the current `Todo` and `Done` options are not acceptable substitutes for `Backlog` and `Closed`.
- If `Needs Approval` or `Blocker` is encountered in Zoho before matching Project options exist, the sync must block rather than silently degrading those states.
- If the Project `Status` field options do not match Zoho naming, the mapping table becomes a translation layer rather than a mirror and should be treated as a temporary fallback only.
- If GitHub Project status is edited manually, one-way Zoho -> GitHub sync will overwrite it unless a guard is added.
- Unknown future Zoho statuses must block or route to a configured fallback rather than guessing.
- Project item creation will need to decide whether to key items by:
  - issue URL
  - issue number
  - Project item ID
- Project APIs can differ between `gh project` and lower-level GraphQL access; implementation should choose one path and keep it consistent.

## [PHASE 5B IMPLEMENTATION PLAN]

1. Treat Project `1` as the implementation target.
2. Update the GitHub Project `Status` field so it exactly mirrors Zoho:
   - `Backlog`
   - `In Progress`
   - `Needs Approval`
   - `Blocker`
   - `Closed`
3. Record the final option IDs in implementation config.
4. Add read-only Project discovery helpers to the script:
   - find target Project
   - fetch fields/options
   - map Zoho status name -> GitHub option ID
5. Extend dry-run reporting to include Project planning:
   - would create/find Project item
   - would set Project status
   - blocked due to unknown status or missing Project config
6. In apply mode only, after repo + issue verification:
   - create or verify the Project item linked to the issue
   - set the `Status` field one-way from Zoho
7. Extend `task_repo_map.json` atomically with Project metadata.
8. Preserve conflict-first behavior:
   - multiple Project item matches -> block
   - unknown Zoho status -> block
   - missing Status field/option -> block

## [BLOCKERS]

- GitHub Project currently does not exactly mirror the Zoho kanban columns.
- Phase 5B should not proceed as a true mirror until matching Project options exist for:
  - `Backlog`
  - `Needs Approval`
  - `Blocker`
  - `Closed`
