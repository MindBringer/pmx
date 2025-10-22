# ------------------------------------------
# rag-backend – vLLM + Haystack 3.x + Audio
# ------------------------------------------
FROM python:3.11-slim

# --- Basis-Einstellungen ---
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# --- System-Pakete ---
#  - build-essential: Kompilieren (z. B. für numpy/scipy)
#  - libsndfile1: Soundfile
#  - ffmpeg: Audio
#  - libgomp1: Torch/OpenBLAS
#  - curl: Healthchecks / Tests
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsndfile1 \
    ffmpeg \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Requirements ---
#   Wichtig: Torch + Torchaudio zuerst installieren (CUDA/CPU),
#   dann Haystack + Integrationen, dann Rest.
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir torch==2.3.1 torchaudio==2.3.1 --extra-index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# --- App kopieren ---
COPY app ./app
COPY config ./config

# --- Environment defaults ---
ENV DEVICE=${DEVICE:-cpu} \
    ASR_ENGINE=${ASR_ENGINE:-faster-whisper} \
    ASR_MODEL=${ASR_MODEL:-medium} \
    ASR_COMPUTE_TYPE=${ASR_COMPUTE_TYPE:-int8} \
    DIAR_ENGINE=${DIAR_ENGINE:-local} \
    DIAR_MAX_SPEAKERS=${DIAR_MAX_SPEAKERS:-0} \
    IDENTIFICATION=${IDENTIFICATION:-true} \
    SPEAKER_STORE=${SPEAKER_STORE:-file}

# --- Expose & Start ---
EXPOSE 8082
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082", "--proxy-headers"]
