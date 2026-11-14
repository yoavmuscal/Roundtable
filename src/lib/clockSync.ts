export interface ClockSample {
  sentAt: number;
  receivedAt: number;
  backendTime: number;
}

export function median(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function estimateClockOffset(samples: ClockSample[]): number {
  return median(
    samples.map((sample) => {
      const roundTrip = sample.receivedAt - sample.sentAt;
      return sample.backendTime + roundTrip / 2 - sample.receivedAt;
    }),
  );
}
