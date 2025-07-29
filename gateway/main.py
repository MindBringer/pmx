from fastapi import FastAPI, Request
import os, httpx

app = FastAPI()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
VLLM_URL = os.getenv("VLLM_URL", "http://vllm:8000")
VLLM_MODELS = os.getenv("VLLM_MODEL", "")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/v1/completions")
async def completions(req: Request):
    data = await req.json()
    model = data.get("model", "")
    url = VLLM_URL if model in VLLM_MODELS else OLLAMA_URL
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{url}/v1/completions", json=data)
        return resp.json()
