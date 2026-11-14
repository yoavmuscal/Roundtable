import { describe, expect, it } from 'vitest';
import { axialToPixel, hexCorners, hexWorldCenter, worldToMap } from './map';

describe('hex map math', () => {
  it('spaces axial neighbors exactly sqrt(3) times the hex size', () => {
    const size = 0.1;
    const a = axialToPixel({ q: 0, r: 0 }, size);
    const b = axialToPixel({ q: 1, r: 0 }, size);
    expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeCloseTo(Math.sqrt(3) * size, 8);
  });

  it('uses pointy-top hexes with a vertex straight up', () => {
    const [top] = hexCorners({ x: 10, y: 10 }, 5);
    expect(top.x).toBeCloseTo(10, 6);
    expect(top.y).toBeCloseTo(5, 6);
  });

  it('keeps the far side at the top of the map', () => {
    const far = worldToMap({ x: 0.9, y: 0 }, { width: 1.8, height: 0.9 }, { width: 352, height: 232 });
    const near = worldToMap({ x: 0.9, y: 0.9 }, { width: 1.8, height: 0.9 }, { width: 352, height: 232 });
    expect(far.y).toBeLessThan(near.y);
  });

  it('uses the same world origin as the backend', () => {
    expect(hexWorldCenter({ q: 0, r: 0 }).x).toBeCloseTo(-0.8, 6);
    expect(hexWorldCenter({ q: 0, r: 0 }).y).toBeCloseTo(-0.8, 6);
  });
});
