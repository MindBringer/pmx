# rag-backend/app/services/asr.py
import os
from typing import List, Tuple, Optional
import tempfile
import subprocess
from faster_whisper import WhisperModel

DEVICE = os.getenv("DEVICE", "cpu")
ASR_MODEL = os.getenv("ASR_MODEL", "medium")
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "int8")  # cpu:int8, gpu:float16

_model_cache: Optional[WhisperModel] = None

def _ffmpeg_to_wav_mono16k(in_path: str) -> str:
    out_path = tempfile.mktemp(suffix=".wav")
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-i", in_path,
        "-ac", "1", "-ar", "16000", "-vn", out_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out_path

def load_asr_model() -> WhisperModel:
    global _model_cache
    if _model_cache is None:
        compute_type = ASR_COMPUTE_TYPE
        device = "cuda" if DEVICE.startswith("cuda") else "cpu"
        _model_cache = WhisperModel(ASR_MODEL, device=device, compute_type=compute_type)
    return _model_cache

def transcribe(path: str, language: Optional[str] = None) -> Tuple[str, List[dict]]:
    """
    Returns (full_text, segments)
    segments: [{start, end, text}]
    """
    wav = _ffmpeg_to_wav_mono16k(path)
    model = load_asr_model()
    segs, info = model.transcribe(wav, language=language)
    segments = []
    texts = []
    for s in segs:
        segments.append({"start": float(s.start), "end": float(s.end), "text": s.text.strip()})
        texts.append(s.text.strip())
    return (" ".join(texts).strip(), segments)
