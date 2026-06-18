"""
Bevco Meeting Transcriber — FastAPI service for Zoho WorkDrive.

v2 pipeline (POST /process_meeting):
  1. Receive the Zoho Flow webhook payload.
  2. Download the MP4 from Zoho WorkDrive (OAuth refresh-token flow).
  3. Extract a small audio track with ffmpeg (handles huge video files).
  4. Transcribe with OpenAI (chunked automatically if over the size limit).
  5. Summarize with OpenAI.
  6. Build metadata.json matching the prior production shape.
  7. Upload transcript / summary / metadata back into WorkDrive.

Heavy work runs in a FastAPI background task so the webhook returns 200
immediately and Zoho Flow never times out. Every major step is logged.
"""

import hashlib
import json
import logging
import math
import mimetypes
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI
from openai import OpenAI
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("transcriber")

# SECURITY: httpx logs full request URLs at INFO, which would leak the Zoho
# token-refresh query string (refresh_token/client_secret) and signed download
# URLs. Silence it so secrets never reach the logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Config (all via environment variables — see .env.example)
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-transcribe-diarize")
# Ordered fallback chain if the primary (diarize) model rejects the audio.
OPENAI_TRANSCRIBE_FALLBACK_MODELS = [
    m.strip() for m in os.getenv(
        "OPENAI_TRANSCRIBE_FALLBACK_MODELS", "gpt-4o-transcribe,whisper-1"
    ).split(",") if m.strip()
]
OPENAI_SUMMARY_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5-mini")

ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID", "")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN", "")
ZOHO_ACCOUNTS_BASE_URL = os.getenv("ZOHO_ACCOUNTS_BASE_URL", "https://accounts.zoho.com")
ZOHO_API_BASE_URL = os.getenv("ZOHO_API_BASE_URL", "https://www.zohoapis.com/workdrive/api/v1")

# OpenAI transcription endpoint rejects files larger than 25 MB. Stay under it.
MAX_AUDIO_BYTES = 24 * 1024 * 1024

app = FastAPI(title="Bevco Meeting Transcriber", version="2.1.7")

# Lightweight in-memory status, keyed by file_id — handy for /status debugging.
# (Resets on each deploy; not durable, just an aid.)
job_status: dict[str, dict] = {}

_openai_client: OpenAI | None = None


def openai_client() -> OpenAI:
    """Lazily create the OpenAI client so import never fails on a missing key."""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


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
    permalink: str | None = None
    event: str | None = None

    class Config:
        extra = "allow"


# ---------------------------------------------------------------------------
# Zoho WorkDrive helpers
# ---------------------------------------------------------------------------
def get_zoho_access_token() -> str:
    """Exchange the long-lived refresh token for a short-lived access token."""
    url = f"{ZOHO_ACCOUNTS_BASE_URL}/oauth/v2/token"
    # Send credentials in the POST body (form-encoded), NOT the URL query string,
    # so they never appear in request-URL logs.
    form = {
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token",
    }
    resp = httpx.post(url, data=form, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Zoho token refresh returned no access_token: {data}")
    return token


def _zoho_download_host() -> str:
    """Derive the WorkDrive download host for the configured data center.
    e.g. https://www.zohoapis.com/... -> https://download.zoho.com"""
    suffix = ".com"
    host = ZOHO_API_BASE_URL.split("//", 1)[-1].split("/", 1)[0]  # www.zohoapis.com
    if "zohoapis" in host:
        suffix = host.split("zohoapis", 1)[-1] or ".com"  # ".com", ".eu", ".in", ...
    return f"https://download.zoho{suffix}"


def _metadata_download_url(file_id: str, token: str) -> str | None:
    """Fetch file metadata and return the download URL Zoho reports for it."""
    url = f"{ZOHO_API_BASE_URL}/files/{file_id}"
    headers = {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Accept": "application/vnd.api+json",
    }
    resp = httpx.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    attrs = (resp.json().get("data") or {}).get("attributes") or {}
    return attrs.get("download_url") or attrs.get("Download") or None


def download_workdrive_file(download_url: str | None, file_id: str | None,
                            token: str, dest_path: str) -> None:
    """Stream a WorkDrive file to disk, trying several strategies and recording
    the full error (status + Zoho response body) from each so failures are
    diagnosable."""
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}

    # Build the ordered list of (label, url) strategies.
    candidates: list[tuple[str, str]] = []
    if download_url:
        candidates.append(("payload_download_url", download_url))
    if file_id:
        try:
            meta_url = _metadata_download_url(file_id, token)
            if meta_url:
                candidates.append(("metadata_download_url", meta_url))
        except Exception as exc:
            logger.warning("Metadata lookup for %s failed: %s", file_id, exc)
        candidates.append(
            ("download_host", f"{_zoho_download_host()}/v1/workdrive/download/{file_id}")
        )

    errors: list[str] = []
    for label, url in candidates:
        try:
            with httpx.stream("GET", url, headers=headers, timeout=None,
                              follow_redirects=True) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", "replace")[:300]
                    raise RuntimeError(f"HTTP {resp.status_code}: {body}")
                with open(dest_path, "wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        fh.write(chunk)
            logger.info("Download succeeded via [%s]", label)
            return
        except Exception as exc:
            logger.warning("Download attempt [%s] %s failed: %s", label, url, exc)
            errors.append(f"[{label}] {exc}")
    raise RuntimeError("All WorkDrive download attempts failed -> " + " || ".join(errors))


def upload_to_workdrive(file_path: str, filename: str, parent_id: str,
                        token: str) -> dict:
    """Upload a single file into a WorkDrive folder via the upload API."""
    url = f"{ZOHO_API_BASE_URL}/upload"
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(file_path, "rb") as fh:
        files = {"content": (filename, fh, mime)}
        data = {
            "parent_id": parent_id,
            "filename": filename,
            "override-name-exist": "true",
        }
        resp = httpx.post(url, headers=headers, data=data, files=files, timeout=180)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Audio / ffmpeg helpers
# ---------------------------------------------------------------------------
# Standard, widely-supported encoding for OpenAI: mp3 / libmp3lame, 16 kHz mono.
_AUDIO_CODEC = ["-ac", "1", "-ar", "16000", "-codec:a", "libmp3lame", "-b:a", "64k"]


def extract_audio(video_path: str, audio_path: str) -> None:
    """Extract a standard mp3 (libmp3lame, 16 kHz, mono, 64k) audio track from
    the video. Drops the video track so even huge MP4s become small audio."""
    cmd = ["ffmpeg", "-y", "-i", video_path, "-vn", *_AUDIO_CODEC, audio_path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise RuntimeError(f"ffmpeg exit {proc.returncode}: " + " | ".join(tail))


def verify_audio(audio_path: str) -> float:
    """Validate the extracted file with ffprobe before sending to OpenAI, and log
    codec/sample_rate/channels/duration/bit_rate/size. Returns duration (s)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries",
        "stream=codec_name,sample_rate,channels,bit_rate:format=duration,size",
        "-of", "json", audio_path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {(out.stderr or '')[-300:]}")
    info = json.loads(out.stdout or "{}")
    streams = info.get("streams") or []
    fmt = info.get("format") or {}
    s0 = streams[0] if streams else {}
    duration = float(fmt.get("duration") or 0)
    details = {
        "codec_name": s0.get("codec_name"),
        "sample_rate": s0.get("sample_rate"),
        "channels": s0.get("channels"),
        "duration": duration,
        "bit_rate": s0.get("bit_rate"),
        "size_bytes": int(fmt.get("size") or os.path.getsize(audio_path)),
    }
    logger.info("Audio probe: %s", details)
    if not streams or duration <= 0 or s0.get("codec_name") != "mp3":
        raise RuntimeError(f"Extracted audio looks invalid: {details}")
    return duration


def get_audio_duration(audio_path: str) -> float:
    """Return media duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return float(out.stdout.strip())


# ---------------------------------------------------------------------------
# OpenAI transcription
# ---------------------------------------------------------------------------
def _extract_text_segments(resp) -> tuple[str, list]:
    """Normalize a transcription response (object / dict / plain str) into
    (text, segments)."""
    if isinstance(resp, str):
        return resp, []

    data = None
    if hasattr(resp, "model_dump"):
        try:
            data = resp.model_dump()
        except Exception:
            data = None
    if data is None and isinstance(resp, dict):
        data = resp
    if data is None:
        text = getattr(resp, "text", "") or ""
        segs = getattr(resp, "segments", None) or []
        return text, list(segs)

    text = data.get("text") or ""
    segs = data.get("segments") or []
    return text, segs


def _call_transcription(audio_path: str, model: str):
    """Single OpenAI transcription call with the right params for the model
    family. Diarize models need response_format=diarized_json + chunking_strategy;
    whisper-1 uses verbose_json (which returns segments); others use json."""
    is_diarize = "diarize" in model.lower()
    with open(audio_path, "rb") as fh:
        if is_diarize:
            return openai_client().audio.transcriptions.create(
                model=model, file=fh, response_format="diarized_json",
                chunking_strategy="auto",
            )
        fmt = "verbose_json" if "whisper" in model.lower() else "json"
        return openai_client().audio.transcriptions.create(
            model=model, file=fh, response_format=fmt,
        )


def _transcribe_one(audio_path: str, model: str) -> tuple[str, list, str]:
    """Transcribe one (size-safe) audio file, trying the primary model then each
    fallback in order. Returns (text, segments, model_used)."""
    chain = [model] + [m for m in OPENAI_TRANSCRIBE_FALLBACK_MODELS if m != model]
    last_exc: Exception | None = None
    for m in chain:
        try:
            resp = _call_transcription(audio_path, m)
            text, segs = _extract_text_segments(resp)
            if text or segs:
                if m != model:
                    logger.info("Transcription succeeded via fallback model %s", m)
                return text, segs, m
            last_exc = RuntimeError(f"{m} returned an empty result")
            logger.warning("Transcription via %s returned empty; trying next", m)
        except Exception as exc:
            last_exc = exc
            logger.warning("Transcription via %s failed (%s); trying next", m, exc)
    raise RuntimeError(f"All transcription models failed: {last_exc}")


def transcribe_audio(audio_path: str, model: str) -> tuple[str, list, str]:
    """Transcribe an audio file, splitting into time-based chunks if it exceeds
    the OpenAI size limit. Returns (raw_text, segments, model_used)."""
    size = os.path.getsize(audio_path)
    if size <= MAX_AUDIO_BYTES:
        return _transcribe_one(audio_path, model)

    duration = get_audio_duration(audio_path)
    num_chunks = math.ceil(size / MAX_AUDIO_BYTES)
    chunk_dur = duration / num_chunks
    logger.info(
        "Audio is %.1f MB (> %d MB limit); splitting into %d chunks (~%.0fs each)",
        size / 1e6, MAX_AUDIO_BYTES // (1024 * 1024), num_chunks, chunk_dur,
    )

    all_text: list[str] = []
    all_segs: list = []
    models_used: set[str] = set()
    for i in range(num_chunks):
        start = i * chunk_dur
        chunk_path = f"{audio_path}.part{i}.mp3"
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-t", str(chunk_dur),
               "-i", audio_path, *_AUDIO_CODEC, chunk_path]
        subprocess.run(cmd, check=True, capture_output=True)
        logger.info("Transcribing chunk %d/%d", i + 1, num_chunks)
        text, segs, used = _transcribe_one(chunk_path, model)
        all_text.append(text)
        all_segs.extend(segs)
        models_used.add(used)
        os.remove(chunk_path)

    model_used = model if models_used == {model} else "+".join(sorted(models_used))
    return "\n".join(t for t in all_text if t), all_segs, model_used


def render_transcript(raw_text: str, segments: list) -> str:
    """Produce a readable transcript. Uses speaker-labeled segments when the
    diarization model provides them, otherwise the plain text."""
    if segments:
        lines = []
        for seg in segments:
            if isinstance(seg, dict):
                speaker = seg.get("speaker")
                text = seg.get("text")
            else:
                speaker = getattr(seg, "speaker", None)
                text = getattr(seg, "text", None)
            if not text:
                continue
            text = text.strip()
            lines.append(f"{speaker}: {text}" if speaker else text)
        if lines:
            return "\n".join(lines)
    return raw_text


# ---------------------------------------------------------------------------
# OpenAI summary
# ---------------------------------------------------------------------------
def summarize(transcript: str, model: str, meeting_name: str) -> str:
    """Generate a clean meeting summary from the transcript."""
    resp = openai_client().chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You write clear, concise, well-structured meeting summaries.",
            },
            {
                "role": "user",
                "content": (
                    f"Meeting: {meeting_name}\n\n"
                    "Write a clean summary of the meeting below. Include these "
                    "sections when the content supports them:\n"
                    "- Overview\n- Key Discussion Points\n- Decisions\n"
                    "- Action Items (with owners and due dates if mentioned)\n\n"
                    f"Transcript:\n{transcript}"
                ),
            },
        ],
    )
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Background pipeline
# ---------------------------------------------------------------------------
def process_meeting_job(payload: dict) -> None:
    file_id = payload.get("file_id") or "unknown"
    file_name = payload.get("file_name") or "meeting.mp4"
    download_url = payload.get("download_url")
    target_folder_id = payload.get("target_folder_id") or payload.get("folder_id")
    meeting_name = Path(file_name).stem

    # Capture what Zoho actually sent (sensitive values redacted to length) so
    # payload-shape problems are visible in /jobs.
    recv = {
        "payload_keys": sorted(payload.keys()),
        "payload_preview": {
            k: (None if v is None
                else f"<{len(str(v))} chars>"
                if any(s in k.lower() for s in ("url", "permalink", "token", "secret"))
                else str(v)[:80])
            for k, v in payload.items()
        },
    }
    job_status[file_id] = {"state": "processing", "step": "start",
                           "file_name": file_name, **recv}

    missing = [
        name for name, val in {
            "OPENAI_API_KEY": OPENAI_API_KEY,
            "ZOHO_CLIENT_ID": ZOHO_CLIENT_ID,
            "ZOHO_CLIENT_SECRET": ZOHO_CLIENT_SECRET,
            "ZOHO_REFRESH_TOKEN": ZOHO_REFRESH_TOKEN,
        }.items() if not val
    ]
    if missing:
        msg = f"Missing required env vars: {', '.join(missing)}"
        logger.error(msg)
        job_status[file_id] = {"state": "error", "error": msg, **recv}
        return
    if not target_folder_id:
        msg = "No target_folder_id (or folder_id) in payload — nowhere to upload results."
        logger.error(msg)
        job_status[file_id] = {"state": "error", "error": msg, **recv}
        return

    workdir = tempfile.mkdtemp(prefix="meeting_")
    try:
        token = get_zoho_access_token()

        # 1. Download -----------------------------------------------------
        video_path = os.path.join(workdir, file_name)
        logger.info("Download started: %s", file_name)
        job_status[file_id]["step"] = "download"
        download_workdrive_file(download_url, file_id, token, video_path)
        downloaded_bytes = os.path.getsize(video_path)
        input_size_mb = round(downloaded_bytes / 1024 / 1024, 2)
        # Sniff the first bytes — if Zoho returned an HTML/JSON error page with a
        # 200, ffmpeg would choke; surface that clearly instead.
        with open(video_path, "rb") as _fh:
            head = _fh.read(16)
        looks_like_text = head[:1] in (b"<", b"{") or head[:5] == b"<!DOC"
        job_status[file_id]["downloaded_mb"] = input_size_mb
        job_status[file_id]["head_hex"] = head.hex()
        logger.info("Download complete: %s (%.2f MB, head=%s)",
                    file_name, input_size_mb, head.hex())
        if downloaded_bytes < 1024 or looks_like_text:
            snippet = head.decode("utf-8", "replace")
            raise RuntimeError(
                f"Downloaded file looks invalid ({downloaded_bytes} bytes, "
                f"starts with {snippet!r}) — likely an error page, not the MP4."
            )

        # 2. Extract audio ------------------------------------------------
        audio_path = os.path.join(workdir, f"{meeting_name}.mp3")
        logger.info("Extracting audio with ffmpeg...")
        job_status[file_id]["step"] = "extract_audio"
        extract_audio(video_path, audio_path)
        audio_duration = verify_audio(audio_path)
        logger.info("Audio extracted & verified: %.2f MB, %.0fs",
                    os.path.getsize(audio_path) / 1024 / 1024, audio_duration)

        # 3. Transcribe ---------------------------------------------------
        logger.info("Transcription started (model=%s)", OPENAI_TRANSCRIBE_MODEL)
        job_status[file_id]["step"] = "transcribe"
        raw_text, segments, transcribe_model_used = transcribe_audio(
            audio_path, OPENAI_TRANSCRIBE_MODEL
        )
        transcript_text = render_transcript(raw_text, segments)
        segment_count = len(segments)
        logger.info(
            "Transcription complete (model=%s): %d segments, %d chars",
            transcribe_model_used, segment_count, len(transcript_text),
        )

        # 4. Summarize ----------------------------------------------------
        logger.info("Summary started (model=%s)", OPENAI_SUMMARY_MODEL)
        job_status[file_id]["step"] = "summarize"
        summary_text = summarize(transcript_text, OPENAI_SUMMARY_MODEL, meeting_name)
        logger.info("Summary complete: %d chars", len(summary_text))

        # 5. Metadata + write files --------------------------------------
        out_names = {
            "transcript": f"{meeting_name}_transcript.txt",
            "summary": f"{meeting_name}_summary.txt",
            "metadata": f"{meeting_name}_metadata.json",
        }
        metadata = {
            "meeting_name": meeting_name,
            "source_file_id": file_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "input_file_name": file_name,
            "input_size_mb": input_size_mb,
            "transcribe_model": transcribe_model_used,
            "summary_model": OPENAI_SUMMARY_MODEL,
            "segment_count": segment_count,
            "output_files": out_names,
        }

        transcript_path = os.path.join(workdir, out_names["transcript"])
        summary_path = os.path.join(workdir, out_names["summary"])
        metadata_path = os.path.join(workdir, out_names["metadata"])
        Path(transcript_path).write_text(transcript_text, encoding="utf-8")
        Path(summary_path).write_text(summary_text, encoding="utf-8")
        Path(metadata_path).write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        # 6. Upload -------------------------------------------------------
        # Refresh the token — transcription of a long meeting can outlast the
        # ~1 hour access-token lifetime.
        token = get_zoho_access_token()
        logger.info("Upload started -> folder %s", target_folder_id)
        job_status[file_id]["step"] = "upload"
        for path in (transcript_path, summary_path, metadata_path):
            name = os.path.basename(path)
            upload_to_workdrive(path, name, target_folder_id, token)
            logger.info("Uploaded %s", name)
        logger.info("Upload complete for meeting '%s'", meeting_name)

        job_status[file_id] = {
            "state": "done",
            "meeting_name": meeting_name,
            "segment_count": segment_count,
            "output_files": out_names,
        }
    except Exception as exc:
        logger.exception("Processing failed for '%s': %s", file_name, exc)
        job_status[file_id] = {"state": "error", "error": str(exc)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {"service": "bevco-meeting-transcriber", "status": "ok", "version": "2.1.7"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/removed-endpoint")
def debug_zoho(file_id: str | None = None):
    """Diagnostic: token scope check, plus (if file_id given) the raw /files/{id}
    metadata and a detailed probe of the download host so we can see the correct
    download mechanism. Remove once download is confirmed."""
    rt = os.getenv("ZOHO_REFRESH_TOKEN", "")
    out: dict = {
        "refresh_token_sha8": hashlib.sha256(rt.encode()).hexdigest()[:8] if rt else None,
        "api_base": ZOHO_API_BASE_URL,
    }
    try:
        token = get_zoho_access_token()
        out["token_refresh"] = "ok"
        hdr = {"Authorization": f"Zoho-oauthtoken {token}"}
        api_hdr = {**hdr, "Accept": "application/vnd.api+json"}

        r = httpx.get(f"{ZOHO_API_BASE_URL}/users/me", headers=api_hdr, timeout=30)
        out["users_me_status"] = r.status_code

        if file_id:
            # Raw file metadata — reveals the correct download attribute/link.
            try:
                m = httpx.get(f"{ZOHO_API_BASE_URL}/files/{file_id}",
                              headers=api_hdr, timeout=30)
                out["files_status"] = m.status_code
                out["files_body"] = m.text[:1200]
            except Exception as exc:
                out["files_error"] = str(exc)

            # Probe the download host with full detail (status, ctype, head bytes).
            dh = f"{_zoho_download_host()}/v1/workdrive/download/{file_id}"
            out["download_host_url"] = dh
            try:
                d = httpx.get(dh, headers=hdr, timeout=60, follow_redirects=True)
                out["download_host_status"] = d.status_code
                out["download_host_ctype"] = d.headers.get("content-type")
                out["download_host_len"] = len(d.content)
                out["download_host_head_hex"] = d.content[:24].hex()
                if d.status_code >= 400:
                    out["download_host_body"] = d.text[:300]
            except Exception as exc:
                out["download_host_error"] = str(exc)
    except Exception as exc:
        out["error"] = str(exc)
    return out


@app.get("/jobs")
def jobs():
    """All processing jobs seen since the last deploy (in-memory), newest-first
    insertion order. Handy for watching a run without knowing its file_id."""
    return job_status


@app.get("/status/{file_id}")
def status(file_id: str):
    return job_status.get(file_id, {"state": "unknown"})


@app.post("/process_meeting")
def process_meeting(payload: MeetingEvent, background_tasks: BackgroundTasks):
    data = payload.model_dump()
    logger.info("Received meeting event: %s", data)
    background_tasks.add_task(process_meeting_job, data)
    return {
        "status": "accepted",
        "file_name": payload.file_name,
        "file_id": payload.file_id,
        "event": payload.event,
        "message": "Payload received. Processing started in the background.",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
