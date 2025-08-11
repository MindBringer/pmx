#!/usr/bin/env bash
set -euo pipefail
export PYTHONUNBUFFERED=1
export RAG_BASE_PATH=${RAG_BASE_PATH:-/rag}
uvicorn app.main:app --host 0.0.0.0 --port ${RAG_PORT:-8082} --reload --proxy-headers
