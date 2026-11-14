import { useMemo } from 'react';
import { ShapeGlyph } from '../lib/shape';
import { useRoundtableStore } from '../state/store';

const WINDOW_SECONDS = 90;
const TICKS = Array.from({ length: 31 }, (_, index) => index * 3);

export function SpeakerTimeline() {
  const people = useRoundtableStore((state) => state.people);
  const history = useRoundtableStore((state) => state.history);
  const sessionTime = useRoundtableStore((state) => state.sessionTime);

  const byPerson = useMemo(() => {
    const grouped = new Map<string, number[]>();
    history.forEach((caption) => {
      if (!caption.personId) return;
      const times = grouped.get(caption.personId) ?? [];
      times.push(caption.start, caption.end ?? caption.start);
      grouped.set(caption.personId, times);
    });
    return grouped;
  }, [history]);

  return (
    <section className="speaker-timeline card" aria-label="Who spoke when">
      <div className="timeline-heading">
        <strong>Who spoke when</strong>
        <span>now</span>
      </div>
      <div className="timeline-rows">
        {people.map((person) => (
          <div className="timeline-row" key={person.id}>
            <div className="timeline-person">
              <ShapeGlyph shape={person.shape} color={person.color} size={12} />
              <span>{person.name}</span>
            </div>
            <div className="timeline-track" aria-label={`${person.name} speech timeline`}>
              {TICKS.map((tick) => (
                <i key={tick} style={{ left: `${(tick / WINDOW_SECONDS) * 100}%` }} />
              ))}
              {(byPerson.get(person.id) ?? []).map((time, index) => (
                <b
                  key={`${time}-${index}`}
                  style={{
                    left: `${Math.min(100, (time / WINDOW_SECONDS) * 100)}%`,
                    background: person.color,
                    color: person.color,
                  }}
                />
              ))}
              <em className="now-line" style={{ left: `${Math.min(100, (sessionTime / WINDOW_SECONDS) * 100)}%` }} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
