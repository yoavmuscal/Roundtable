import { useEffect } from 'react';
import { EnrollScreen } from './components/EnrollScreen';
import { LiveScreen } from './components/LiveScreen';
import { ReviewScreen } from './components/ReviewScreen';
import { SetupScreen } from './components/SetupScreen';
import { TopBar } from './components/TopBar';
import {
  releaseScreenWakeLock,
  requestScreenWakeLock,
  startBackgroundCompatibility,
} from './services/background';
import { roundtableClient } from './services/roundtableClient';
import { useRoundtableStore } from './state/store';

function focusMeetingQuestion() {
  const state = useRoundtableStore.getState();
  if (state.phase !== 'review') state.openAsk();
  window.setTimeout(() => document.getElementById('meeting-question')?.focus(), 0);
}

export default function App() {
  const phase = useRoundtableStore((state) => state.phase);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedPhase = params.get('screen');
    if (requestedPhase === 'setup' || requestedPhase === 'enroll' || requestedPhase === 'live' || requestedPhase === 'review') {
      useRoundtableStore.getState().setPhase(requestedPhase);
      roundtableClient.pinnedPhase = requestedPhase;
    }
    roundtableClient.connect();
    const stopBackgroundCompatibility = startBackgroundCompatibility();
    let autoplaySent = params.get('autoplay') !== '1';
    const unsubscribeAutoplay = useRoundtableStore.subscribe((state) => {
      if (!autoplaySent && state.connected) {
        autoplaySent = true;
        if (requestedPhase === 'enroll' || requestedPhase === 'live' || requestedPhase === 'review') {
          useRoundtableStore.getState().setPhase(requestedPhase);
        }
        roundtableClient.control('start');
      }
    });

    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        focusMeetingQuestion();
        return;
      }
      if (event.key.toLowerCase() === 'l') useRoundtableStore.getState().toggleLargeCaptions();
      if (event.key.toLowerCase() === 'h') useRoundtableStore.getState().toggleHistory();
      if (event.key.toLowerCase() === 'r' && !event.metaKey && !event.ctrlKey && !event.altKey) {
        const backend = useRoundtableStore.getState().status.backend;
        if (backend === 'live') {
          useRoundtableStore.getState().resetSession();
          useRoundtableStore.getState().setPhase('review');
          roundtableClient.control('demo-replay');
        } else {
          // Sim/replay: play the recorded session on the live canvas.
          useRoundtableStore.getState().resetSession();
          useRoundtableStore.getState().setPhase('live');
          roundtableClient.control('start');
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      unsubscribeAutoplay();
      stopBackgroundCompatibility();
      roundtableClient.disconnect();
    };
  }, []);

  useEffect(() => {
    if (phase === 'live') {
      void requestScreenWakeLock();
    } else {
      void releaseScreenWakeLock();
    }
  }, [phase]);

  return (
    <div className="app-shell">
      <TopBar />
      {phase === 'setup' ? <SetupScreen /> : null}
      {phase === 'enroll' ? <EnrollScreen /> : null}
      {phase === 'live' ? <LiveScreen /> : null}
      {phase === 'review' ? <ReviewScreen /> : null}
    </div>
  );
}
