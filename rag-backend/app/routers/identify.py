# identify.py — Speaker Identification (ECAPA-TDNN), FastAPI endpoint
# Variante A: getrennt von STT/Diarize, robust & produktionstauglich
import os
import json
import uuid
import glob
import time
import shutil
import tempfile
import subprocess
from dataclasses import dataclass
from typing import List, Dict, Optional

import numpy as np
import soundfile as sf
import torch
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi import APIRouter, UploadFile, File, Form

# ---- Konfig aus ENV ----
FFMPEG_BIN            = os.getenv("FFMPEG_BIN", "ffmpeg")
SPEAKER_STORE         = os.getenv("SPEAKER_STORE", "/app/storage/speakers")  # Verzeichnis der enrollten Sprecher
SPEAKER_SIM_THRESHOLD = float(os.getenv("SPEAKER_SIM_THRESHOLD", "0.82"))  # Cosine-Similarity-Threshold (0..1)
TOP_K_DEFAULT         = int(os.getenv("SPEAKER_TOP_K", "3"))
DEVICE                = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu")

# speechbrain Modellquelle (ECAPA)
SB_SOURCE             = os.getenv("SB_SOURCE", "speechbrain/spkrec-ecapa-voxceleb")

# ---- FastAPI ----
router = APIRouter(prefix="/identify", tags=["audio"])

# ---- Lazy-Modell (einmal pro Prozess) ----
_sb_classifier = None
def get_sb_model():
    global _sb_classifier
    if _sb_classifier is None:
        from speechbrain.inference.speaker import EncoderClassifier
        _sb_classifier = EncoderClassifier.from_hparams(
            source=SB_SOURCE,
            run_opts={"device": DEVICE}
        )
    return _sb_classifier

# ---- Utils ----
def _ffmpeg_wav_mono16k(inp_path: str, out_path: str) -> None:
    """Konvertiert zuverlässig ohne Längencut nach WAV mono/16k."""
    cmd = [FFMPEG_BIN, "-y", "-i", inp_path, "-ac", "1", "-ar", "16000", "-vn", out_path]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='ignore') or proc.stdout.decode(errors='ignore')}")

def _audio_duration_ms(wav_path: str) -> int:
    data, sr = sf.read(wav_path)
    n = data.shape[0] if isinstance(data, np.ndarray) else len(data)
    return int(n * 1000 / sr)

def _slice_ms(wav_path: str, start_ms: int, end_ms: int) -> np.ndarray:
    """Liest wav und gibt Samples [start_ms:end_ms] (mono) als float32 zurück."""
    data, sr = sf.read(wav_path, dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data[:, 0]
    start_idx = max(0, int((start_ms / 1000.0) * sr))
    end_idx = min(len(data), int((end_ms / 1000.0) * sr))
    if end_idx <= start_idx:
        return np.zeros(0, dtype="float32")
    return data[start_idx:end_idx]

def _l2_normalize(vec: np.ndarray, eps=1e-9) -> np.ndarray:
    n = np.linalg.norm(vec) + eps
    return vec / n

def _cosine_sim(a: np.ndarray, b: np.ndarray, eps=1e-9) -> float:
    return float(np.dot(a, b) / ((np.linalg.norm(a) + eps) * (np.linalg.norm(b) + eps)))

# ---- Enrollment-Store ----

@dataclass
class SpeakerEntry:
    id: str
    name: str
    emb: np.ndarray
    meta: Dict

class SpeakerDB:
    """
    Erwartet im SPEAKER_STORE:
      - Entweder Paare <speaker_id>.npy (+ optional <speaker_id>.json)
      - oder Unterordner pro Sprecher mit 'embedding.npy' + optional 'meta.json'
    .npy enthält L2-normalisiertes Embedding (1D).
    """
    def __init__(self, root: str):
        self.root = root
        self.entries: List[SpeakerEntry] = []
        self._last_scan_ts = 0.0
        self._last_mtime = 0.0
        os.makedirs(self.root, exist_ok=True)
        self._scan()

    def _current_mtime(self) -> float:
        mtimes = []
        for p in glob.glob(os.path.join(self.root, "**"), recursive=True):
            try:
                mtimes.append(os.path.getmtime(p))
            except Exception:
                pass
        return max(mtimes) if mtimes else 0.0

    def _scan(self):
        self.entries.clear()
        # Variante 1: <id>.npy (+ .json)
        for npy in glob.glob(os.path.join(self.root, "*.npy")):
            sid = os.path.splitext(os.path.basename(npy))[0]
            meta_path = os.path.join(self.root, sid + ".json")
            try:
                emb = np.load(npy).astype("float32").reshape(-1)
                emb = _l2_normalize(emb)
            except Exception:
                continue
            meta = {}
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    meta = {}
            name = meta.get("name") or meta.get("label") or sid
            self.entries.append(SpeakerEntry(id=sid, name=name, emb=emb, meta=meta))

        # Variante 2: Ordner/<id>/embedding.npy (+ meta.json)
        for d in glob.glob(os.path.join(self.root, "*")):
            if not os.path.isdir(d):
                continue
            npy = os.path.join(d, "embedding.npy")
            if not os.path.exists(npy):
                continue
            sid = os.path.basename(d)
            meta_path = os.path.join(d, "meta.json")
            try:
                emb = np.load(npy).astype("float32").reshape(-1)
                emb = _l2_normalize(emb)
            except Exception:
                continue
            meta = {}
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    meta = {}
            name = meta.get("name") or meta.get("label") or sid
            self.entries.append(SpeakerEntry(id=sid, name=name, emb=emb, meta=meta))

        self._last_scan_ts = time.time()
        self._last_mtime = self._current_mtime()

    def refresh_if_changed(self):
        mtime = self._current_mtime()
        if mtime > self._last_mtime:
            self._scan()

    def topk(self, q_emb: np.ndarray, top_k: int = TOP_K_DEFAULT) -> List[Dict]:
        sims = []
        for e in self.entries:
            sims.append((e, _cosine_sim(q_emb, e.emb)))
        sims.sort(key=lambda x: x[1], reverse=True)
        out = []
        for e, s in sims[:max(1, top_k)]:
            out.append({
                "id": e.id,
                "name": e.name,
                "similarity": float(s),
                "meta": e.meta
            })
        return out

    def best(self, q_emb: np.ndarray, threshold: float = SPEAKER_SIM_THRESHOLD) -> Optional[Dict]:
        top1 = self.topk(q_emb, top_k=1)
        if not top1:
            return None
        cand = top1[0]
        if cand["similarity"] >= threshold:
            return cand
        return None

_speaker_db = SpeakerDB(SPEAKER_STORE)

# ---- Embedding mit speechbrain (ECAPA) ----
def _embed_waveform(wave: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    """
    wave: float32 mono [-1,1]
    returns L2-normalized embedding (1D np.ndarray float32)
    """
    if wave.ndim != 1:
        wave = wave.reshape(-1)
    # speechbrain erwartet torch.Tensor [batch, time]
    wav_t = torch.from_numpy(wave).unsqueeze(0)  # [1, T]
    classifier = get_sb_model()
    with torch.no_grad():
        emb = classifier.encode_batch(wav_t)  # [1, 192] typischerweise
    emb = emb.squeeze(0).cpu().numpy().astype("float32").reshape(-1)
    return _l2_normalize(emb)

def _embed_file_segment(wav_path: str, start_ms: Optional[int] = None, end_ms: Optional[int] = None) -> np.ndarray:
    if start_ms is None or end_ms is None:
        # ganzes File
        wave, sr = sf.read(wav_path, dtype="float32", always_2d=False)
        if wave.ndim > 1:
            wave = wave[:, 0]
        return _embed_waveform(wave, sample_rate=sr)
    else:
        seg = _slice_ms(wav_path, int(start_ms), int(end_ms))
        if len(seg) == 0:
            # leeres Segment -> Null-Embedding (wird nie threshold überschreiten)
            return np.zeros(192, dtype="float32")
        return _embed_waveform(seg, sample_rate=16000)

# ---- Schemas ----
class SegmentIn(BaseModel):
    start_ms: int
    end_ms: int

class IdentifyResponse(BaseModel):
    file_duration_ms: int
    overall: Optional[Dict] = None
    topk_overall: List[Dict] = []
    segments: List[Dict] = []
    threshold: float
    top_k: int
    debug: Optional[Dict] = None

# ---- Endpoint ----
@router.post("")
async def identify_endpoint(
    file: UploadFile = File(...),
    hints: Optional[str] = Form(default=None),     # "alice,bob"
    top_k: Optional[int] = Form(default=None),
    threshold: Optional[float] = Form(default=None),
    # Optional: bereitgestellte Segmente (JSON-String oder leer)
    segments_json: Optional[str] = Form(default=None),
):
    """
    Identifiziert Sprecher per ECAPA-Embedding gegen Enrollment-Datenbank.
    - Wenn 'segments_json' angegeben wird (z.B. aus Deiner Diarize oder Whisper-Segmentierung),
      wird pro Segment ein Embedding berechnet und gematcht.
    - Ohne Segmente wird ein Overall-Embedding berechnet (für Ein-Personen-Audio sehr brauchbar).
    Rückgabewerte enthalten 'overall' (Top-Match) + 'topk_overall' sowie pro Segment 'best' + 'topk'.
    """
    # Arbeitsverzeichnis
    workdir = tempfile.mkdtemp(prefix="ident_")
    src_path = os.path.join(workdir, f"src_{uuid.uuid4().hex}")
    wav_path = os.path.join(workdir, f"conv_{uuid.uuid4().hex}.wav")

    try:
        # Datei speichern
        with open(src_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        # Konvertieren nach WAV mono/16k
        _ffmpeg_wav_mono16k(src_path, wav_path)
        dur_ms = _audio_duration_ms(wav_path)

        # Parameter
        th = SPEAKER_SIM_THRESHOLD if threshold is None else float(threshold)
        k = TOP_K_DEFAULT if (top_k is None or top_k <= 0) else int(top_k)

        # DB refresh (Hot-Reload, falls neue Sprecher eingeschrieben wurden)
        _speaker_db.refresh_if_changed()

        # Hints: können optional die Reihenfolge bevorzugter Namen beeinflussen
        hints_list = []
        if hints:
            hints_list = [h.strip() for h in hints.split(",") if h.strip()]

        # Overall-Embedding
        overall_emb = _embed_file_segment(wav_path, None, None)
        topk_overall = _speaker_db.topk(overall_emb, top_k=k)
        best_overall = None
        if topk_overall:
            # einfache Hint-Bias: wenn hint im Namen, kleine Bonifikation
            biased = []
            for cand in topk_overall:
                bonus = 0.0
                if hints_list and any(h.lower() in cand["name"].lower() for h in hints_list):
                    bonus = 0.01
                biased.append((cand, cand["similarity"] + bonus))
            biased.sort(key=lambda x: x[1], reverse=True)
            topk_overall = [c for c, _ in biased]
            if topk_overall[0]["similarity"] >= th:
                best_overall = topk_overall[0]

        # Segment-basierte Identify (optional)
        seg_results: List[Dict] = []
        seg_list: List[SegmentIn] = []
        if segments_json:
            try:
                payload = json.loads(segments_json)
                if isinstance(payload, list):
                    seg_list = [SegmentIn(**s) for s in payload]
                elif isinstance(payload, dict) and "segments" in payload and isinstance(payload["segments"], list):
                    seg_list = [SegmentIn(**s) for s in payload["segments"]]
            except Exception:
                seg_list = []

        for s in seg_list:
            emb = _embed_file_segment(wav_path, s.start_ms, s.end_ms)
            topk = _speaker_db.topk(emb, top_k=k)
            best = topk[0] if (topk and topk[0]["similarity"] >= th) else None

            # Hint-Bias auch hier (leicht)
            if topk:
                biased = []
                for cand in topk:
                    bonus = 0.0
                    if hints_list and any(h.lower() in cand["name"].lower() for h in hints_list):
                        bonus = 0.01
                    biased.append((cand, cand["similarity"] + bonus))
                biased.sort(key=lambda x: x[1], reverse=True)
                topk = [c for c, _ in biased]
                best = topk[0] if (topk and topk[0]["similarity"] >= th) else best

            seg_results.append({
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "best": best,
                "topk": topk
            })

        out = {
            "file_duration_ms": dur_ms,
            "overall": best_overall,
            "topk_overall": topk_overall,
            "segments": seg_results,
            "threshold": th,
            "top_k": k,
            "debug": {
                "store": SPEAKER_STORE,
                "num_speakers": len(_speaker_db.entries),
                "device": DEVICE,
                "model": SB_SOURCE,
                "hints": hints_list
            }
        }
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass
