# rag-backend/app/transcribe.py
# transcribe.py — Variante A (robust, keine Hard-Cuts), FastAPI Router

import os
import uuid
import shutil
import tempfile
import subprocess
from typing import List, Optional, Tuple

import numpy as np
import soundfile as sf
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from faster_whisper import WhisperModel

# --------- Konfiguration über ENV ----------
ASR_MODEL         = os.getenv("ASR_MODEL", "medium")
ASR_DEVICE        = os.getenv("DEVICE", "cuda")  # "cuda" | "cpu"
ASR_COMPUTE_TYPE  = os.getenv("ASR_COMPUTE_TYPE", "float16")  # "float16"|"int8_float16"|"int8"|"float32"
ASR_BEAM_SIZE     = int(os.getenv("ASR_BEAM_SIZE", "5"))
ASR_CHUNK_LENGTH  = int(os.getenv("ASR_CHUNK_LENGTH", "120"))  # Sekunden (120 empfohlen)
ASR_VAD_FILTER    = os.getenv("ASR_VAD_FILTER", "true").lower() in ("1", "true", "yes", "on")
FFMPEG_BIN        = os.getenv("FFMPEG_BIN", "ffmpeg")

# --------- FastAPI Router ----------
router = APIRouter(tags=["audio"])

# Whisper Model warm halten (GPU spart massiv Zeit)
_whisper_model: Optional[WhisperModel] = None
def get_model() -> WhisperModel:
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = WhisperModel(
            ASR_MODEL, device=ASR_DEVICE, compute_type=ASR_COMPUTE_TYPE
        )
    return _whisper_model

# --------- Helpers ----------
def _ffmpeg_wav_mono16k(inp_path: str, out_path: str) -> None:
    """Konvertiert Audio zuverlässig nach WAV mono/16k, ohne Längen-Cut."""
    cmd = [FFMPEG_BIN, "-y", "-i", inp_path, "-ac", "1", "-ar", "16000", "-vn", out_path]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed: {proc.stderr.decode(errors='ignore') or proc.stdout.decode(errors='ignore')}"
        )

def _audio_duration_ms(wav_path: str) -> int:
    data, sr = sf.read(wav_path)
    n = data.shape[0] if isinstance(data, np.ndarray) else len(data)
    return int(n * 1000 / sr)

def _collect_transcript(whisper_segments) -> Tuple[str, List[dict]]:
    text_total: List[str] = []
    segments: List[dict] = []
    for s in whisper_segments:
        stext = (s.text or "").strip()
        if stext:
            text_total.append(stext)
        segments.append({
            "start_ms": int((getattr(s, "start", 0.0) or 0.0) * 1000),
            "end_ms":   int((getattr(s, "end", 0.0)   or 0.0) * 1000),
            "text":     stext
        })
    return ("".join(text_total)).strip(), segments

# --------- Response Model ----------
class TranscribeOut(BaseModel):
    text: str
    segments: List[dict]
    info: dict
    summary: Optional[dict] = None  # Platz für Downstream-Summary (deutsche Keys)
    debug: Optional[dict]  = None

# --------- Endpoint ----------
@router.post("/transcribe", response_model=TranscribeOut)
async def transcribe_endpoint(
    file: UploadFile = File(...),
    language: Optional[str] = Form(default=None),      # z.B. "de"
    vad_filter: Optional[bool] = Form(default=None),   # override
    chunk_length: Optional[int] = Form(default=None),  # override Sekunden
):
    """
    Transkribiert die komplette Datei – keine Diarize-Cuts, robust gegen 24s-Kappung.
    """
    workdir = tempfile.mkdtemp(prefix="transc_")
    src_path = os.path.join(workdir, f"src_{uuid.uuid4().hex}")
    wav_path = os.path.join(workdir, f"conv_{uuid.uuid4().hex}.wav")

    # Defaults ggf. aus ENV
    use_vad = ASR_VAD_FILTER if vad_filter is None else bool(vad_filter)
    chunk_len = ASR_CHUNK_LENGTH if (chunk_length is None or chunk_length <= 0) else int(chunk_length)

    try:
        # Datei persistieren (streamed read)
        with open(src_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        # Reencode → WAV mono/16k (keine Längenlimits)
        _ffmpeg_wav_mono16k(src_path, wav_path)
        dur_ms = _audio_duration_ms(wav_path)

        # Transcribe (ganze Datei, große Chunks, optional VAD)
        model = get_model()
        it, info = model.transcribe(
            wav_path,
            language=language or None,
            vad_filter=use_vad,
            chunk_length=chunk_len if chunk_len > 0 else None,
            beam_size=ASR_BEAM_SIZE,
            temperature=0.0,
        )
        whisper_segments = list(it)
        full_text, segments = _collect_transcript(whisper_segments)

        # Optionale leere Summary-Struktur (deutsch) → kompatibel mit deinem Renderer / Summarizer
        summary = {
            "tldr": [],
            "entscheidungen": [],
            "aktionen": [],
            "offene_fragen": [],
            "risiken": [],
            "zeitachse": [],
            "redeanteile": [],
        }

        out = {
            "text": full_text,
            "segments": segments,
            "info": {
                "language": getattr(info, "language", None),
                "duration_ms": dur_ms,
                "model": ASR_MODEL,
                "device": ASR_DEVICE,
                "compute_type": ASR_COMPUTE_TYPE,
                "vad_filter": use_vad,
                "chunk_length_s": chunk_len,
                "beam_size": ASR_BEAM_SIZE,
            },
            "summary": summary,
            "debug": {
                "input_filename": file.filename,
                "workdir": os.path.basename(workdir),
            },
        }
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        # Aufräumen
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass
