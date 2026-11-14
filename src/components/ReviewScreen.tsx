import { FormEvent, useState } from 'react';
import { formatClock } from '../lib/map';
import { CaptionText } from '../lib/nameText';
import { ShapeGlyph } from '../lib/shape';
import { roundtableClient } from '../services/roundtableClient';
import { useRoundtableStore } from '../state/store';

export function ReviewScreen() {
  const refined = useRoundtableStore((state) => state.refined);
  const refineProgress = useRoundtableStore((state) => state.refineProgress);
  const refineMessage = useRoundtableStore((state) => state.refineMessage);
  const people = useRoundtableStore((state) => state.people);
  const answer = useRoundtableStore((state) => state.answer);
  const history = useRoundtableStore((state) => state.history);
  const [question, setQuestion] = useState('');

  const ask = (event: FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text) return;
    roundtableClient.ask(text);
    setQuestion('');
  };

  const turns = refined?.turns.length
    ? refined.turns
    : history.map((caption) => ({
        id: caption.turnId,
        personId: caption.personId ?? '',
        text: caption.text,
        start: caption.start,
        end: caption.end ?? caption.start,
        confidence: caption.confidence,
        tags: caption.nameAlert ? ['name alert'] : [],
      }));

  return (
    <main className="review-screen">
      <section className="review-summary card">
        <p className="eyebrow">After Stop · refined locally</p>
        <h1>Review the meeting without replaying the whole room.</h1>
        {refined ? (
          <>
            <div className="correction-badge">
              Corrected {refined.correctedTurns} of {refined.totalTurns} turns
            </div>
            <p>{refined.summary}</p>
            <div className="topic-list">
              {refined.topics.map((topic) => <span key={topic}>{topic}</span>)}
            </div>
            <h2>Action items</h2>
            <ul className="action-list">
              {refined.actionItems.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </>
        ) : (
          <div className="refine-waiting">
            <div className="progress-ring" style={{ '--progress': `${Math.round(refineProgress * 100)}%` } as React.CSSProperties}>
              {Math.round(refineProgress * 100)}%
            </div>
            <p>{refineMessage || 'Run or replay a session, then Stop to refine it with SpeakerKit and Bonsai.'}</p>
          </div>
        )}
        <form className="ask-form" onSubmit={ask}>
          <label htmlFor="meeting-question">Ask about this meeting</label>
          <div>
            <input
              id="meeting-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="What did Maya ask about the launch?"
            />
            <button type="submit" className="primary">Ask</button>
          </div>
        </form>
        {answer ? (
          <article className="inline-answer">
            <strong>{answer.question}</strong>
            <p>{answer.text}</p>
            <div className="citations">
              {answer.citedTurnIds.map((turnId) => <span key={turnId}>{turnId}</span>)}
            </div>
          </article>
        ) : null}
      </section>

      <section className="transcript card" aria-label="Refined transcript">
        <div className="card-heading">
          <strong>Transcript</strong>
          <span>{turns.length} turns</span>
        </div>
        <div className="turn-list">
          {turns.length ? turns.map((turn) => {
            const person = people.find((item) => item.id === turn.personId);
            return (
              <article key={turn.id} id={turn.id} className="turn-row">
                <div className="history-meta">
                  <ShapeGlyph shape={person?.shape ?? 'circle'} color={person?.color ?? '#8B7CF6'} />
                  <strong>{person?.name ?? 'Unknown'}</strong>
                  <span>{formatClock(turn.start)}</span>
                  <em>{Math.round(turn.confidence * 100)}%</em>
                </div>
                <p><CaptionText text={turn.text} people={people} /></p>
                <div className="tag-list">
                  {turn.tags.map((tag) => <span key={tag}>{tag}</span>)}
                </div>
              </article>
            );
          }) : <p className="empty-state">No finalized turns yet.</p>}
        </div>
      </section>
    </main>
  );
}
