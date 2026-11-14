import { AnswerCard } from './AnswerCard';
import { CaptionHistory } from './CaptionHistory';
import { OnDeviceCard } from './OnDeviceCard';
import { QuestionsCard } from './QuestionsCard';
import { RoomMap } from './RoomMap';
import { SpeakerLanes } from './SpeakerLanes';
import { TalkTimeRings } from './TalkTimeRings';
import { VideoStage } from './VideoStage';
import { roundtableClient } from '../services/roundtableClient';
import { useRoundtableStore } from '../state/store';

export function LiveScreen() {
  const replay = useRoundtableStore((state) => state.replay);
  const level = useRoundtableStore((state) => state.level);
  const connected = useRoundtableStore((state) => state.connected);

  return (
    <main className="live-screen" aria-label="Live conversation view">
      <div className="live-canvas">
        <VideoStage />
        <SpeakerLanes />
        <RoomMap />
        <TalkTimeRings />
        <QuestionsCard />
        <OnDeviceCard />
      </div>
      <div className="live-controls" aria-label="Session controls">
        <div className="audio-meter" aria-label={`Audio level ${Math.round(level * 100)} percent`}>
          <span style={{ width: `${Math.min(100, level * 180)}%` }} />
        </div>
        <span>{replay ? `Replaying ${replay.session} at ${replay.speed}×` : connected ? 'Local session ready' : 'Backend offline'}</span>
        <button type="button" onClick={() => roundtableClient.control('start')} className="primary">
          Start
        </button>
        <button type="button" onClick={() => roundtableClient.control('stop')}>
          Stop + refine
        </button>
      </div>
      <CaptionHistory />
      <AnswerCard />
    </main>
  );
}
