# Guarded Zoho Projects Task Creation Scaffold

## Scope

[`scripts/create_tasks_guarded.py`](../scripts/create_tasks_guarded.py) is the first transport scaffold for Zoho Projects task creation. It reads only `payloads_that_would_be_created` from an existing registry report, validates the complete batch, and sends only each validated `task_parameters` map through a client interface.

Default execution is dry-run. This stage does not wire Zoho Flow, WorkDrive triggers, Deluge execution, registry persistence, processed-file state, or OAuth token refresh. No live request was made while implementing or testing this scaffold.

## Execution Flow

```text
registry report JSON
  -> read payloads_that_would_be_created
  -> structurally inspect every payload
  -> default dry-run: return summary, make zero client calls
  -> requested live mode: verify both live keys
  -> preflight every payload before the first client call
  -> reject the entire batch if any payload is blocked
  -> send only task_parameters through TaskCreateClient
  -> return responses without persisting registry state
```

The entire batch is preflighted before the first call. A validation failure cannot create a partial batch. Transport failures can still occur after an earlier request succeeds; because registry persistence and reconciliation are not implemented in this stage, any future live pilot must use a single reviewed payload first.

## Two-Key Live Lock

Live mode requires both:

1. the `--live` CLI flag; and
2. `LIVE_ZOHO_TASK_CREATE=true` in the process environment.

Either key by itself is insufficient. Without `--live`, the code never constructs the HTTP client and never invokes a supplied fake client. With `--live` but without the exact unlock value (case-insensitive after trimming), execution fails before payload preflight or transport use.

Example dry-run inspection:

```bash
python3 scripts/create_tasks_guarded.py <registry-report.json>
```

The dry-run output contains counts and validation errors only; it does not print task descriptions or send anything.

The live command shape is deliberately documented without real values:

```bash
LIVE_ZOHO_TASK_CREATE=true \
ZOHO_PROJECTS_API_DOMAIN=<https-origin> \
ZOHO_PROJECTS_PORTAL_ID=<portal-id> \
ZOHO_PROJECTS_PROJECT_ID=<project-id> \
ZOHO_PROJECTS_ACCESS_TOKEN=<short-lived-access-token> \
python3 scripts/create_tasks_guarded.py <registry-report.json> --live
```

Do not place real values in source code, shell history, committed `.env` files, fixtures, or documentation. The scaffold does not accept or refresh a refresh token and contains no client secret or API key handling.

## Live Payload Preconditions

Every payload must satisfy all conditions below:

- `validation.ready_for_live` is true;
- `validation.missing_status_id` is false;
- `validation.missing_tag_ids` is an empty list;
- `status.name` is exactly `In Progress`;
- `status.id` is present;
- `status.verified` is true;
- `task_parameters.custom_status` equals the verified status ID;
- all four required tag names have IDs;
- `task_parameters.tagIds` exactly matches those four IDs;
- task name and description are present; and
- portal and project IDs are present and consistent across the batch.

`status.verified: true` is an explicit assertion that both the ID-to-name mapping and create-time status parameter behavior were checked in the target Zoho Projects configuration. Merely discovering a numeric ID is not sufficient.

If any payload fails, the entire batch is rejected before the first client call. Current Stage 4/5 fixtures are expected to fail this preflight.

## Configuration Still Missing

The committed payload builder currently identifies these blockers:

- verified `In Progress` custom status ID;
- verified create-time use of that status ID;
- tag ID for `meeting-action`;
- tag ID for `zoho-ai-generated`.

The known `automation` and `internal-work` tag IDs remain configured, but live preflight requires all four. Until the missing IDs and status behavior are verified, payloads remain `ready_for_live: false` and cannot be sent.

The official Tasks API documents the create endpoint and parameters such as `name`, `description`, `person_responsible`, and `tagIds`. Its current page documents `custom_status` for task updates, while create-time status handling requires target-environment verification. This scaffold therefore requires the verified status ID in both the envelope and `task_parameters` before sending.

## Client and Transport Boundary

`TaskCreateClient` exposes one method:

```text
create_task(task_parameters) -> response map
```

The executor passes no registry report, validation envelope, portal ID, project ID, or status metadata to this method. It sends only a copied `task_parameters` map that passed preflight. Tests use a fake client to prove the boundary and call counts.

`ZohoProjectsHttpClient` is instantiated only in unlocked live mode when no client is injected. It reads these runtime values from environment variables:

- `ZOHO_PROJECTS_API_DOMAIN`
- `ZOHO_PROJECTS_PORTAL_ID`
- `ZOHO_PROJECTS_PROJECT_ID`
- `ZOHO_PROJECTS_ACCESS_TOKEN`
- optional `ZOHO_PROJECTS_TIMEOUT_SECONDS`

The API domain must be a plain HTTPS origin, portal/project IDs must be numeric, and the environment target must match the validated payload target. The client serializes `task_parameters` as form data for the documented Projects create-task endpoint.

## Registry Behavior

The scaffold reads candidate payloads but does not read, write, commit, or reconcile `proposed_registry_state`. Every result reports `registry_persisted: false`.

Future persistence must record an action only after its task creation result is confirmed and must handle partial network failure idempotently. That work is explicitly outside this stage.

## Explicitly Not Included

- Zoho Flow setup or actions
- WorkDrive triggers or file fetching
- Deluge deployment
- registry persistence
- processed-file mutation
- OAuth refresh flow
- task-list creation
- status/tag discovery
- live pilot execution

## Tests

Run the complete suite:

```bash
python3 -m unittest discover -s tests -v
```

The guard tests prove:

- dry-run makes zero client calls;
- `--live` behavior fails without `LIVE_ZOHO_TASK_CREATE=true`;
- payloads marked not live-ready are rejected;
- missing/unverified status and tag configuration blocks every call;
- full-batch validation occurs before the first call;
- a fake client receives only validated `task_parameters`; and
- an empty registry-report candidate list creates no tasks.

## Official Reference

- [Zoho Projects Tasks API](https://www.zoho.com/projects/help/rest-api/tasks-api.html)
