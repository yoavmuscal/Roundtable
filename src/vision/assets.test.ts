import { existsSync, statSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const assets = [
  'public/vision/wasm/vision_wasm_internal.js',
  'public/vision/wasm/vision_wasm_internal.wasm',
  'public/vision/models/face_landmarker.task',
  'public/vision/models/pose_landmarker_lite.task',
];

describe('local vision assets', () => {
  it('bundles MediaPipe WASM and both models for offline runtime', () => {
    for (const asset of assets) {
      expect(existsSync(asset), asset).toBe(true);
      expect(statSync(asset).size, asset).toBeGreaterThan(100_000);
    }
  });
});
