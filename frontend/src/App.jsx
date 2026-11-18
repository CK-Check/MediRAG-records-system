// App.jsx - sidebar + chat screen. Talks to the backend ONLY through api.js and shows answers with ChatAnswer.jsx.
import { useEffect, useRef, useState } from 'react';
import { ArrowUp, FileLock2, Info, LoaderCircle, MessageSquarePlus, ShieldCheck, ShieldPlus, Cpu, UserRound } from 'lucide-react';
import { askBackend, describeError, resetConversation } from './api.js';
import ChatAnswer from './ChatAnswer.jsx';
import './App.css';

// Clickable examples. They only fill the input box, so you can edit them first.
const EXAMPLES = [
  'Can you tell me about Tad Grimes?',
  'When was Tad Grimes’s last visit?',
  'How did Tad’s weight change?',
  'Calculate the BMI for a patient who weighs 80 kg and is 175 cm tall.',
];

const STATUS = [
  { label: 'Local Index', value: 'Encrypted', Icon: FileLock2, tone: 'blue' },
  { label: 'Offline LLM', value: 'Active', Icon: Cpu, tone: 'blue' },
  { label: 'HIPAA Guard', value: 'DP-RAG (ε=1.2)', Icon: ShieldPlus, tone: 'strong' },
];

export default function App() {
  const [messages, setMessages] = useState([]); // { id, role: 'user' | 'assistant' | 'error' | 'notice', text?, response? }
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [patientName, setPatientName] = useState(null);
  const nextId = useRef(1);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [messages, loading]);

  const add = (message) => setMessages((all) => [...all, { id: nextId.current++, ...message }]);

  async function send(text) {
    const query = text.trim();
    if (!query || loading) return;
    add({ role: 'user', text: query });
    setInput('');
    setLoading(true);
    try {
      const response = await askBackend(query);
      if (response.patient_name) setPatientName(response.patient_name);
      if (response.notice) add({ role: 'notice', text: response.notice });
      add({ role: 'assistant', response });
    } catch (err) {
      add({ role: 'error', text: describeError(err) });
    } finally {
      setLoading(false);
    }
  }

  async function newConversation() {
    if (loading) return;
    await resetConversation();
    setMessages([]);
    setPatientName(null);
    setInput('');
  }

  function onSubmit(event) {
    event.preventDefault();
    send(input);
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <ShieldCheck size={22} aria-hidden="true" />
          <h1>MediRAG Secure</h1>
        </div>

        <section aria-labelledby="status-title">
          <h2 id="status-title" className="side-label">COMPLIANCE STATUS</h2>
          <ul className="status-list">
            {STATUS.map(({ label, value, Icon, tone }) => (
              <li key={label}>
                <span className="status-name"><Icon size={14} aria-hidden="true" />{label}</span>
                <span className={`status-value ${tone}`}>{value}</span>
              </li>
            ))}
          </ul>
        </section>

        <aside className="env-note">
          <strong>Clinical Environment:</strong> This system runs 100% locally. Patient Electronic Health
          Records (EHR) and laboratory data are mathematically protected from embedding inversion attacks.
        </aside>

        <div className="side-actions">
          {patientName && (
            <span className="patient-chip" title="The patient this conversation is about">
              <UserRound size={14} aria-hidden="true" />
              <span>Discussing: {patientName}</span>
            </span>
          )}
          <button type="button" className="new-chat" onClick={newConversation} disabled={loading || messages.length === 0}>
            <MessageSquarePlus size={16} aria-hidden="true" />
            <span>New conversation</span>
          </button>
        </div>
      </aside>

      <div className="chat">
        <main className="messages" aria-live="polite">
          <p className="system-note">
            System ready. Ask a question about your indexed documents. All processing is 100% offline and private.
          </p>

          {messages.length === 0 && (
            <div className="examples">
              {EXAMPLES.map((example) => (
                <button key={example} type="button" className="example" onClick={() => setInput(example)}>
                  {example}
                </button>
              ))}
            </div>
          )}

          {messages.map((m) => {
            if (m.role === 'user') return <div key={m.id} className="bubble user">{m.text}</div>;
            if (m.role === 'error') return <div key={m.id} className="bubble error" role="alert">{m.text}</div>;
            if (m.role === 'notice') {
              return (
                <div key={m.id} className="notice" role="status">
                  <Info size={14} aria-hidden="true" />
                  <span>{m.text}</span>
                </div>
              );
            }
            return <ChatAnswer key={m.id} response={m.response} />;
          })}

          {loading && (
            <div className="loading">
              <LoaderCircle size={16} className="spin" aria-hidden="true" />
              <span>Working… the first answer can take a minute or two while the model loads.</span>
            </div>
          )}
          <div ref={bottomRef} />
        </main>

        <form className="composer" onSubmit={onSubmit}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about your documents..."
            aria-label="Your question"
            disabled={loading}
            autoFocus
          />
          <button type="submit" disabled={loading || !input.trim()} aria-label="Send">
            <ArrowUp size={18} aria-hidden="true" />
          </button>
        </form>
      </div>
    </div>
  );
}
