# rag-backend/app/services/spk_embed.py
import os
import json
import uuid
import numpy as np
import tempfile
import subprocess
from typing import Dict, List, Tuple, Optional
import threading

import torch
import torchaudio
from speechbrain.pretrained import EncoderClassifier

# -------------------- Config --------------------
DEVICE = "cuda" if os.getenv("DEVICE", "cpu").startswith("cuda") and torch.cuda.is_available() else "cpu"

SPEAKER_STORE = os.getenv("SPEAKER_STORE", "file").lower()      # "file" | "qdrant"
SPEAKER_DIR = os.getenv("SPEAKER_DIR", "/data/speakers")        # für file-Store
SPEAKER_COLLECTION = os.getenv("SPEAKER_COLLECTION", "pmx_speakers")
SPEAKER_VEC_SIZE = int(os.getenv("SPEAKER_VEC_SIZE", "192"))    # ecapa-voxceleb ≈ 192
SPEAKER_JSON = os.path.join(SPEAKER_DIR, "index.json")

QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "").strip()

_classifier_cache: Optional[EncoderClassifier] = None
_qdrant = None
_lock = threading.Lock()

# -------------------- Helpers --------------------
def _ensure_dirs():
    if SPEAKER_STORE == "file":
        os.makedirs(SPEAKER_DIR, exist_ok=True)

def _ffmpeg_to_wav_mono16k(in_path: str) -> str:
    out_path = tempfile.mktemp(suffix=".wav")
    cmd = ["ffmpeg", "-nostdin", "-y", "-i", in_path, "-ac", "1", "-ar", "16000", "-vn", out_path]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out_path

def load_embedder() -> EncoderClassifier:
    global _classifier_cache
    if _classifier_cache is None:
        _classifier_cache = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": DEVICE}
        )
    return _classifier_cache

def audio_to_embedding(path: str) -> np.ndarray:
    wav = _ffmpeg_to_wav_mono16k(path)
    try:
        with torch.inference_mode():
            signal, sr = torchaudio.load(wav)
            signal = signal.to(DEVICE)
            emb = load_embedder().encode_batch(signal).mean(dim=1).squeeze(0).detach().cpu().numpy()
        return emb.astype(np.float32)
    finally:
        try:
            os.remove(wav)
        except Exception:
            pass
        if DEVICE.startswith("cuda") and torch.cuda.is_available():
            # Speicher zeitnah freigeben
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

# -------------------- File-based store --------------------
def _file_load() -> List[Dict]:
    _ensure_dirs()
    if not os.path.exists(SPEAKER_JSON):
        return []
    try:
        with open(SPEAKER_JSON, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []

def _file_save(items: List[Dict]):
    _ensure_dirs()
    tmp = SPEAKER_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SPEAKER_JSON)

# -------------------- Qdrant store --------------------
def _get_qdrant():
    global _qdrant
    if _qdrant is not None:
        return _qdrant
    if SPEAKER_STORE != "qdrant" or not QDRANT_URL:
        return None
    try:
        from qdrant_client import QdrantClient
        _qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
        return _qdrant
    except Exception as e:
        print(f"[spk] Qdrant disabled: {e}")
        return None

def _qdrant_ensure_collection(dim: int) -> None:
    qc = _get_qdrant()
    if not qc:
        return
    from qdrant_client.http.models import Distance, VectorParams
    try:
        # nur anlegen, wenn nicht vorhanden
        cols = [c.name for c in qc.get_collections().collections]
        if SPEAKER_COLLECTION not in cols:
            qc.recreate_collection(
                collection_name=SPEAKER_COLLECTION,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
    except Exception as e:
        print(f"[spk] ensure collection error: {e}")

def _qdrant_list() -> List[Dict]:
    qc = _get_qdrant()
    if not qc:
        return []
    try:
        res, _ = qc.scroll(collection_name=SPEAKER_COLLECTION, with_payload=True, limit=1000)
        out = []
        for p in res:
            payload = p.payload or {}
            out.append({"id": str(p.id), "name": payload.get("name", "Unbekannt")})
        return out
    except Exception as e:
        print(f"[spk] list (qdrant) error: {e}")
        return []

def _qdrant_upsert(spk_id: str, name: str, vector: np.ndarray) -> bool:
    qc = _get_qdrant()
    if not qc:
        return False
    from qdrant_client.http.models import PointStruct
    try:
        qc.upsert(
            collection_name=SPEAKER_COLLECTION,
            points=[PointStruct(id=spk_id, vector=vector.tolist(), payload={"name": name})],
        )
        return True
    except Exception as e:
        # Dimension mismatch? -> einmalig mit korrekter Dim neu anlegen und erneut versuchen
        msg = str(e).lower()
        if "dimension" in msg or "vector size" in msg or "wrong vector" in msg:
            try:
                _qdrant_recreate_collection(len(vector))
                qc.upsert(
                    collection_name=SPEAKER_COLLECTION,
                    points=[{"id": spk_id, "vector": vector.tolist(), "payload": {"name": name}}],
                )
                return True
            except Exception as e2:
                print(f"[spk] upsert after recreate failed: {e2}")
        print(f"[spk] upsert (qdrant) error: {e}")
        return False

def _qdrant_recreate_collection(dim: int):
    qc = _get_qdrant()
    if not qc:
        return
    from qdrant_client.http.models import Distance, VectorParams
    print(f"[spk] recreate collection {SPEAKER_COLLECTION} with dim {dim}")
    qc.recreate_collection(
        collection_name=SPEAKER_COLLECTION,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )

def _qdrant_delete(spk_id: str) -> bool:
    qc = _get_qdrant()
    if not qc:
        return False
    try:
        qc.delete(collection_name=SPEAKER_COLLECTION, points_selector=[spk_id])
        return True
    except Exception as e:
        print(f"[spk] delete (qdrant) error: {e}")
        return False

def _qdrant_retrieve_vector(spk_id: str) -> Optional[np.ndarray]:
    qc = _get_qdrant()
    if not qc:
        return None
    try:
        recs = qc.retrieve(collection_name=SPEAKER_COLLECTION, ids=[spk_id], with_vectors=True)
        if not recs:
            return None
        vec = getattr(recs[0], "vector", None) or getattr(recs[0], "vectors", None)
        if isinstance(vec, dict):  # named vectors
            vec = next(iter(vec.values()))
        if vec is None:
            return None
        return np.array(vec, dtype=np.float32)
    except Exception as e:
        print(f"[spk] retrieve (qdrant) error: {e}")
        return None

# -------------------- Public API (unchanged signatures) --------------------
def list_speakers() -> List[Dict]:
    if SPEAKER_STORE == "qdrant" and _get_qdrant():
        lst = _qdrant_list()
        if lst:
            return lst
        # Fallback auf File-Store, falls Qdrant leer/Fehler
    with _lock:
        return _file_load()

def enroll_speaker(name: str, path: str) -> Dict:
    emb = audio_to_embedding(path)
    dim = int(emb.shape[0])
    spk_id = str(uuid.uuid4())

    if SPEAKER_STORE == "qdrant" and _get_qdrant():
        _qdrant_ensure_collection(dim)
        if _qdrant_upsert(spk_id, name, emb):
            return {"id": spk_id, "name": name, "dim": dim}

    # Fallback: File-Store
    with _lock:
        os.makedirs(SPEAKER_DIR, exist_ok=True)
        np.save(os.path.join(SPEAKER_DIR, f"{spk_id}.npy"), emb)
        items = _file_load()
        items.append({"id": spk_id, "name": name})
        _file_save(items)
    return {"id": spk_id, "name": name, "dim": dim}

def delete_speaker(spk_id: str) -> bool:
    ok = False
    if SPEAKER_STORE == "qdrant" and _get_qdrant():
        ok = _qdrant_delete(spk_id)
    with _lock:
        items = _file_load()
        n0 = len(items)
        items = [x for x in items if x.get("id") != spk_id]
        if len(items) != n0:
            _file_save(items)
            ok = True
        npy = os.path.join(SPEAKER_DIR, f"{spk_id}.npy")
        if os.path.exists(npy):
            try:
                os.remove(npy)
            except Exception:
                pass
    return ok

def load_embedding(spk_id: str) -> Optional[np.ndarray]:
    if SPEAKER_STORE == "qdrant" and _get_qdrant():
        v = _qdrant_retrieve_vector(spk_id)
        if v is not None:
            return v
    npy = os.path.join(SPEAKER_DIR, f"{spk_id}.npy")
    if not os.path.exists(npy):
        return None
    return np.load(npy)

def identify_embedding(emb: np.ndarray, threshold: float = 0.25, hints: Optional[List[str]] = None) -> Tuple[Optional[str], float]:
    """
    Return (speaker_name, distance) if match below threshold else (None, best_distance)
    distance = 1 - cosine_similarity  (0 = identisch, 1 = maximal verschieden)
    """
    # Qdrant-Suche (schnell & skalierbar)
    if SPEAKER_STORE == "qdrant" and _get_qdrant():
        try:
            from qdrant_client.http.models import Filter, FieldCondition, MatchAny, MatchValue
            qfilter = None
            if hints:
                # Filter auf Namen (ODER)
                qfilter = Filter(should=[FieldCondition(key="name", match=MatchAny(any=list(hints)))])
            res = _qdrant.search(
                collection_name=SPEAKER_COLLECTION,
                query_vector=emb.tolist(),
                limit=1,
                query_filter=qfilter
            )
            if res:
                hit = res[0]
                # Qdrant score bei COSINE ist Similarity -> Distanz = 1 - score
                dist = float(1.0 - hit.score)
                name = (hit.payload or {}).get("name", "Unbekannt")
                if dist <= threshold:
                    return (name, dist)
                return (None, dist)
        except Exception as e:
            print(f"[spk] identify (qdrant) error: {e}")

    # File-Store / Fallback: brute-force Cosine
    from numpy.linalg import norm
    items = list_speakers()
    if hints:
        items = [x for x in items if x.get("name") in hints or x.get("id") in hints]
    if not items:
        return (None, 1.0)

    best_name, best_dist = None, 1.0
    for it in items:
        ref = load_embedding(it["id"])
        if ref is None:
            continue
        sim = float(np.dot(emb, ref) / (norm(emb) * norm(ref) + 1e-9))
        dist = 1.0 - sim
        if dist < best_dist:
            best_dist, best_name = dist, it["name"]
    if best_dist <= threshold:
        return (best_name, best_dist)
    return (None, best_dist)
