/**
 * Shared Roundtable WebSocket message contract.
 * Keep semantically aligned with backend/app/contract.py; change both together.
 */

export const CONTRACT_VERSION = 1;

export const PERSON_IDS = ['p1', 'p2', 'p3', 'p4'] as const;
export type PersonId = (typeof PERSON_IDS)[number];

export const BROWSER_MESSAGE_TYPES = [
  'hello',
  'ping',
  'calibrate',
  'faces',
  'control',
  'ask',
  'seat_drag',
] as const;
export type BrowserMessageType = (typeof BROWSER_MESSAGE_TYPES)[number];

export const BACKEND_MESSAGE_TYPES = [
  'replay',
  'pong',
  'calibration_result',
  'people',
  'enroll_prompt',
  'people_frame',
  'level',
  'caption',
  'active_speaker',
  'tags',
  'map',
  'stats',
  'status',
  'answer',
  'phase',
  'refine_progress',
  'refined',
  'error',
] as const;
export type BackendMessageType = (typeof BACKEND_MESSAGE_TYPES)[number];

export const CONTROL_ACTIONS = [
  'start',
  'stop',
  'enroll_next',
  'enroll_redo',
  'enroll_skip',
  'ask_begin',
  'ask_end',
  'recalibrate',
  'confirm_seats',
] as const;
export type ControlAction = (typeof CONTROL_ACTIONS)[number];

export const PHASES = ['setup', 'enroll', 'live', 'refine', 'review'] as const;
export type Phase = (typeof PHASES)[number];

export const SPEAKERS = [
  { id: 'p1', color: '#8B7CF6', shape: 'circle' },
  { id: 'p2', color: '#2DD4A7', shape: 'square' },
  { id: 'p3', color: '#F5A524', shape: 'diamond' },
  { id: 'p4', color: '#F472B6', shape: 'triangle' },
] as const;

export const DEFAULT_THRESHOLDS = {
  fusionTop: 0.35,
  fusionMargin: 0.12,
  fusionFallback: 0.25,
  previousSpeakerWindowS: 1.5,
  mouthScale: 0.08,
  activeHysteresisS: 0.3,
  reachCapMinM: 0.35,
  reachCapScaleM: 0.7,
  trackerMatchDistance: 0.15,
  trackerReidentifySimilarity: 0.8,
  trackerAwayAfterS: 2.0,
  trackerNewcomerAfterS: 3.0,
  seatFollowDistanceM: 0.5,
  seatFollowAfterS: 3.0,
} as const;

export interface Point {
  x: number;
  y: number;
}

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface FaceObservation {
  faceBox: Box;
  mouthScore: number;
  jawVariation: number;
  shoulderPoint: Point;
  chestPoint: Point;
  headTopPoint: Point;
  torsoVisible: boolean;
  shirtHistogram: number[];
}

export interface BrowserMessage {
  type: BrowserMessageType;
  version?: number;
  [key: string]: unknown;
}

export interface BackendMessage {
  type: BackendMessageType;
  version: number;
  time: number;
  [key: string]: unknown;
}

export function turnId(sequence: number): string {
  if (sequence < 1) throw new Error('turn sequence is one-based');
  return `turn_${String(sequence).padStart(4, '0')}`;
}

export function validateBrowserMessage(message: BrowserMessage): BrowserMessage {
  if (!BROWSER_MESSAGE_TYPES.includes(message.type)) {
    throw new Error(`unknown browser message type: ${String(message.type)}`);
  }
  const version = message.version ?? CONTRACT_VERSION;
  if (version !== CONTRACT_VERSION) {
    throw new Error(`unsupported contract version ${version}; expected ${CONTRACT_VERSION}`);
  }
  if (
    message.type === 'control' &&
    !CONTROL_ACTIONS.includes(message.action as ControlAction)
  ) {
    throw new Error(`unknown control action: ${String(message.action)}`);
  }
  return message;
}
