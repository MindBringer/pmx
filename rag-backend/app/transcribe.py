# rag-backend/app/transcribe.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional, List, Dict, Any, Tuple
import os, tempfile, shutil, subprocess
import numpy as np

# --- ASR (faster-whisper) ---
from faster_whisper import WhisperModel

# --- Speaker Embeddings (SpeechBrain ECAPA) ---
import torch
import torchaudio
from speechbrain.pretrained import EncoderClassifier

# --- Qdrant ---
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

router = APIRouter(tags=['transcribe'])

# --------- ENV ---------
DEVICE = 'cuda' if os.getenv('DEVICE','cpu').startswith('cuda') and torch.cuda.is_available() else 'cpu'
ASR_MODEL = os.getenv('ASR_MODEL', 'medium')
ASR_COMPUTE_TYPE = os.getenv('ASR_COMPUTE_TYPE', 'int8')  # cpu:int8, gpu:float16
QDRANT_URL = os.getenv('QDRANT_URL', 'http://qdrant:6333')
QDRANT_API_KEY = os.getenv('QDRANT_API_KEY', None)
SPEAKER_COLLECTION = os.getenv('SPEAKER_COLLECTION', 'speakers')
EMBED_DIM = 192  # ECAPA

# --------- Lazy singletons ---------
_asr_model: Optional[WhisperModel] = None
_spk_model: Optional[EncoderClassifier] = None
_qdrant: Optional[QdrantClient] = None

def _ffmpeg_to_wav_mono16k(in_path: str) -> str:
    out_path = tempfile.mktemp(suffix=".wav")
    cmd = ["ffmpeg","-nostdin","-y","-i",in_path,"-ac","1","-ar","16000","-vn",out_path]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out_path

def asr_model() -> WhisperModel:
    global _asr_model
    if _asr_model is None:
        device = 'cuda' if DEVICE == 'cuda' else 'cpu'
        _asr_model = WhisperModel(ASR_MODEL, device=device, compute_type=ASR_COMPUTE_TYPE)
    return _asr_model

def spk_model() -> EncoderClassifier:
    global _spk_model
    if _spk_model is None:
        _spk_model = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                                    run_opts={"device": DEVICE})
    return _spk_model

def qdrant() -> QdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        # ensure collection
        colls = [c.name for c in _qdrant.get_collections().collections]
        if SPEAKER_COLLECTION not in colls:
            _qdrant.recreate_collection(
                collection_name=SPEAKER_COLLECTION,
                vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE)
            )
    return _qdrant

# --------- Speaker store (Qdrant) ---------
def _embed_audio(path: str) -> np.ndarray:
    wav = _ffmpeg_to_wav_mono16k(path)
    sig, sr = torchaudio.load(wav)
    sig = sig.to(DEVICE)
    emb = spk_model().encode_batch(sig).mean(dim=1).squeeze(0).detach().cpu().numpy().astype(np.float32)
    return emb

def speakers_list() -> List[Dict[str, Any]]:
    # We keep simple metadata in payload (name); using non-paginated scroll for demo
    # In real usage, maintain a side metadata collection or payload index
    res = qdrant().scroll(collection_name=SPEAKER_COLLECTION, limit=1000)[0]
    out = []
    for p in res:
        out.append({"id": p.id, "name": (p.payload or {}).get("name", None)})
    return out

def speakers_enroll(name: str, file_path: str) -> Dict[str, Any]:
    emb = _embed_audio(file_path)
    point = PointStruct(id=None, vector=emb.tolist(), payload={"name": name})
    qdrant().upsert(SPEAKER_COLLECTION, [point])
    return {"name": name, "dim": EMBED_DIM}

def speakers_delete(spk_id: str) -> bool:
    try:
        qdrant().delete(SPEAKER_COLLECTION, points_selector=[spk_id])
        return True
    except Exception:
        return False

def speakers_identify(emb: np.ndarray, hints: Optional[List[str]] = None, threshold: float = 0.25) -> Tuple[Optional[str], float]:
    client = qdrant()
    flt = None
    if hints:
        flt = Filter(must=[FieldCondition(key="name", match=MatchValue(value=h)) for h in hints])
    srch = client.search(collection_name=SPEAKER_COLLECTION, query_vector=emb.tolist(), limit=1, query_filter=flt)
    if not srch:
        return (None, 1.0)
    pt = srch[0]
    # cosine distance: 1 - cosine_similarity
    dist = float(pt.score)  # qdrant returns SIMILARITY for cosine by default (higher better). For safety map:
    # convert similarity to distance
    sim = dist
    d = 1.0 - sim
    name = (pt.payload or {}).get("name")
    if d <= threshold:
        return (name, d)
    return (None, d)

# --------- Diarization (tokenfrei) ---------
import collections, contextlib, wave, math

def _read_wave_mono16k(path):
    with contextlib.closing(wave.open(path, 'rb')) as wf:
        assert wf.getnchannels() == 1 and wf.getsampwidth() == 2 and wf.getframerate() == 16000
        pcm = wf.readframes(wf.getnframes())
        return pcm, 16000

import webrtcvad
def _vad_segments(wav_path: str, aggressiveness: int = 2):
    pcm, sr = _read_wave_mono16k(wav_path)
    vad = webrtcvad.Vad(aggressiveness)
    frame_ms = 30
    n = int(sr * (frame_ms/1000.0) * 2)
    frames = [pcm[i:i+n] for i in range(0, len(pcm), n)]
    t, step = 0.0, frame_ms/1000.0
    segs = []
    rb = collections.deque(maxlen=10)
    trig, seg_start = False, 0.0
    for fr in frames:
        is_speech = vad.is_speech(fr, sr)
        if not trig:
            rb.append((fr, t, is_speech))
            if sum(1 for x in rb if x[2]) > 0.9*rb.maxlen:
                trig = True; seg_start = rb[0][1]; rb.clear()
        else:
            rb.append((fr, t, is_speech))
            if sum(1 for x in rb if not x[2]) > 0.9*rb.maxlen:
                segs.append((seg_start, t)); trig=False; rb.clear()
        t += step
    if trig: segs.append((seg_start, t))
    # merge tiny gaps
    merged = []
    for s,e in segs:
        if not merged: merged.append([s,e])
        else:
            if s - merged[-1][1] < 0.25: merged[-1][1]=e
            else: merged.append([s,e])
    return [(float(s),float(e)) for s,e in merged]

def _slice_to_wav(src: str, start: float, end: float) -> str:
    out = tempfile.mktemp(suffix=".wav")
    dur = max(0.01, end-start)
    subprocess.run(["ffmpeg","-nostdin","-y","-i",src,"-ss",f"{start:.3f}","-t",f"{dur:.3f}","-ac","1","-ar","16000","-vn",out],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out

def diarize_local(path: str, identify: bool, hints: Optional[List[str]] = None) -> List[Dict[str,Any]]:
    base_wav = _ffmpeg_to_wav_mono16k(path)
    segs = _vad_segments(base_wav)
    if not segs: return []
    centroids: List[np.ndarray] = []; counts: List[int] = []; assign: List[int]=[]
    def cosine(a,b): return float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)+1e-9))
    thr_new = 0.75
    embs_per_seg: List[np.ndarray] = []
    for (s,e) in segs:
        clip = _slice_to_wav(path, s, e)
        emb = _embed_audio(clip)
        embs_per_seg.append(emb)
        if not centroids:
            centroids.append(emb.copy()); counts.append(1); assign.append(0)
        else:
            sims = [cosine(emb,c) for c in centroids]; j=int(np.argmax(sims))
            if sims[j] < thr_new:
                centroids.append(emb.copy()); counts.append(1); assign.append(len(centroids)-1)
            else:
                k=counts[j]; centroids[j]=(centroids[j]*k+emb)/(k+1); counts[j]+=1; assign.append(j)
    label_map: Dict[int,str] = {}; next_id=1
    segments: List[Dict[str,Any]] = []
    for i,(s,e) in enumerate(segs):
        cid = assign[i]
        if cid not in label_map: label_map[cid]=f"spk{next_id}"; next_id+=1
        segments.append({"speaker":label_map[cid], "start":float(s), "end":float(e), "conf":0.6})

    if identify and segments:
        # aggregate per speaker and identify
        for lab in set(x["speaker"] for x in segments):
            idxs = [i for i,(s,e) in enumerate(segs) if label_map[assign[i]]==lab]
            if not idxs: continue
            m = np.mean(np.stack([embs_per_seg[i] for i in idxs], axis=0), axis=0)
            name, dist = speakers_identify(m, hints=hints, threshold=0.25)
            if name:
                for seg in segments:
                    if seg["speaker"]==lab:
                        seg["name"]=name
                        seg["conf"]=max(seg.get("conf",0.6), 1.0-float(dist))
    return segments

# --------- Merge ASR & Diar ---------
def _merge(asr_segments: List[Dict[str,Any]], spk_segments: List[Dict[str,Any]]) -> List[Dict[str,Any]]:
    if not spk_segments:
        return [{"speaker":"spk1","start":s["start"],"end":s["end"],"text":s["text"]} for s in asr_segments]
    out=[]
    for a in asr_segments:
        mid=(a["start"]+a["end"])/2.0
        covering=[s for s in spk_segments if s["start"]<=mid<=s["end"]]
        s = covering[0] if covering else min(spk_segments, key=lambda x: abs(((x["start"]+x["end"])/2.0)-mid))
        item={"speaker":s["speaker"],"start":a["start"],"end":a["end"],"text":a["text"]}
        if "name" in s: item["name"]=s["name"]
        out.append(item)
    return out

def _to_srt(items: List[Dict[str,Any]]) -> str:
    def fmt(t):
        h=int(t//3600); m=int((t%3600)//60); s=t%60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.',',')
    lines=[]
    for i,it in enumerate(items, start=1):
        lines.append(str(i))
        lines.append(f"{fmt(it['start'])} --> {fmt(it['end'])}")
        who = it.get("name") or it.get("speaker","spk")
        lines.append(f"[{who}] {it['text']}")
        lines.append("")
    return "\n".join(lines)

# --------- Routes ---------
@router.post("/transcribe")
async def do_transcribe(
    file: UploadFile = File(...),
    diarize_flag: bool = Form(False),
    identify: bool = Form(False),
    language: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    speaker_hints: Optional[str] = Form(None),
):
    try:
        tmp = tempfile.mktemp(suffix=os.path.splitext(file.filename or '')[-1] or ".bin")
        with open(tmp, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # ASR
        wav = _ffmpeg_to_wav_mono16k(tmp)
        model = asr_model()
        segs, info = model.transcribe(wav, language=language)
        asr_segments = [{"start": float(s.start), "end": float(s.end), "text": s.text.strip()} for s in segs]
        text = " ".join([s["text"] for s in asr_segments]).strip()

        spk_segments: List[Dict[str,Any]] = []
        if diarize_flag:
            hints = [h.strip() for h in (speaker_hints or "").split(",") if h.strip()] or None
            spk_segments = diarize_local(tmp, identify=identify, hints=hints)

        merged = _merge(asr_segments, spk_segments)
        srt = _to_srt(merged)

        return {
            "ok": True,
            "language": getattr(info, "language", None),
            "text": text,
            "segments": merged,
            "speakers_detected": sorted(list({(x.get("name") or x["speaker"]) for x in merged})),
            "tags": [t.strip() for t in (tags or "").split(",") if t.strip()],
            "artifacts": {"srt_inline": srt}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        try: os.remove(tmp)
        except Exception: pass

# --- Speaker management (Qdrant) ---
@router.get("/speakers")
def api_speakers_list():
    return speakers_list()

@router.post("/speakers/enroll")
async def api_speakers_enroll(name: str = Form(...), file: UploadFile = File(...)):
    try:
        tmp = tempfile.mktemp(suffix=os.path.splitext(file.filename or '')[-1] or ".bin")
        with open(tmp, "wb") as f:
            shutil.copyfileobj(file.file, f)
        return speakers_enroll(name, tmp)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try: os.remove(tmp)
        except Exception: pass

@router.delete("/speakers/{spk_id}")
def api_speakers_delete(spk_id: str):
    ok = speakers_delete(spk_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Speaker not found")
    return {"status":"ok"}
