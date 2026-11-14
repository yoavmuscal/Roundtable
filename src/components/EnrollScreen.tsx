import { useEffect, useRef, useState } from 'react';
import { promptSentences, sentenceHeard, sentencesHeard } from '../lib/enrollment';
import { MAX_PEOPLE, MIN_PEOPLE, addPerson, removePerson } from '../lib/people';
import { ShapeGlyph } from '../lib/shape';
import { roundtableClient } from '../services/roundtableClient';
import { useRoundtableStore } from '../state/store';

export function EnrollScreen() {
  const people = useRoundtableStore((state) => state.people);
  const setPeopleNames = useRoundtableStore((state) => state.setPeopleNames);
  const enrollPrompt = useRoundtableStore((state) => state.enrollPrompt);
  const level = useRoundtableStore((state) => state.level);
  const status = useRoundtableStore((state) => state.status);
  const sessionTime = useRoundtableStore((state) => state.sessionTime);
  const listening = status.transcriberState === 'listening';
  const live = status.backend === 'live';
  // Seconds of voice heard for each person during their prompt (from live mic levels).
  const [voiced, setVoiced] = useState<Record<string, number>>({});
  const [promptStartedAt, setPromptStartedAt] = useState(0);
  const lastLevelAt = useRef<number | undefined>(undefined);
  const currentId = enrollPrompt?.personId;
  const [recording, setRecording] = useState(false);
  useEffect(() => {
    setRecording(false);
    setPromptStartedAt(useRoundtableStore.getState().sessionTime);
    lastLevelAt.current = undefined;
  }, [currentId]);
  useEffect(() => {
    if (!currentId || !recording) return;
    const previous = lastLevelAt.current;
    lastLevelAt.current = sessionTime;
    if (previous === undefined || level < 0.02) return;
    const step = Math.min(0.2, Math.max(0, sessionTime - previous));
    setVoiced((current) => ({ ...current, [currentId]: (current[currentId] ?? 0) + step }));
  }, [level, sessionTime, currentId, recording]);
  const heard = useRoundtableStore((state) => {
    if (!recording) return '';
    const lines = Object.values(state.captions)
      .filter((caption) => caption.start >= promptStartedAt - 0.2)
      .sort((a, b) => (a.end ?? a.start) - (b.end ?? b.start))
      .map((caption) => caption.text);
    return lines.join(' ');
  });
  const sentences = enrollPrompt ? promptSentences(enrollPrompt.prompt) : [];
  const spokeEnough = Boolean(currentId && (voiced[currentId] ?? 0) >= 1.2);
  const heardFlags = enrollPrompt && recording && spokeEnough ? sentencesHeard(enrollPrompt.prompt, heard) : sentences.map(() => false);
  const currentHeard = Boolean(recording && spokeEnough && enrollPrompt && currentId && sentenceHeard(enrollPrompt.prompt, heard));
  // People whose enrollment sentences Argmax recognised (kept after moving to the next person).
  const [heardOk, setHeardOk] = useState<Record<string, boolean>>({});
  useEffect(() => {
    if (currentHeard && currentId) setHeardOk((current) => (current[currentId] ? current : { ...current, [currentId]: true }));
  }, [currentHeard, currentId]);
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

  const beginRecording = () => {
    if (!currentId) return;
    useRoundtableStore.setState({ captions: {}, latestByPerson: {}, history: [] });
    setHeardOk((current) => ({ ...current, [currentId]: false }));
    setVoiced((current) => ({ ...current, [currentId]: 0 }));
    setPromptStartedAt(useRoundtableStore.getState().sessionTime);
    setRecording(true);
    roundtableClient.control('enroll-arm', JSON.stringify(withAliases()));
  };

  const start = () => {
    const enrolled = withAliases();
    setPeopleNames(enrolled);
    // Enrollment speech is not part of the meeting.
    useRoundtableStore.setState({
      captions: {},
      latestByPerson: {},
      history: [],
      talkShares: [],
      openQuestions: [],
      overdueQuestions: [],
      mapHexes: [],
      answer: undefined,
      refined: undefined,
      visionReady: false,
    });
    roundtableClient.control('start', JSON.stringify(enrolled));
    setPhase('live');
  };

  return (
    <main className="enroll-screen screen-panel">
      <section className="setup-copy">
        <p className="eyebrow">Step 2 · Enroll speakers</p>
        <h1>Names power the alert a Deaf user should never miss.</h1>
        <p>
          Add each person's name and optional aliases. Each person reads two sentences
          (about five seconds) so the final refine pass can match voices to seats.
        </p>
        {enrollPrompt ? (
          <div className={currentHeard ? 'enroll-prompt heard' : 'enroll-prompt'} role="status">
            <span>
              {enrollPrompt.index + 1} of {enrollPrompt.total}
            </span>
            <strong>{recording ? 'Read both sentences out loud.' : 'Press Begin recording, then read both sentences.'}</strong>
            <ul className="sentence-checks">
              {sentences.map((sentence, index) => (
                <li key={sentence} className={heardFlags[index] ? 'ok' : undefined}>
                  <span aria-hidden="true">{heardFlags[index] ? '✓' : index + 1}</span>
                  {sentence}
                </li>
              ))}
            </ul>
            <em className="enroll-heard">
              {!live
                ? 'Replay mode: voice enrollment runs only in live mode.'
                : !recording
                  ? 'Not recording yet.'
                  : !listening
                    ? 'Argmax is loading Whisper (about 20 s)…'
                    : heard
                      ? `Heard: “${heard}”`
                      : 'Recording… speak now.'}
            </em>
            {live && currentId && currentHeard ? (
              <div className="sentence-heard" role="status">
                <span aria-hidden="true">✓</span>
                <div>
                  <strong>Both sentences heard</strong>
                  <small>Argmax recognised them. Press Next speaker.</small>
                </div>
              </div>
            ) : null}
            {status.voiceWarning ? (
              <div className="voice-warning" role="alert">{status.voiceWarning}</div>
            ) : null}
            {live && currentId && recording ? (
              <em className="enroll-captured">
                Voice captured: {(voiced[currentId] ?? 0).toFixed(1)} s {(voiced[currentId] ?? 0) >= 5 ? '✓ enough, press Next speaker' : '(aim for 5 s)'}
              </em>
            ) : null}
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
          <button type="button" className="primary" onClick={beginRecording} disabled={!enrollPrompt || recording}>
            {recording ? 'Recording…' : 'Begin recording'}
          </button>
          <button type="button" onClick={() => { setRecording(false); roundtableClient.control('enroll-redo', JSON.stringify(withAliases())); }}>Redo sample</button>
          <button type="button" onClick={() => roundtableClient.control('enroll-skip', JSON.stringify(withAliases()))}>Skip</button>
          <button
            type="button"
            className={live && currentId && heardOk[currentId] ? 'primary' : undefined}
            onClick={() => roundtableClient.control('enroll-next', JSON.stringify(withAliases()))}
          >
            Next speaker
          </button>
          <button
            type="button"
            className="primary"
            onClick={start}
            disabled={live && !listening}
            title={live && !listening ? 'Waiting for Argmax to finish loading Whisper' : undefined}
          >
            {live && !listening ? 'Waiting for Argmax…' : 'Start live session'}
          </button>
        </div>
      </section>
      <section className="enroll-cards" aria-label="Speaker enrollment">
        {people.map((person, index) => (
          <article
            key={person.id}
            className={[
              'enroll-card',
              enrollPrompt?.personId === person.id ? 'current' : '',
              heardOk[person.id] ? 'heard' : '',
            ].filter(Boolean).join(' ')}
            style={{ borderColor: person.color }}
            aria-current={enrollPrompt?.personId === person.id ? 'step' : undefined}
          >
            <div className="person-heading">
              <ShapeGlyph shape={person.shape} color={person.color} size={24} />
              <span>Speaker {index + 1}</span>
              {heardOk[person.id] ? <em className="heard-stamp">✓ Heard</em> : null}
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
            {live ? (
              <p className={heardOk[person.id] ? 'voice-done' : 'voice-pending'}>
                {heardOk[person.id]
                  ? '✓ Both sentences heard'
                  : enrollPrompt?.personId === person.id
                    ? 'Listening for both sentences…'
                    : 'Not enrolled yet'}
              </p>
            ) : null}
            <div className="voice-meter" aria-label={`Live microphone level for ${person.name}`}>
              <span
                style={{
                  width: `${enrollPrompt?.personId === person.id ? Math.min(100, Math.round(level * 900)) : 0}%`,
                  background: person.color,
                }}
              />
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
