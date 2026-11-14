import { useMemo } from 'react';
import type { Caption, Person } from '../contract';
import { layoutBubbles } from '../lib/bubbles';
import { clamp } from '../lib/geometry';
import { ShapeGlyph } from '../lib/shape';
import { useRoundtableStore } from '../state/store';

const STAGE = { width: 752, height: 424 };

function PersonSilhouette({ personId, people }: { personId: string; people: Person[] }) {
  const frame = useRoundtableStore((state) => state.frames.find((item) => item.id === personId));
  const activeSpeakerId = useRoundtableStore((state) => state.activeSpeakerId);
  const level = useRoundtableStore((state) => state.level);
  if (!frame) return null;
  const person = people.find((item) => item.id === personId);
  const color = person?.color ?? '#8B7CF6';
  const left = frame.faceBox.x * STAGE.width;
  const top = frame.faceBox.y * STAGE.height;
  const width = frame.faceBox.width * STAGE.width;
  const height = frame.faceBox.height * STAGE.height;
  const active = activeSpeakerId === personId;
  const torsoTop = top + height * 1.05;
  const torsoHeight = frame.anchor.mode === 'head' ? 40 : 92;
  const away = frame.state === 'away';

  return (
    <div className={away ? 'person-layer away' : 'person-layer'}>
      <div
        className={active ? 'torso active' : 'torso'}
        style={{
          left: left - width * 0.35,
          top: torsoTop,
          width: width * 1.7,
          height: torsoHeight,
          borderColor: color,
          background: `linear-gradient(180deg, ${color}42, ${color}16)`,
          boxShadow: active ? `0 0 ${18 + level * 40}px ${color}66` : undefined,
        }}
      />
      <div
        className={active ? 'face-box active' : 'face-box'}
        style={{ left, top, width, height, borderColor: color, boxShadow: active ? `0 0 ${16 + level * 42}px ${color}88` : undefined }}
      >
        <span className="eye" />
        <span className="eye right" />
        <span className="mouth" style={{ transform: `scaleY(${0.35 + clamp(frame.mouth, 0, 1)})` }} />
      </div>
      <div className="name-tag" style={{ left: left + width / 2, top: top + height + 8, borderColor: color }}>
        <ShapeGlyph shape={person?.shape ?? 'circle'} color={color} size={13} />
        {person?.name ?? personId}
        {frame.state === 'standing' ? <em>standing</em> : null}
      </div>
    </div>
  );
}

export function VideoStage() {
  const people = useRoundtableStore((state) => state.people);
  const frames = useRoundtableStore((state) => state.frames);
  const captions = useRoundtableStore((state) => state.captions);
  const latestByPerson = useRoundtableStore((state) => state.latestByPerson);
  const sessionTime = useRoundtableStore((state) => state.sessionTime);
  const largeCaptions = useRoundtableStore((state) => state.largeCaptions);
  const stageAlert = useRoundtableStore((state) => state.stageAlert);
  const level = useRoundtableStore((state) => state.level);
  const activeSpeakerId = useRoundtableStore((state) => state.activeSpeakerId);

  const latestCaptions = useMemo(() => {
    const byPerson = new Map<string, Caption>();
    Object.entries(latestByPerson).forEach(([personId, captionId]) => {
      const caption = captions[captionId];
      if (caption && sessionTime - (caption.end ?? caption.start) <= 3.5) byPerson.set(personId, caption);
    });
    return byPerson;
  }, [captions, latestByPerson, sessionTime]);

  const bubbles = useMemo(
    () => layoutBubbles(frames, latestCaptions, STAGE, largeCaptions),
    [frames, latestCaptions, largeCaptions],
  );
  const offCameraSpeaking = level > 0.12 && !activeSpeakerId;

  return (
    <section
      className={stageAlert ? 'video-stage name-alert' : 'video-stage'}
      aria-label="Camera view with speaker-pinned captions"
    >
      <div className="dot-grid" aria-hidden="true" />
      {frames.length === 0 ? (
        <div className="stage-placeholder">
          <strong>Ready for the room</strong>
          <span>Start the replay or a live session to pin captions to speakers.</span>
        </div>
      ) : null}
      {people.map((person) => (
        <PersonSilhouette key={person.id} personId={person.id} people={people} />
      ))}
      {bubbles.map((bubble) => {
        const person = people.find((item) => item.id === bubble.personId);
        return (
          <article
            key={`${bubble.personId}-${bubble.turnId}`}
            className={[
              'speech-bubble',
              bubble.confidence < 0.5 ? 'low-confidence' : '',
              bubble.nameAlert ? 'mentioned' : '',
              largeCaptions ? 'large' : '',
            ].join(' ')}
            style={{
              left: bubble.x,
              top: bubble.y,
              width: bubble.width,
              minHeight: bubble.height,
              opacity: bubble.opacity,
              borderColor: person?.color,
            }}
          >
            <span>{bubble.text}</span>
            <i className={`tail ${bubble.tail}`} style={{ borderColor: person?.color }} aria-hidden="true" />
          </article>
        );
      })}
      {offCameraSpeaking ? (
        <div className="off-camera-cue" role="status">
          <span aria-hidden="true">●</span> Someone is speaking off-camera
        </div>
      ) : null}
      {stageAlert ? <div className="alert-frame" role="status">Your name was mentioned</div> : null}
    </section>
  );
}
