// ChatAnswer.jsx - shows one backend response (single answer, or intent "multi" with several parts).
// Usage:  <ChatAnswer response={data} />
import { Database } from 'lucide-react';

function Sources({ sources }) {
  const unique = [...new Set(sources || [])];
  if (unique.length === 0) return null;
  return (
    <div className="sources">
      <span className="sources-label"><Database size={12} aria-hidden="true" />Sources Used</span>
      <div className="sources-row">
        {unique.map((s) => <span key={s} className="source-chip">{s}</span>)}
      </div>
    </div>
  );
}

function AnswerBlock({ number, question, answer, sources }) {
  return (
    <div className="answer-card">
      {question && <p className="answer-question">{number ? `${number}. ` : ''}{question}</p>}
      <p className="answer-text">{answer ?? ''}</p>
      <Sources sources={sources} />
    </div>
  );
}

export default function ChatAnswer({ response }) {
  if (!response) return null;
  const parts = response.intent === 'multi' && Array.isArray(response.parts) ? response.parts : null;

  if (parts) {
    return (
      <div>
        {parts.map((p, i) => (
          <AnswerBlock key={`${i}-${p.question}`} number={i + 1} question={p.question} answer={p.answer} sources={p.sources} />
        ))}
      </div>
    );
  }
  return <AnswerBlock answer={response.answer} sources={response.sources} />;
}
