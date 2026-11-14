import { useEffect, useMemo, useRef } from 'react';
import type { Caption } from '../contract';
import { CaptionText } from '../lib/nameText';
import { ShapeGlyph } from '../lib/shape';
import { useRoundtableStore } from '../state/store';

const MAX_ENTRIES = 10;

/** Color-coded running transcript under the video: finished turns plus what is being said now. */
export function LiveTranscript() {
  const history = useRoundtableStore((state) => state.history);
  const captions = useRoundtableStore((state) => state.captions);
  const people = useRoundtableStore((state) => state.people);
  const activeSpeakerId = useRoundtableStore((state) => state.activeSpeakerId);
  const largeCaptions = useRoundtableStore((state) => state.largeCaptions);
  const scroller = useRef<HTMLDivElement>(null);

  const entries = useMemo(() => {
    const finalTurns = new Set(history.map((caption) => caption.turnId));
    const live = Object.values(captions).filter((caption) => caption.kind === 'partial' && !finalTurns.has(caption.turnId));
    // One in-progress entry per turn (the newest partial).
    const latestPartial = new Map<string, Caption>();
    live.forEach((caption) => {
      const current = latestPartial.get(caption.turnId);
      if (!current || (caption.end ?? caption.start) >= (current.end ?? current.start)) latestPartial.set(caption.turnId, caption);
    });
    return [...history, ...latestPartial.values()]
      .sort((a, b) => a.start - b.start)
      .slice(-MAX_ENTRIES);
  }, [history, captions]);

  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [entries]);

  return (
    <section className={largeCaptions ? 'live-transcript card large' : 'live-transcript card'} aria-label="Live transcript" aria-live="polite">
      <div ref={scroller} className="live-transcript-lines">
        {entries.length ? (
          entries.map((caption) => {
            const person = people.find((item) => item.id === caption.personId)
              ?? people.find((item) => item.id === activeSpeakerId)
              ?? people[0];
            const color = person?.color ?? '#9AA1AD';
            return (
              <span key={caption.id} className={caption.kind === 'partial' ? 'transcript-entry partial' : 'transcript-entry'}>
                <ShapeGlyph shape={person?.shape ?? 'circle'} color={color} size={10} />
                <b style={{ color }}>{person?.name ?? 'Speaker'}</b>
                <CaptionText text={caption.text} people={people} />
              </span>
            );
          })
        ) : (
          <span className="transcript-empty">Live transcript appears here as people speak.</span>
        )}
      </div>
    </section>
  );
}
