import { percentage } from '../lib/map';
import { useRoundtableStore } from '../state/store';

const RADIUS = 25;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function TalkTimeRings() {
  const people = useRoundtableStore((state) => state.people);
  const shares = useRoundtableStore((state) => state.talkShares);

  return (
    <section className="talk-rings card" aria-label="Talk time per person">
      <div className="card-heading plain-heading">
        <strong>Talk time</strong>
      </div>
      <div className="individual-rings" style={{ gridTemplateColumns: `repeat(${Math.max(1, people.length)}, 1fr)` }}>
        {people.map((person) => {
          const share = shares.find((item) => item.personId === person.id)?.share ?? 0;
          return (
            <div key={person.id} className="talk-person">
              <svg viewBox="0 0 64 64" role="img" aria-label={`${person.name} spoke ${percentage(share)}`}>
                <circle cx="32" cy="32" r={RADIUS} fill="none" stroke="#252c38" strokeWidth="5" />
                <circle
                  cx="32"
                  cy="32"
                  r={RADIUS}
                  fill="none"
                  stroke={person.color}
                  strokeWidth="5"
                  strokeLinecap="round"
                  strokeDasharray={`${share * CIRCUMFERENCE} ${CIRCUMFERENCE}`}
                  transform="rotate(-90 32 32)"
                  style={{ transition: 'stroke-dasharray 300ms ease' }}
                />
                <text x="32" y="36.5" textAnchor="middle">{percentage(share)}</text>
              </svg>
              <span>{person.name}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
