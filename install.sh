#!/usr/bin/env bash
set -e

check_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Error: $1 is not installed."; exit 1; }
}

check_cmd docker
check_cmd docker-compose || check_cmd docker\ compose

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from example"
fi

docker compose pull

docker compose up -d

echo "Waiting for containers to become healthy..."
HEALTHY=0
for i in {1..20}; do
  unhealthy=$(docker compose ps --format '{{.Name}} {{.Health}}' | awk '$2!="healthy"')
  if [ -z "$unhealthy" ]; then
    HEALTHY=1
    break
  fi
  sleep 3
  echo "Still starting..."
done

if [ $HEALTHY -eq 1 ]; then
  echo "All services are healthy."
else
  echo "Some services are not healthy:" >&2
  docker compose ps
fi

echo "\nUsage instructions:"
echo "- Ollama: http://localhost:${OLLAMA_PORT:-11434}"
echo "- vLLM:  http://localhost:${VLLM_PORT:-8000}/v1"
echo "- Gateway (optional): http://localhost:${GATEWAY_PORT:-8080}"

