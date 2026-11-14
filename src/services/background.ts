import { useRoundtableStore } from '../state/store';

let wakeLock: WakeLockSentinel | undefined;

export async function requestScreenWakeLock(): Promise<boolean> {
  if (!('wakeLock' in navigator) || document.hidden || wakeLock) return false;
  try {
    wakeLock = await navigator.wakeLock.request('screen');
    wakeLock.addEventListener?.('release', () => {
      wakeLock = undefined;
    });
    return true;
  } catch {
    return false;
  }
}

export async function releaseScreenWakeLock(): Promise<void> {
  if (!wakeLock) return;
  const current = wakeLock;
  wakeLock = undefined;
  if (!current.released) await current.release().catch(() => undefined);
}

export function startBackgroundCompatibility(): () => void {
  const updateVisibility = () => {
    const backgrounded = document.hidden;
    useRoundtableStore.getState().setBackgrounded(backgrounded);
    if (!backgrounded && useRoundtableStore.getState().phase === 'live') {
      void requestScreenWakeLock();
    }
  };
  document.addEventListener('visibilitychange', updateVisibility);
  updateVisibility();
  return () => {
    document.removeEventListener('visibilitychange', updateVisibility);
    void releaseScreenWakeLock();
  };
}
