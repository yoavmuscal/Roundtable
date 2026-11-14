import { FormEvent, useLayoutEffect, useState } from 'react';
import { AnswerCard } from './AnswerCard';
import { CaptionHistory } from './CaptionHistory';
import { LiveTranscript } from './LiveTranscript';
import { OnDeviceCard } from './OnDeviceCard';
import { QuestionsCard } from './QuestionsCard';
import { RoomMap } from './RoomMap';
import { SpeakerTimeline } from './SpeakerTimeline';
import { TalkTimeRings } from './TalkTimeRings';
import { VideoStage } from './VideoStage';
import { roundtableClient } from '../services/roundtableClient';
import { useRoundtableStore } from '../state/store';

function LiveAsk() {
  const askOpen = useRoundtableStore((state) => state.askOpen);
  const closeAsk = useRoundtableStore((state) => state.closeAsk);
  const [question, setQuestion] = useState('');
  if (!askOpen) return null;

  const ask = (event: FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text) return;
    roundtableClient.ask(text);
    setQuestion('');
  };

  return (
    <form className="live-ask" onSubmit={ask}>
      <label htmlFor="meeting-question">Ask about this meeting</label>
      <div>
        <input
          id="meeting-question"
          value={question}
          autoFocus
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="What was just decided?"
        />
        <button type="submit" className="primary">Ask</button>
        <button type="button" onClick={closeAsk} aria-label="Close ask">×</button>
      </div>
    </form>
  );
}

const CANVAS = { width: 1200, height: 680 };
const TOP_BAR = 64;

/** Scale the fixed 1200 x 680 live canvas so it fits any laptop or projector. */
function useLiveScale() {
  useLayoutEffect(() => {
    const root = document.documentElement;
    const update = () => {
      const byWidth = (window.innerWidth - 48) / CANVAS.width;
      const byHeight = (window.innerHeight - TOP_BAR - 32) / CANVAS.height;
      const scale = Math.max(0.5, Math.min(byWidth, byHeight, 1.4));
      root.style.setProperty('--live-scale', scale.toFixed(4));
    };
    update();
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('resize', update);
      root.style.removeProperty('--live-scale');
    };
  }, []);
}

export function LiveScreen() {
  useLiveScale();
  const status = useRoundtableStore((state) => state.status);
  const visionReady = useRoundtableStore((state) => state.visionReady);
  const loading = status.backend === 'live' && (status.transcriberState !== 'listening' || !visionReady);

  return (
    <main className="live-screen" aria-label="Live conversation view">
      {loading ? (
        <div className="model-loading" role="status">
          <div className="progress-ring" style={{ '--progress': status.transcriberState === 'listening' ? '70%' : '35%' } as React.CSSProperties}>
            <span>{status.transcriberState === 'listening' ? '70%' : '35%'}</span>
          </div>
          <strong>Loading models</strong>
          <p>
            {status.transcriberState === 'listening'
              ? 'Starting the camera and face tracking.'
              : 'Argmax is loading Whisper. Face tracking starts alongside it.'}
          </p>
        </div>
      ) : null}
      <div className="live-frame">
        <div className="live-canvas">
          <VideoStage />
          <LiveTranscript />
          <SpeakerTimeline />
          <RoomMap />
          <TalkTimeRings />
          <QuestionsCard />
          <OnDeviceCard />
        </div>
      </div>
      <CaptionHistory />
      <LiveAsk />
      <AnswerCard />
    </main>
  );
}
