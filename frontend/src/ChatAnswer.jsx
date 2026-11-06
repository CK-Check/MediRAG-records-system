// ChatAnswer.jsx - shows one backend response.
// Handles single answers AND intent "multi" (several questions answered separately).
// Usage:  <ChatAnswer response={data} />      where data is what askBackend() returned.
import { Calculator, Database, Layers, Search, Tag, TrendingUp, User } from 'lucide-react';

const ROUTES = {
  calculate: { label: 'Calculator', Icon: Calculator },
  trend: { label: 'Trend', Icon: TrendingUp },
  lookup: { label: 'Record lookup', Icon: Database },
  search: { label: 'AI search', Icon: Search },
  multi: { label: 'Several questions', Icon: Layers },
  need_patient: { label: 'Patient needed', Icon: User },
};

// Neutral colours that work in both light and dark pages.
const line = '1px solid rgba(128,128,128,0.35)';
const styles = {
  card: { border: line, borderRadius: 10, padding: '12px 14px', margin: '8px 0', textAlign: 'left' },
  question: { fontWeight: 600, margin: '0 0 6px' },
  answer: { whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5, margin: 0 },
  row: { display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', marginTop: 10 },
  badge: { display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, opacity: 0.75, marginBottom: 6 },
  chip: { display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, border: line, borderRadius: 999, padding: '2px 8px', opacity: 0.85 },
};

function RouteBadge({ intent }) {
  const route = ROUTES[intent];
  if (!route) return null;
  const { Icon, label } = route;
  return (
    <div style={styles.badge}>
      <Icon size={14} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

function Sources({ sources }) {
  const unique = [...new Set(sources || [])];
  if (unique.length === 0) return null;
  return (
    <div style={styles.row} aria-label="Sources">
      {unique.map((s) => (
        <span key={s} style={styles.chip}>
          <Tag size={12} aria-hidden="true" />
          {s}
        </span>
      ))}
    </div>
  );
}

function AnswerBlock({ number, question, answer, sources, intent }) {
  return (
    <div style={styles.card}>
      <RouteBadge intent={intent} />
      {question && <p style={styles.question}>{number ? `${number}. ` : ''}{question}</p>}
      <p style={styles.answer}>{answer ?? ''}</p>
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
          <AnswerBlock key={`${i}-${p.question}`} number={i + 1} question={p.question}
            answer={p.answer} sources={p.sources} intent={p.intent} />
        ))}
      </div>
    );
  }
  return <AnswerBlock answer={response.answer} sources={response.sources} intent={response.intent} />;
}