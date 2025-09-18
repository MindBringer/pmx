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
    tmp = None
    try:
        suffix = os.path.splitext(file.filename or "")[-1] or ".wav"
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            shutil.copyfileobj(file.file, f)
        await file.close()
        res = enroll_speaker(name=name, path=tmp)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

@router.delete("/{speaker_id}")
def remove(speaker_id: str):
    ok = delete_speaker(speaker_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Speaker not found")
    return {"status":"ok"}
