# diarize.py — Variante A (Analytics only, keine Cuts), FastAPI endpoint
import os
import uuid
import shutil
import tempfile
import subprocess
from typing import List, Tuple, Optional

import numpy as np
import soundfile as sf
import webrtcvad
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse

# --------- Konfig ----------
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")

# --------- FastAPI App (eigene App oder in main.py mounten) ----------
app = FastAPI(title="audio-api (diarize)", version="A-1.0")

# --------- Helpers ----------
def _ffmpeg_wav_mono16k(inp_path: str, out_path: str) -> None:
    """Konvertiert Audio zuverlässig nach WAV mono/16k, ohne Längen-Cut."""
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", inp_path,
        "-ac", "1",
        "-ar", "16000",
        "-vn",
        out_path
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='ignore') or proc.stdout.decode(errors='ignore')}")

def _audio_duration_ms(wav_path: str) -> int:
    data, sr = sf.read(wav_path)
    n = data.shape[0] if isinstance(data, np.ndarray) else len(data)
    return int(n * 1000 / sr)

def _frames_from_audio(wav_path: str, frame_ms: int = 30) -> Tuple[List[bytes], int]:
    """Teilt PCM16 (mono,16k) in kleine Frames für VAD; gibt (frames,samplerate) zurück."""
    data, sr = sf.read(wav_path, dtype="int16")
    if data.ndim > 1:
        data = data[:, 0]
    bytes_per_sample = 2  # int16
    frame_len = int(sr * (frame_ms / 1000.0))
    frames = []
    for i in range(0, len(data) - frame_len + 1, frame_len):
        chunk = data[i:i + frame_len].tobytes()
        frames.append(chunk)
    return frames, sr

def _vad_segments(wav_path: str,
                  aggressiveness: int = 2,
                  min_speech_ms: int = 300,
                  min_silence_ms: int = 500,
                  frame_ms: int = 30) -> List[Tuple[int, int]]:
    """
    Erzeugt grobe Sprachsegmente (Start/Ende in ms) über die gesamte Datei.
    Keine harte Obergrenze; robust gegen kurze Pausen.
    """
    vad = webrtcvad.Vad(aggressiveness)
    frames, sr = _frames_from_audio(wav_path, frame_ms=frame_ms)
    hop_ms = frame_ms

    speech_runs: List[Tuple[int, int]] = []
    in_speech = False
    seg_start_ms = 0
    current_len_ms = 0
    silence_run_ms = 0

    for idx, frame in enumerate(frames):
        ts_ms = idx * hop_ms
        is_speech = vad.is_speech(frame, sr)

        if is_speech:
            if not in_speech:
                in_speech = True
                seg_start_ms = ts_ms
                current_len_ms = 0
                silence_run_ms = 0
            current_len_ms += hop_ms
        else:
            if in_speech:
                silence_run_ms += hop_ms
                # wenn genug Stille nach Sprache → Segment beenden
                if silence_run_ms >= min_silence_ms and current_len_ms >= min_speech_ms:
                    end_ms = ts_ms - (silence_run_ms - hop_ms)
                    speech_runs.append((seg_start_ms, end_ms))
                    in_speech = False
            # reset current_len, wenn wir lange in Stille sind
            if not in_speech:
                current_len_ms = 0
                silence_run_ms = 0

    # Falls am Ende noch Sprache offen ist:
    if in_speech:
        end_ms = len(frames) * hop_ms
        if end_ms - seg_start_ms >= min_speech_ms:
            speech_runs.append((seg_start_ms, end_ms))

    # Zusammenführen von nahe beieinander liegenden Segmenten (< 250ms Lücke)
    merged: List[Tuple[int, int]] = []
    if speech_runs:
        cur_s, cur_e = speech_runs[0]
        for s, e in speech_runs[1:]:
            if s - cur_e <= 250:
                cur_e = e
            else:
                merged.append((cur_s, cur_e))
                cur_s, cur_e = s, e
        merged.append((cur_s, cur_e))

    return merged

# --------- Endpoint ----------
@app.post("/diarize")
async def diarize_endpoint(
    file: UploadFile = File(...),
    vad_aggr: int = Form(default=2),             # 0..3 (3 = aggressiv)
    min_speech_ms: int = Form(default=300),
    min_silence_ms: int = Form(default=500),
):
    """
    Gibt eine VAD-basierte Sprach-/Stille-Timeline zurück (Analytics).
    WICHTIG: Diese Segmente dienen nur der Anzeige / Analyse,
             es werden KEINE Audioschnitte erzwungen (keine 24s-Falle).
    """
    workdir = tempfile.mkdtemp(prefix="diar_")
    src_path = os.path.join(workdir, f"src_{uuid.uuid4().hex}")
    wav_path = os.path.join(workdir, f"conv_{uuid.uuid4().hex}.wav")
    try:
        with open(src_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        _ffmpeg_wav_mono16k(src_path, wav_path)
        dur_ms = _audio_duration_ms(wav_path)

        timeline = _vad_segments(
            wav_path,
            aggressiveness=int(vad_aggr),
            min_speech_ms=int(min_speech_ms),
            min_silence_ms=int(min_silence_ms),
            frame_ms=30
        )

        out = {
            "duration_ms": dur_ms,
            "segments": [{"from": s, "to": e} for s, e in timeline],
            "debug": {
                "params": {
                    "vad_aggr": int(vad_aggr),
                    "min_speech_ms": int(min_speech_ms),
                    "min_silence_ms": int(min_silence_ms),
                },
                "workdir": os.path.basename(workdir)
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
