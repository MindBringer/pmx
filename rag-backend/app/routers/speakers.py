# rag-backend/app/routers/speakers.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import List, Dict
import tempfile, shutil, os
from ..services.spk_embed import list_speakers, enroll_speaker, delete_speaker

router = APIRouter(prefix="/speakers", tags=["speakers"])

@router.get("")
def get_speakers() -> List[Dict]:
    return list_speakers()

@router.post("/enroll")
async def enroll(name: str = Form(...), file: UploadFile = File(...)) -> Dict:
    try:
        tmp = tempfile.mktemp(suffix=os.path.splitext(file.filename)[-1])
        with open(tmp, "wb") as f:
            shutil.copyfileobj(file.file, f)
        return enroll_speaker(name=name, path=tmp)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{speaker_id}")
def remove(speaker_id: str):
    ok = delete_speaker(speaker_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Speaker not found")
    return {"status":"ok"}
