# rag-backend/app/transcribe.py

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Request
from typing import List, Optional, Dict, Any, Union
import os
import tempfile
import json

from faster_whisper import WhisperModel
from haystack import Document

from .auth import verify_api_key  # wie bei /index & /query
from .pipelines import build_index_pipeline

router = APIRouter()

# --- Whisper-Model lazy global ---
_WHISPER_MODEL: Optional[WhisperModel] = None


def get_whisper_model() -> WhisperModel:
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        model_name = os.getenv("WHISPER_MODEL", "small")
        device = os.getenv("WHISPER_DEVICE", "cpu")                 # "cpu" | "cuda"
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")    # "int8", "int8_float16", "float16"
        download_root = os.getenv("WHISPER_CACHE", "/app/storage/whisper")
        os.makedirs(download_root, exist_ok=True)
        _WHISPER_MODEL = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=download_root,
        )
    return _WHISPER_MODEL


def _normalize_tags(raw: Optional[Union[str, List[str]]]) -> List[str]:
    """
    Akzeptiert:
      - mehrere Felder: ["a","b"]    (z. B. -F "tags=a" -F "tags=b")
      - JSON-String: '["a","b"]'
      - CSV: "a,b"
      - Einzelwert: "a"
      - None
    und gibt eine Liste ohne Duplikate zurück.
    """
    if raw is None:
        return []

    tags: List[str] = []

    if isinstance(raw, list):
        tags = [str(x).strip() for x in raw if str(x).strip()]
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        # JSON-Liste?
        if (s.startswith("[") and s.endswith("]")) or (s.startswith('"') and s.endswith('"')):
            try:
                j = json.loads(s)
                if isinstance(j, list):
                    tags = [str(x).strip() for x in j if str(x).strip()]
                else:
                    tags = [str(j).strip()]
            except Exception:
                # Fallback: CSV
                tags = [t.strip() for t in s.split(",") if t.strip()]
        else:
            # CSV oder Einzelwert
            if "," in s:
                tags = [t.strip() for t in s.split(",") if t.strip()]
            else:
                tags = [s]
    else:
        tags = [str(raw).strip()]

    # Duplikate entfernen, Reihenfolge beibehalten
    seen = set()
    uniq: List[str] = []
    for t in tags:
        if t and t not in seen:
            uniq.append(t)
            seen.add(t)
    return uniq


@router.post("/transcribe")
async def transcribe_and_index(
    request: Request,
    file: UploadFile = File(..., description="Audio-Datei (mp3, m4a, wav, ogg, webm, etc.)"),
    # Wichtig: NICHT List[str], sonst 422 durch Pydantic-Validation.
    tags: Optional[Union[str, List[str]]] = Form(None, description="Tags als Mehrfachfeld, CSV oder JSON"),
    language: Optional[str] = Form(None, description="z. B. 'de' oder 'en' (Auto, wenn leer)"),
    index: Optional[bool] = Form(True, description="wenn true, wird das Transkript indexiert"),
    _: None = Depends(verify_api_key),
):
    """
    1) Audio → Transkript (faster-whisper)
    2) Optional: Transkript im Vektor-Store indexieren (gleiche Collection wie /index)
    """

    # --- Tags robust normalisieren (akzeptiert Mehrfachfelder, JSON oder CSV) ---
    norm_tags: List[str]
    if tags is None:
        # Versuche Roh-Form zu lesen (z. B. falls Client Mehrfachfelder gesendet hat)
        form = await request.form()
        multi = form.getlist("tags")
        if multi:
            norm_tags = _normalize_tags(multi)
        else:
            norm_tags = _normalize_tags(form.get("tags"))
    else:
        norm_tags = _normalize_tags(tags)

    # --- Datei temporär sichern ---
    try:
        suffix = os.path.splitext(file.filename or "")[1] or ".audio"
        data = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Upload fehlgeschlagen: {e}")

    try:
        # --- Transkribieren ---
        model = get_whisper_model()
        segments, info = model.transcribe(
            tmp_path,
            language=language,   # None => Auto
            beam_size=5,
            vad_filter=True,
        )
        text = " ".join([seg.text.strip() for seg in segments]).strip()

        if not text:
            return {"transcript": "", "language": getattr(info, "language", None), "indexed": 0, "files": []}

        indexed = 0
        details: List[Dict[str, Any]] = []

        # --- Optional: Indexieren ---
        if index:
            doc = Document(
                content=text,
                meta={
                    "filename": file.filename or "audio",
                    "mime": file.content_type or "audio",
                    "source": "audio-transcript",
                    "language": getattr(info, "language", None),
                    "tags": norm_tags,
                },
            )
            pipe, _store = build_index_pipeline()
            # entspricht /index: cleaner → splitter → embed → write
            pipe.run({"clean": {"documents": [doc]}})
            indexed = 1
            details.append({"filename": file.filename, "chunks": "auto"})

        return {
            "transcript": text,
            "language": getattr(info, "language", None),
            "indexed": indexed,
            "files": details,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transkription fehlgeschlagen: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
