# rag-backend/app/auth.py
import os
from typing import Optional
from fastapi import Header, HTTPException

def verify_api_key(x_api_key: Optional[str] = Header(None)):
    expected = os.getenv("API_KEY", "change-me")
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
