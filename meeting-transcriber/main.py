"""
Bevco Meeting Transcriber — FastAPI service for Zoho WorkDrive.

v1 scope:
  - Accept a webhook payload from Zoho Flow on POST /process_meeting
  - Log the payload
  - Return status "accepted"

Transcription / summarization / upload are intentionally NOT implemented yet.
See the TODO blocks in process_meeting() for the planned pipeline.
"""

import logging
import os

from fastapi import FastAPI
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("transcriber")

# ---------------------------------------------------------------------------
# Config (all via environment variables — see .env.example)
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID", "")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN", "")
ZOHO_ACCOUNTS_URL = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com")
ZOHO_WORKDRIVE_API = os.getenv("ZOHO_WORKDRIVE_API", "https://www.zohoapis.com/workdrive/api/v1")
OPENAI_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
OPENAI_SUMMARY_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini")

app = FastAPI(title="Bevco Meeting Transcriber", version="0.1.0")


# ---------------------------------------------------------------------------
# Request model — matches the payload Zoho Flow sends.
# Extra fields are allowed so Zoho can add keys without breaking the endpoint.
# ---------------------------------------------------------------------------
class MeetingEvent(BaseModel):
    team_folder: str | None = None
    file_name: str | None = None
    file_id: str | None = None
    download_url: str | None = None
    folder_id: str | None = None
    target_folder_id: str | None = None
    event: str | None = None

    class Config:
        extra = "allow"


# ---------------------------------------------------------------------------
# Health check — Railway and uptime monitors hit this.
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {"service": "bevco-meeting-transcriber", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# Main webhook endpoint
# ---------------------------------------------------------------------------
@app.post("/process_meeting")
def process_meeting(payload: MeetingEvent):
    logger.info("Received meeting event: %s", payload.model_dump())

    # =====================================================================
    # TODO 1: Download the MP4 from Zoho WorkDrive
    # ---------------------------------------------------------------------
    # - Get a fresh Zoho access token from the refresh token
    #   (POST {ZOHO_ACCOUNTS_URL}/oauth/v2/token with grant_type=refresh_token).
    # - Use payload.download_url (or the WorkDrive download endpoint with
    #   payload.file_id) to stream the file to a temp path under /tmp.
    # - Verify the file is a video before continuing.
    # =====================================================================

    # =====================================================================
    # TODO 2: Send the audio to OpenAI for transcription
    # ---------------------------------------------------------------------
    # - Use OPENAI_API_KEY + OPENAI_TRANSCRIBE_MODEL (default whisper-1).
    # - WorkDrive recordings may exceed the API size limit (~25 MB) — plan to
    #   extract/compress the audio track or chunk long meetings.
    # - Collect the full transcript text (+ optional timestamps).
    # =====================================================================

    # =====================================================================
    # TODO 3: Generate a summary
    # ---------------------------------------------------------------------
    # - Call a chat model (OPENAI_SUMMARY_MODEL) with the transcript.
    # - Produce: overview, key decisions, action items, attendees if inferable.
    # =====================================================================

    # =====================================================================
    # TODO 4: Build metadata.json
    # ---------------------------------------------------------------------
    # - Capture: original file_name, file_id, processed_at timestamp,
    #   model versions used, duration, transcript word count, summary.
    # =====================================================================

    # =====================================================================
    # TODO 5: Upload results back to WorkDrive
    # ---------------------------------------------------------------------
    # - Upload transcript.txt, summary.md, metadata.json into
    #   payload.target_folder_id via the WorkDrive upload API.
    # - Consider a subfolder named after the meeting for tidy organization.
    # =====================================================================

    return {
        "status": "accepted",
        "file_name": payload.file_name,
        "file_id": payload.file_id,
        "event": payload.event,
        "message": "Payload received and logged. Transcription not yet implemented.",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
