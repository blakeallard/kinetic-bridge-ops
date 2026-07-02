# Zoho Projects Payload Builder

## Scope

[`scripts/build_projects_payloads.py`](../scripts/build_projects_payloads.py) converts validated parsed action-item maps into inert Zoho Projects task payload envelopes. It is a local, standard-library-only transformation. It does not perform OAuth, `invokeURL`, HTTP requests, Zoho Projects calls, task creation, Flow actions, WorkDrive operations, or registry writes.

The Python parser remains the parsing source of truth, and the Deluge parser remains a draft translation of that parser. The payload builder does not parse summary text or reinterpret owners and due dates.

## Configuration

Non-secret configuration is centralized in constants and `ProjectsPayloadConfig`:

| Setting | Value/behavior |
| --- | --- |
| Portal ID | `898600220` |
| Project ID | `2543412000001324010` |
| Status name | Always `In Progress` |
| Known owners | Blake Allard, Bill Beverley, Bryan Ovalle IDs from the project brief |
| Known tag IDs | `automation` and `internal-work` |
| Required tags without verified IDs | `meeting-action`, `zoho-ai-generated` |
| Maximum task name length | 250 characters, pending live Zoho verification |

These values are identifiers, not secrets. The builder contains no credentials, tokens, API keys, endpoints, or local machine paths. A configuration with any status other than `In Progress` is rejected.

## Input Contract

`build_task_payload` accepts one parsed action-item map and a required authoritative `meeting_name`. Requiring the meeting name separately prevents the builder from guessing it from the source filename.

Required parsed fields:

- `action_text`
- `owner_resolution`
- `source_file_name`
- `action_hash`
- `detected_owners`

Optional nullable parsed fields:

- `owner_id`
- `owner_raw`
- `due_date_text`

Allowed owner resolutions are `matched`, `missing`, `unresolved`, and `multiple`. A matched owner must use one of the configured known IDs. The builder rejects an unconfigured ID rather than assigning it.

`build_task_payloads` accepts a sequence of these maps and applies the same meeting name and configuration to each.

## Output Contract

Every result is an inert envelope:

```text
{
  dry_run: true,
  portal_id: "...",
  project_id: "...",
  status: {name: "In Progress", id: null, verified: false},
  tags: [{name: "automation", id: "..."}, ...],
  task_parameters: {
    name: "Meeting name - Explicit action",
    description: "...",
    tagIds: ["known-tag-id", "known-tag-id"],
    person_responsible: "known-owner-id"  // matched owner only
  },
  validation: {
    ready_for_live: false,
    missing_status_id: true,
    missing_tag_ids: [...],
    owner_assignment: "matched" | "unassigned"
  }
}
```

The official Projects create-task documentation names `name`, `description`, optional `person_responsible`, and `tagIds` as request parameters. `task_parameters` uses those documented names. The surrounding envelope is an internal dry-run contract, not a request body and not authorization to send anything.

The current create-task documentation does not establish how this project should set its custom `In Progress` status during creation. The builder therefore records the required status intent but leaves its ID null and marks every payload not live-ready. The two required tag names whose IDs are not yet known receive null IDs and are also reported as blockers. Only the two verified tag IDs appear in `task_parameters.tagIds`.

## Owner Assignment

The assignment rule is fail-closed:

| `owner_resolution` | Payload behavior |
| --- | --- |
| `matched` | Add `person_responsible` using the configured known owner ID |
| `missing` | Omit `person_responsible` |
| `unresolved` | Omit `person_responsible` |
| `multiple` | Omit `person_responsible`, even if all detected people are known |

For every case, the description includes raw owner text, resolution, and the complete detected-owner list. Nonmatched records remain unassigned; there is no Blake fallback in this payload stage.

## Description Template

The deterministic plain-text description preserves:

- source type (`Zoho AI meeting summary`);
- source filename;
- authoritative meeting name;
- original action text;
- raw owner text;
- owner resolution and detected-owner details;
- raw due-date text and an explicit statement that no date calculation occurred; and
- action hash.

It then includes these Workflow Diagnostic fields, each set to `Not provided`:

- Requested task
- Business problem
- Desired workflow
- Success criteria
- Current status
- Problem type
- Systems involved
- Data needed
- Access / approval needed
- Information between systems
- One-sentence diagnosis
- Next action

The builder does not infer or populate any diagnostic answer from the action text or meeting name.

## Dry-Run Enforcement

Dry-run defaults to true. Passing `dry_run=False` raises an error. There is no live branch, transport adapter, authentication code, endpoint, or network dependency.

For local inspection:

```bash
python3 scripts/build_projects_payloads.py \
  samples/expected/known_owner_summary.json \
  --meeting-name "Website Planning Meeting"
```

The command reads one local parsed JSON file and prints payload JSON to stdout.

## Fixtures and Tests

Checked-in payload fixtures:

- [`samples/payloads/known_owner_payload.json`](../samples/payloads/known_owner_payload.json)
- [`samples/payloads/unassigned_owner_payloads.json`](../samples/payloads/unassigned_owner_payloads.json)

Run all parser and payload tests with:

```bash
python3 -m unittest discover -s tests -v
```

The tests cover matched assignment, missing/unresolved/multiple unassignment, diagnostic review markers, fixture parity, rejection of unknown matched IDs, and rejection of live mode.

## Official Field References

- [Zoho Projects Tasks API](https://www.zoho.com/projects/help/rest-api/tasks-api.html)
- [Zoho Projects Tags API](https://www.zoho.com/projects/help/rest-api/tags.html)
