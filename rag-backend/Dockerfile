# ------------------------------------------
# rag-backend – vLLM + Haystack 2.x + Audio
# ------------------------------------------
FROM python:3.11-slim

# --- Basis-Einstellungen ---
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# --- System-Pakete ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libsndfile1 \
    ffmpeg \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Requirements ---
COPY requirements.txt /app/requirements.txt

# Installation in optimierter Reihenfolge
RUN pip install --upgrade pip setuptools wheel && \
    # 1. Torch CPU-Version
    pip install --no-cache-dir torch==2.3.1 torchaudio==2.3.1 \
        --extra-index-url https://download.pytorch.org/whl/cpu && \
    # 2. Sentence Transformers (vor Haystack!)
    pip install --no-cache-dir "sentence-transformers>=2.6.1" && \
    # 3. Haystack Core mit Integrationen
    pip install --no-cache-dir "haystack-ai>=2.18.0,<3" && \
    pip install --no-cache-dir "qdrant-haystack>=9.2.0" && \
    pip install --no-cache-dir "ollama-haystack>=1.0.0" && \
    # 4. Rest der Dependencies
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
    SPEAKER_STORE=${SPEAKER_STORE:-file} \
    QDRANT_URL=${QDRANT_URL:-http://qdrant:6333} \
    QDRANT_COLLECTION=${QDRANT_COLLECTION:-pmx_docs} \
    EMBED_MODEL=${EMBED_MODEL:-mixedbread-ai/mxbai-embed-large-v1} \
    EMBED_DIM=${EMBED_DIM:-1024} \
    OPENAI_BASE_URL=${OPENAI_BASE_URL:-http://vllm:8000/v1} \
    GENERATOR_MODEL=${GENERATOR_MODEL:-meta-llama/Meta-Llama-3.1-8B-Instruct}

# --- Expose & Start ---
EXPOSE 8082
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082", "--proxy-headers"]