# identify.py — Speaker Identification (ECAPA-TDNN), FastAPI endpoint
# Robust: unterstützt Qdrant (über spk_embed) und File-Store, liefert Namen & TopK.

import os
import json
import uuid
import time
import glob
import shutil
import tempfile
import subprocess
from typing import List, Dict, Optional, Tuple

import numpy as np
import soundfile as sf
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse

# ===== Konfiguration aus ENV =====
FFMPEG_BIN             = os.getenv("FFMPEG_BIN", "ffmpeg")

# Modus: 'qdrant' ODER 'file'
SPEAKER_STORE_MODE     = os.getenv("SPEAKER_STORE", "file").lower()
SPEAKER_DIR            = os.getenv("SPEAKER_DIR", "/app/storage/speakers")  # nur File-Mode

# Schwellen & TopK
SPEAKER_SIM_THRESHOLD  = float(os.getenv("SPEAKER_SIM_THRESHOLD", "0.70"))  # Similarity (0..1)
TOP_K_DEFAULT          = int(os.getenv("SPEAKER_TOP_K", "3"))

# Aus spk_embed verwenden wir die gleichen Embeddings & (für Qdrant) die Suche
from app.services.spk_embed import audio_to_embedding, identify_embedding_full  # type: ignore

router = APIRouter(prefix="/identify", tags=["audio"])

# ===== Utilities =====
def _ffmpeg_wav_mono16k(inp_path: str, out_path: str) -> None:
    """Konvertiert zuverlässig ohne Längencut nach WAV mono/16k."""
    cmd = [FFMPEG_BIN, "-nostdin", "-y", "-i", inp_path, "-ac", "1", "-ar", "16000", "-vn", out_path]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).decode(errors="ignore")
        raise RuntimeError(f"ffmpeg failed: {err}")

def _audio_duration_ms(wav_path: str) -> int:
    data, sr = sf.read(wav_path)
    n = data.shape[0] if isinstance(data, np.ndarray) else len(data)
    return int(n * 1000 / sr)

def _cut_to_tmp_wav(src_path: str, start_ms: int, end_ms: int) -> str:
    """Schneidet [start_ms, end_ms] nach WAV 16k/mono und gibt Temp-Pfad zurück."""
    if end_ms <= start_ms:
        raise ValueError("invalid segment range")
    tmp_wav = tempfile.mktemp(suffix=".wav")
    cmd = [
        FFMPEG_BIN, "-nostdin", "-y",
        "-ss", f"{start_ms/1000:.3f}",
        "-to", f"{end_ms/1000:.3f}",
        "-i", src_path,
        "-ac", "1", "-ar", "16000", "-vn", tmp_wav
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tmp_wav

def _parse_hints(hints_raw: Optional[str]) -> Optional[List[str]]:
    if not hints_raw:
        return None
    # JSON-Liste bevorzugen
    try:
        v = json.loads(hints_raw)
        if isinstance(v, list):
            out = [str(x).strip() for x in v if isinstance(x, (str, int))]
            return [x for x in out if x]
    except Exception:
        pass
    # Fallback: Komma-Liste
    out = [h.strip() for h in str(hints_raw).split(",") if h.strip()]
    return out or None

# ===== File-Store Datenbank (einfach & schnell) =====
class _FileDB:
    """Lädt Enrollment-Daten aus SPEAKER_DIR. Erwartet *.npy und optional index.json."""
    def __init__(self, root: str):
        self.root = root
        os.makedirs(self.root, exist_ok=True)
        self.entries: List[Dict] = []   # [{id,name,vector}]
        self._last_scan_ts = 0.0
        self._last_mtime = 0.0
        self._scan()

    def _current_mtime(self) -> float:
        mtimes = []
        for p in glob.glob(os.path.join(self.root, "**"), recursive=True):
            try:
                mtimes.append(os.path.getmtime(p))
            except Exception:
                pass
        return max(mtimes) if mtimes else 0.0

    def _scan(self) -> None:
        self.entries.clear()
        # index.json mit Namen bevorzugen
        index_json = os.path.join(self.root, "index.json")
        name_by_id: Dict[str, str] = {}
        if os.path.exists(index_json):
            try:
                arr = json.load(open(index_json, "r", encoding="utf-8"))
                for it in arr or []:
                    if isinstance(it, dict) and it.get("id"):
                        name_by_id[it["id"]] = it.get("name") or it["id"]
            except Exception:
                pass

        for npy in glob.glob(os.path.join(self.root, "*.npy")):
            sid = os.path.splitext(os.path.basename(npy))[0]
            try:
                vec = np.load(npy).astype("float32").reshape(-1)
                # keine Annahme über L2-Norm – audio_to_embedding liefert bereits normierte Vektoren;
                # falls nicht, schadet Normierung nicht.
                n = np.linalg.norm(vec) + 1e-9
                vec = vec / n
                name = name_by_id.get(sid, sid)
                self.entries.append({"id": sid, "name": name, "vector": vec})
            except Exception:
                continue

        self._last_scan_ts = time.time()
        self._last_mtime = self._current_mtime()

    def refresh_if_changed(self) -> None:
        mtime = self._current_mtime()
        if mtime > self._last_mtime:
            self._scan()

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b) / ((np.linalg.norm(a) + 1e-9) * (np.linalg.norm(b) + 1e-9)))

    def topk(self, q_vec: np.ndarray, k: int) -> List[Dict]:
        scored: List[Tuple[Dict, float]] = []
        for e in self.entries:
            s = self._cosine_sim(q_vec, e["vector"])
            scored.append((e, s))
        scored.sort(key=lambda t: t[1], reverse=True)
        out = [{"id": e["id"], "name": e["name"], "similarity": float(s)} for e, s in scored[:max(1, k)]]
        return out

_file_db = _FileDB(SPEAKER_DIR) if SPEAKER_STORE_MODE != "qdrant" else None


# ===== Health =====
@router.get("/health")
def identify_health():
    num = len(_file_db.entries) if _file_db else None
    return {
        "status": "ok",
        "mode": SPEAKER_STORE_MODE,
        "dir": SPEAKER_DIR if SPEAKER_STORE_MODE != "qdrant" else None,
        "file_entries": num,
        "threshold": SPEAKER_SIM_THRESHOLD,
        "top_k_default": TOP_K_DEFAULT,
    }


# ===== Haupt-Endpoint =====
@router.post("")
async def identify_endpoint(
    file: UploadFile = File(...),
    # optional: JSON-Liste [{"start_ms":..,"end_ms":..}, ...] ODER Objekt {"segments":[...]}
    segments_json: Optional[str] = Form(default=None),
    # optional: Hints (JSON-Liste oder Komma-getrennt)
    hints: Optional[str] = Form(default=None),
    # optional: TopK & Schwelle (Similarity 0..1)
    top_k: Optional[int] = Form(default=None),
    sim_threshold: Optional[float] = Form(default=None),
):
    """
    Identifiziert Sprecher anhand von Enrollment-Daten.
    - Unterstützt Qdrant (SPEAKER_STORE=qdrant) oder File-Store (SPEAKER_STORE=file).
    - Liefert 'overall' + 'topk_overall' sowie pro Segment 'best' + 'topk'.
    - similarity ist COSINE-Similarity (0..1). 'best' nur, wenn >= sim_threshold.
    """
    # Arbeitsverzeichnis & Input persistieren
    workdir = tempfile.mkdtemp(prefix="ident_")
    src_path = os.path.join(workdir, f"src_{uuid.uuid4().hex}")
    wav_path = os.path.join(workdir, f"conv_{uuid.uuid4().hex}.wav")

    try:
        with open(src_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        # Reencode -> WAV mono/16k
        _ffmpeg_wav_mono16k(src_path, wav_path)
        dur_ms = _audio_duration_ms(wav_path)

        # Parameter
        k = TOP_K_DEFAULT if (top_k is None or int(top_k) <= 0) else int(top_k)
        thr = SPEAKER_SIM_THRESHOLD if (sim_threshold is None) else float(sim_threshold)
        hint_list = _parse_hints(hints)

        # Segmente parsen
        seg_list: List[Dict] = []
        if segments_json:
            try:
                payload = json.loads(segments_json)
                if isinstance(payload, list):
                    seg_list = payload
                elif isinstance(payload, dict) and isinstance(payload.get("segments"), list):
                    seg_list = payload["segments"]
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"segments_json invalid: {e}")

        if not seg_list:
            # Fallback: ein Segment = gesamte Datei
            seg_list = [{"start_ms": 0, "end_ms": dur_ms}]

        # --- Overall-Embedding (ganze Datei) ---
        # Wir nutzen audio_to_embedding() aus spk_embed (identische Pipeline)
        overall_emb = audio_to_embedding(wav_path)

        if SPEAKER_STORE_MODE == "qdrant":
            overall_res = identify_embedding_full(overall_emb, top_k=k, sim_threshold=thr, hints=hint_list)
            topk_overall = overall_res.get("topk", [])
            best_overall = overall_res.get("best", None)
        else:
            assert _file_db is not None
            _file_db.refresh_if_changed()
            topk_overall = _file_db.topk(overall_emb, k)
            # leichte Hint-Bias
            if hint_list and topk_overall:
                biased = []
                for c in topk_overall:
                    bonus = 0.01 if any(h.lower() in c["name"].lower() for h in hint_list) else 0.0
                    biased.append((c, c["similarity"] + bonus))
                biased.sort(key=lambda t: t[1], reverse=True)
                topk_overall = [c for c, _ in biased]
            best_overall = topk_overall[0] if (topk_overall and topk_overall[0]["similarity"] >= thr) else None

        # --- Pro Segment ---
        seg_out: List[Dict] = []
        for s in seg_list:
            try:
                start = int(s.get("start_ms", 0))
                end   = int(s.get("end_ms", 0))
            except Exception:
                start, end = 0, 0
            if end <= start:
                seg_out.append({"start_ms": start, "end_ms": end, "best": None, "topk": []})
                continue

            # Segment-Embedding (per Cut -> audio_to_embedding)
            cut_wav = _cut_to_tmp_wav(wav_path, start, end)
            try:
                emb = audio_to_embedding(cut_wav)
            finally:
                try: os.remove(cut_wav)
                except Exception: pass

            if SPEAKER_STORE_MODE == "qdrant":
                r = identify_embedding_full(emb, top_k=k, sim_threshold=thr, hints=hint_list)
                topk = r.get("topk", [])
                best = r.get("best", None)
            else:
                assert _file_db is not None
                _file_db.refresh_if_changed()
                topk = _file_db.topk(emb, k)
                if hint_list and topk:
                    biased = []
                    for c in topk:
                        bonus = 0.01 if any(h.lower() in c["name"].lower() for h in hint_list) else 0.0
                        biased.append((c, c["similarity"] + bonus))
                    biased.sort(key=lambda t: t[1], reverse=True)
                    topk = [c for c, _ in biased]
                best = topk[0] if (topk and topk[0]["similarity"] >= thr) else None

            seg_out.append({
                "start_ms": start, "end_ms": end,
                "best": best, "topk": topk
            })

        return JSONResponse({
            "file_duration_ms": dur_ms,
            "overall": best_overall,
            "topk_overall": topk_overall,
            "segments": seg_out,
            "threshold": thr,
            "top_k": k,
            "debug": {
                "mode": SPEAKER_STORE_MODE,
                "dir": SPEAKER_DIR if SPEAKER_STORE_MODE != "qdrant" else None,
                "hints": hint_list,
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass
