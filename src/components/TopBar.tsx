import { formatClock } from '../lib/map';
import { roundtableClient } from '../services/roundtableClient';
import { useRoundtableStore } from '../state/store';

const phaseLabels = {
  setup: 'Setup',
  enroll: 'Enroll',
  live: 'Live',
  review: 'Review',
} as const;

export function TopBar() {
  const phase = useRoundtableStore((state) => state.phase);
  const connected = useRoundtableStore((state) => state.connected);
  const connectionMessage = useRoundtableStore((state) => state.connectionMessage);
  const sessionTime = useRoundtableStore((state) => state.sessionTime);
  const largeCaptions = useRoundtableStore((state) => state.largeCaptions);
  const historyOpen = useRoundtableStore((state) => state.historyOpen);
  const setPhase = useRoundtableStore((state) => state.setPhase);
  const toggleLargeCaptions = useRoundtableStore((state) => state.toggleLargeCaptions);
  const toggleHistory = useRoundtableStore((state) => state.toggleHistory);

  return (
    <header className="top-bar">
      <div className="brand" aria-label="Roundtable">
        <span className="brand-mark">RT</span>
        <div>
          <strong>Roundtable</strong>
          <small>Live, offline, for everyone</small>
        </div>
      </div>

      <nav className="phase-nav" aria-label="Screens">
        {(Object.keys(phaseLabels) as Array<keyof typeof phaseLabels>).map((item) => (
          <button
            key={item}
            type="button"
            className={item === phase ? 'active' : ''}
            onClick={() => setPhase(item)}
          >
            {phaseLabels[item]}
          </button>
        ))}
      </nav>

      <div className="top-actions">
        <span className={connected ? 'connection connected' : 'connection'}>
          <span aria-hidden="true" /> {connectionMessage}
        </span>
        <span className="session-clock" aria-label="Session time">
          {formatClock(sessionTime)}
        </span>
        <button type="button" onClick={toggleHistory} aria-pressed={historyOpen} title="Caption history (H)">
          History <kbd>H</kbd>
        </button>
        <button type="button" onClick={toggleLargeCaptions} aria-pressed={largeCaptions} title="Large captions (L)">
          Large <kbd>L</kbd>
        </button>
        <button
          type="button"
          className="primary"
          onClick={() => {
            useRoundtableStore.getState().resetSession();
            roundtableClient.control('start');
          }}
          title="Replay recorded session (R)"
        >
          Replay <kbd>R</kbd>
        </button>
      </div>
    </header>
  );
}
