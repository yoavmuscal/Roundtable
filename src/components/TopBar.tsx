import { formatClock } from '../lib/map';
import { roundtableClient } from '../services/roundtableClient';
import { useRoundtableStore } from '../state/store';

function focusMeetingQuestion() {
  useRoundtableStore.getState().setPhase('review');
  window.setTimeout(() => document.getElementById('meeting-question')?.focus(), 0);
}

const SESSION_DATE = new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });

export function TopBar() {
  const phase = useRoundtableStore((state) => state.phase);
  const connected = useRoundtableStore((state) => state.connected);
  const backgrounded = useRoundtableStore((state) => state.backgrounded);
  const sessionTime = useRoundtableStore((state) => state.sessionTime);
  const largeCaptions = useRoundtableStore((state) => state.largeCaptions);
  const historyOpen = useRoundtableStore((state) => state.historyOpen);
  const replay = useRoundtableStore((state) => state.replay);
  const toggleLargeCaptions = useRoundtableStore((state) => state.toggleLargeCaptions);
  const toggleHistory = useRoundtableStore((state) => state.toggleHistory);

  return (
    <header className="top-bar">
      <div className="brand" aria-label="Roundtable">
        <strong>Roundtable</strong>
        <small>{replay ? `Replay · ${replay.session}` : `Team sync · ${SESSION_DATE}`}</small>
      </div>

      <div className="top-actions">
        <button type="button" className="ask-pill" onClick={focusMeetingQuestion} title="Ask about the meeting (⌘K)">
          <span className="ask-dot" aria-hidden="true" />
          <span>Hold space to ask · ⌘K</span>
        </button>
        <div className="utility-buttons" aria-label="Accessibility display controls">
          <button
            type="button"
            className={historyOpen ? 'icon-button active' : 'icon-button'}
            onClick={toggleHistory}
            aria-pressed={historyOpen}
            aria-label="Toggle caption history"
            title="Caption history (H)"
          >
            ≡
          </button>
          <button
            type="button"
            className={largeCaptions ? 'icon-button active' : 'icon-button'}
            onClick={toggleLargeCaptions}
            aria-pressed={largeCaptions}
            aria-label="Toggle large captions"
            title="Large captions (L)"
          >
            Aa
          </button>
        </div>
        <span
          className={connected ? 'session-clock connected' : 'session-clock'}
          title={backgrounded ? 'UI is backgrounded; the local backend keeps the session running' : connected ? 'Local backend connected' : 'Local backend disconnected'}
        >
          <span aria-hidden="true" /> {formatClock(sessionTime)}
        </span>
        <button
          type="button"
          className="stop-button"
          onClick={() => {
            roundtableClient.control('stop');
            // Refine takes a while (SpeakerKit + Bonsai); leave Live now and show its progress.
            useRoundtableStore.setState({
              phase: 'review',
              refined: undefined,
              refineProgress: 0.05,
              refineMessage: 'Stopping and saving the recording…',
            });
          }}
          disabled={phase !== 'live'}
        >
          Stop
        </button>
      </div>
    </header>
  );
}
