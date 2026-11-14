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
  useRoundtableStore.getState().setPhase('review');
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

    let spaceAskActive = false;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        focusMeetingQuestion();
        return;
      }
      if (event.code === 'Space' && useRoundtableStore.getState().phase === 'live') {
        event.preventDefault();
        if (!spaceAskActive && !event.repeat) {
          spaceAskActive = true;
          roundtableClient.control('ask-begin');
        }
        return;
      }
      if (event.key.toLowerCase() === 'l') useRoundtableStore.getState().toggleLargeCaptions();
      if (event.key.toLowerCase() === 'h') useRoundtableStore.getState().toggleHistory();
      if (event.key.toLowerCase() === 'r' && useRoundtableStore.getState().status.backend !== 'live') {
        // R replays the recorded session. In live mode a session starts only from Enroll.
        useRoundtableStore.getState().resetSession();
        useRoundtableStore.getState().setPhase('live');
        roundtableClient.control('start');
      }
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code === 'Space' && spaceAskActive) {
        spaceAskActive = false;
        roundtableClient.control('ask-end');
      }
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
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
