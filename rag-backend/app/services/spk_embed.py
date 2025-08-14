# rag-backend/app/services/spk_embed.py
import os
import json
import uuid
import numpy as np
import tempfile
import subprocess
from typing import Dict, List, Tuple, Optional
import torch
import torchaudio
from speechbrain.pretrained import EncoderClassifier

DEVICE = "cuda" if os.getenv("DEVICE", "cpu").startswith("cuda") and torch.cuda.is_available() else "cpu"
SPEAKER_STORE = os.getenv("SPEAKER_STORE", "file")
SPEAKER_DIR = os.getenv("SPEAKER_DIR", "/data/speakers")

_classifier_cache: Optional[EncoderClassifier] = None

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
    signal, sr = torchaudio.load(wav)
    signal = signal.to(DEVICE)
    emb = load_embedder().encode_batch(signal).mean(dim=1).squeeze(0).detach().cpu().numpy()
    return emb.astype(np.float32)

# ---- File-based store (default) ----
def list_speakers() -> List[Dict]:
    _ensure_dirs()
    idx_path = os.path.join(SPEAKER_DIR, "index.json")
    if not os.path.exists(idx_path):
        return []
    with open(idx_path, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_index(items: List[Dict]):
    idx_path = os.path.join(SPEAKER_DIR, "index.json")
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

def enroll_speaker(name: str, path: str) -> Dict:
    _ensure_dirs()
    emb = audio_to_embedding(path)
    spk_id = str(uuid.uuid4())
    np.save(os.path.join(SPEAKER_DIR, f"{spk_id}.npy"), emb)
    items = list_speakers()
    items.append({"id": spk_id, "name": name})
    _save_index(items)
    return {"id": spk_id, "name": name, "dim": int(emb.shape[0])}

def delete_speaker(spk_id: str) -> bool:
    _ensure_dirs()
    items = list_speakers()
    items2 = [x for x in items if x["id"] != spk_id]
    if len(items2) == len(items):
        return False
    _save_index(items2)
    npy = os.path.join(SPEAKER_DIR, f"{spk_id}.npy")
    if os.path.exists(npy):
        os.remove(npy)
    return True

def load_embedding(spk_id: str) -> Optional[np.ndarray]:
    npy = os.path.join(SPEAKER_DIR, f"{spk_id}.npy")
    if not os.path.exists(npy):
        return None
    return np.load(npy)

def identify_embedding(emb: np.ndarray, threshold: float = 0.25, hints: Optional[List[str]] = None) -> Tuple[Optional[str], float]:
    """
    Return (speaker_name, distance) if match below threshold else (None, distance_of_best)
    Distance = 1 - cosine_similarity
    """
    from numpy.linalg import norm
    items = list_speakers()
    if hints:
        items = [x for x in items if x["name"] in hints or x["id"] in hints]
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
            best_dist = dist
            best_name = it["name"]
    if best_dist <= threshold:
        return (best_name, best_dist)
    return (None, best_dist)
