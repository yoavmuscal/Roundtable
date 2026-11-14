import { percentage } from '../lib/map';
import { useRoundtableStore } from '../state/store';

const RADIUS = 27;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function TalkTimeRings() {
  const people = useRoundtableStore((state) => state.people);
  const shares = useRoundtableStore((state) => state.talkShares);

  return (
    <section className="talk-rings card" aria-label="Talk time per person">
      <div className="card-heading plain-heading">
        <strong>Talk time</strong>
      </div>
      <div className="individual-rings">
        {people.map((person) => {
          const share = shares.find((item) => item.personId === person.id)?.share ?? 0;
          return (
            <div key={person.id} className="talk-person">
              <svg viewBox="0 0 72 72" role="img" aria-label={`${person.name} spoke ${percentage(share)}`}>
                <circle cx="36" cy="36" r={RADIUS} fill="none" stroke="#252C38" strokeWidth="8" />
                <circle
                  cx="36"
                  cy="36"
                  r={RADIUS}
                  fill="none"
                  stroke={person.color}
                  strokeWidth="8"
                  strokeLinecap="round"
                  strokeDasharray={`${share * CIRCUMFERENCE} ${CIRCUMFERENCE}`}
                  transform="rotate(-90 36 36)"
                />
                <text x="36" y="40" textAnchor="middle">{percentage(share)}</text>
              </svg>
              <span>{person.name}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
