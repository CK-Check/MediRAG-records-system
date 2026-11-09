"""
agentic_pipeline.py  -  The "receptionist" (LangGraph state machine).

   question --> [router] --+--> calculate --> END
                           +--> trend ------> END
                           +--> lookup -----> END   (falls back to search if nothing matched)
                           +--> search -----> END   (vector search + local LLM)
                           +--> need_patient -> END (asks "which patient?")

Only 'search' uses the AI model. The other routes are exact Python.
"""
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from src import tools
from src.session_memory import SessionStore

ROOT = Path(__file__).resolve().parent.parent
NO_ANSWER = "I could not find this in the patient records."

PROMPT = """You are a clinical records assistant. Answer the question using ONLY the context below.
Rules:
- Copy names, dates, numbers and units EXACTLY as written in the context. Never rewrite or reformat a date.
- When you give a value, include the date it was recorded.
- If the answer is not in the context, reply exactly: {no_answer}
- Answer in 1 to 4 short sentences or a short list. Do not add notes, comments or opinions.
- Do not guess, diagnose, or give medical advice.

{history_block}Context:
{context}

Question: {question}
Answer:"""


class AgentState(TypedDict, total=False):
    query: str
    patient_id: Optional[str]
    intent: str
    answer: Optional[str]
    sources: List[str]
    history: List[str]        # earlier user questions in this conversation (input)
    last_metrics: List[str]   # vital sign(s) asked about previously (input)
    metrics: List[str]        # vital sign(s) used in THIS answer (output, remembered for next time)


def _ollama_host():
    """Read OLLAMA_HOST (e.g. 127.0.0.1:11434) so the port lives in ONE place."""
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").strip()
    if not host.startswith("http"):
        host = "http://" + host
    return host.replace("0.0.0.0", "127.0.0.1")   # 0.0.0.0 is for listening, not connecting


def ollama_generate(prompt, model=os.environ.get("OLLAMA_MODEL", "phi3"), host=None):
    """Talk to the local Ollama server. No internet involved."""
    host = host or _ollama_host()
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0, "num_ctx": 4096}}).encode()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never use a proxy
    last_error = None
    for _attempt in range(3):
        try:
            req = urllib.request.Request(f"{host}/api/generate", data=body,
                                         headers={"Content-Type": "application/json"})
            with opener.open(req, timeout=300) as r:
                return json.loads(r.read())["response"].strip()
        except urllib.error.HTTPError as e:     # 500: runner may have failed to start; retry
            last_error = e
        except urllib.error.URLError as e:      # server not reachable at all: retrying won't help
            last_error = e
            break
    if last_error is None:   # cannot happen (every loop pass returns or sets it); this also satisfies the type checker
        raise RuntimeError("The Ollama request failed for an unknown reason.")
    raise last_error


# ----------------------------------------------------------------- routing
CALC_RE = re.compile(r"\b(calculate|compute|work out)\b")
TREND_RE = re.compile(r"trend|over time|over the years|changed?\b|history of|progress|increas|decreas|gain|loss|since|from \d{4}")
LOOKUP_RE = re.compile(r"allerg|medication|medicine|\bdrugs?\b|prescri|condition|diagnos|problem|"
                       r"latest|most recent|vitals|\blabs?\b|summary|\bdob\b|\bage\b|born|gender|status|deceased")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
PRONOUN_RE = re.compile(r"\b(he|she|his|her|him|they|their|it|its|that|this|those|these|there)\b")


def classify(query):
    q = query.lower()
    has_numbers = bool(re.search(r"\d\s*(kg|lbs?|cm|m|mg/kg)\b", q))
    if CALC_RE.search(q) or ("bmi" in q and has_numbers) or "mg/kg" in q:
        return "calculate"
    if tools.is_dose_question(q):
        return "dose"
    if tools.metrics_in(q) and (TREND_RE.search(q) or YEAR_RE.search(q)):
        return "trend"
    if tools.is_overview(q) or tools.LAST_VISIT_RE.search(q) or tools.is_date_visit_question(q) or LOOKUP_RE.search(q):
        return "lookup"
    return "search"


class MediRAGAgent:
    def __init__(self, records_dir=None, index_dir=None, embeddings=None, llm=None, k=4, sessions=None):
        self.records_dir = Path(records_dir or ROOT / "records")
        self.index_dir = Path(index_dir or ROOT / "index")
        self.embeddings = embeddings
        self.llm = llm or ollama_generate
        self.k = k
        self.sessions = sessions if sessions is not None else SessionStore()   # short-term memory (RAM only)
        self._store = None
        self.records = {}
        for p in self.records_dir.glob("*.json"):
            rec = json.loads(p.read_text(encoding="utf-8"))
            self.records[rec["patient_id"]] = rec
        self.graph = self._build_graph()

    # ---- patient resolution: which patient is the question about?
    def patients_in_text(self, query):
        """IDs of every patient NAMED in the text (a name word or an ID). Whole words only."""
        q = query.lower()
        hits = []
        for pid, rec in self.records.items():
            name = re.sub(r"^(ms|mr|mrs|dr)\.?\s+", "", rec["patient_name"].lower())
            words = [w for w in name.split() if len(w) >= 3] + [pid.lower()]
            if any(re.search(rf"\b{re.escape(w)}\b", q) for w in words):
                hits.append(pid)
        return hits

    def resolve_patient(self, query):
        hits = self.patients_in_text(query)
        if len(hits) == 1:
            return hits[0]
        if not hits and len(self.records) == 1:      # only one patient loaded: no name needed
            return next(iter(self.records))
        return None

    def _patient_name(self, pid):
        return self.records[pid]["patient_name"] if pid in self.records else None

    # ---- graph nodes
    def router_node(self, state):
        query = state["query"]
        intent = classify(query)
        # Follow-up such as "And in 2025?": no vital sign named, so reuse the previous one.
        if (intent == "search" and state.get("last_metrics") and len(query.split()) <= 8
                and not tools.metrics_in(query) and (YEAR_RE.search(query) or TREND_RE.search(query.lower()))):
            intent = "trend"
        needs_patient = intent in ("trend", "lookup", "search")
        if intent in ("trend", "lookup", "search", "dose") and len(self.patients_in_text(query)) > 1:
            return {"intent": "need_patient", "patient_id": None, "sources": [],
                    "answer": "This question mentions more than one patient. Please ask about one patient at a time."}
        if intent == "dose":      # a patient is optional here, and a lone loaded patient is NOT assumed
            hits = self.patients_in_text(query)
            return {"intent": intent, "patient_id": state.get("patient_id") or (hits[0] if len(hits) == 1 else None)}
        pid = state.get("patient_id") or self.resolve_patient(query)
        if needs_patient and pid is None:
            return {"intent": "need_patient", "patient_id": None, "sources": [],
                    "answer": "Please include the patient's name or ID in your question."}
        return {"intent": intent, "patient_id": pid}

    def dose_node(self, state):
        query = state["query"]
        hits = self.patients_in_text(query)
        record = self.records.get(state.get("patient_id")) if state.get("patient_id") else None
        label = record["patient_name"] if record else None
        text, src = tools.dose_answer(record, query, label, patient_named=len(hits) == 1)
        return {"answer": text, "sources": src}

    def calculate_node(self, state):
        record = self.records.get(state.get("patient_id"))
        return {"answer": tools.calculate(state["query"], record), "sources": ["Python calculator"]}

    def trend_node(self, state):
        query = state["query"]
        named = tools.metrics_in(query)
        override = None if named else tools.metrics_by_label(state.get("last_metrics") or [])
        text, src = tools.trend(self.records[state["patient_id"]], query, metrics=override or None)
        labels = [m[0] for m in (named or override or [])]
        return {"answer": text, "sources": src, "metrics": labels}

    def lookup_node(self, state):
        text, src = tools.lookup(self.records[state["patient_id"]], state["query"])
        return {"answer": text, "sources": src}  # answer=None -> falls back to search

    def search_node(self, state):
        if self._store is None:
            from src.qdrant_store import QdrantStore
            try:
                self._store = QdrantStore.load_local(str(self.index_dir), self.embeddings)
            except FileNotFoundError:
                return {"answer": "The search index has not been built yet. Stop the server, run "
                                  "'python ingest.py', check that it ends with a [done] line, then start the server again.",
                        "sources": []}
        query = state["query"]
        history = state.get("history") or []
        retrieval_query, history_block = query, ""
        if history:
            if len(query.split()) <= 7 and PRONOUN_RE.search(query.lower()):
                retrieval_query = f"{history[-1]} {query}"      # "Why was she given that?" -> add the previous question
            history_block = ("Earlier questions in this conversation (only to understand what words like 'he', 'it' or "
                             "'that' refer to. Never use them as facts):\n"
                             + "\n".join(f"- {h}" for h in history[-3:]) + "\n\n")
        docs = self._store.similarity_search(
            retrieval_query, k=self.k, filter={"patient_id": state["patient_id"]})
        if not docs:
            return {"answer": NO_ANSWER, "sources": []}
        sources = [f"{d.metadata['section'].split(' (')[0]}" + (f" {d.metadata['date']}" if "date" in d.metadata else "")
                   for d in docs]
        context = "\n\n".join(d.page_content for d in docs)
        prompt = PROMPT.format(no_answer=NO_ANSWER, history_block=history_block, context=context, question=query)
        try:
            answer = self.llm(prompt)
        except Exception as e:  # Ollama not running, model missing, etc.
            reason = getattr(e, "reason", e)
            answer = (f"The local AI model failed: {type(e).__name__}: {reason}. "
                      "Check that Ollama is running and that 'ollama pull phi3' was done. "
                      "Retrieved records:\n\n" + context)
        if NO_ANSWER in answer:          # refusal: the retrieved chunks were not the answer, so do not cite them
            sources = []
        return {"answer": answer, "sources": sources}

    # ---- wiring
    def _build_graph(self):
        g = StateGraph(AgentState)
        g.add_node("router", self.router_node)
        g.add_node("calculate", self.calculate_node)
        g.add_node("dose", self.dose_node)
        g.add_node("trend", self.trend_node)
        g.add_node("lookup", self.lookup_node)
        g.add_node("search", self.search_node)
        g.set_entry_point("router")
        g.add_conditional_edges("router", lambda s: s["intent"], {
            "calculate": "calculate", "dose": "dose", "trend": "trend", "lookup": "lookup",
            "search": "search", "need_patient": END})
        g.add_conditional_edges("trend", lambda s: "search" if s.get("answer") is None else "done",
                                {"search": "search", "done": END})
        g.add_conditional_edges("lookup", lambda s: "search" if s.get("answer") is None else "done",
                                {"search": "search", "done": END})
        g.add_edge("calculate", END)
        g.add_edge("dose", END)
        g.add_edge("search", END)
        return g.compile()

    def close(self):
        if self._store is not None:
            self._store.close()

    def _ask_one(self, query, patient_id=None, history=None, last_metrics=None) -> Dict[str, Any]:
        state: AgentState = {"query": query, "history": list(history or []), "last_metrics": list(last_metrics or [])}
        if patient_id:
            state["patient_id"] = patient_id
        out = self.graph.invoke(state)
        return {"question": query, "intent": out.get("intent"), "answer": out.get("answer"),
                "sources": out.get("sources", []), "patient_id": out.get("patient_id"),
                "metrics": out.get("metrics", [])}

    def ask(self, query, session_id=None):
        """Answer one message. With a session_id the agent remembers the patient, the last
        vital sign and the last few questions between messages. Without one it is stateless."""
        session = self.sessions.get(session_id) if session_id else None
        previous_pid = session.patient_id if session else None

        # One message can hold several questions. Split at question marks and
        # answer each one on its own route, so nothing is silently dropped.
        parts = [p.strip() for p in re.split(r"(?<=\?)\s*", query) if p.strip()] or [query]

        in_whole = self.patients_in_text(query)
        current = in_whole[0] if len(in_whole) == 1 else previous_pid   # carry the patient over
        history = list(session.questions) if session else []
        last_metrics = list(session.last_metrics) if session else []
        used_metrics: List[str] = []
        results: List[Dict[str, Any]] = []

        for part in parts:
            named = self.patients_in_text(part)
            if len(named) == 1:
                pid = named[0]
            elif len(named) > 1:
                pid = None            # several patients named: the router will refuse, never guess
            else:
                pid = current         # no name in this part: continue with the patient in the conversation
            r = self._ask_one(part, pid, history, last_metrics)
            if r["patient_id"]:
                current = r["patient_id"]
            if r["metrics"]:
                last_metrics = used_metrics = r["metrics"]
            history = history + [part]
            results.append(r)

        if session:
            self.sessions.remember(session, current, used_metrics, parts)

        notice = None
        if previous_pid and current and current != previous_pid:
            notice = f"Now discussing {self._patient_name(current)}."
        extra = {"patient_id": current, "patient_name": self._patient_name(current), "notice": notice}

        if len(results) == 1:
            r = results[0]
            return {"intent": r["intent"], "answer": r["answer"], "sources": r["sources"], **extra}

        answer = "\n\n".join(f"{i}. {r['question']}\n{r['answer']}" for i, r in enumerate(results, 1))
        sources = list(dict.fromkeys(s for r in results for s in r["sources"]))
        return {"intent": "multi", "answer": answer, "sources": sources, "parts": results, **extra}