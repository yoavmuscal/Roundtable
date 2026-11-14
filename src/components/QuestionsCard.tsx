import { formatClock } from '../lib/map';
import { useRoundtableStore } from '../state/store';

export function QuestionsCard() {
  const openQuestions = useRoundtableStore((state) => state.openQuestions);
  const overdueQuestions = useRoundtableStore((state) => state.overdueQuestions);
  const questions = [...overdueQuestions, ...openQuestions.filter((item) => !item.overdue)].slice(0, 3);

  return (
    <section className="questions-card card" aria-label="Open questions">
      <div className="card-heading">
        <strong>Questions</strong>
        <span>{overdueQuestions.length} overdue</span>
      </div>
      {questions.length ? (
        <ul>
          {questions.map((question) => (
            <li key={question.id} className={question.overdue ? 'overdue' : ''}>
              <span>{question.text}</span>
              <small>{formatClock(question.createdAt)}</small>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty-state">Questions asked during the meeting will stay visible here.</p>
      )}
    </section>
  );
}
