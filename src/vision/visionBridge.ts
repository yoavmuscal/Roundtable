import type { ClientMessage } from '../contract';
import type { VisionObservation } from './MediaPipeVision';

export type VisionSend = (message: ClientMessage) => boolean;

export function sendVisionObservations(
  observations: VisionObservation[],
  atSeconds: number,
  send: VisionSend,
): boolean {
  return send({
    type: 'faces',
    at: atSeconds,
    faces: observations,
  });
}
