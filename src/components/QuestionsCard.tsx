import { useRoundtableStore } from '../state/store';

export function QuestionsCard() {
  const openQuestions = useRoundtableStore((state) => state.openQuestions);
  const overdueQuestions = useRoundtableStore((state) => state.overdueQuestions);
  const people = useRoundtableStore((state) => state.people);
  const overdue = new Set(overdueQuestions.map((question) => question.turnId));

  return (
    <section className="questions-card card" aria-label="Open questions">
      <div className="card-heading plain-heading">
        <strong>Open questions</strong>
      </div>
      <div className="question-count">{openQuestions.length}</div>
      <p className={overdueQuestions.length ? 'overdue-copy' : 'empty-state'}>
        {overdueQuestions.length ? `${overdueQuestions.length} unanswered > 60 s` : openQuestions.length ? 'Waiting for an answer' : 'No unanswered questions'}
      </p>
      <ul className="question-list">
        {openQuestions.slice(-3).map((question) => {
          const person = people.find((item) => item.id === question.askerId);
          return (
            <li key={question.turnId} className={overdue.has(question.turnId) ? 'overdue' : undefined} style={{ borderColor: person?.color ?? '#5B8DEF' }}>
              {question.text}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
