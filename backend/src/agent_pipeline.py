import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional, TypedDict
from langchain_core.vectorstores import InMemoryVectorStore

from langgraph.graph import END, StateGraph

from src.qdrant_store import QdrantStore
from src import tools

ROOT = Path(__file__).resolve().parent.parent
NO_ANSWER = "I could not find this in the patient records."

PROMPT = """You are a clinical records assistant. Answer the question using ONLY the context below.
Rules:
- Copy names, dates, numbers and units EXACTLY as written in the context. Never rewrite or reformat a date.
- When you give a value, include the date it was recorded.
- If the answer is not in the context, reply exactly: {no_answer}
- Answer in 1 to 4 short sentences or a short list. Do not add notes, comments or opinions.
- Do not guess, diagnose, or give medical advice.

Context:
{context}

Question: {question}
Answer:"""


class AgentState(TypedDict, total=False):
    query: str
    patient_id: Optional[str]
    intent: str
    answer: Optional[str]
    sources: List[str]


def ollama_generate(
    prompt, 
    model=os.getenv('OLLAMA_MODEL', 'phi3'), 
    host= os.getenv("OLLAMA_HOST", "http://localhost:11434")
):
    """Talk to the local Ollama server. No internet involved."""
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt, 
            "stream": False,
            "options": {"temperature": 0}
        }).encode()
    req = urllib.request.Request(
        f"{host}/api/generate", 
        data=body,
        headers={"Content-Type": "application/json"}
        )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())["response"].strip()


# ----------------------------------------------------------------- routing
CALC_RE = re.compile(r"\b(calculate|compute|work out)\b")
TREND_RE = re.compile(r"trend|over time|over the years|changed?\b|history of|progress|increas|decreas|gain|loss|since|from \d{4}")
LOOKUP_RE = re.compile(r"allerg|medication|medicine|\bdrugs?\b|prescri|condition|diagnos|problem|"
                       r"latest|most recent|vitals|\blabs?\b|summary|\bdob\b|\bage\b|born|gender|status|deceased")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def classify(query):
    q = query.lower()
    has_numbers = bool(re.search(r"\d\s*(kg|lbs?|cm|m|mg/kg)\b", q))
    if CALC_RE.search(q) or ("bmi" in q and has_numbers) or "mg/kg" in q:
        return "calculate"
    if tools.metrics_in(q) and (TREND_RE.search(q) or YEAR_RE.search(q)):
        return "trend"
    if tools.is_overview(q) or tools.LAST_VISIT_RE.search(q) or tools.is_date_visit_question(q) or LOOKUP_RE.search(q):
        return "lookup"
    return "search"


class MediRAGAgent:
    def __init__(self, records_dir=None, index_dir=None, embeddings=None, llm=None, k=4):
        self.records_dir = Path(records_dir or ROOT / "records")
        self.index_dir = Path(index_dir or ROOT / "index")
        self.embeddings = embeddings
        self.llm = llm or ollama_generate
        self.k = k
        self._store = None
        self.records = {}
        for p in self.records_dir.glob("*.json"):
            rec = json.loads(p.read_text(encoding="utf-8"))
            self.records[rec["patient_id"]] = rec
        self.graph = self._build_graph()

    # ---- patient resolution: which patient is the question about?
    def resolve_patient(self, query):
        q = query.lower()
        hits = []
        for pid, rec in self.records.items():
            name = re.sub(r"^(ms|mr|mrs|dr)\.?\s+", "", rec["patient_name"].lower())
            tokens = [t for t in name.split() if len(t) >= 3]
            if pid.lower() in q or any(t in q for t in tokens):
                hits.append(pid)
        if len(hits) == 1:
            return hits[0]
        if not hits and len(self.records) == 1:
            return next(iter(self.records))
        return None

    # ---- graph nodes
    def router_node(self, state):
        intent = classify(state["query"])
        pid = state.get("patient_id") or self.resolve_patient(state["query"])
        needs_patient = intent in ("trend", "lookup", "search")
        if needs_patient and pid is None:
            return {"intent": "need_patient", "patient_id": None,
                    "answer": "Please include the patient's name or ID in your question.", "sources": []}
        return {"intent": intent, "patient_id": pid}

    def calculate_node(self, state):
        record = self.records.get(state.get("patient_id"))
        return {"answer": tools.calculate(state["query"], record), "sources": ["Python calculator"]}

    def trend_node(self, state):
        text, src = tools.trend(self.records[state["patient_id"]], state["query"])
        return {"answer": text, "sources": src}

    def lookup_node(self, state):
        text, src = tools.lookup(self.records[state["patient_id"]], state["query"])
        return {"answer": text, "sources": src}  # answer=None -> falls back to search

    def search_node(self, state):
        if self.embeddings is None:
            raise ValueError("Embeddings must be initialized before loading the vector store.")
        if self._store is None:
            try:
                self._store = QdrantStore.load_local(str(self.index_dir), self.embeddings)
            except FileNotFoundError:
                return {"answer": "The search index has not been built yet. Stop the server, run "
                                  "'python ingest.py', check that it ends with a [done] line, then start the server again.",
                        "sources": []}
        pid = state["patient_id"]
        docs = self._store.similarity_search(
            state["query"], 
            k=self.k, 
            filter={"patient_id": state["patient_id"]}
        )
        if not docs:
            return {"answer": NO_ANSWER, "sources": []}
        sources = [f"{d.metadata['section'].split(' (')[0]}" + (f" {d.metadata['date']}" if "date" in d.metadata else "")
                   for d in docs]
        context = "\n\n".join(d.page_content for d in docs)
        prompt = PROMPT.format(no_answer=NO_ANSWER, context=context, question=state["query"])
        try:
            answer = self.llm(prompt)
        except Exception as e:  # Ollama not running, model missing, etc.
            answer = (f"The local AI model is not reachable ({type(e).__name__}). "
                      "Start Ollama and run 'ollama pull phi3'. Retrieved records:\n\n" + context)
        if NO_ANSWER is answer:
            sources = []
        return {"answer": answer, "sources": sources}

    # ---- wiring
    def _build_graph(self):
        g = StateGraph(AgentState)
        g.add_node("router", self.router_node)
        g.add_node("calculate", self.calculate_node)
        g.add_node("trend", self.trend_node)
        g.add_node("lookup", self.lookup_node)
        g.add_node("search", self.search_node)
        g.set_entry_point("router")
        g.add_conditional_edges("router", lambda s: s["intent"], {
            "calculate": "calculate", "trend": "trend", "lookup": "lookup",
            "search": "search", "need_patient": END})
        g.add_conditional_edges("trend", lambda s: "search" if s.get("answer") is None else "done",
                                {"search": "search", "done": END})
        g.add_conditional_edges("lookup", lambda s: "search" if s.get("answer") is None else "done",
                                {"search": "search", "done": END})
        g.add_edge("calculate", END)
        g.add_edge("search", END)
        return g.compile()

    def close(self):
        if self._store is not None:
            self._store.close()

    def _ask_one(self, query, patient_id=None):
        state: AgentState = {"query": query}
        if patient_id:
            state["patient_id"] = patient_id
        out = self.graph.invoke(state)
        return {"question": query, "intent": out.get("intent"), "answer": out.get("answer"),
                "sources": out.get("sources", []), "patient_id": out.get("patient_id")}

    def ask(self, query):
        # One message can hold several questions. Split at question marks and
        # answer each one on its own route, so nothing is silently dropped.
        parts = [p.strip() for p in re.split(r"(?<=\?)\s*", query) if p.strip()]
        if len(parts) <= 1:
            r = self._ask_one(query)
            return {k: r[k] for k in ("intent", "answer", "sources", "patient_id")}

        pid = self.resolve_patient(query)          # who the WHOLE message is about
        results = [self._ask_one(p, pid) for p in parts]
        answer = "\n\n".join(f"{i}. {r['question']}\n{r['answer']}" for i, r in enumerate(results, 1))
        sources = list(dict.fromkeys(s for r in results for s in r["sources"]))
        return {"intent": "multi", "answer": answer, "sources": sources,
                "patient_id": pid, "parts": results}