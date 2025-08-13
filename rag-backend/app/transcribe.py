from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from typing import List, Optional, Dict, Any
import os
import tempfile
from faster_whisper import WhisperModel

from haystack import Document
from .auth import verify_api_key  # wie bei /index & /query
from .pipelines import build_index_pipeline

router = APIRouter()

# --- Whisper-Model lazy global ---
_WHISPER_MODEL = None

def get_whisper_model() -> WhisperModel:
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        model_name = os.getenv("WHISPER_MODEL", "small")
        device = os.getenv("WHISPER_DEVICE", "cpu")           # "cpu" | "cuda"
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")  # z.B. "int8", "int8_float16", "float16"
        download_root = os.getenv("WHISPER_CACHE", "/app/storage/whisper")
        os.makedirs(download_root, exist_ok=True)
        _WHISPER_MODEL = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=download_root,
        )
    return _WHISPER_MODEL


@router.post("/transcribe")
def transcribe_and_index(
    file: UploadFile = File(..., description="Audio-Datei (mp3, m4a, wav, ogg, webm, etc.)"),
    tags: Optional[List[str]] = Form(None, description="optionale Tags; mehrfaches Feld"),
    language: Optional[str] = Form(None, description="z. B. 'de' oder 'en' (Auto, wenn leer)"),
    index: bool = Form(True, description="wenn true, wird das Transkript in den Vektor-Store geschrieben"),
    _: None = Depends(verify_api_key),
):
    """
    1) Audio → Transkript (faster-whisper)
    2) Optional: Transkript als Text in denselben Vektor-Store indexieren (wie /index)
    """
    # 0) Datei sichern
    try:
        suffix = os.path.splitext(file.filename or "")[1] or ".audio"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Upload fehlgeschlagen: {e}")

    try:
        # 1) Transkribieren
        model = get_whisper_model()
        segments, info = model.transcribe(
            tmp_path,
            language=language,      # None => Auto
            beam_size=5,
            vad_filter=True,
        )
        text = " ".join([seg.text.strip() for seg in segments]).strip()

        if not text:
            return {"transcript": "", "language": info.language, "indexed": 0, "files": []}

        # 2) Optional: Indexieren (wie /index – nur ohne Datei-Konvert-Umweg)
        indexed = 0
        details: List[Dict[str, Any]] = []
        if index:
            doc = Document(
                content=text,
                meta={
                    "filename": file.filename or "audio",
                    "mime": file.content_type or "audio",
                    "source": "audio-transcript",
                    "language": info.language,
                    "tags": tags or [],
                },
            )
            pipe, _store = build_index_pipeline()
            # identisch zu /index: cleaner → splitter → embed → write
            pipe.run({"clean": {"documents": [doc]}})
            indexed = 1
            details.append({"filename": file.filename, "chunks": "auto"})

        return {
            "transcript": text,
            "language": info.language,
            "indexed": indexed,
            "files": details,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transkription fehlgeschlagen: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
