/** Turn getUserMedia failures into a short, actionable message for the stage. */
export function describeCameraError(error: unknown): string {
  const name = error instanceof DOMException || error instanceof Error ? error.name : '';
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'Camera blocked. Allow it for localhost (address-bar lock icon, then Camera, then Allow) and for this browser in System Settings, Privacy & Security, Camera. Then press Retry.';
    case 'NotReadableError':
    case 'AbortError':
      return 'Camera is busy. Quit FaceTime, Zoom, Photo Booth or other apps using it, then press Retry.';
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'That camera is not available. Pick another camera, or reconnect the iPhone by cable.';
    case 'NotSupportedError':
      return 'This window cannot open cameras. Open http://localhost:8000 in Chrome or use the Roundtable app.';
    default:
      return error instanceof Error && error.message ? `Camera error: ${error.message}` : 'Camera unavailable.';
  }
}
