/**
 * Roundtable shared message contract.
 *
 * Keep this file structurally mirrored with backend/contract.py. Any contract
 * change must update both copies in the same commit.
 */
export type Phase = 'setup' | 'enroll' | 'live' | 'review';
export type NetworkState = 'none' | 'detected';
export type SpeakerShape = 'circle' | 'square' | 'diamond' | 'triangle';
export type AnchorMode = 'chest' | 'head' | 'left' | 'right' | 'top';
export type PersonState = 'seated' | 'standing' | 'away';
export type CaptionKind = 'partial' | 'final';
export type BackendMode = 'simulation' | 'live';

export interface Point {
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Person {
  id: string;
  name: string;
  aliases: string[];
  color: string;
  shape: SpeakerShape;
}

export interface CalibrationPayload {
  corners: [Point, Point, Point, Point];
  tableSize: Size;
  center: Point;
}

export interface CalibrationResult {
  ok: boolean;
  message: string;
  centerError?: number;
  gridLines?: Point[][];
}

export interface Anchor {
  point: Point;
  mode: AnchorMode;
}

export interface PersonFrame {
  id: string;
  faceBox: Box;
  anchor: Anchor;
  mapPosition: Point;
  state: PersonState;
  mouth: number;
}

export interface Caption {
  id: string;
  turnId: string;
  personId?: string;
  text: string;
  start: number;
  end?: number;
  kind: CaptionKind;
  confidence: number;
  nameAlert?: boolean;
}

export interface Turn {
  id: string;
  personId: string;
  text: string;
  start: number;
  end: number;
  confidence: number;
  tags: string[];
}

export interface Question {
  id: string;
  turnId: string;
  text: string;
  askerId: string;
  createdAt: number;
  answeredAt?: number;
  overdue: boolean;
}

export interface TalkShare {
  personId: string;
  seconds: number;
  share: number;
}

export interface HexCell {
  q: number;
  r: number;
  ownerId?: string;
  opacity: number;
  share: number;
  contested: boolean;
}

export interface StatusPayload {
  model: string;
  secondsPerTurn: number;
  ramGb: number;
  network: NetworkState;
  backend: BackendMode;
  connected: boolean;
  /** Argmax streaming transcriber: off, loading (model warming ~20 s) or listening. */
  transcriberState?: 'off' | 'loading' | 'listening';
  /** SpeakerKit put two people's enrollment clips in the same voice group. */
  voiceWarning?: string;
}

export interface RefinedPayload {
  correctedTurns: number;
  totalTurns: number;
  topics: string[];
  summary: string;
  actionItems: string[];
  turns: Turn[];
}

export interface AnswerPayload {
  question: string;
  text: string;
  citedTurnIds: string[];
}

export type ClientMessage =
  | { type: 'hello'; client: string; version: number }
  | { type: 'ping'; nonce: string; sentAt: number }
  | { type: 'calibrate'; payload: CalibrationPayload }
  | {
      type: 'faces';
      at: number;
      faces: Array<{
        personId?: string;
        faceBox: Box;
        mouth: number;
        jawVariation: number;
        shoulder: Point;
        chest: Point;
        headTop: Point;
        torsoVisible: boolean;
        shirtHistogram: number[];
      }>;
    }
  | {
      type: 'control';
      action:
        | 'start'
        | 'stop'
        | 'enroll-next'
        | 'enroll-redo'
        | 'enroll-skip'
        | 'ask-begin'
        | 'ask-end'
        | 'recalibrate'
        | 'confirm-seats'
        | 'demo-replay';
      value?: string;
    }
  | { type: 'ask'; text: string }
  | { type: 'seat-drag'; personId: string; mapPosition: Point };

export type ServerMessage =
  | { type: 'pong'; nonce: string; backendTime: number }
  | { type: 'calibration'; result: CalibrationResult }
  | { type: 'people'; people: Person[] }
  | { type: 'enroll-prompt'; personId: string; prompt: string; index: number; total: number }
  | { type: 'people-frame'; at: number; people: PersonFrame[] }
  | { type: 'level'; at: number; rms: number }
  | { type: 'caption'; caption: Caption }
  | { type: 'active-speaker'; personId?: string; at: number; confidence: number }
  | { type: 'tags'; turnId: string; tags: string[]; repliesTo?: string; actionOwnerId?: string }
  | { type: 'map'; at: number; hexes: HexCell[] }
  | {
      type: 'stats';
      at: number;
      talkShares: TalkShare[];
      openQuestions: Question[];
      overdueQuestions: Question[];
    }
  | { type: 'status'; status: StatusPayload }
  | { type: 'answer'; answer: AnswerPayload }
  | { type: 'phase'; phase: Phase }
  | { type: 'refine-progress'; progress: number; message: string }
  | { type: 'refined'; refined: RefinedPayload }
  | { type: 'replay'; session: string; videoUrl?: string; speed: number }
  | { type: 'error'; message: string; code?: string };

export const CONTRACT_VERSION = 1;

export const DEFAULT_PEOPLE: Person[] = [
  { id: 'p1', name: 'Yoav', aliases: ['Yoav'], color: '#8B7CF6', shape: 'circle' },
  { id: 'p2', name: 'Maya', aliases: ['Maya'], color: '#2DD4A7', shape: 'square' },
  { id: 'p3', name: 'Lee', aliases: ['Lee'], color: '#F5A524', shape: 'diamond' },
];

export const DEFAULT_TABLE_SIZE: Size = { width: 1.8, height: 0.9 };
