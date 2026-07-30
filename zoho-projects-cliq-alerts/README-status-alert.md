# Zoho Projects → Cliq Status Alert Script

Replaces the Enterprise-only Zoho Flow "Task Updated" trigger.

When a task needs to be moved to **Blocker** or **Needs Approval**, run this script instead of dragging the card in the UI. The script updates the task status via the Zoho Projects API and immediately posts a formatted message to the configured Cliq channel — no Enterprise plan required.

---

## Why This Exists

Zoho Flow's **"Task updated in project"** trigger requires Zoho Projects Enterprise.  
Zoho Projects native webhooks also require Enterprise.  
This script bypasses both by using the Zoho Projects REST API directly.

**References:**
- Zoho Projects Webhooks (Enterprise-only): https://help.zoho.com/portal/en/kb/projects/settings-in-zoho-projects/automation/task-automation/articles/webhooks-for-tasks
- Zoho Cliq Channel Webhook endpoint: https://www.zoho.com/cliq/help/platform/webhook-tokens.html

---

## Prerequisites

- Python 3.8+ (no external packages — stdlib only)
- Zoho OAuth self-client with a refresh token  
  Scopes needed: `ZohoProjects.tasks.ALL`, `ZohoProjects.portals.READ`  
  Create at: https://api-console.zoho.com/
- Zoho Cliq webhook token (see Setup Step 2)

---

## Setup

### Step 1 — Configure credentials

```bash
cp scripts/.env.example scripts/.env
# Edit scripts/.env and fill in all values
```

### Step 2 — Get Cliq channel webhook URL

1. Open Zoho Cliq
2. Go to **Settings → Bots & Tools → Webhook Tokens**
3. Authenticate with 2FA
4. Click **Generate New Token** (or use an existing one)
5. Click the token → **Get Webhook URL**
6. Select module: **Channels** → pick your channel name
7. Copy the full URL (includes `zapikey=...`)
8. Paste into `CLIQ_CHANNEL_WEBHOOK_URL` in your `.env`

### Step 3 — Verify task statuses exist

Ensure "Blocker" and "Needs Approval" exist as custom statuses in your project.  
Check via: Zoho Projects → your project → Settings → Task Status

---

## Usage

```bash
cd /path/to/project

# Move a task to Blocker
python scripts/update_task_status_and_alert.py \
  --task-id 2543412000001324999 \
  --status "Blocker" \
  --comment "Blocked waiting on vendor API credentials"

# Move a task to Needs Approval
python scripts/update_task_status_and_alert.py \
  --task-id 2543412000001324999 \
  --status "Needs Approval" \
  --comment "Ready for Bill to review and approve"

# With custom updated-by name
python scripts/update_task_status_and_alert.py \
  --task-id 2543412000001324999 \
  --status "Blocker" \
  --updated-by "Bryan"
```

### Arguments

| Argument | Required | Description |
|---|---|---|
| `--task-id` | ✅ | Numeric Zoho Projects task ID |
| `--status` | ✅ | `"Blocker"` or `"Needs Approval"` (exact match to your status names) |
| `--comment` | ❌ | Comment to add to the task and include in Cliq message |
| `--updated-by` | ❌ | Name shown in Cliq notification (default: Blake) |

---

## Finding a Task ID

The task ID is the numeric part of the task URL in Zoho Projects:
```
https://projects.zoho.com/portal/bevcollc/projects/2543412000001324010/#tasks:2543412000001324999
                                                                                  ↑ task ID
```

Or from the Zoho Projects MCP tool in Claude Code (`get_tasks_by_project`).

---

## What the Cliq Message Looks Like

```
🚫 Task Status Update

Task: T44 — Email-to-Task Automation (BE-9-T44)
New Status: Blocker
Updated by: Blake
Time: 2026-06-23 14:32
Comment: Waiting on vendor API credentials

[ Open Task ]
```

---

## Do Not Commit

`.env` is excluded from version control. Never add credentials to `.env.example` or any tracked file.

---

## Limitations

- The person running the script must have edit access to the task in Zoho Projects.
- Task status names must match exactly (case-sensitive) to what is configured in the project.
- OAuth refresh tokens expire if unused; regenerate at https://api-console.zoho.com/ if needed.
- This does not replace the existing Zoho Flow — the Flow remains disabled/inactive. It can be re-enabled if the plan is upgraded to Enterprise.
