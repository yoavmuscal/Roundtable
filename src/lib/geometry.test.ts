import { describe, expect, it } from 'vitest';
import type { Point } from '../contract';
import {
  applyHomography,
  coverTransform,
  homographyFromPoints,
  invert3x3,
  normalizedToStage,
  validateCalibration,
} from './geometry';

const corners: [Point, Point, Point, Point] = [
  { x: 0.22, y: 0.7 },
  { x: 0.78, y: 0.7 },
  { x: 0.97, y: 0.98 },
  { x: 0.03, y: 0.98 },
];

const table = [
  { x: 0, y: 0 },
  { x: 1.8, y: 0 },
  { x: 1.8, y: 0.9 },
  { x: 0, y: 0.9 },
];

describe('calibration geometry', () => {
  it('round-trips a homography', () => {
    const h = homographyFromPoints(table, corners);
    const inverse = invert3x3(h);
    const projected = applyHomography(h, { x: 0.9, y: 0.45 });
    const original = applyHomography(inverse, projected);
    expect(original.x).toBeCloseTo(0.9, 6);
    expect(original.y).toBeCloseTo(0.45, 6);
  });

  it('rejects crossed corner order with a plain-English message', () => {
    const crossed: [Point, Point, Point, Point] = [corners[0], corners[2], corners[1], corners[3]];
    expect(
      validateCalibration({ corners: crossed, tableSize: { width: 1.8, height: 0.9 }, center: { x: 0.5, y: 0.84 } }),
    ).toContain('crosses over itself');
  });

  it('cover-fit round-trips overlay points through one transform', () => {
    const transform = coverTransform({ width: 752, height: 424 }, { width: 16, height: 9 });
    expect(transform.offsetX).toBeCloseTo(-0.889, 3);
    expect(transform.offsetY).toBeCloseTo(0, 3);
    expect(normalizedToStage({ x: 0.5, y: 0.5 }, { width: 752, height: 424 }).y).toBeCloseTo(212, 3);
  });
});
