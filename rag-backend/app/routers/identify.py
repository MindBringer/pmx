# identify.py — Speaker Identification (ECAPA-TDNN), FastAPI endpoint
# Unterstützt: Datei-Store *oder* Qdrant-Store. Serverseitige Redeanteile.

import os
import json
import uuid
import glob
import time
import shutil
import tempfile
import subprocess
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

import numpy as np
import soundfile as sf
import torch
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# =========================
# Konfiguration aus ENV
# =========================
FFMPEG_BIN            = os.getenv("FFMPEG_BIN", "ffmpeg")

# Backendwahl: 'qdrant' | 'file'
_SPEAKER_BACKEND_ENV  = os.getenv("SPEAKER_BACKEND", "").strip().lower()
_SPEAKER_STORE_ENV    = os.getenv("SPEAKER_STORE", "").strip()  # kann 'qdrant'|'file' ODER Pfad sein
if _SPEAKER_BACKEND_ENV in ("qdrant", "file"):
    SPEAKER_BACKEND = _SPEAKER_BACKEND_ENV
else:
    if _SPEAKER_STORE_ENV.lower() in ("qdrant", "file"):
        SPEAKER_BACKEND = _SPEAKER_STORE_ENV.lower()
    else:
        # Wenn nichts explizit gesetzt: file-Store mit diesem Pfad
        SPEAKER_BACKEND = "file"

# Datei-Store Pfad (nur relevant wenn Backend=file)
FILE_SPEAKER_DIR      = _SPEAKER_STORE_ENV if SPEAKER_BACKEND == "file" and _SPEAKER_STORE_ENV else "/app/storage/speakers"

# Qdrant-Settings (nur relevant wenn Backend=qdrant)
QDRANT_URL            = os.getenv("QDRANT_URL", "").strip()
QDRANT_API_KEY        = os.getenv("QDRANT_API_KEY", "").strip() or None
SPEAKER_COLLECTION    = os.getenv("SPEAKER_COLLECTION", "speakers")

# Identify-Parameter
SPEAKER_SIM_THRESHOLD = float(os.getenv("SPEAKER_SIM_THRESHOLD", "0.82"))  # Cosine similarity in [0..1]
TOP_K_DEFAULT         = int(os.getenv("SPEAKER_TOP_K", "3"))

# Modell/Device
DEVICE                = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
SB_SOURCE             = os.getenv("SB_SOURCE", "speechbrain/spkrec-ecapa-voxceleb")

# =========================
# FastAPI
# =========================
router = APIRouter(prefix="/identify", tags=["audio"])

# =========================
# SpeechBrain ECAPA Modell
# =========================
_sb_classifier = None
def get_sb_model():
    """Einmal laden, dann cachen (aufs richtige DEVICE)."""
    global _sb_classifier
    if _sb_classifier is None:
        from speechbrain.inference.speaker import EncoderClassifier
        _sb_classifier = EncoderClassifier.from_hparams(
            source=SB_SOURCE,
            run_opts={"device": DEVICE}
        )
    return _sb_classifier

# =========================
# Audio Utils
# =========================
def _ffmpeg_wav_mono16k(inp_path: str, out_path: str) -> None:
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

def _slice_ms(wav_path: str, start_ms: int, end_ms: int) -> np.ndarray:
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

# =========================
# Store-Interfaces
# =========================
@dataclass
class SpeakerCand:
    id: str
    name: str
    similarity: float
    meta: Dict

class BaseStore:
    def refresh_if_changed(self): ...
    def topk(self, q_emb: np.ndarray, top_k: int) -> List[Dict]: ...
    def best(self, q_emb: np.ndarray, threshold: float) -> Optional[Dict]: ...
    def health_info(self) -> Dict: ...

# ---- Datei-Store ----
@dataclass
class SpeakerEntry:
    id: str
    name: str
    emb: np.ndarray
    meta: Dict

class FileSpeakerDB(BaseStore):
    def __init__(self, root: str):
        self.root = root
        self.entries: List[SpeakerEntry] = []
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

        # A) <id>.npy (+ optional <id>.json)
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

        # B) Ordner/<id>/embedding.npy (+ meta.json)
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

        self._last_mtime = self._current_mtime()

    def refresh_if_changed(self):
        mtime = self._current_mtime()
        if mtime > self._last_mtime:
            self._scan()

    def topk(self, q_emb: np.ndarray, top_k: int) -> List[Dict]:
        sims: List[Tuple[SpeakerEntry, float]] = []
        for e in self.entries:
            sims.append((e, _cosine_sim(q_emb, e.emb)))
        sims.sort(key=lambda x: x[1], reverse=True)
        out: List[Dict] = []
        for e, s in sims[:max(1, top_k)]:
            out.append({
                "id": e.id,
                "name": e.name,
                "similarity": float(s),
                "meta": e.meta
            })
        return out

    def best(self, q_emb: np.ndarray, threshold: float) -> Optional[Dict]:
        t = self.topk(q_emb, top_k=1)
        if not t:
            return None
        c = t[0]
        return c if c["similarity"] >= threshold else None

    def health_info(self) -> Dict:
        return {"backend": "file", "dir": self.root, "num_speakers": len(self.entries)}

# ---- Qdrant-Store ----
class QdrantSpeakerDB(BaseStore):
    def __init__(self, url: str, api_key: Optional[str], collection: str):
        self.url = url
        self.api_key = api_key
        self.collection = collection
        self.client = None
        self._init_client()

    def _init_client(self):
        try:
            from qdrant_client import QdrantClient
            self.client = QdrantClient(url=self.url, api_key=self.api_key)
        except Exception as e:
            self.client = None
            print(f"[identify] Qdrant disabled: {e}")

    def refresh_if_changed(self):  # nichts zu tun
        pass

    def _name_by_id(self, sid: str) -> str:
        if not self.client:
            return sid
        try:
            recs = self.client.retrieve(
                collection_name=self.collection,
                ids=[sid],
                with_payload=True
            )
            if recs and recs[0].payload:
                nm = recs[0].payload.get("name") or recs[0].payload.get("label")
                if isinstance(nm, str) and nm.strip():
                    return nm
        except Exception:
            pass
        return sid

    def _qfilter_from_hints(self, hints: List[str]):
        if not hints:
            return None
        try:
            from qdrant_client.http.models import Filter, FieldCondition, MatchAny
            # MatchAny auf payload.name
            return Filter(should=[FieldCondition(key="name", match=MatchAny(any=list(hints)))])
        except Exception:
            return None

    def topk(self, q_emb: np.ndarray, top_k: int) -> List[Dict]:
        if not self.client:
            return []
        try:
            res = self.client.search(
                collection_name=self.collection,
                query_vector=q_emb.tolist(),
                limit=max(1, int(top_k)),
            )
            out: List[Dict] = []
            for hit in res:
                sid = str(hit.id)
                name = (hit.payload or {}).get("name") or self._name_by_id(sid)
                out.append({
                    "id": sid,
                    "name": name,
                    "similarity": float(hit.score),  # COSINE collection ⇒ score ist similarity
                    "meta": (hit.payload or {})
                })
            return out
        except Exception as e:
            print(f"[identify] qdrant topk error: {e}")
            return []

    def topk_with_filter(self, q_emb: np.ndarray, top_k: int, hints: List[str]) -> List[Dict]:
        if not self.client:
            return []
        try:
            qfilter = self._qfilter_from_hints(hints)
            res = self.client.search(
                collection_name=self.collection,
                query_vector=q_emb.tolist(),
                limit=max(1, int(top_k)),
                query_filter=qfilter
            )
            out: List[Dict] = []
            for hit in res:
                sid = str(hit.id)
                name = (hit.payload or {}).get("name") or self._name_by_id(sid)
                out.append({
                    "id": sid,
                    "name": name,
                    "similarity": float(hit.score),
                    "meta": (hit.payload or {})
                })
            return out
        except Exception as e:
            print(f"[identify] qdrant topk(filter) error: {e}")
            return []

    def best(self, q_emb: np.ndarray, threshold: float) -> Optional[Dict]:
        t = self.topk(q_emb, top_k=1)
        if not t:
            return None
        c = t[0]
        return c if c["similarity"] >= threshold else None

    def health_info(self) -> Dict:
        info = {"backend": "qdrant", "url": self.url, "collection": self.collection}
        try:
            cols = self.client.get_collections()
            names = [c.name for c in cols.collections]
            info["collection_exists"] = self.collection in names
        except Exception as e:
            info["collection_exists"] = False
            info["warn"] = str(e)
        return info

# Store-Instanz wählen
if SPEAKER_BACKEND == "qdrant" and QDRANT_URL:
    _store: BaseStore = QdrantSpeakerDB(QDRANT_URL, QDRANT_API_KEY, SPEAKER_COLLECTION)
else:
    _store = FileSpeakerDB(FILE_SPEAKER_DIR)

# =========================
# Embedding mit ECAPA
# =========================
def _embed_waveform(wave: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    if wave.ndim != 1:
        wave = wave.reshape(-1)
    wav_t = torch.from_numpy(wave).unsqueeze(0)  # [1, T]
    classifier = get_sb_model()
    with torch.no_grad():
        emb = classifier.encode_batch(wav_t)  # [1, 192] typischerweise
    emb = emb.squeeze(0).cpu().numpy().astype("float32").reshape(-1)
    return _l2_normalize(emb)

def _embed_file_segment(wav_path: str, start_ms: Optional[int] = None, end_ms: Optional[int] = None) -> np.ndarray:
    if start_ms is None or end_ms is None:
        wave, sr = sf.read(wav_path, dtype="float32", always_2d=False)
        if wave.ndim > 1:
            wave = wave[:, 0]
        return _embed_waveform(wave, sample_rate=sr)
    seg = _slice_ms(wav_path, int(start_ms), int(end_ms))
    if len(seg) == 0:
        return np.zeros(192, dtype="float32")
    return _embed_waveform(seg, sample_rate=16000)

# =========================
# API Schemas
# =========================
class SegmentIn(BaseModel):
    start_ms: int
    end_ms: int

class IdentifyResponse(BaseModel):
    file_duration_ms: int
    overall: Optional[Dict] = None
    topk_overall: List[Dict] = []
    segments: List[Dict] = []
    speaking_shares: List[Dict] = []
    threshold: float
    top_k: int
    debug: Optional[Dict] = None

# =========================
# Health
# =========================
@router.get("/health")
def identify_health():
    try:
        _store.refresh_if_changed()
        info = _store.health_info()
        return {
            "status": "ok",
            "device": DEVICE,
            "model": SB_SOURCE,
            "identify_backend": info,
            "threshold": SPEAKER_SIM_THRESHOLD,
            "top_k_default": TOP_K_DEFAULT,
        }
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

# =========================
# Redeanteile Utilities (NEU)
# =========================
def _normalize_percents(items: List[Dict], key: str = "percent", target: float = 100.0) -> List[Dict]:
    """Skaliert Prozentwerte so, dass die Summe exakt 'target' ergibt."""
    s = sum(float(x.get(key, 0.0)) for x in items)
    if s <= 0:
        return items
    scale = target / s
    for x in items:
        x[key] = float(x.get(key, 0.0)) * scale
    total = sum(x[key] for x in items)
    if abs(total - target) > 1e-6:
        diff = target - total
        items.sort(key=lambda z: z[key], reverse=True)
        items[0][key] += diff
    return items

def _calc_speaking_shares(seg_results: List[Dict], file_duration_ms: Optional[int] = None) -> List[Dict]:
    """
    Erwartet seg_results: [{start_ms, end_ms, best|None, ...}, ...]
    Gibt Liste [{name, ms, percent}] zurück, auf 100% normiert.
    """
    buckets: Dict[str, int] = {}
    total_ms = 0
    unknown_ms = 0

    for s in seg_results or []:
        try:
            st = int(s.get("start_ms", 0))
            en = int(s.get("end_ms", 0))
        except Exception:
            st, en = 0, 0
        dur = max(0, en - st)
        total_ms += dur

        best = s.get("best") or {}
        name = (best.get("name") or "").strip() if isinstance(best, dict) else ""
        if not name:
            unknown_ms += dur
            name = None

        key = name if (name and isinstance(name, str)) else "Unbekannt"
        buckets[key] = buckets.get(key, 0) + dur

    if total_ms <= 0 and file_duration_ms:
        total_ms = int(file_duration_ms)

    shares: List[Dict] = []
    for name, ms in buckets.items():
        pct = 0.0 if total_ms <= 0 else (ms / float(total_ms)) * 100.0
        shares.append({"name": name, "ms": int(ms), "percent": pct})

    shares.sort(key=lambda x: x["ms"], reverse=True)
    _normalize_percents(shares, key="percent", target=100.0)
    for x in shares:
        x["percent"] = round(x["percent"], 1)
    return shares

# =========================
# Endpoint
# =========================
@router.post("", response_model=IdentifyResponse)
async def identify_endpoint(
    file: UploadFile = File(...),
    hints: Optional[str] = Form(default=None),     # "Name1,Name2"
    top_k: Optional[int] = Form(default=None),
    threshold: Optional[float] = Form(default=None),
    segments_json: Optional[str] = Form(default=None),  # JSON array [{start_ms,end_ms},...]
):
    """
    Identifiziert Sprecher per ECAPA-Embedding gegen Enrollment-DB (Qdrant oder Datei).
    - Mit 'segments_json' werden pro Segment Embeddings gematcht und angereichert.
    - Ohne Segmente: Overall-Embedding (gut für 1-Personen-Audio).
    Rückgabe enthält 'speaking_shares' (serverseitig berechnet) und angereicherte 'segments'.
    """
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

        # Auf WAV mono/16k wandeln
        _ffmpeg_wav_mono16k(src_path, wav_path)
        dur_ms = _audio_duration_ms(wav_path)

        # Parameter
        th = SPEAKER_SIM_THRESHOLD if threshold is None else float(threshold)
        k  = TOP_K_DEFAULT if (top_k is None or top_k <= 0) else int(top_k)

        # Store refresh (bei file)
        _store.refresh_if_changed()

        # Hints parsen
        hints_list = []
        if hints:
            hints_list = [h.strip() for h in hints.split(",") if h.strip()]

        # Overall
        overall_emb = _embed_file_segment(wav_path, None, None)

        if isinstance(_store, QdrantSpeakerDB) and hints_list:
            topk_overall = _store.topk_with_filter(overall_emb, top_k=k, hints=hints_list)
        else:
            topk_overall = _store.topk(overall_emb, top_k=k)

        best_overall = None
        if topk_overall:
            # leichte Hint-Bonifikation (gleiches Verhalten in beiden Backends)
            biased = []
            for cand in topk_overall:
                bonus = 0.01 if (hints_list and any(h.lower() in str(cand.get("name","")).lower() for h in hints_list)) else 0.0
                biased.append((cand, float(cand.get("similarity", 0.0)) + bonus))
            biased.sort(key=lambda x: x[1], reverse=True)
            topk_overall = [c for c, _ in biased]
            if topk_overall[0].get("similarity", 0.0) >= th:
                best_overall = topk_overall[0]

        # Segmente?
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
            if isinstance(_store, QdrantSpeakerDB) and hints_list:
                topk = _store.topk_with_filter(emb, top_k=k, hints=hints_list)
            else:
                topk = _store.topk(emb, top_k=k)

            best = topk[0] if (topk and float(topk[0].get("similarity", 0.0)) >= th) else None

            # erneute Hint-Bias (leicht)
            if topk:
                biased = []
                for cand in topk:
                    bonus = 0.01 if (hints_list and any(h.lower() in str(cand.get("name","")).lower() for h in hints_list)) else 0.0
                    biased.append((cand, float(cand.get("similarity", 0.0)) + bonus))
                biased.sort(key=lambda x: x[1], reverse=True)
                topk = [c for c, _ in biased]
                best = topk[0] if (topk and float(topk[0].get("similarity", 0.0)) >= th) else best

            seg_results.append({
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "best": best,
                "topk": topk
            })

        # ---- Redeanteile serverseitig berechnen + Segmente anreichern ----
        def _seg_speaker_name(seg: Dict) -> Optional[str]:
            if isinstance(seg.get("speaker"), str) and seg["speaker"].strip():
                return seg["speaker"].strip()
            if isinstance(seg.get("name"), str) and seg["name"].strip():
                return seg["name"].strip()
            b = seg.get("best") or {}
            if isinstance(b, dict):
                nm = b.get("name") or b.get("id")
                if isinstance(nm, str) and nm.strip():
                    return nm.strip()
            tk = seg.get("topk") or []
            if isinstance(tk, list) and tk:
                first = tk[0]
                if isinstance(first, dict):
                    nm = first.get("name") or first.get("id")
                    if isinstance(nm, str) and nm.strip():
                        return nm.strip()
            return None

        enriched_segments: List[Dict] = []
        for seg in seg_results:
            st = int(seg.get("start_ms", 0))
            en = int(seg.get("end_ms", 0))
            dur = max(0, en - st)
            who = _seg_speaker_name(seg) or "Unbekannt"
            seg_out = dict(seg)
            seg_out["speaker"] = who
            seg_out["duration_ms"] = dur
            enriched_segments.append(seg_out)

        # Redeanteile exakt auf 100% normiert berechnen
        speaking_shares = _calc_speaking_shares(enriched_segments, file_duration_ms=dur_ms)

        out = {
            "file_duration_ms": dur_ms,
            "overall": best_overall,
            "topk_overall": topk_overall,
            "segments": enriched_segments,
            "speaking_shares": speaking_shares,
            "threshold": th,
            "top_k": k,
            "debug": {
                "backend": SPEAKER_BACKEND,
                "file_dir": FILE_SPEAKER_DIR if isinstance(_store, FileSpeakerDB) else None,
                "qdrant_url": QDRANT_URL if isinstance(_store, QdrantSpeakerDB) else None,
                "collection": SPEAKER_COLLECTION if isinstance(_store, QdrantSpeakerDB) else None,
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
