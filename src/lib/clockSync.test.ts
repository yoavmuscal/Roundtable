import { describe, expect, it } from 'vitest';
import { estimateClockOffset, median } from './clockSync';

describe('clock sync', () => {
  it('uses the median offset', () => {
    expect(median([4, 1, 9, 2, 7])).toBe(4);
    const offset = estimateClockOffset([
      { sentAt: 1, receivedAt: 1.1, backendTime: 6.05 },
      { sentAt: 2, receivedAt: 2.1, backendTime: 7.05 },
      { sentAt: 3, receivedAt: 3.1, backendTime: 8.05 },
    ]);
    expect(offset).toBeCloseTo(5, 5);
  });
});
