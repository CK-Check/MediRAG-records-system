"""
session_memory.py  -  Short-term conversation memory.

What is remembered, per chat session (the frontend sends a session_id):
  patient_id    the patient being discussed, so "What about his heart rate?" works
  last_metrics  the last vital sign(s) asked about, so "And in 2025?" works
  questions     the last few USER questions only. Answers are never stored, so a
                wrong or garbled answer can never turn into a "fact" later.

Safety and privacy choices:
  - kept in this process's RAM only: nothing is written to disk
  - a session expires after `ttl_seconds` of silence (default 30 minutes)
  - at most `max_sessions` are kept; the least recently used are dropped first
  - the server restarting wipes everything

Limits: one server process only. Several workers (or several machines) would not
share sessions; for that, keep the same fields in Redis or a database instead.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class Session:
    patient_id: Optional[str] = None
    last_metrics: List[str] = field(default_factory=list)   # labels such as "Weight"
    questions: List[str] = field(default_factory=list)      # recent user questions (never answers)
    last_used: float = 0.0


class SessionStore:
    def __init__(self, ttl_seconds: int = 1800, max_sessions: int = 200, max_questions: int = 4,
                 clock: Callable[[], float] = time.time):
        self.ttl = ttl_seconds
        self.max_sessions = max_sessions
        self.max_questions = max_questions
        self._clock = clock
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> Session:
        """Return the session (creating it if new or expired) and mark it as just used."""
        now = self._clock()
        with self._lock:
            self._purge(now)
            session = self._sessions.get(session_id)
            if session is None:
                session = Session()
                self._sessions[session_id] = session
            session.last_used = now
            return session

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def remember(self, session: Session, patient_id: Optional[str], metrics: List[str], questions: List[str]) -> None:
        """Update a session after a request. Keeps only the newest few questions."""
        if patient_id:
            session.patient_id = patient_id
        if metrics:
            session.last_metrics = list(metrics)
        session.questions = (session.questions + list(questions))[-self.max_questions:]
        session.last_used = self._clock()

    def _purge(self, now: float) -> None:
        for sid in [s for s, v in self._sessions.items() if now - v.last_used > self.ttl]:
            del self._sessions[sid]
        while len(self._sessions) >= self.max_sessions:          # drop the least recently used
            oldest = min(self._sessions, key=lambda s: self._sessions[s].last_used)
            del self._sessions[oldest]

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)