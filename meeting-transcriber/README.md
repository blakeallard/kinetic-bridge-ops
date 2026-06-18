# Bevco Meeting Transcriber

Minimal FastAPI service that receives Zoho WorkDrive meeting-recording events
from Zoho Flow and (eventually) transcribes + summarizes them, writing the
results back to WorkDrive.

**v1 status:** the webhook is live — it logs the payload and returns
`accepted`. Transcription is stubbed out (see the TODOs in `main.py`).

## Endpoint

### `POST /process_meeting`

Request body (sent by Zoho Flow):

```json
{
  "team_folder": "Org Meeting Recordings",
  "file_name": "Test Meeting.mp4",
  "file_id": "...",
  "download_url": "...",
  "folder_id": "...",
  "target_folder_id": "...",
  "event": "file_upload"
}
```

Response:

```json
{
  "status": "accepted",
  "file_name": "Test Meeting.mp4",
  "file_id": "...",
  "event": "file_upload",
  "message": "Payload received and logged. Transcription not yet implemented."
}
```

Health checks: `GET /` and `GET /health`.

## Local development

```bash
python3.13 -m venv .venv          # 3.14 homebrew build is broken on this machine
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # fill in values
uvicorn main:app --reload
```

Test it:

```bash
curl -X POST http://localhost:8000/process_meeting \
  -H "Content-Type: application/json" \
  -d '{"team_folder":"Org Meeting Recordings","file_name":"Test Meeting.mp4","file_id":"abc","download_url":"https://...","folder_id":"f1","target_folder_id":"f2","event":"file_upload"}'
```

Interactive docs at http://localhost:8000/docs.

## Deploy to Railway

1. Push this repo to GitHub
   (`https://github.com/blake-bevco-tech/bevco-meeting-transcriber`).
2. In Railway: **New Project → Deploy from GitHub repo** → pick this repo.
3. Railway reads `railway.json` (Nixpacks build, uvicorn start command,
   `/health` healthcheck). `$PORT` is injected automatically.
4. Add the environment variables from `.env.example` in the service
   **Variables** tab.
5. Point your Zoho Flow webhook at
   `https://<your-app>.up.railway.app/process_meeting`.

## Roadmap (the TODOs in `main.py`)

1. Download the MP4 from Zoho WorkDrive
2. Send audio to OpenAI for transcription
3. Generate a summary
4. Build `metadata.json`
5. Upload transcript / summary / metadata back to WorkDrive
