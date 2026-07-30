# Bevco Meeting Transcriber

FastAPI service that receives Zoho WorkDrive meeting-recording events from Zoho
Flow, transcribes and summarizes the recording with OpenAI, and writes the
results back into WorkDrive.

**v2 status:** full pipeline implemented — download → audio extract → transcribe
→ summarize → upload. Heavy work runs in a background task so the webhook
returns immediately.

## Pipeline

`POST /process_meeting` (called by Zoho Flow) kicks off, in the background:

1. **Download** the MP4 from WorkDrive (OAuth refresh-token flow; tries the
   payload's `download_url`, then the WorkDrive download API by `file_id`).
2. **Extract audio** with ffmpeg → mono 16 kHz 32 kbps mp3. This drops the video
   track so even a 500 MB+ MP4 becomes a small audio file.
3. **Transcribe** with OpenAI. If the audio still exceeds the 25 MB API limit it
   is automatically split into time-based chunks and re-joined.
4. **Summarize** the transcript with OpenAI.
5. **Build** `{meeting}_metadata.json` (prior production shape).
6. **Upload** `{meeting}_transcript.txt`, `{meeting}_summary.txt`, and
   `{meeting}_metadata.json` into `target_folder_id`.

Every step logs a clear line (download started/complete, transcription
started/complete, summary, upload started/complete, errors) so Railway logs are
easy to follow.

## Endpoints

- `POST /process_meeting` — Zoho Flow webhook. Returns `{"status":"accepted"}`
  immediately and processes in the background.
- `GET /health` — health check (used by Railway).
- `GET /` — service info.
- `GET /status/{file_id}` — in-memory job status for debugging (`processing` /
  `done` / `error`). Resets on each deploy.

### Webhook payload (from Zoho Flow)

```json
{
  "team_folder": "Org Meeting Recordings",
  "file_name": "Test Meeting.mp4",
  "file_id": "...",
  "download_url": "https://download-accl.zoho.com/v1/workdrive/download/...",
  "folder_id": "...",
  "target_folder_id": "...",
  "permalink": "https://workdrive.zoho.com/file/...",
  "event": "file_upload"
}
```

### metadata.json output shape

```json
{
  "meeting_name": "Blake Weekly Tag-Up",
  "source_file_id": "...",
  "created_at": "2026-06-01T19:11:34",
  "input_file_name": "Blake Weekly Tag-Up.mp4",
  "input_size_mb": 525.24,
  "transcribe_model": "gpt-4o-transcribe-diarize",
  "summary_model": "gpt-5-mini",
  "segment_count": 491,
  "output_files": {
    "transcript": "Blake Weekly Tag-Up_transcript.txt",
    "summary": "Blake Weekly Tag-Up_summary.txt",
    "metadata": "Blake Weekly Tag-Up_metadata.json"
  }
}
```

## Railway environment variables

Set these in the service **Variables** tab:

| Variable | Example / default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | `sk-...` | **Required.** |
| `OPENAI_TRANSCRIBE_MODEL` | `gpt-4o-transcribe-diarize` | Transcription model. |
| `OPENAI_SUMMARY_MODEL` | `gpt-5-mini` | Summary model. |
| `ZOHO_CLIENT_ID` | | **Required.** From the Zoho self-client. |
| `ZOHO_CLIENT_SECRET` | | **Required.** |
| `ZOHO_REFRESH_TOKEN` | | **Required.** |
| `ZOHO_ACCOUNTS_BASE_URL` | `https://accounts.zoho.com` | Match your DC (`.com`/`.eu`/`.in`/...). |
| `ZOHO_API_BASE_URL` | `https://www.zohoapis.com/workdrive/api/v1` | Match your DC. |
| `LOG_LEVEL` | `INFO` | Optional. |

`PORT` is injected by Railway automatically. ffmpeg is installed via
`nixpacks.toml`.

## Local development

```bash
python3.13 -m venv .venv          # 3.14 homebrew build is broken on this machine
source .venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg               # needed locally for the full pipeline
cp .env.example .env              # fill in values
uvicorn main:app --reload
```

Quick smoke test of the webhook accept path (won't fully process without real
WorkDrive/OpenAI access):

```bash
curl -X POST http://localhost:8000/process_meeting \
  -H "Content-Type: application/json" \
  -d '{"team_folder":"Org Meeting Recordings","file_name":"Test Meeting.mp4","file_id":"abc","download_url":"https://...","folder_id":"f1","target_folder_id":"f2","event":"file_upload"}'

curl http://localhost:8000/health
curl http://localhost:8000/status/abc
```

Interactive docs at http://localhost:8000/docs.

## Deploy to Railway

1. Push to GitHub (`https://github.com/blake-bevco-tech/bevco-meeting-transcriber`).
2. Railway auto-redeploys on push. It reads `railway.json` (Nixpacks build,
   uvicorn start, `/health` healthcheck) and `nixpacks.toml` (installs ffmpeg).
3. Ensure all **Required** environment variables above are set.
4. Zoho Flow already POSTs to
   `https://bevco-meeting-transcriber-production.up.railway.app/process_meeting`.
