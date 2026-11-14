import { describe, expect, it } from 'vitest';
import {
  bhattacharyyaSimilarity,
  buildAnchors,
  mouthScore,
  nearestPoseIndex,
  shirtHistogram,
  strictlyIncreasingTimestamp,
} from './math';

function samples(values: number[]) {
  return values.map((value, index) => ({ time: index / 20, value }));
}

describe('browser vision math', () => {
  it('scores a moving jaw high and a held-open jaw low', () => {
    const moving = mouthScore(samples([0.1, 0.7, 0.1, 0.7, 0.1, 0.7]), 0.25);
    const held = mouthScore(samples([0.7, 0.7, 0.7, 0.7, 0.7, 0.7]), 0.25);
    expect(moving).toBe(1);
    expect(held).toBe(0);
  });

  it('matches a face to the pose by nose point', () => {
    const face = { x: 0.4, y: 0.3, width: 0.1, height: 0.1 };
    const poses = [
      [{ x: 0.8, y: 0.4 }],
      [{ x: 0.45, y: 0.34 }],
    ];
    expect(nearestPoseIndex(face, poses)).toBe(1);
  });

  it('uses chest when torso clears the table and head otherwise', () => {
    const face = { x: 0.4, y: 0.3, width: 0.1, height: 0.1 };
    const pose = new Array(33).fill({ x: 0, y: 0 });
    pose[11] = { x: 0.4, y: 0.45 };
    pose[12] = { x: 0.5, y: 0.45 };
    pose[23] = { x: 0.4, y: 0.8 };
    pose[24] = { x: 0.5, y: 0.8 };
    const chest = buildAnchors(face, pose, 0.7);
    expect(chest.anchorMode).toBe('chest');
    const head = buildAnchors(face, pose, 0.55);
    expect(head.anchorMode).toBe('head');
    expect(head.headTop.y).toBeLessThan(face.y);
  });

  it('separates red and blue shirt histograms', () => {
    const red = new Uint8ClampedArray(100 * 100 * 4);
    const blue = new Uint8ClampedArray(100 * 100 * 4);
    for (let index = 0; index < 100 * 100; index += 1) {
      red.set([220, 20, 20, 255], index * 4);
      blue.set([20, 20, 220, 255], index * 4);
    }
    const box = { x: 0, y: 0, width: 1, height: 1 };
    const redHistogram = shirtHistogram(red, 100, 100, box);
    const blueHistogram = shirtHistogram(blue, 100, 100, box);
    expect(bhattacharyyaSimilarity(redHistogram, blueHistogram)).toBeLessThan(0.1);
  });

  it('forces MediaPipe video timestamps to increase', () => {
    expect(strictlyIncreasingTimestamp(undefined, 10)).toBe(10);
    expect(strictlyIncreasingTimestamp(10, 10)).toBe(11);
    expect(strictlyIncreasingTimestamp(10, 12)).toBe(12);
  });
});
