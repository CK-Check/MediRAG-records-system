// api.js - the ONLY place that knows where the backend lives.
// Put VITE_API_URL=http://127.0.0.1:5000 in rag-frontend/.env (restart `npm run dev` after editing it).
import axios from 'axios';

export const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:5000';

const client = axios.create({
  baseURL: API_URL,
  timeout: 300000, // the first model answer can take a minute or two while Phi-3 loads
});

/** Send one message. Returns the backend JSON: { intent, answer, sources, patient_id, parts? } */
export async function askBackend(query) {
  const { data } = await client.post('/chat', { query });
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