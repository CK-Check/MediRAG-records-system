"""
api.py  -  The "switchboard". Start with:  python api.py
Endpoints:  GET /health     POST /chat  {"query": "..."}
"""
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager

from src.agent_pipeline import MediRAGAgent
from src.dp_embeddings import DPHuggingFaceEmbeddings

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.agent = MediRAGAgent(embeddings=DPHuggingFaceEmbeddings())
    yield
    app.state.agent.close()
    app.state.agent = None

app = FastAPI(title="MediRAG", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["http://localhost:3000", "http://localhost:5173"], 
    allow_methods=["*"], 
    allow_headers=["*"]
)

class ChatRequest(BaseModel):
    query: str


@app.get("/health")
def health(request: Request):
    agent = request.app.state.agent
    return {"status": "ok", "patients_loaded": len(agent.records)}


@app.post("/chat")
def chat(request: Request, req: ChatRequest):
    return request.app.state.agent.ask(req.query)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)
