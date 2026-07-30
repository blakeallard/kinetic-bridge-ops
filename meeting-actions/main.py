#!/usr/bin/env python3
"""
Bevco Meeting Actions — FastAPI service for Railway.

POST /process_summary
  Receives a meeting summary (text + filename + portal/project metadata) from
  a Zoho Flow webhook, runs BEVCO worksheet-based task extraction with OpenAI
  gpt-4o-mini, dedupes, and creates Zoho Projects tasks.

GET /health
  Liveness probe for Railway.

Same deploy pattern as bevco-meeting-transcriber (Nixpacks + uvicorn).
"""

import logging
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import pipeline

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
# httpx logs full request URLs at INFO — the Zoho token refresh would leak
# client_secret/refresh_token into Railway logs. Silence it.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("meeting-actions")

app = FastAPI(title="Bevco Meeting Actions", version="1.0.0")


class ProcessSummaryRequest(BaseModel):
    summary_text: str
    summary_file_name: str
    portal_id: str | None = None      # "bevcollc" or numeric; non-numeric → env default
    project_id: str | None = None
    dry_run: bool = False
    blake_only: bool = False
    force: bool = False  # bypass the processed_notes.json skip only


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/process_summary")
def process_summary(req: ProcessSummaryRequest) -> dict:
    if not req.summary_text.strip():
        raise HTTPException(status_code=422, detail="summary_text is empty")
    logger.info(
        "process_summary: file=%s dry_run=%s blake_only=%s",
        req.summary_file_name, req.dry_run, req.blake_only,
    )
    try:
        return pipeline.process_summary(
            summary_text=req.summary_text,
            summary_file_name=req.summary_file_name,
            portal_id=req.portal_id,
            project_id=req.project_id,
            dry_run=req.dry_run,
            blake_only=req.blake_only,
            force=req.force,
        )
    except Exception as e:
        logger.exception("process_summary failed for %s", req.summary_file_name)
        raise HTTPException(status_code=500, detail=str(e))
