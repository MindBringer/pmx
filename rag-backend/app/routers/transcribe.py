# rag-backend/app/transcribe.py
# transcribe.py — Variante A (robust, keine Hard-Cuts), FastAPI Router

import logging
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
ASR_MODEL               = os.getenv("ASR_MODEL", "medium")
ASR_DEVICE              = os.getenv("DEVICE", "cuda")  # "cuda" | "cpu"
ASR_COMPUTE_TYPE        = os.getenv("ASR_COMPUTE_TYPE", "float16")  # "float16"|"int8_float16"|"int8"|"float32"
ASR_BEAM_SIZE           = int(os.getenv("ASR_BEAM_SIZE", "5"))
ASR_BEST_OF             = int(os.getenv("ASR_BEST_OF", "1"))
ASR_TEMPERATURE         = float(os.getenv("ASR_TEMPERATURE", "0.0"))
ASR_INITIAL_PROMPT      = os.getenv("ASR_INITIAL_PROMPT", "").strip()
ASR_CHUNK_LENGTH        = int(os.getenv("ASR_CHUNK_LENGTH", "120"))  # Sekunden (120 empfohlen)
ASR_VAD_FILTER          = os.getenv("ASR_VAD_FILTER", "true").lower() in ("1", "true", "yes", "on")
ASR_NO_SPEECH_THRESHOLD = float(os.getenv("ASR_NO_SPEECH_THRESHOLD", "0.8"))
ASR_LOG_PROB_THRESHOLD  = float(os.getenv("ASR_LOG_PROB_THRESHOLD", "-1.0"))
FFMPEG_BIN              = os.getenv("FFMPEG_BIN", "ffmpeg")

# --------- FastAPI Router ----------
router = APIRouter(prefix="/transcribe", tags=["audio"])

logger = logging.getLogger(__name__)

@router.on_event("startup")
def preload_model() -> None:
    """Ensure the Whisper model is loaded when the application starts."""
    try:
        get_model()
    except Exception:  # pragma: no cover - logging of unexpected errors
        logger.exception("Failed to preload Whisper model during startup")

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
@router.post("", response_model=TranscribeOut)
async def transcribe_endpoint(
    file: UploadFile = File(...),

    # Bestehende/optionale Overrides
    language: Optional[str] = Form(default=None),      # z.B. "de"
    vad_filter: Optional[bool] = Form(default=None),   # override
    chunk_length: Optional[int] = Form(default=None),  # override Sekunden

    # NEU: feinere Steuerung pro Request
    beam_size: Optional[int] = Form(default=None),
    best_of: Optional[int] = Form(default=None),
    temperature: Optional[float] = Form(default=None),
    initial_prompt: Optional[str] = Form(default=None),

    # Optional: Schwellenwerte überschreiben
    no_speech_threshold: Optional[float] = Form(default=None),
    log_prob_threshold: Optional[float] = Form(default=None),
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

    # Effektive Parameter (ENV-Default -> Request-Override)
    eff_beam_size = ASR_BEAM_SIZE if (beam_size is None or beam_size <= 0) else int(beam_size)
    eff_best_of = ASR_BEST_OF if (best_of is None or best_of <= 0) else int(best_of)
    eff_temperature = ASR_TEMPERATURE if (temperature is None) else float(temperature)
    eff_initial_prompt = (initial_prompt if (initial_prompt is not None and initial_prompt.strip()) else ASR_INITIAL_PROMPT)
    eff_no_speech_threshold = ASR_NO_SPEECH_THRESHOLD if (no_speech_threshold is None) else float(no_speech_threshold)
    eff_log_prob_threshold = ASR_LOG_PROB_THRESHOLD if (log_prob_threshold is None) else float(log_prob_threshold)

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
            no_speech_threshold=eff_no_speech_threshold,
            log_prob_threshold=eff_log_prob_threshold,
            chunk_length=chunk_len if chunk_len > 0 else None,

            # NEU: dynamische Decoding-Parameter
            beam_size=eff_beam_size,
            best_of=eff_best_of,               # wir geben es durch; nutzt Sampling, wenn beam_size==1
            temperature=eff_temperature,       # float oder Liste; hier float
            initial_prompt=(eff_initial_prompt or None),
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
                "beam_size": eff_beam_size,
                "best_of": eff_best_of,
                "temperature": eff_temperature,
                "used_initial_prompt": bool(eff_initial_prompt),
                "no_speech_threshold": eff_no_speech_threshold,
                "log_prob_threshold": eff_log_prob_threshold,
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
