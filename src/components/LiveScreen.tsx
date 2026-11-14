import { useLayoutEffect } from 'react';
import { AnswerCard } from './AnswerCard';
import { CaptionHistory } from './CaptionHistory';
import { OnDeviceCard } from './OnDeviceCard';
import { QuestionsCard } from './QuestionsCard';
import { RoomMap } from './RoomMap';
import { SpeakerTimeline } from './SpeakerTimeline';
import { TalkTimeRings } from './TalkTimeRings';
import { VideoStage } from './VideoStage';

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

  return (
    <main className="live-screen" aria-label="Live conversation view">
      <div className="live-frame">
        <div className="live-canvas">
          <VideoStage />
          <SpeakerTimeline />
          <RoomMap />
          <TalkTimeRings />
          <QuestionsCard />
          <OnDeviceCard />
        </div>
      </div>
      <CaptionHistory />
      <AnswerCard />
    </main>
  );
}
