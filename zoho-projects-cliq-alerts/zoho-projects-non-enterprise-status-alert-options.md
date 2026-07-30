# Zoho Projects Non-Enterprise Status Alert — Options Analysis

**Goal:** Post a Zoho Cliq notification immediately when a task is moved to **Blocker** or **Needs Approval**, without Zoho Projects Enterprise.

**Date:** 2026-06-23  
**Author:** Blake (AI Automation Intern)

---

## Why the Current Flow Fails

The Zoho Flow trigger **"Task updated in project"** (Zoho Projects → Task updated) requires **Enterprise plan**.

- Confirmation: Zoho Projects Webhooks help doc — `Feature Availability: Enterprise plan.`  
  Source: https://help.zoho.com/portal/en/kb/projects/settings-in-zoho-projects/automation/task-automation/articles/webhooks-for-tasks

The Flow cannot be enabled at plan activation time; the FORBIDDEN error fires before any runtime logic executes.

---

## Plan Feature Research — What's Available Without Enterprise?

| Feature | Free | Premium | Enterprise | Source |
|---|---|---|---|---|
| Zoho Flow "Task Updated" trigger | ❌ | ❌ | ✅ | Zoho Flow UI |
| Native Webhooks (Projects UI) | ❌ | ❌ | ✅ | help.zoho.com/...webhooks-for-tasks |
| Blueprint (workflow automation) | ❌ | ✅ | ✅ | help.zoho.com/...blueprint-projects |
| Email Alerts (via Blueprint) | ❌ | ✅ (Blueprint-linked only) | ✅ | help.zoho.com/...automation-alerts |
| Zoho Projects REST API (task update) | ✅ | ✅ | ✅ | zoho.com/projects/help/rest-api/tasks-api.html |
| Cliq Channel Webhook POST | ✅ | ✅ | ✅ | zoho.com/cliq/help/platform/webhook-tokens.html |

**Key finding:** Blueprint is available on **Premium** (not just Enterprise). If Bevco is on Premium, a Blueprint can fire email alerts on transition — but **not Cliq messages** without an additional webhook, which itself requires Enterprise.

**Safest assumption without confirming plan:** Treat all native Projects-side automation (webhooks, Blueprints with webhook) as unavailable.

---

## Options Ranked Table

| # | Option | Immediate? | Requires Enterprise? | Uses Existing Flow? | Setup Effort | Exact Steps | Risk / Limitation |
|---|---|---|---|---|---|---|---|
| 1 | **Python script via CLI / Claude Code** — calls Zoho Projects API to update status, then POSTs to Cliq channel webhook | ✅ Yes | ❌ No | Partially (Cliq bot message reused) | Low (1–2 hrs) | See Implementation below | Team must run script instead of dragging task card in UI. Requires OAuth token refresh. |
| 2 | **Blueprint (Premium plan) + Email Alert → email-to-Cliq bridge** | ~30 sec delay | ❌ No (Premium) | ❌ No | Medium (3–4 hrs) | Create Blueprint for status transitions; attach Email Alert; set up email forwarding or Zoho Flow email trigger into Cliq | Adds email round-trip; Cliq message is delayed and plain-text; requires Bill to configure Blueprint as admin |
| 3 | **Zoho Flow — email trigger** — Blueprint fires email → Flow watches inbox → Flow posts to Cliq | ~1–2 min delay | ❌ No | ✅ Cliq blocks reused | Medium–High (4–6 hrs) | Blueprint email → dedicated mailbox → Zoho Flow "Email received" trigger (non-Enterprise) → existing Cliq message blocks | Blueprint requires Premium; email polling adds latency; fragile |
| 4 | **n8n automation** — Poll Projects API every 1–2 min for status changes, post to Cliq | 1–2 min delay | ❌ No | ❌ No | Medium (2–3 hrs) | n8n HTTP node polls `/tasks`; compare status; POST to Cliq webhook | Not immediate; polling uses API quota; Bevco's n8n instance is active but has only one inactive workflow currently |
| 5 | **Zoho Projects Enterprise upgrade** | ✅ Yes | ✅ Yes | ✅ Full | None (admin action only) | Bill upgrades portal plan → re-enable existing Flow | Adds cost per user; decision for Bill |

---

## ✅ Recommended Implementation: Option 1 — Python CLI Script

**Rationale:**
- Immediately available today with no plan changes.
- Uses the same Cliq bot/channel already tested and working.
- Replaces manual status drag with a single CLI command that does both actions atomically.
- Fully reversible — does not modify the existing Flow.
- Can be run from Claude Code or terminal by Blake.

**What changes operationally:**
> Instead of dragging a task card to "Blocker" or "Needs Approval" in the Projects UI, Blake (or another authorized user) runs:
> ```
> python scripts/update_task_status_and_alert.py --task-id <ID> --status "Blocker" --comment "Waiting on vendor"
> ```
> The script updates the task status via API and immediately POSTs a formatted Cliq message.

---

## Sources

| Item | URL |
|---|---|
| Zoho Projects Webhooks (Enterprise-only) | https://help.zoho.com/portal/en/kb/projects/settings-in-zoho-projects/automation/task-automation/articles/webhooks-for-tasks |
| Zoho Projects Blueprint (Premium+) | https://help.zoho.com/portal/en/kb/projects/settings-in-zoho-projects/automation/task-automation/articles/blueprint-projects |
| Zoho Projects Email Alerts | https://help.zoho.com/portal/en/kb/projects/settings-in-zoho-projects/automation/task-automation/articles/automation-alerts |
| Zoho Projects Tasks REST API | https://www.zoho.com/projects/help/rest-api/tasks-api.html |
| Zoho Projects V3 API Docs | https://projects.zoho.com/api-docs |
| Zoho Cliq Webhook Tokens & Endpoints | https://www.zoho.com/cliq/help/platform/webhook-tokens.html |
| Zoho Cliq Channel Message Endpoint | https://cliq.zoho.com/api/v2/channelsbyname/{channel}/message?zapikey={token} |
