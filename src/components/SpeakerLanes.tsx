import { ShapeGlyph } from '../lib/shape';
import { useRoundtableStore } from '../state/store';

export function SpeakerLanes() {
  const people = useRoundtableStore((state) => state.people);
  const captions = useRoundtableStore((state) => state.captions);
  const latestByPerson = useRoundtableStore((state) => state.latestByPerson);
  const talkShares = useRoundtableStore((state) => state.talkShares);
  const activeSpeakerId = useRoundtableStore((state) => state.activeSpeakerId);

  return (
    <section className="speaker-lanes" aria-label="Speaker lanes">
      {people.map((person) => {
        const caption = captions[latestByPerson[person.id] ?? ''];
        const share = talkShares.find((item) => item.personId === person.id);
        return (
          <article key={person.id} className={activeSpeakerId === person.id ? 'lane active' : 'lane'}>
            <div className="lane-heading">
              <ShapeGlyph shape={person.shape} color={person.color} />
              <strong>{person.name}</strong>
              <span>{share ? `${Math.round(share.share * 100)}%` : '0%'}</span>
            </div>
            <p>{caption?.text ?? 'Waiting for speech…'}</p>
          </article>
        );
      })}
    </section>
  );
}
