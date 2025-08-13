FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1         PYTHONDONTWRITEBYTECODE=1         PYTHONUNBUFFERED=1

WORKDIR /app

# System packages for converters (pdf/html/markdown) and mime sniffing
RUN apt-get update && apt-get install -y --no-install-recommends         build-essential curl poppler-utils libmagic1 ffmpeg &&         rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config

EXPOSE 8082
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082", "--proxy-headers"]
