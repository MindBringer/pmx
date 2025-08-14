# rag-backend/app/services/vad.py
import collections
import contextlib
import wave
import webrtcvad

def read_wave(path):
    with contextlib.closing(wave.open(path, 'rb')) as wf:
        num_channels = wf.getnchannels()
        assert num_channels == 1
        sample_width = wf.getsampwidth()
        assert sample_width == 2
        sample_rate = wf.getframerate()
        assert sample_rate == 16000
        pcm_data = wf.readframes(wf.getnframes())
        return pcm_data, sample_rate

def frame_generator(frame_duration_ms, pcm, sample_rate):
    n = int(sample_rate * (frame_duration_ms / 1000.0) * 2)
    for i in range(0, len(pcm), n):
        yield pcm[i:i + n]

def vad_collector(sample_rate, frame_duration_ms, padding_ms, vad, frames):
    num_padding_frames = int(padding_ms / frame_duration_ms)
    ring_buffer = collections.deque(maxlen=num_padding_frames)
    triggered = False
    voiced_frames = []
    segments = []
    t = 0.0
    step = frame_duration_ms / 1000.0
    seg_start = 0.0

    for frame in frames:
        is_speech = vad.is_speech(frame, sample_rate)
        if not triggered:
            ring_buffer.append((frame, t, is_speech))
            if sum(1 for f in ring_buffer if f[2]) > 0.9 * ring_buffer.maxlen:
                triggered = True
                seg_start = ring_buffer[0][1]
                voiced_frames.extend([f[0] for f in ring_buffer])
                ring_buffer.clear()
        else:
            voiced_frames.append(frame)
            if sum(1 for f in ring_buffer if not f[2]) > 0.9 * ring_buffer.maxlen:
                seg_end = t
                segments.append((seg_start, seg_end))
                ring_buffer.clear()
                voiced_frames = []
                triggered = False
        ring_buffer.append((frame, t, is_speech))
        t += step
    if triggered:
        segments.append((seg_start, t))
    return segments

def detect_speech_segments(wav_path: str, aggressiveness: int = 2):
    pcm, sr = read_wave(wav_path)
    vad = webrtcvad.Vad(aggressiveness)
    frames = list(frame_generator(30, pcm, sr))
    segments = vad_collector(sr, 30, 300, vad, frames)
    # merge tiny gaps
    merged = []
    for seg in segments:
        if not merged:
            merged.append(list(seg))
        else:
            if seg[0] - merged[-1][1] < 0.25:
                merged[-1][1] = seg[1]
            else:
                merged.append(list(seg))
    return [(float(s), float(e)) for s, e in merged]
