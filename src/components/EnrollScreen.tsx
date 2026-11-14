import { useState } from 'react';
import { MAX_PEOPLE, MIN_PEOPLE, addPerson, removePerson } from '../lib/people';
import { ShapeGlyph } from '../lib/shape';
import { roundtableClient } from '../services/roundtableClient';
import { useRoundtableStore } from '../state/store';

export function EnrollScreen() {
  const people = useRoundtableStore((state) => state.people);
  const setPeopleNames = useRoundtableStore((state) => state.setPeopleNames);
  const enrollPrompt = useRoundtableStore((state) => state.enrollPrompt);
  const setPhase = useRoundtableStore((state) => state.setPhase);
  const [aliases, setAliases] = useState<Record<string, string>>({});

  const updateName = (personId: string, name: string) => {
    setPeopleNames(people.map((person) => (person.id === personId ? { ...person, name } : person)));
  };

  const withAliases = () =>
    people.map((person) => ({
      ...person,
      aliases: [person.name, ...(aliases[person.id]?.split(',').map((item) => item.trim()).filter(Boolean) ?? [])],
    }));

  const start = () => {
    const enrolled = withAliases();
    setPeopleNames(enrolled);
    roundtableClient.control('start', JSON.stringify(enrolled));
    setPhase('live');
  };

  return (
    <main className="enroll-screen screen-panel">
      <section className="setup-copy">
        <p className="eyebrow">Step 2 · Enroll speakers</p>
        <h1>Names power the alert a Deaf user should never miss.</h1>
        <p>
          Add each person's name and optional aliases. During enrollment, ask each person to say a
          short sentence so the final refine pass can match voices to seats.
        </p>
        {enrollPrompt ? (
          <div className="enroll-prompt" role="status">
            <span>
              {enrollPrompt.index + 1} of {enrollPrompt.total}
            </span>
            <strong>{enrollPrompt.prompt}</strong>
          </div>
        ) : null}
        <div className="button-row">
          <button
            type="button"
            onClick={() => setPeopleNames(addPerson(people))}
            disabled={people.length >= MAX_PEOPLE}
            title={people.length >= MAX_PEOPLE ? 'Roundtable tracks up to four people' : 'Add another speaker'}
          >
            + Add speaker
          </button>
          <span className="people-count">{people.length} of {MAX_PEOPLE} seats</span>
        </div>
        <div className="button-row">
          <button type="button" onClick={() => roundtableClient.control('enroll-redo', JSON.stringify(withAliases()))}>Redo sample</button>
          <button type="button" onClick={() => roundtableClient.control('enroll-skip', JSON.stringify(withAliases()))}>Skip</button>
          <button type="button" onClick={() => roundtableClient.control('enroll-next', JSON.stringify(withAliases()))}>Next speaker</button>
          <button type="button" className="primary" onClick={start}>Start live session</button>
        </div>
      </section>
      <section className="enroll-cards" aria-label="Speaker enrollment">
        {people.map((person, index) => (
          <article
            key={person.id}
            className={enrollPrompt?.personId === person.id ? 'enroll-card current' : 'enroll-card'}
            style={{ borderColor: person.color }}
            aria-current={enrollPrompt?.personId === person.id ? 'step' : undefined}
          >
            <div className="person-heading">
              <ShapeGlyph shape={person.shape} color={person.color} size={24} />
              <span>Speaker {index + 1}</span>
              <button
                type="button"
                className="remove-person"
                onClick={() => setPeopleNames(removePerson(people, person.id))}
                disabled={people.length <= MIN_PEOPLE}
                aria-label={`Remove ${person.name}`}
                title="Remove this speaker"
              >
                ×
              </button>
            </div>
            <label>
              Name
              <input value={person.name} onChange={(event) => updateName(person.id, event.target.value)} />
            </label>
            <label>
              Aliases <small>comma separated</small>
              <input
                value={aliases[person.id] ?? ''}
                onChange={(event) => setAliases((current) => ({ ...current, [person.id]: event.target.value }))}
                placeholder="e.g. Yoyo"
              />
            </label>
            <div className="voice-meter" aria-label={`Voice sample status for ${person.name}`}>
              <span style={{ width: `${enrollPrompt?.personId === person.id ? 70 : 100}%`, background: person.color }} />
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
