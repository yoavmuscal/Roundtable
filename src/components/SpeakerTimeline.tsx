import { useMemo } from 'react';
import { ShapeGlyph } from '../lib/shape';
import { useRoundtableStore } from '../state/store';

const WINDOW_SECONDS = 90;
const TICKS = Array.from({ length: 31 }, (_, index) => index * 3);
const DOT_EVERY_SECONDS = 1.5;

export function SpeakerTimeline() {
  const people = useRoundtableStore((state) => state.people);
  const history = useRoundtableStore((state) => state.history);
  const sessionTime = useRoundtableStore((state) => state.sessionTime);

  const byPerson = useMemo(() => {
    const grouped = new Map<string, number[]>();
    history.forEach((caption) => {
      if (!caption.personId) return;
      const times = grouped.get(caption.personId) ?? [];
      const end = caption.end ?? caption.start;
      for (let t = caption.start; t <= end + 1e-6; t += DOT_EVERY_SECONDS) times.push(t);
      grouped.set(caption.personId, times);
    });
    return grouped;
  }, [history]);

  // The window slides once the session is longer than 90 s so "now" stays in view.
  const windowStart = Math.max(0, sessionTime - WINDOW_SECONDS);
  const position = (time: number) => ((time - windowStart) / WINDOW_SECONDS) * 100;

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
              {(byPerson.get(person.id) ?? [])
                .filter((time) => time >= windowStart)
                .map((time, index) => (
                  <b
                    key={`${time}-${index}`}
                    style={{ left: `${Math.min(100, position(time))}%`, background: person.color, color: person.color }}
                  />
                ))}
              <em className="now-line" style={{ left: `${Math.min(100, position(sessionTime))}%` }} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
