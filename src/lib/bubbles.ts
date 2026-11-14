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

export function estimateBubbleSize(_text: string, largeMode: boolean): Size {
  // Generous height so 3-4 lines fit with zero bottom clipping while keeping width constant.
  return largeMode ? { width: 330, height: 158 } : { width: 232, height: 124 };
}

function tailWords(text: string, maxChars: number): string {
  const clean = text.trim();
  if (clean.length <= maxChars) return clean;
  const words = clean.split(/\s+/);
  const kept: string[] = [];
  let length = 1; // ellipsis
  for (let idx = words.length - 1; idx >= 0; idx -= 1) {
    const word = words[idx]!;
    const added = kept.length ? word.length + 1 : word.length;
    if (length + added > maxChars && kept.length > 0) break;
    kept.unshift(word);
    length += added;
  }
  return `…${kept.join(' ')}`;
}

function intersects(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

function candidateForMode(anchor: Point, mode: AnchorMode, size: Size, stage: Size): Box {
  // Head placement clears the name tag drawn above the face bracket (build guide 6.10).
  const gap = mode === 'chest' ? 18 : mode === 'head' ? 44 : 12;
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
  // Keep bubbles off every face bracket and every name tag, not just the raw face box.
  const occupied: Box[] = frames.flatMap((frame) => {
    const faceWidth = frame.faceBox.width * stage.width;
    const faceHeight = frame.faceBox.height * stage.height;
    const centerX = (frame.faceBox.x + frame.faceBox.width / 2) * stage.width;
    const centerY = (frame.faceBox.y + frame.faceBox.height / 2) * stage.height;
    const head = Math.max(faceWidth, faceHeight) * 1.3;
    const bracket = { x: centerX - (head + 40) / 2, y: centerY - (head + 36) / 2, width: head + 40, height: head + 36 };
    const tag = { x: centerX - 48, y: centerY - head / 2 - 52, width: 96, height: 26 };
    return [bracket, tag];
  });
  const modes: AnchorMode[] = ['chest', 'head', 'right', 'left', 'top'];

  return frames.flatMap((frame) => {
    const caption = captionsByPerson.get(frame.id);
    if (!caption) return [];
    const text = tailWords(caption.text, largeMode ? 76 : 88);
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
