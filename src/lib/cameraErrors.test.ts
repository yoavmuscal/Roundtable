import { describe, expect, it } from 'vitest';
import { describeCameraError } from './cameraErrors';

describe('describeCameraError', () => {
  it('explains a blocked camera with the fix', () => {
    const message = describeCameraError(new DOMException('Permission denied', 'NotAllowedError'));
    expect(message).toMatch(/Camera blocked/);
    expect(message).toMatch(/Privacy & Security/);
  });

  it('explains a camera held by another app', () => {
    expect(describeCameraError(new DOMException('busy', 'NotReadableError'))).toMatch(/busy/);
  });

  it('falls back to the raw message', () => {
    expect(describeCameraError(new Error('weird'))).toBe('Camera error: weird');
  });
});
