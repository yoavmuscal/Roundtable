import { useRoundtableStore } from '../state/store';

export function QuestionsCard() {
  const openQuestions = useRoundtableStore((state) => state.openQuestions);
  const overdueQuestions = useRoundtableStore((state) => state.overdueQuestions);

  return (
    <section className="questions-card card" aria-label="Open questions">
      <div className="card-heading plain-heading">
        <strong>Open questions</strong>
      </div>
      <div className="question-count">{openQuestions.length}</div>
      <p className={overdueQuestions.length ? 'overdue-copy' : 'empty-state'}>
        {overdueQuestions.length
          ? `${overdueQuestions.length} unanswered > 60 s`
          : 'No unanswered questions'}
      </p>
    </section>
  );
}
