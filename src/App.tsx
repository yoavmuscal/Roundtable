import { useEffect } from 'react';
import { EnrollScreen } from './components/EnrollScreen';
import { LiveScreen } from './components/LiveScreen';
import { ReviewScreen } from './components/ReviewScreen';
import { SetupScreen } from './components/SetupScreen';
import { TopBar } from './components/TopBar';
import { roundtableClient } from './services/roundtableClient';
import { useRoundtableStore } from './state/store';

export default function App() {
  const phase = useRoundtableStore((state) => state.phase);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requestedPhase = params.get('screen');
    if (requestedPhase === 'setup' || requestedPhase === 'enroll' || requestedPhase === 'live' || requestedPhase === 'review') {
      useRoundtableStore.getState().setPhase(requestedPhase);
    }
    roundtableClient.connect();
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
      if (event.key.toLowerCase() === 'l') useRoundtableStore.getState().toggleLargeCaptions();
      if (event.key.toLowerCase() === 'h') useRoundtableStore.getState().toggleHistory();
      if (event.key.toLowerCase() === 'r') {
        useRoundtableStore.getState().resetSession();
        roundtableClient.control('start');
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      unsubscribeAutoplay();
      roundtableClient.disconnect();
    };
  }, []);

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
