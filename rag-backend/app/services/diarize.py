# rag-backend/app/services/diarize.py
import os
from typing import List, Dict, Tuple, Optional
import tempfile
import subprocess
import numpy as np
from .vad import detect_speech_segments
from .spk_embed import audio_to_embedding, identify_embedding

DIAR_ENGINE = os.getenv("DIAR_ENGINE", "local")
DIAR_MAX_SPEAKERS = int(os.getenv("DIAR_MAX_SPEAKERS", "0"))  # 0 -> auto
IDENTIFICATION = os.getenv("IDENTIFICATION", "true").lower() == "true"

def _ffmpeg_slice(in_path: str, start: float, end: float) -> str:
    out_path = tempfile.mktemp(suffix=".wav")
    dur = max(0.01, end - start)
    cmd = ["ffmpeg", "-nostdin", "-y", "-i", in_path, "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
           "-ac", "1", "-ar", "16000", "-vn", out_path]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out_path

def diarize_local(path: str, hints: Optional[List[str]] = None) -> List[Dict]:
    """
    Tokenfreie, CPU-taugliche Diarization:
      1) VAD -> Sprachsegmente
      2) Embedding je Segment (ECAPA)
      3) Online-Clustering: Zuordnung per Cosine-Threshold zu existierenden Centroids,
         sonst neuer Sprecher.
    Liefert Liste [{speaker: "spk1", start, end, conf, name?}]
    """
    # 1) VAD
    wav = tempfile.mktemp(suffix=".wav")
    subprocess.run(["ffmpeg","-nostdin","-y","-i", path,"-ac","1","-ar","16000","-vn",wav],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    segs = detect_speech_segments(wav, aggressiveness=2)
    if not segs:
        return []
    # 2) Embeddings + Online-Clustering
    centroids: List[np.ndarray] = []
    counts: List[int] = []
    out: List[Dict] = []
    assign: List[int] = []

    def cosine(a,b): 
        return float(np.dot(a,b) / (np.linalg.norm(a)*np.linalg.norm(b) + 1e-9))

    threshold_new = 0.75  # Cosine < 0.75 => neuer Sprecher (konservativ)
    for (s, e) in segs:
        clip = _ffmpeg_slice(path, s, e)
        emb = audio_to_embedding(clip)
        if len(centroids) == 0:
            centroids.append(emb.copy())
            counts.append(1)
            assign.append(0)
        else:
            sims = [cosine(emb, c) for c in centroids]
            j = int(np.argmax(sims))
            if sims[j] < threshold_new:
                centroids.append(emb.copy())
                counts.append(1)
                assign.append(len(centroids)-1)
            else:
                # update centroid
                k = counts[j]
                centroids[j] = (centroids[j]*k + emb) / (k+1)
                counts[j] += 1
                assign.append(j)

    # Map to spk labels in occurrence order:
    remap = {}
    next_id = 1
    segments = []
    for idx, (s, e) in enumerate(segs):
        ci = assign[idx]
        if ci not in remap:
            remap[ci] = f"spk{next_id}"
            next_id += 1
        segments.append({"speaker": remap[ci], "start": float(s), "end": float(e), "conf": 0.6})

    # Optional: Identification gegen Enrollments
    if IDENTIFICATION:
        names: Dict[str, Tuple[Optional[str], float]] = {}
        for lab in set([x["speaker"] for x in segments]):
            # aggregate emb of this speaker (mean of its segments)
            embs = []
            for i,(s,e) in enumerate(segs):
                if remap[assign[i]] == lab:
                    clip = _ffmpeg_slice(path, s, e)
                    embs.append(audio_to_embedding(clip))
            if embs:
                m = np.mean(np.stack(embs, axis=0), axis=0)
                name, dist = identify_embedding(m, threshold=0.25, hints=hints)
                names[lab] = (name, dist)
        for seg in segments:
            nm, dist = names.get(seg["speaker"], (None, 1.0))
            if nm:
                seg["name"] = nm
                seg["conf"] = max(0.6, 1.0 - float(dist))  # simple mapping
    return segments

def diarize(path: str, hints: Optional[List[str]] = None) -> List[Dict]:
    # Hooks: pyannote / nemo später implementierbar
    if DIAR_ENGINE == "local":
        return diarize_local(path, hints=hints)
    # elif DIAR_ENGINE == "pyannote":
    #     ...
    # elif DIAR_ENGINE == "nemo":
    #     ...
    return diarize_local(path, hints=hints)
