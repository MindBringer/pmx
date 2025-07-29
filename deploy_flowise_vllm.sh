#!/bin/bash
set -e

# Deploy vLLM with local Mistral model and Flowise frontend

# Check for required commands
command -v docker >/dev/null 2>&1 || { echo "Docker is required but not installed." >&2; exit 1; }

# Check OpenAI API key for ChatGPT access
if [ -z "$OPENAI_API_KEY" ]; then
  echo "Please export OPENAI_API_KEY with your ChatGPT API key." >&2
  exit 1
fi

# Optional HuggingFace token for downloading models
HUGGINGFACE_TOKEN=${HUGGINGFACE_TOKEN:-""}

# Create Docker network if not exists
if ! docker network ls --format '{{.Name}}' | grep -q '^llm-network$'; then
  docker network create llm-network
fi

# Run vLLM container with Mistral model
if ! docker ps --format '{{.Names}}' | grep -q '^mistral-vllm$'; then
  docker run -d \
    --name mistral-vllm \
    --network llm-network \
    -p 8000:8000 \
    -v "$(pwd)/models:/root/.cache/huggingface" \
    -e HUGGING_FACE_HUB_TOKEN="$HUGGINGFACE_TOKEN" \
    vllm/vllm-openai:latest \
    python3 -m vllm.entrypoints.openai.api_server \
      --model mistralai/Mistral-7B-Instruct-v0.3 \
      --host 0.0.0.0 \
      --port 8000 \
      --served-model-name mistral-7b
fi

# Run Flowise frontend container
if ! docker ps --format '{{.Names}}' | grep -q '^flowise$'; then
  docker run -d \
    --name flowise \
    --network llm-network \
    -p 3000:3000 \
    -e PORT=3000 \
    -e DATABASE_PATH=/data \
    -e FLOWISE_USERNAME=admin \
    -e FLOWISE_PASSWORD=admin \
    -e OPENAI_API_KEY="$OPENAI_API_KEY" \
    -e FLOWISE_OPENAI_BASE_URL=http://mistral-vllm:8000/v1 \
    -v flowise_data:/data \
    flowiseai/flowise:latest
fi

echo "Flowise is running on http://localhost:3000" 
echo "vLLM endpoint available at http://localhost:8000/v1"
