import { formatClock, percentage } from '../lib/map';
import { ShapeGlyph } from '../lib/shape';
import { useRoundtableStore } from '../state/store';

function polar(center: number, radius: number, fraction: number) {
  const angle = fraction * Math.PI * 2 - Math.PI / 2;
  return { x: center + radius * Math.cos(angle), y: center + radius * Math.sin(angle) };
}

function arcPath(center: number, radius: number, start: number, end: number) {
  const a = polar(center, radius, start);
  const b = polar(center, radius, end);
  return `M ${a.x} ${a.y} A ${radius} ${radius} 0 ${end - start > 0.5 ? 1 : 0} 1 ${b.x} ${b.y}`;
}

export function TalkTimeRings() {
  const people = useRoundtableStore((state) => state.people);
  const shares = useRoundtableStore((state) => state.talkShares);
  const total = shares.reduce((sum, item) => sum + item.seconds, 0);
  let cursor = 0;

  return (
    <section className="talk-rings card" aria-label="Talk time per person">
      <div className="card-heading">
        <strong>Talk time</strong>
        <span>{total ? formatClock(total) : '0:00'} total</span>
      </div>
      <div className="rings-content">
        <svg viewBox="0 0 126 126" className="donut" role="img" aria-label="Talk share chart">
          <circle cx="63" cy="63" r="48" fill="none" stroke="#2A303C" strokeWidth="15" />
          {shares.map((share) => {
            const person = people.find((item) => item.id === share.personId);
            const start = cursor;
            const end = cursor + share.share;
            cursor = end;
            return (
              <path
                key={share.personId}
                d={arcPath(63, 48, start, Math.max(start + 0.001, end - 0.004))}
                fill="none"
                stroke={person?.color ?? '#8B7CF6'}
                strokeWidth="15"
                strokeLinecap="round"
              />
            );
          })}
          <text x="63" y="59" textAnchor="middle" className="donut-total">
            {total ? formatClock(total) : '0:00'}
          </text>
          <text x="63" y="76" textAnchor="middle" className="donut-caption">
            speaking
          </text>
        </svg>
        <div className="share-list">
          {people.map((person) => {
            const share = shares.find((item) => item.personId === person.id);
            return (
              <div key={person.id}>
                <ShapeGlyph shape={person.shape} color={person.color} size={13} />
                <span>{person.name}</span>
                <strong>{share ? percentage(share.share) : '0%'}</strong>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
