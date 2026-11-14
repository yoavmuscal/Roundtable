import type { Box, Point } from '../contract';

export interface TimedValue {
  time: number;
  value: number;
}

export interface VisionAnchorResult {
  chest: Point;
  headTop: Point;
  torsoVisible: boolean;
  anchorMode: 'chest' | 'head';
}

export function standardDeviation(values: number[]): number {
  if (values.length < 2) return 0;
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length;
  return variance < 1e-12 ? 0 : Math.sqrt(variance);
}

export function mouthScore(history: TimedValue[], now: number, scale = 0.08): number {
  const values = history
    .filter((sample) => now - sample.time <= 0.5)
    .map((sample) => sample.value);
  return Math.min(1, standardDeviation(values) / scale);
}

export function landmarksBox(landmarks: Array<{ x: number; y: number }>): Box {
  if (!landmarks.length) return { x: 0, y: 0, width: 0, height: 0 };
  const xs = landmarks.map((landmark) => landmark.x);
  const ys = landmarks.map((landmark) => landmark.y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  return {
    x: minX,
    y: minY,
    width: Math.max(0, Math.max(...xs) - minX),
    height: Math.max(0, Math.max(...ys) - minY),
  };
}

export function centerOf(box: Box): Point {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

export function nearestPoseIndex(face: Box, poses: Array<Array<{ x: number; y: number }>>): number | undefined {
  const center = centerOf(face);
  let bestIndex: number | undefined;
  let bestDistance = Number.POSITIVE_INFINITY;
  poses.forEach((landmarks, index) => {
    const nose = landmarks[0];
    if (!nose) return;
    const distance = Math.hypot(nose.x - center.x, nose.y - center.y);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestDistance <= Math.max(0.12, face.width * 1.5) ? bestIndex : undefined;
}

export function buildAnchors(
  face: Box,
  pose: Array<{ x: number; y: number }> | undefined,
  tableTopY?: number,
): VisionAnchorResult {
  const leftShoulder = pose?.[11];
  const rightShoulder = pose?.[12];
  const leftHip = pose?.[23];
  const rightHip = pose?.[24];
  const shoulder = leftShoulder && rightShoulder
    ? { x: (leftShoulder.x + rightShoulder.x) / 2, y: (leftShoulder.y + rightShoulder.y) / 2 }
    : { x: face.x + face.width / 2, y: face.y + face.height * 1.15 };
  const hip = leftHip && rightHip
    ? { x: (leftHip.x + rightHip.x) / 2, y: (leftHip.y + rightHip.y) / 2 }
    : { x: shoulder.x, y: shoulder.y + face.height };
  const chest = {
    x: shoulder.x + (hip.x - shoulder.x) * 0.45,
    y: shoulder.y + (hip.y - shoulder.y) * 0.45,
  };
  const headTop = { x: face.x + face.width / 2, y: face.y - face.height * 0.35 };
  const torsoVisible = chest.y < 0.92 && (tableTopY === undefined || chest.y + 0.08 < tableTopY);
  return { chest, headTop, torsoVisible, anchorMode: torsoVisible ? 'chest' : 'head' };
}

export function shirtHistogram(
  pixels: Uint8ClampedArray,
  imageWidth: number,
  imageHeight: number,
  box: Box,
): number[] {
  const histogram = new Array<number>(32).fill(0);
  const left = Math.max(0, Math.floor(box.x * imageWidth));
  const top = Math.max(0, Math.floor(box.y * imageHeight));
  const right = Math.min(imageWidth, Math.ceil((box.x + box.width) * imageWidth));
  const bottom = Math.min(imageHeight, Math.ceil((box.y + box.height) * imageHeight));
  for (let y = top; y < bottom; y += 2) {
    for (let x = left; x < right; x += 2) {
      const offset = (y * imageWidth + x) * 4;
      const [hue, saturation] = rgbToHueSaturation(pixels[offset], pixels[offset + 1], pixels[offset + 2]);
      const hueBin = Math.min(7, Math.floor(hue / 45));
      const saturationBin = Math.min(3, Math.floor(saturation * 4));
      histogram[hueBin * 4 + saturationBin] += 1;
    }
  }
  const total = histogram.reduce((sum, value) => sum + value, 0);
  return total ? histogram.map((value) => value / total) : histogram;
}

export function rgbToHueSaturation(red: number, green: number, blue: number): [number, number] {
  const r = red / 255;
  const g = green / 255;
  const b = blue / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  const saturation = max < 0.15 ? 0 : max === 0 ? 0 : delta / max;
  if (delta === 0) return [0, saturation];
  let hue: number;
  if (max === r) hue = 60 * (((g - b) / delta) % 6);
  else if (max === g) hue = 60 * ((b - r) / delta + 2);
  else hue = 60 * ((r - g) / delta + 4);
  return [(hue + 360) % 360, saturation];
}

export function bhattacharyyaSimilarity(a: number[], b: number[]): number {
  const length = Math.max(a.length, b.length);
  let sum = 0;
  for (let index = 0; index < length; index += 1) {
    sum += Math.sqrt((a[index] ?? 0) * (b[index] ?? 0));
  }
  return sum;
}

export function strictlyIncreasingTimestamp(previous: number | undefined, candidate: number): number {
  return previous === undefined ? candidate : Math.max(candidate, previous + 1);
}
