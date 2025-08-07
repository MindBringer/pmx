from fastapi import FastAPI, UploadFile, File
from retriever import query_index
from pydantic import BaseModel

import shutil
import os

app = FastAPI()

class RAGQuery(BaseModel):
    query: str
    top_k: int = 3

@app.post("/rag/query")
async def rag_query(payload: RAGQuery):
    answer = query_index(payload.query, top_k=payload.top_k)
    return {"context": str(answer)}

UPLOAD_DIR = "./documents"

@app.post("/rag/upload")
async def upload_file(file: UploadFile = File(...)):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "success", "filename": file.filename}