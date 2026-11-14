import { useEffect, useMemo, useRef, useState } from 'react';
import type { Caption, Person, PersonFrame } from '../contract';
import { layoutBubbles } from '../lib/bubbles';
import { CaptionText } from '../lib/nameText';
import { ShapeGlyph } from '../lib/shape';
import { roundtableClient } from '../services/roundtableClient';
import { useRoundtableStore } from '../state/store';
import { MediaPipeBrowserVision, listCameras } from '../vision/MediaPipeVision';
import { describeCameraError } from '../lib/cameraErrors';
import { sendVisionObservations } from '../vision/visionBridge';

const STAGE = { width: 752, height: 424 };
const CAMERA_KEY = 'roundtable.cameraId';

function savedCameraId(): string {
  try {
    return globalThis.localStorage?.getItem(CAMERA_KEY) ?? '';
  } catch {
    return '';
  }
}
/** Top edge of the drawn table plane; silhouette bodies end here. */
const TABLE_TOP = STAGE.height - 88;

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
  const faceWidth = frame.faceBox.width * STAGE.width;
  const faceHeight = frame.faceBox.height * STAGE.height;
  const centerX = (frame.faceBox.x + frame.faceBox.width / 2) * STAGE.width;
  const centerY = (frame.faceBox.y + frame.faceBox.height / 2) * STAGE.height;
  const active = activeSpeakerId === frame.id;
  const away = frame.state === 'away';

  // Silhouette geometry is derived from the face box so it tracks the person.
  const head = minimal ? Math.max(faceWidth, faceHeight) : Math.max(faceWidth, faceHeight) * 1.3;
  const headTop = centerY - head / 2;
  const bracketWidth = head + 40;
  const bracketHeight = head + 36;
  const bodyWidth = head * 1.6;
  const bodyTop = centerY + head / 2 - 8;
  const bodyHeight = Math.max(48, TABLE_TOP - bodyTop + 4);
  const glowSize = head * 2.2 + level * 60;

  return (
    <div className={away ? 'person-layer away' : 'person-layer'}>
      <div className="person-label" style={{ left: centerX, top: headTop - 48, color }}>
        <ShapeGlyph shape={person?.shape ?? 'circle'} color={color} size={13} />
        <span>{person?.name ?? frame.id}</span>
      </div>
      {!minimal ? (
        <>
          <div
            className={active ? 'head-glow active' : 'head-glow'}
            style={{ left: centerX - glowSize / 2, top: centerY - glowSize / 2, width: glowSize, height: glowSize, color }}
          />
          <div
            className="body-shape"
            style={{ left: centerX - bodyWidth / 2, top: bodyTop, width: bodyWidth, height: bodyHeight }}
          />
          <div className="head-circle" style={{ left: centerX - head / 2, top: headTop, width: head, height: head }} />
        </>
      ) : null}
      <div
        className={active ? 'face-bracket active' : 'face-bracket'}
        style={{ left: centerX - bracketWidth / 2, top: centerY - bracketHeight / 2, width: bracketWidth, height: bracketHeight, color }}
      >
        <i /><i /><i /><i />
      </div>
      {frame.state === 'standing' ? (
        <em className="standing-pill" style={{ left: centerX, top: bodyTop + 10 }}>standing</em>
      ) : null}
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
  const connected = useRoundtableStore((state) => state.connected);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [cameraActive, setCameraActive] = useState(false);
  const [cameraError, setCameraError] = useState<string>();
  const [cameraId, setCameraId] = useState<string>(savedCameraId);
  const [cameras, setCameras] = useState<MediaDeviceInfo[]>([]);
  const [attempt, setAttempt] = useState(0);

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
    setCameraError(undefined);
    const vision = new MediaPipeBrowserVision({
      deviceId: cameraId || undefined,
      onObservations: (observations, atSeconds) => {
        sendVisionObservations(observations, atSeconds, (message) => roundtableClient.send(message));
      },
      onError: (error) => {
        if (!cancelled) setCameraError(describeCameraError(error));
      },
    });
    vision
      .start(video)
      .then(async () => {
        if (cancelled) return;
        setCameraActive(true);
        setCameras(await listCameras());
      })
      .catch(async (error: unknown) => {
        if (cancelled) return;
        setCameraError(describeCameraError(error));
        setCameras(await listCameras().catch(() => []));
      });
    return () => {
      cancelled = true;
      vision.stop();
      if (video.srcObject instanceof MediaStream) video.srcObject.getTracks().forEach((track) => track.stop());
      video.srcObject = null;
      setCameraActive(false);
    };
  }, [cameraRequested, replayVideoUrl, cameraId, attempt]);

  const chooseCamera = (id: string) => {
    try {
      globalThis.localStorage?.setItem(CAMERA_KEY, id);
    } catch {
      // Private windows may block storage; the choice still applies for this session.
    }
    setCameraId(id);
  };

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
  // Words with no matched speaker (no face moving, or camera off) still need to be readable.
  const unattributed = useMemo(() => {
    const latest = Object.values(captions)
      .filter((caption) => !caption.personId || !frames.some((frame) => frame.id === caption.personId))
      .sort((a, b) => (b.end ?? b.start) - (a.end ?? a.start))[0];
    if (!latest || sessionTime - (latest.end ?? latest.start) > 3.5) return undefined;
    return latest;
  }, [captions, frames, sessionTime]);
  const offCameraSpeaking = level > 0.12 && !activeSpeakerId;
  const mediaActive = Boolean(replayVideoUrl || cameraActive);
  const stageClass = ['video-stage', mediaActive ? 'media-present' : ''].join(' ').trim();

  return (
    <section className={stageClass} aria-label="Camera view with speaker-pinned captions">
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
      <div className="stage-pill"><span /> {replay ? 'REPLAY' : status.backend === 'live' ? `LIVE · Argmax ${status.transcriberState === 'listening' ? 'listening' : 'loading…'}` : 'LIVE · cam 1'}</div>
      {status.backend === 'live' && status.transcriberState !== 'listening' && frames.length > 0 ? (
        <div className="argmax-loading" role="status">Argmax is loading Whisper (about 20 s). Start talking when the badge says listening.</div>
      ) : null}
      <div className="stage-note">Captions pinned to chest</div>
      {frames.length === 0 && !mediaActive ? (
        <div className="stage-placeholder">
          <strong>Ready for the room</strong>
          <span>
            {connected
              ? status.backend === 'live'
                ? 'Calibrate and enroll first, or start now with the default speakers.'
                : 'Start the replay or a live session to pin captions to speakers.'
              : 'Waiting for the local backend on :8000…'}
          </span>
          <button
            type="button"
            className="primary"
            disabled={!connected || (status.backend === 'live' && status.transcriberState !== 'listening')}
            onClick={() => {
              useRoundtableStore.getState().resetSession();
              useRoundtableStore.getState().setPhase('live');
              roundtableClient.control('start');
            }}
          >
            {status.backend === 'live' ? 'Start live session' : 'Start replay'} <kbd>R</kbd>
          </button>
        </div>
      ) : null}
      {cameraRequested && !replayVideoUrl ? (
        <label className="camera-picker">
          <span>Camera</span>
          <select value={cameraId} onChange={(event) => chooseCamera(event.target.value)} aria-label="Choose camera">
            <option value="">Auto (iPhone if connected)</option>
            {cameras.map((camera, index) => (
              <option key={camera.deviceId || index} value={camera.deviceId}>
                {camera.label || `Camera ${index + 1}`}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {cameraError ? (
        <div className="camera-error" role="alert">
          <span>{cameraError}</span>
          <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry</button>
        </div>
      ) : null}
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
      {unattributed ? (
        <div className={largeCaptions ? 'stage-subtitle large' : 'stage-subtitle'} role="status" aria-live="polite">
          <CaptionText text={unattributed.text.length > 110 ? `…${unattributed.text.slice(-109)}` : unattributed.text} people={people} />
        </div>
      ) : null}
      {offCameraSpeaking ? (
        <div className="off-camera-cue" role="status">
          <span aria-hidden="true">●</span> Someone is speaking off-camera
        </div>
      ) : null}
    </section>
  );
}
