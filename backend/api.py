"""
api.py  -  The "switchboard". Start with:  python api.py
Endpoints:  GET /health     POST /chat  {"query": "..."}
"""
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.agent_pipeline import MediRAGAgent
from src.dp_embeddings import DPHuggingFaceEmbeddings

PORT = 5000   # any port Windows allows; keep your frontend URL in sync


@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP: runs once, before the first request. Built once, so each question is fast.
    app.state.agent = MediRAGAgent(embeddings=DPHuggingFaceEmbeddings())
    yield
    # SHUTDOWN: runs once, when the server stops.
    app.state.agent.close()
    app.state.agent = None


app = FastAPI(title="MediRAG", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = Field(default=None, max_length=64)   # lets the backend remember the conversation


class ResetRequest(BaseModel):
    session_id: str = Field(max_length=64)


@app.get("/health")
def health(request: Request):
    agent = request.app.state.agent
    return {"status": "ok", "patients_loaded": len(agent.records)}


@app.post("/chat")
def chat(req: ChatRequest, request: Request):
    return request.app.state.agent.ask(req.query, req.session_id)


@app.post("/reset")
def reset(req: ResetRequest, request: Request):
    """Start a new conversation: forget the patient and recent questions for this session."""
    request.app.state.agent.sessions.reset(req.session_id)
    return {"status": "reset"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)