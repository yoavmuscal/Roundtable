import { create } from 'zustand';
import type {
  AnswerPayload,
  CalibrationResult,
  Caption,
  HexCell,
  Person,
  PersonFrame,
  Phase,
  Question,
  RefinedPayload,
  ServerMessage,
  StatusPayload,
  TalkShare,
} from '../contract';
import { DEFAULT_PEOPLE, DEFAULT_TABLE_SIZE } from '../contract';
import { matchingPeople } from '../lib/accessibility';

interface EnrollPrompt {
  personId: string;
  prompt: string;
  index: number;
  total: number;
}

interface ReplayInfo {
  session: string;
  videoUrl?: string;
  speed: number;
}

interface RoundtableState {
  phase: Phase;
  connected: boolean;
  backgrounded: boolean;
  connectionMessage: string;
  clockOffset: number;
  people: Person[];
  frames: PersonFrame[];
  level: number;
  captions: Record<string, Caption>;
  latestByPerson: Record<string, string>;
  history: Caption[];
  activeSpeakerId?: string;
  activeSpeakerConfidence: number;
  mapHexes: HexCell[];
  talkShares: TalkShare[];
  openQuestions: Question[];
  overdueQuestions: Question[];
  status: StatusPayload;
  answer?: AnswerPayload;
  refined?: RefinedPayload;
  refineProgress: number;
  refineMessage: string;
  calibration?: CalibrationResult;
  enrollPrompt?: EnrollPrompt;
  replay?: ReplayInfo;
  largeCaptions: boolean;
  historyOpen: boolean;
  stageAlert: boolean;
  sessionTime: number;
  tableSize: { width: number; height: number };
  applyMessage: (message: ServerMessage) => void;
  setConnected: (connected: boolean, message?: string) => void;
  setBackgrounded: (backgrounded: boolean) => void;
  setClockOffset: (offset: number) => void;
  setPhase: (phase: Phase) => void;
  setPeopleNames: (people: Person[]) => void;
  toggleLargeCaptions: () => void;
  toggleHistory: () => void;
  clearAnswer: () => void;
  resetSession: () => void;
}

const savedLargeCaptions = globalThis.localStorage?.getItem('roundtable.largeCaptions') === 'true';

const defaultStatus: StatusPayload = {
  model: 'Replay simulation',
  secondsPerTurn: 0,
  ramGb: 0,
  network: 'none',
  backend: 'simulation',
  connected: false,
};

export const useRoundtableStore = create<RoundtableState>((set, get) => ({
  phase: 'setup',
  connected: false,
  backgrounded: false,
  connectionMessage: 'Connecting to local backend…',
  clockOffset: 0,
  people: DEFAULT_PEOPLE,
  frames: [],
  level: 0,
  captions: {},
  latestByPerson: {},
  history: [],
  activeSpeakerConfidence: 0,
  mapHexes: [],
  talkShares: [],
  openQuestions: [],
  overdueQuestions: [],
  status: defaultStatus,
  refineProgress: 0,
  refineMessage: '',
  largeCaptions: savedLargeCaptions,
  historyOpen: false,
  stageAlert: false,
  sessionTime: 0,
  tableSize: DEFAULT_TABLE_SIZE,

  applyMessage: (message) => {
    const state = get();
    switch (message.type) {
      case 'pong':
        break;
      case 'people':
        set({ people: message.people });
        break;
      case 'phase':
        set({ phase: message.phase });
        break;
      case 'replay':
        set({ replay: message });
        break;
      case 'calibration':
        set({ calibration: message.result });
        break;
      case 'enroll-prompt':
        set({ enrollPrompt: message });
        break;
      case 'people-frame':
        set({ frames: message.people, sessionTime: message.at });
        break;
      case 'level':
        set({ level: message.rms, sessionTime: message.at });
        break;
      case 'caption': {
        const people = state.people;
        const nameAlert =
          message.caption.kind === 'final' &&
          (message.caption.nameAlert || matchingPeople(message.caption.text, people).length > 0);
        const caption = { ...message.caption, nameAlert };
        const captions = { ...state.captions, [caption.id]: caption };
        const latestByPerson = caption.personId
          ? { ...state.latestByPerson, [caption.personId]: caption.id }
          : state.latestByPerson;
        const history =
          caption.kind === 'final'
            ? [...state.history.filter((item) => item.turnId !== caption.turnId), caption].slice(-80)
            : state.history;
        set({
          captions,
          latestByPerson,
          history,
          stageAlert: nameAlert,
          sessionTime: Math.max(state.sessionTime, caption.end ?? caption.start),
        });
        if (nameAlert) {
          window.setTimeout(() => {
            if (get().stageAlert) set({ stageAlert: false });
          }, 1500);
        }
        break;
      }
      case 'active-speaker':
        set({
          activeSpeakerId: message.personId,
          activeSpeakerConfidence: message.confidence,
          sessionTime: message.at,
        });
        break;
      case 'map':
        set({ mapHexes: message.hexes, sessionTime: message.at });
        break;
      case 'stats':
        set({
          talkShares: message.talkShares,
          openQuestions: message.openQuestions,
          overdueQuestions: message.overdueQuestions,
          sessionTime: message.at,
        });
        break;
      case 'status':
        set({ status: message.status });
        break;
      case 'answer':
        set({ answer: message.answer });
        break;
      case 'refine-progress':
        set({ refineProgress: message.progress, refineMessage: message.message });
        break;
      case 'refined':
        set({ refined: message.refined, phase: 'review', refineProgress: 1 });
        break;
      case 'error':
        set({ connectionMessage: message.message });
        break;
      case 'tags': {
        const refined = state.refined;
        if (!refined) break;
        set({
          refined: {
            ...refined,
            turns: refined.turns.map((turn) =>
              turn.id === message.turnId ? { ...turn, tags: message.tags } : turn,
            ),
          },
        });
        break;
      }
      default:
        break;
    }
  },

  setConnected: (connected, message) =>
    set({
      connected,
      connectionMessage: message ?? (connected ? 'Connected locally' : 'Disconnected'),
      status: { ...get().status, connected },
    }),
  setBackgrounded: (backgrounded) => set({ backgrounded }),
  setClockOffset: (offset) => set({ clockOffset: offset }),
  setPhase: (phase) => set({ phase }),
  setPeopleNames: (people) => set({ people }),
  toggleLargeCaptions: () => {
    const next = !get().largeCaptions;
    globalThis.localStorage?.setItem('roundtable.largeCaptions', String(next));
    set({ largeCaptions: next });
  },
  toggleHistory: () => set({ historyOpen: !get().historyOpen }),
  clearAnswer: () => set({ answer: undefined }),
  resetSession: () =>
    set({
      phase: 'setup',
      frames: [],
      captions: {},
      latestByPerson: {},
      history: [],
      activeSpeakerId: undefined,
      activeSpeakerConfidence: 0,
      mapHexes: [],
      talkShares: [],
      openQuestions: [],
      overdueQuestions: [],
      answer: undefined,
      refined: undefined,
      refineProgress: 0,
      refineMessage: '',
      calibration: undefined,
      enrollPrompt: undefined,
      sessionTime: 0,
      level: 0,
    }),
}));
