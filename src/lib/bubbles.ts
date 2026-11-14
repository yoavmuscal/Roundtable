import type { AnchorMode, Box, Caption, PersonFrame, Point, Size } from '../contract';
import { clamp, normalizedToStage } from './geometry';

export interface BubbleLayout {
  personId: string;
  turnId: string;
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
  tail: AnchorMode;
  opacity: number;
  confidence: number;
  nameAlert: boolean;
}

const tailDirection: Record<AnchorMode, Point> = {
  chest: { x: 0, y: 1 },
  head: { x: 0, y: -1 },
  left: { x: -1, y: 0 },
  right: { x: 1, y: 0 },
  top: { x: 0, y: -1 },
};

export function estimateBubbleSize(text: string, largeMode: boolean): Size {
  const fontSize = largeMode ? 21 : 14;
  const maxWidth = largeMode ? 330 : 232;
  const charWidth = fontSize * (largeMode ? 0.54 : 0.53);
  const naturalWidth = Math.min(maxWidth, Math.ceil(text.length * charWidth + 32));
  const charsPerLine = Math.max(12, Math.floor((naturalWidth - 32) / charWidth));
  const lines = Math.max(1, Math.min(2, Math.ceil(text.length / charsPerLine)));
  return {
    width: naturalWidth,
    height: (largeMode ? 54 : 46) + (lines - 1) * (largeMode ? 25 : 20),
  };
}

function intersects(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

function candidateForMode(anchor: Point, mode: AnchorMode, size: Size, stage: Size): Box {
  const gap = mode === 'chest' ? 18 : 12;
  let x = anchor.x - size.width / 2;
  let y = anchor.y - size.height - gap;
  if (mode === 'chest') y = anchor.y + gap;
  if (mode === 'left') {
    x = anchor.x - size.width - gap;
    y = anchor.y - size.height / 2;
  }
  if (mode === 'right') {
    x = anchor.x + gap;
    y = anchor.y - size.height / 2;
  }
  if (mode === 'top') y = 8;
  return {
    x: clamp(x, 8, Math.max(8, stage.width - size.width - 8)),
    y: clamp(y, 8, Math.max(8, stage.height - size.height - 8)),
    width: size.width,
    height: size.height,
  };
}

export function layoutBubbles(
  frames: PersonFrame[],
  captionsByPerson: Map<string, Caption>,
  stage: Size,
  largeMode: boolean,
): BubbleLayout[] {
  const newest = Math.max(
    0,
    ...Array.from(captionsByPerson.values()).map((caption) => caption.end ?? caption.start),
  );
  const faceBoxes = frames.map((frame) => ({
    x: frame.faceBox.x * stage.width,
    y: frame.faceBox.y * stage.height,
    width: frame.faceBox.width * stage.width,
    height: frame.faceBox.height * stage.height,
  }));
  const occupied: Box[] = [...faceBoxes];
  const modes: AnchorMode[] = ['chest', 'head', 'right', 'left', 'top'];

  return frames.flatMap((frame) => {
    const caption = captionsByPerson.get(frame.id);
    if (!caption) return [];
    const text = caption.text.length > 54 ? `…${caption.text.slice(-53).trimStart()}` : caption.text;
    const size = estimateBubbleSize(text, largeMode);
    const anchor = normalizedToStage(frame.anchor.point, stage);
    const preferred = modes.indexOf(frame.anchor.mode) >= 0 ? frame.anchor.mode : 'chest';
    const ordered = [preferred, ...modes.filter((mode) => mode !== preferred)];
    let box = candidateForMode(anchor, ordered[0], size, stage);
    let selectedMode = ordered[0];
    for (const mode of ordered) {
      const candidate = candidateForMode(anchor, mode, size, stage);
      if (!occupied.some((other) => intersects(candidate, other))) {
        box = candidate;
        selectedMode = mode;
        break;
      }
    }
    occupied.push(box);
    const age = Math.max(0, newest - (caption.end ?? caption.start));
    return [
      {
        personId: frame.id,
        turnId: caption.turnId,
        text,
        x: box.x,
        y: box.y,
        width: box.width,
        height: box.height,
        tail: tailDirection[selectedMode] ? selectedMode : 'chest',
        opacity: age <= 0.05 ? 1 : 0.45,
        confidence: caption.confidence,
        nameAlert: Boolean(caption.nameAlert),
      },
    ];
  });
}
