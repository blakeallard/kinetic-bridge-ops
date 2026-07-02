#!/usr/bin/env python3
"""
zoho_client.py
Direct Zoho Projects API client (OAuth refresh-token flow) for the
meeting-actions Railway service. No Claude CLI, no MCP.

All credentials come from environment variables:
    ZOHO_CLIENT_ID
    ZOHO_CLIENT_SECRET
    ZOHO_REFRESH_TOKEN
    ZOHO_ACCOUNTS_BASE_URL      (default https://accounts.zoho.com)
    ZOHO_PROJECTS_API_BASE      (default https://projectsapi.zoho.com)

Legacy aliases ZOHO_ACCOUNTS_DOMAIN / ZOHO_PROJECTS_API_DOMAIN (used by the
old local .env for zoho_task_folder_sync) are honored as fallbacks so the
same .env keeps working locally.
"""

import logging
import time
import os
import uuid

import httpx

logger = logging.getLogger("meeting-actions.zoho")


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


class ZohoClient:
    """Thin Zoho Projects v1 REST client with cached access-token refresh."""

    def __init__(self) -> None:
        self.client_id = _env("ZOHO_CLIENT_ID")
        self.client_secret = _env("ZOHO_CLIENT_SECRET")
        self.refresh_token = _env("ZOHO_REFRESH_TOKEN")
        self.accounts_base = _env(
            "ZOHO_ACCOUNTS_BASE_URL", "ZOHO_ACCOUNTS_DOMAIN",
            default="https://accounts.zoho.com",
        ).rstrip("/")
        self.api_base = _env(
            "ZOHO_PROJECTS_API_BASE", "ZOHO_PROJECTS_API_DOMAIN", "ZOHO_API_BASE",
            default="https://projectsapi.zoho.com",
        ).rstrip("/")
        self._token: str | None = None
        self._token_expiry: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

    # ── auth ────────────────────────────────────────────────────────────────

    def get_access_token(self) -> str:
        if self._token and time.time() < self._token_expiry:
            return self._token
        if not self.configured:
            raise RuntimeError(
                "Zoho OAuth env vars missing (ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET"
                " / ZOHO_REFRESH_TOKEN)"
            )
        resp = httpx.post(
            f"{self.accounts_base}/oauth/v2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError(f"No access_token in Zoho response: {payload}")
        self._token = token
        # Tokens last 1h; refresh a few minutes early.
        self._token_expiry = time.time() + int(payload.get("expires_in", 3600)) - 300
        return token

    def _headers(self) -> dict:
        return {"Authorization": f"Zoho-oauthtoken {self.get_access_token()}"}

    # ── tasks ───────────────────────────────────────────────────────────────

    def get_existing_tasks(self, portal_id: str, project_id: str) -> list[dict]:
        """All tasks in the project (paginated). Returns raw task dicts."""
        tasks: list[dict] = []
        index, page_size = 1, 100
        while True:
            resp = httpx.get(
                f"{self.api_base}/restapi/portal/{portal_id}/projects/{project_id}/tasks/",
                params={"index": index, "range": page_size},
                headers=self._headers(),
                timeout=30,
            )
            if resp.status_code == 204:  # Zoho returns 204 for an empty page
                break
            resp.raise_for_status()
            page = resp.json().get("tasks", [])
            tasks.extend(page)
            if len(page) < page_size:
                break
            index += page_size
        return tasks

    def create_task(
        self,
        portal_id: str,
        project_id: str,
        name: str,
        description_html: str,
        owner_zpuid: str | None = None,
        tasklist_id: str | None = None,
    ) -> dict:
        """Create a task; returns the created task dict from Zoho."""
        params: dict = {"name": name[:250], "description": description_html}
        if owner_zpuid:
            params["person_responsible"] = owner_zpuid
        if tasklist_id:
            params["tasklist_id"] = tasklist_id
        resp = httpx.post(
            f"{self.api_base}/restapi/portal/{portal_id}/projects/{project_id}/tasks/",
            data=params,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        created = resp.json().get("tasks", [])
        if not created:
            raise RuntimeError(f"Zoho create_task returned no task: {resp.text[:300]}")
        return created[0]

    def attach_html(
        self,
        portal_id: str,
        project_id: str,
        task_id: str,
        html: str,
        filename: str,
    ) -> dict:
        """Attach an HTML file to a task (multipart upload).

        May be rejected if the portal's attachment-upload setting is off —
        callers should treat failures as non-fatal.
        """
        boundary = f"----ZohoBoundary{uuid.uuid4().hex}"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: text/html; charset=utf-8\r\n\r\n"
        ).encode() + html.encode() + f"\r\n--{boundary}--\r\n".encode()
        resp = httpx.post(
            f"{self.api_base}/restapi/portal/{portal_id}/projects/{project_id}"
            f"/tasks/{task_id}/attachments/",
            content=body,
            headers={
                **self._headers(),
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
