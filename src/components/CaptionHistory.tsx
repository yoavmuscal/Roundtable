import { useEffect, useRef, useState } from 'react';
import { formatClock } from '../lib/map';
import { CaptionText } from '../lib/nameText';
import { ShapeGlyph } from '../lib/shape';
import { useRoundtableStore } from '../state/store';

export function CaptionHistory() {
  const open = useRoundtableStore((state) => state.historyOpen);
  const history = useRoundtableStore((state) => state.history);
  const people = useRoundtableStore((state) => state.people);
  const toggleHistory = useRoundtableStore((state) => state.toggleHistory);
  const [paused, setPaused] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!paused && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [history, paused, open]);

  if (!open) return null;

  return (
    <aside className="caption-history" aria-label="Caption history">
      <div className="history-heading">
        <div>
          <strong>Caption history</strong>
          <span>Last few minutes</span>
        </div>
        <button type="button" onClick={toggleHistory} aria-label="Close caption history">
          ×
        </button>
      </div>
      <div
        ref={listRef}
        className="history-list"
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
      >
        {history.length ? (
          history.map((caption) => {
            const person = people.find((item) => item.id === caption.personId);
            return (
              <article key={caption.id} className={caption.nameAlert ? 'history-row mentioned' : 'history-row'}>
                <div className="history-meta">
                  <ShapeGlyph shape={person?.shape ?? 'circle'} color={person?.color ?? '#8B7CF6'} size={14} />
                  <strong>{person?.name ?? 'Unknown'}</strong>
                  <span>{formatClock(caption.start)}</span>
                </div>
                <p><CaptionText text={caption.text} people={people} /></p>
                {caption.nameAlert ? <em>Name alert</em> : null}
              </article>
            );
          })
        ) : (
          <p className="empty-state">Final captions will appear here as people speak.</p>
        )}
      </div>
    </aside>
  );
}
