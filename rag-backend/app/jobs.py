# rag-backend/app/jobs.py
import asyncio, time, json, uuid
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])

class Job:
    def __init__(self, title: str):
        self.id = str(uuid.uuid4())
        self.title = title
        self.created = time.time()
        self.done = False
        self.result: Optional[Dict[str, Any]] = None
        self.events_queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        self.backlog: list[Dict[str, Any]] = []  # für neue Abonnenten

    async def push(self, evt: Dict[str, Any]):
        self.backlog.append(evt)
        await self.events_queue.put(evt)

JOBS: Dict[str, Job] = {}

@router.post("")
async def create_job(payload: Dict[str, Any]):
    title = str(payload.get("title") or "Agentenlauf")
    job = Job(title)
    JOBS[job.id] = job
    # erstes Event
    await job.push({"type":"started","ts":time.time(),"title":job.title})
    return {"job_id": job.id}

@router.get("/{job_id}/events")
async def stream_events(job_id: str, request: Request):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")

    async def event_gen():
        # backlog zuerst senden
        for evt in job.backlog:
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        # dann live-Stream + Heartbeat
        while True:
            # Heartbeat alle 25s, damit Proxys die Verbindung offen lassen
            try:
                evt = await asyncio.wait_for(job.events_queue.get(), timeout=25)
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield f": heartbeat\n\n"  # Kommentar-Event (SSE-Keepalive)
            # Client abgebrochen?
            if await request.is_disconnected():
                break

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # Nginx: Buffering aus
        "Connection": "keep-alive",
        "Content-Type": "text/event-stream; charset=utf-8",
    }
    return StreamingResponse(event_gen(), headers=headers)

@router.post("/{job_id}/events")
async def post_event(job_id: str, payload: Dict[str, Any]):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    await job.push({"type":"progress","ts":time.time(), **payload})
    return {"ok": True}

@router.post("/{job_id}/complete")
async def post_complete(job_id: str, payload: Dict[str, Any]):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    job.done = True
    job.result = payload
    await job.push({"type":"complete","ts":time.time()})
    return {"ok": True}

@router.get("/{job_id}/result")
async def get_result(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if not job.done:
        return {"status":"running"}
    return {"status":"done","result":job.result}
