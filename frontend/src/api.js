// api.js - the ONLY place that knows where the backend lives.
// Put VITE_API_URL=http://127.0.0.1:5000 in rag-frontend/.env (restart `npm run dev` after editing it).
import axios from 'axios';

export const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:5000';

const client = axios.create({
  baseURL: API_URL,
  timeout: 300000, // the first model answer can take a minute or two while Phi-3 loads
});

// --- conversation memory -------------------------------------------------------
// The backend remembers the patient and recent questions per session_id. The id lives in
// sessionStorage: it is private to this browser tab and disappears when the tab is closed.
const SESSION_KEY = 'medirag_session_id';
let fallbackId = null; // used only if sessionStorage is blocked

function makeId() {
  return globalThis.crypto?.randomUUID?.() ?? `s-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function getSessionId() {
  try {
    let id = sessionStorage.getItem(SESSION_KEY);
    if (!id) {
      id = makeId();
      sessionStorage.setItem(SESSION_KEY, id);
    }
    return id;
  } catch {
    fallbackId = fallbackId || makeId();
    return fallbackId;
  }
}

/** Start a new conversation: the backend forgets this session and we switch to a fresh id. */
export async function resetConversation() {
  const oldId = getSessionId();
  try {
    await client.post('/reset', { session_id: oldId });
  } catch {
    // If the backend is unreachable there is nothing to forget; the new id still starts clean.
  }
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
  fallbackId = null;
  return getSessionId();
}

/** Send one message. Returns { intent, answer, sources, patient_id, patient_name, notice, parts? } */
export async function askBackend(query) {
  const { data } = await client.post('/chat', { query, session_id: getSessionId() });
  return data;
}

/** Turn an axios error into a sentence a user can act on. */
export function describeError(err) {
  if (err.code === 'ECONNABORTED') {
    return 'The backend took too long to answer. The AI model may still be loading; try again in a minute.';
  }
  if (err.response) {
    return `The backend returned an error (HTTP ${err.response.status}). Check the backend terminal for details.`;
  }
  return `Cannot reach the backend at ${API_URL}. Is "python api.py" running, and is this page's address allowed in api.py (CORS)?`;
}