# rag-backend/app/transcribe.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional, List, Dict, Any, Tuple
import os, tempfile, shutil, subprocess
import numpy as np
from uuid import uuid4
from datetime import datetime

# --- ASR (faster-whisper) ---
from faster_whisper import WhisperModel

# --- Speaker Embeddings (SpeechBrain ECAPA) ---
import torch
import torchaudio
# FIX: neuer Pfad seit SpeechBrain 1.0
from speechbrain.inference import EncoderClassifier

# --- Qdrant ---
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

router = APIRouter(tags=['transcribe'])

# --------- ENV ---------
DEVICE = 'cuda' if os.getenv('DEVICE','cpu').startswith('cuda') and torch.cuda.is_available() else 'cpu'
ASR_MODEL = os.getenv('ASR_MODEL', 'medium')
# BESSER: Default je nach Device
ASR_COMPUTE_TYPE = os.getenv('ASR_COMPUTE_TYPE', 'float16' if DEVICE=='cuda' else 'int8')
QDRANT_URL = os.getenv('QDRANT_URL', 'http://qdrant:6333')
QDRANT_API_KEY = os.getenv('QDRANT_API_KEY', None)
SPEAKER_COLLECTION = os.getenv('SPEAKER_COLLECTION', 'speakers')
EMBED_DIM = 192  # ECAPA
SPEAKER_SIM_THRESHOLD = float(os.getenv('SPEAKER_SIM_THRESHOLD', '0.25'))  # Cosine-Distanz

# --------- Lazy singletons ---------
_asr_model: Optional[WhisperModel] = None
_spk_model: Optional[EncoderClassifier] = None
_qdrant: Optional[QdrantClient] = None

# --------- Audio IO / FFMPEG ---------
def _ffmpeg_to_wav_mono16k(path: str) -> str:
    """
    Konvertiert beliebige Eingaben nach WAV mono 16k (PCM 16-bit).
    """
    tmpdir = tempfile.mkdtemp(prefix="asr_")
    out_path = os.path.join(tmpdir, "audio_mono16k.wav")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", path,
        "-ac", "1",
        "-ar", "16000",
        "-vn",
        "-acodec","pcm_s16le",  # FIX: explizit PCM 16-bit little endian
        out_path
    ]
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
        _spk_model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": DEVICE}
        )
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
    pts, _ = qdrant().scroll(collection_name=SPEAKER_COLLECTION, limit=1000)
    return [{"id": p.id, "name": (p.payload or {}).get("name")} for p in pts]

def speakers_enroll(name: str, file_path: str, spk_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Legt einen Sprecher in Qdrant an. Wenn keine ID übergeben wurde,
    wird eine UUID (String-ID) erzeugt, um PointStruct-Validierungsfehler zu vermeiden.
    """
    emb = _embed_audio(file_path)
    sid = spk_id or str(uuid4())
    point = PointStruct(
        id=sid,
        vector=emb.tolist(),
        payload={
            "name": name,
            "type": "speaker",
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
    )
    # upsert mit benannten Parametern (kompatibel mit aktuellen qdrant-client Versionen)
    qdrant().upsert(collection_name=SPEAKER_COLLECTION, points=[point])
    return {"ok": True, "id": sid, "speaker_id": sid, "name": name, "dim": EMBED_DIM}

def speakers_delete(spk_id: str) -> bool:
    try:
        qdrant().delete(SPEAKER_COLLECTION, points_selector=[spk_id])
        return True
    except Exception:
        return False

def _attach_identity_to_segments(segments: List[Dict[str,Any]], identify: Optional[Dict[str,Any]]) -> List[Dict[str,Any]]:
    """
    Wenn Identify vorhanden & confident, Namen in alle Segmente schreiben.
    """
    if not identify or not identify.get("name"):
        return segments
    name = identify["name"]
    dist = identify.get("distance")
    score = identify.get("score")
    confident = False
    if dist is not None:
        confident = dist <= SPEAKER_SIM_THRESHOLD
    if score is not None:
        confident = confident or (score >= 0.75)
    if confident:
        for s in segments:
            if not s.get("name"):  # nicht überschreiben, falls segmentweise Ident schon da
                s["name"] = name
    return segments

def speakers_identify(emb: np.ndarray, hints: Optional[List[str]] = None, threshold: Optional[float] = None) -> Tuple[Optional[str], float, Optional[float]]:
    client = qdrant()
    flt = None
    if hints:
        flt = Filter(must=[FieldCondition(key="name", match=MatchValue(value=h)) for h in hints])
    srch = client.search(collection_name=SPEAKER_COLLECTION, query_vector=emb.tolist(), limit=1, query_filter=flt)
    if not srch:
        return (None, 1.0, None)
    pt = srch[0]
    sim = float(pt.score)                    # COSINE Similarity in [0..1]
    dist = 1.0 - sim                         # Distanz: kleiner ist besser
    name = (pt.payload or {}).get("name")
    thr = SPEAKER_SIM_THRESHOLD if threshold is None else threshold
    if dist <= thr:
        return (name, dist, sim)
    return (None, dist, sim)

# --------- Diarization (tokenfrei) ---------
import contextlib, wave, collections

def _read_wave_mono16k(path):
    with contextlib.closing(wave.open(path, 'rb')) as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        frames = wf.getnframes()
        pcm = wf.readframes(frames)
        return np.frombuffer(pcm, dtype=np.int16)

def diarize_segments(wav_mono16k_path: str, window_ms: int = 8000, step_ms: int = 4000, energy_threshold: float = 0.01):
    """
    Sehr einfache Energie-basierte "Diarization" (VAD-ähnlich) ohne externe Modelle.
    Liefert Segmente [(start_ms, end_ms)].
    """
    pcm = _read_wave_mono16k(wav_mono16k_path).astype(np.float32) / 32768.0
    win = int((16000 * window_ms) / 1000)
    step = int((16000 * step_ms) / 1000)
    segs = []
    start = None
    for i in range(0, len(pcm) - win, step):
        frame = pcm[i:i+win]
        e = float(np.mean(frame * frame))
        if e >= energy_threshold and start is None:
            start = i
        if e < energy_threshold and start is not None:
            segs.append((int(start * 1000 / 16000), int(i * 1000 / 16000)))
            start = None
    if start is not None:
        segs.append((int(start * 1000 / 16000), int(len(pcm) * 1000 / 16000)))
    return segs

# --------- API ---------
@router.post("/transcribe")
async def do_transcribe(
    file: UploadFile = File(...),
    diarize_flag: bool = Form(False),
    identify: bool = Form(False),
    language: Optional[str] = Form(None),
    speaker_hints: Optional[str] = Form(None),  # NEU: "A, B, C"
):
    """
    Transkribiert Audio. Optional: einfache Diarisierung + Sprecher-Identifikation (Qdrant).
    - diarize_flag=True: segmentiert Audio, transkribiert pro Segment
    - identify=True: identifiziert Sprecher (mit optionalen Hints), schreibt Namen in Segmente
    """
    tmp = None
    wav = None
    tmp_cuts = []
    try:
        # Datei in tmp schreiben
        tmp = tempfile.mktemp(suffix=os.path.splitext(file.filename or '')[-1] or ".bin")
        with open(tmp, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # nach WAV mono16k
        wav = _ffmpeg_to_wav_mono16k(tmp)

        # ggf. Segmente bilden
        segments_time = None
        if diarize_flag:
            segments_time = diarize_segments(wav)  # [(start_ms, end_ms)]

        # ASR Model
        model = asr_model()

        text_total = ""
        results: List[Dict[str,Any]] = []

        hints_list = None
        if speaker_hints:
            # "A, B ,C" -> ["A","B","C"]
            hints_list = [h.strip() for h in speaker_hints.split(",") if h.strip()]

        if segments_time:
            # Diarisierung aktiv: pro Segment transkribieren UND (falls identify) direkt identifizieren
            for (s_ms, e_ms) in segments_time:
                # via ffmpeg schneiden
                cut = tempfile.mktemp(suffix=".wav")
                tmp_cuts.append(cut)
                dur = max(0.0, (e_ms - s_ms) / 1000.0)
                cmd = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{s_ms/1000.0:.3f}",
                    "-t", f"{dur:.3f}",
                    "-i", wav,
                    "-acodec","pcm_s16le",
                    "-ar","16000",
                    "-ac","1",
                    cut
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                seg_it, _ = model.transcribe(cut, language=language if language else None)
                seg_text = "".join([c.text for c in seg_it]).strip()
                text_total += (seg_text + " ") if seg_text else ""

                seg_out = {"start_ms": s_ms, "end_ms": e_ms, "text": seg_text}

                if and (e_ms - s_ms) >= 1500:  # nur bei Segmenten >= 1.5s
                    # segmentweise ECAPA-Embedding + Qdrant
                    with torch.no_grad():
                        emb = _embed_audio(cut)
                    who, dist, sim = speakers_identify(emb, hints=hints_list)
                    if who:
                        seg_out["name"] = who
                    if sim is not None:
                        seg_out["score"] = sim
                        seg_out["distance"] = dist

                results.append(seg_out)
        else:
            # Keine Diarisierung: gesamte Datei transkribieren mit Whisper-Segmenten (start/end in Sekunden)
            it, info = model.transcribe(wav, language=language if language else None)
            whisper_segments = list(it)
            text_total = "".join([c.text for c in whisper_segments]).strip()

            # vorerst ohne Identify in jedem Segment -> setzen wir ggf. gesammelt weiter unten
            for c in whisper_segments:
                # c.start / c.end in Sekunden (kann None sein, dann auf 0 fallen)
                s_ms = int((c.start or 0.0) * 1000)
                e_ms = int((c.end or 0.0) * 1000)
                results.append({"start_ms": s_ms, "end_ms": e_ms, "text": (c.text or "").strip()})

        # optionale Identifikation auf gesamtem File (Fallback / Schneller Pfad)
        ident = None
        if identify:
            with torch.no_grad():
                emb_file = _embed_audio(tmp)
            who, dist, sim = speakers_identify(emb_file, hints=hints_list)
            ident = {"name": who, "distance": dist}
            if sim is not None:
                ident["score"] = sim

            # Falls wir KEINE segmentweise Identify gemacht haben (z. B. ohne Diarisierung),
            # trage den Namen in die Segmente ein, wenn confident.
            if not segments_time:
                results = _attach_identity_to_segments(results, ident)

        return {
            "text": text_total.strip(),
            "segments": results,
            "identify": ident
        }

    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=f"ffmpeg failed: {e.stderr.decode('utf-8','ignore')}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Transcribe failed: {e}")
    finally:
        # Cleanup
        if tmp:
            try: os.remove(tmp)
            except Exception: pass
        if wav:
            try: os.remove(wav)
            except Exception: pass
        for c in tmp_cuts:
            try: os.remove(c)
            except Exception: pass


# --- Speaker management (Qdrant) ---
@router.get("/speakers")
def api_speakers_list():
    return speakers_list()

@router.post("/speakers/enroll")
async def api_speakers_enroll(
    name: str = Form(...),
    file: UploadFile = File(...),
    id: Optional[str] = Form(None),
    speaker_id: Optional[str] = Form(None),
):
    try:
        tmp = tempfile.mktemp(suffix=os.path.splitext(file.filename or '')[-1] or ".bin")
        with open(tmp, "wb") as f:
            shutil.copyfileobj(file.file, f)
        sid = id or speaker_id
        return speakers_enroll(name, tmp, spk_id=sid)
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
