import { useRoundtableStore } from '../state/store';

export function AnswerCard() {
  const answer = useRoundtableStore((state) => state.answer);
  const clearAnswer = useRoundtableStore((state) => state.clearAnswer);
  if (!answer) return null;

  return (
    <aside className="answer-card" aria-label="Answer about the meeting">
      <div className="card-heading">
        <strong>Answer</strong>
        <button type="button" onClick={clearAnswer} aria-label="Dismiss answer">
          ×
        </button>
      </div>
      <p className="answer-question">{answer.question}</p>
      <p>{answer.text}</p>
      <div className="citations">
        {answer.citedTurnIds.map((turnId) => (
          <span key={turnId}>{turnId}</span>
        ))}
      </div>
    </aside>
  );
}
