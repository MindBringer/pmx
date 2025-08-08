from fastapi import FastAPI, Query
from pipeline import rag_pipeline

app = FastAPI()

@app.get("/")
def healthcheck():
    return {"status": "ok"}

@app.get("/query")
def query(q: str = Query(..., description="Die Benutzerfrage")):
    result = rag_pipeline.run(query=q)
    return {
        "answer": result["answers"][0].answer,
        "context": [doc.content for doc in result["answers"][0].meta["context_documents"]]
    }
