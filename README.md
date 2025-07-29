# AI Stack with Ollama and vLLM

This repository provides a minimal yet production oriented setup for running local large language models with [Ollama](https://github.com/ollama/ollama) and [vLLM](https://github.com/vllm-project/vllm). An optional Python gateway can proxy requests to either backend based on the selected model. The stack is prepared for a future migration to Kubernetes.

## Features

- **Ollama** – run multiple models locally
- **vLLM** – OpenAI compatible API
- **Gateway** – optional FastAPI proxy
- Container health checks and volume mounts
- All configuration via environment variables

## Setup

1. Install Docker and Docker Compose.
2. Copy `.env.example` to `.env` and adjust the variables if needed.
3. Run the installation script:

```bash
./install.sh
```

This will start the services and verify that all containers become healthy.

### Default Ports

- Ollama: `${OLLAMA_PORT}` (default `11434`)
- vLLM: `${VLLM_PORT}` (default `8000`)
- Gateway: `${GATEWAY_PORT}` (default `8080`)

Models will be stored in the directories defined by `OLLAMA_DATA` and `VLLM_DATA`.

## Usage

- **Ollama** API: `http://localhost:${OLLAMA_PORT}`
- **vLLM** API (OpenAI compatible): `http://localhost:${VLLM_PORT}/v1`
- **Gateway** (if enabled): `http://localhost:${GATEWAY_PORT}`

Example call against vLLM:

```bash
curl http://localhost:${VLLM_PORT}/v1/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "mistral", "prompt": "Hello"}'
```

The gateway inspects the model name and forwards the request either to vLLM or Ollama. See `gateway/main.py` for details.

## Extending the Stack

- Add more models by adjusting `OLLAMA_MODELS` and `VLLM_MODEL` in the `.env` file.
- Connect to cloud LLM providers by adding additional services or extending the gateway.
- For Kubernetes, use the same images and environment variables in your manifests or Helm charts.

## Gateway

The optional gateway is a small FastAPI application. It listens on `${GATEWAY_PORT}` and forwards requests depending on the model name. If you do not need it, remove the service from `docker-compose.yml`.

