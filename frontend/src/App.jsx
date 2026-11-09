// App.jsx - the whole chat screen: header, message list, input box.
// It talks to the backend ONLY through api.js and shows answers with ChatAnswer.jsx.
import { useEffect, useRef, useState } from 'react';
import { Info, LoaderCircle, MessageSquarePlus, Send, Stethoscope, UserRound } from 'lucide-react';
import { askBackend, describeError, resetConversation } from './api.js';
import ChatAnswer from './ChatAnswer.jsx';
import './App.css';

// Clickable examples. They only fill the input box, so you can edit them first.
// Change the names to match the patient files in source_documents/.
const EXAMPLES = [
  'Can you tell me about Tad Grimes?',
  'When was Tad Grimes’s last visit?',
  'How did Tad’s weight change?',
  'Calculate the BMI for a patient who weighs 80 kg and is 175 cm tall.',
];

export default function App() {
  const [messages, setMessages] = useState([]); // { id, role: 'user' | 'assistant' | 'error' | 'notice', text?, response? }
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [patientName, setPatientName] = useState(null); // who the conversation is about (from the backend)
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
      if (response.notice) add({ role: 'notice', text: response.notice }); // e.g. "Now discussing ..."
      add({ role: 'assistant', response });
    } catch (err) {
      add({ role: 'error', text: describeError(err) });
    } finally {
      setLoading(false);
    }
  }

  async function newConversation() {
    if (loading) return;
    await resetConversation();     // the backend forgets the patient and recent questions
    setMessages([]);
    setPatientName(null);
    setInput('');
  }

  function onSubmit(event) {
    event.preventDefault();
    send(input);
  }

  return (
    <div className="app">
      <header className="app-header">
        <Stethoscope size={22} aria-hidden="true" />
        <div className="app-title">
          <h1>MediRAG</h1>
          <p>Offline clinical records assistant</p>
        </div>
        <div className="header-actions">
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
      </header>

      <main className="messages" aria-live="polite">
        {messages.length === 0 && (
          <section className="empty">
            <p>Ask about a patient’s record. Include the patient’s name or ID once; follow-up questions remember who you mean.</p>
            <div className="examples">
              {EXAMPLES.map((example) => (
                <button key={example} type="button" className="example" onClick={() => setInput(example)}>
                  {example}
                </button>
              ))}
            </div>
          </section>
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
          placeholder="Ask a question about a patient…"
          aria-label="Your question"
          disabled={loading}
          autoFocus
        />
        <button type="submit" disabled={loading || !input.trim()} aria-label="Send">
          <Send size={18} aria-hidden="true" />
        </button>
      </form>
      <p className="disclaimer">Answers come from local patient records. Not medical advice.</p>
    </div>
  );
}