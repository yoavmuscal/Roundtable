import { useEffect, useMemo, useRef, useState } from 'react';
import type { Caption, Person, PersonFrame } from '../contract';
import { layoutBubbles } from '../lib/bubbles';
import { CaptionText } from '../lib/nameText';
import { ShapeGlyph } from '../lib/shape';
import { roundtableClient } from '../services/roundtableClient';
import { useRoundtableStore } from '../state/store';
import { MediaPipeBrowserVision } from '../vision/MediaPipeVision';
import { sendVisionObservations } from '../vision/visionBridge';

const STAGE = { width: 752, height: 424 };

function PersonSilhouette({
  frame,
  person,
  minimal,
}: {
  frame: PersonFrame;
  person?: Person;
  minimal: boolean;
}) {
  const activeSpeakerId = useRoundtableStore((state) => state.activeSpeakerId);
  const level = useRoundtableStore((state) => state.level);
  const color = person?.color ?? '#8B7CF6';
  const left = frame.faceBox.x * STAGE.width;
  const top = frame.faceBox.y * STAGE.height;
  const width = frame.faceBox.width * STAGE.width;
  const height = frame.faceBox.height * STAGE.height;
  const centerX = left + width / 2;
  const active = activeSpeakerId === frame.id;
  const away = frame.state === 'away';
  const bodyWidth = width * 1.68;
  const bodyTop = top + height * 1.1;

  return (
    <div className={away ? 'person-layer away' : 'person-layer'}>
      <div className="person-label" style={{ left: centerX, top: top - 34, color }}>
        <ShapeGlyph shape={person?.shape ?? 'circle'} color={color} size={13} />
        <span>{person?.name ?? frame.id}</span>
      </div>
      <div
        className={active ? 'face-bracket active' : 'face-bracket'}
        style={{ left: left - 7, top: top - 8, width: width + 14, height: height + 15, color }}
      >
        <i /><i /><i /><i />
      </div>
      {!minimal ? (
        <>
          <div
            className={active ? 'head-circle active' : 'head-circle'}
            style={{
              left,
              top,
              width,
              height,
              boxShadow: active ? `0 0 ${18 + level * 30}px ${color}55` : undefined,
            }}
          />
          <div
            className={active ? 'body-shape active' : 'body-shape'}
            style={{
              left: centerX - bodyWidth / 2,
              top: bodyTop,
              width: bodyWidth,
              height: Math.min(112, STAGE.height - bodyTop - 64),
              borderColor: `${color}66`,
            }}
          />
        </>
      ) : null}
      <div
        className="chest-bracket"
        style={{ left: left - 4, top: bodyTop + 2, width: width + 8, height: 34, color }}
      >
        <i /><i /><i /><i />
      </div>
      {frame.state === 'standing' ? <em className="standing-pill" style={{ left: centerX, top: bodyTop - 26 }}>standing</em> : null}
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
  const level = useRoundtableStore((state) => state.level);
  const activeSpeakerId = useRoundtableStore((state) => state.activeSpeakerId);
  const replay = useRoundtableStore((state) => state.replay);
  const status = useRoundtableStore((state) => state.status);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [cameraActive, setCameraActive] = useState(false);
  const [cameraError, setCameraError] = useState<string>();

  const replayVideoUrl = replay?.videoUrl;
  const cameraRequested =
    !replay &&
    (new URLSearchParams(window.location.search).get('camera') === '1' || status.backend === 'live');

  // Live mode: the browser owns the camera and runs MediaPipe face/pose tracking
  // fully offline (local WASM + models), then streams observations to the backend.
  useEffect(() => {
    const video = videoRef.current;
    if (!cameraRequested || replayVideoUrl || !video) return;
    let cancelled = false;
    const vision = new MediaPipeBrowserVision({
      onObservations: (observations, atSeconds) => {
        sendVisionObservations(observations, atSeconds, (message) => roundtableClient.send(message));
      },
      onError: (error) => {
        if (!cancelled) setCameraError(error.message);
      },
    });
    vision
      .start(video)
      .then(() => {
        if (!cancelled) setCameraActive(true);
      })
      .catch((error: unknown) => {
        if (!cancelled) setCameraError(error instanceof Error ? error.message : 'Camera unavailable');
      });
    return () => {
      cancelled = true;
      vision.stop();
      setCameraActive(false);
    };
  }, [cameraRequested, replayVideoUrl]);

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
  const mediaActive = Boolean(replayVideoUrl || cameraActive);

  return (
    <section
      className={mediaActive ? 'video-stage media-present' : 'video-stage'}
      aria-label="Camera view with speaker-pinned captions"
    >
      {replayVideoUrl ? <img className="camera-feed" src={replayVideoUrl} alt="Recorded session video" /> : null}
      {cameraRequested && !replayVideoUrl ? (
        <video
          ref={videoRef}
          className="camera-feed"
          style={{ opacity: cameraActive ? 1 : 0 }}
          autoPlay
          muted
          playsInline
        />
      ) : null}
      <div className="dot-grid" aria-hidden="true" />
      <div className="stage-horizon" aria-hidden="true" />
      <div className="table-plane" aria-hidden="true" />
      <div className="stage-pill"><span /> {cameraActive ? 'LIVE · iPhone cam' : 'LIVE · cam 1'}</div>
      <div className="stage-note">Captions pinned to chest</div>
      {frames.length === 0 && !mediaActive ? (
        <div className="stage-placeholder">
          <strong>Ready for the room</strong>
          <span>Start the replay or a live session to pin captions to speakers.</span>
        </div>
      ) : null}
      {cameraError ? <div className="camera-error">{cameraError}; using tracker overlays only.</div> : null}
      {frames.map((frame) => (
        <PersonSilhouette
          key={frame.id}
          frame={frame}
          person={people.find((item) => item.id === frame.id)}
          minimal={mediaActive}
        />
      ))}
      {bubbles.map((bubble) => {
        const person = people.find((item) => item.id === bubble.personId);
        const isQuestion = bubble.text.includes('?');
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
              height: bubble.height,
              opacity: bubble.opacity,
              borderColor: person?.color,
            }}
          >
            <span><CaptionText text={bubble.text} people={people} /></span>
            {isQuestion ? <b className="question-badge">?</b> : null}
            <i className={`tail ${bubble.tail}`} style={{ borderColor: person?.color }} aria-hidden="true" />
          </article>
        );
      })}
      {offCameraSpeaking ? (
        <div className="off-camera-cue" role="status">
          <span aria-hidden="true">●</span> Someone is speaking off-camera
        </div>
      ) : null}
    </section>
  );
}
