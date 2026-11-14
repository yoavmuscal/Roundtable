import { AnswerCard } from './AnswerCard';
import { CaptionHistory } from './CaptionHistory';
import { OnDeviceCard } from './OnDeviceCard';
import { QuestionsCard } from './QuestionsCard';
import { RoomMap } from './RoomMap';
import { SpeakerTimeline } from './SpeakerTimeline';
import { TalkTimeRings } from './TalkTimeRings';
import { VideoStage } from './VideoStage';
import { roundtableClient } from '../services/roundtableClient';
import { useRoundtableStore } from '../state/store';

export function LiveScreen() {
  const frames = useRoundtableStore((state) => state.frames);

  return (
    <main className="live-screen" aria-label="Live conversation view">
      <div className="live-canvas">
        <VideoStage />
        <SpeakerTimeline />
        <RoomMap />
        <TalkTimeRings />
        <QuestionsCard />
        <OnDeviceCard />
      </div>
      {frames.length === 0 ? (
        <button
          type="button"
          className="start-fab primary"
          onClick={() => roundtableClient.control('start')}
        >
          Start replay
        </button>
      ) : null}
      <CaptionHistory />
      <AnswerCard />
    </main>
  );
}
