# Roundtable

**Your conversation, mapped — live, offline, for everyone.**

Roundtable is an accessibility-first meeting mapper for a Deaf or hard-of-hearing person following a group conversation. It pins color- and shape-coded captions to each speaker, maps speech around the table, preserves caption history, and alerts the reader when their name is said — all locally, with no runtime cloud dependency.

## Current milestone

This branch contains the Yoav-owned UI/accessibility foundation plus a compatible local replay backend:

- Setup screen with four-corner calibration, perspective grid, Check B center validation, and draggable seat markers.
- Speaker enrollment screen with editable names and aliases.
- Live screen matching the 1200 × 680 build-guide layout:
  - speaker-pinned speech bubbles with chest/head/side fallback placement;
  - colorblind-safe color + shape identity;
  - top-down room map with heat, active-speaker glow, away/standing states, camera wedge;
  - talk-time rings, open/overdue questions, and on-device status;
  - off-camera speaker cue.
- MVP accessibility features:
  - name alert using case-insensitive word-boundary matching;
  - persistent large-caption mode (`L`);
  - caption history (`H`) with auto-scroll/pause-on-hover and highlighted name alerts;
  - keyboard-safe labeled controls.
- Review screen with corrected-turn badge, topics, summary, action items, transcript, and typed Q&A citations.
- FastAPI WebSocket replay backend with a 91-second synthetic session, moving seat, temporary absence, scripted questions, name alert, answer card, and mock refine pass.
- Shared Python/TypeScript message contract in `backend/contract.py` and `src/contract.ts`.

## Run locally

Development mode uses two localhost processes:

```bash
npm install
python3 -m pip install -r requirements.txt
npm run backend
```

In a second terminal:

```bash
npm run dev
```

Open <http://127.0.0.1:5173>. Press `R` to run the synthetic session.

For the offline demo build, use one local process:

```bash
npm start
```

Open <http://127.0.0.1:8000>. FastAPI serves the production UI and WebSocket from the same localhost origin.

## Offline and background behavior

- The built UI has no CDN, remote-font, or runtime download dependency; Inter is bundled under its OFL license.
- `public/sw.js` caches the production app shell for repeat localhost launches. WebSocket and `/api` traffic are intentionally never cached.
- The FastAPI backend owns transcription, diarization, Bonsai calls, session events, and replay state. The React app is a renderer/controller connected through localhost JSON messages.
- Browser camera and MediaPipe vision require an open browser tab, but a backgrounded tab marks its visibility state, keeps the WebSocket client reconnecting, and requests a screen wake lock while Live is visible.
- Argmax runs outside the browser as the native Swift `argmax-cli` process, so model inference is not paused by React rendering.

## Checks

```bash
npm test
npm run build
```

The suite currently covers calibration geometry, Check B, cover-fit overlay alignment, hex spacing/map orientation, clock synchronization, name-alert boundaries, fake-session accessibility cases, target talk shares, refine payload shape, and heat-map ownership.

## Repository workflow

- `main` stays runnable.
- `backend` is Cello's branch.
- `ui` is Yoav's branch.
- Pull both branches before integration; merge `backend` first, then `ui`.
- The message contract has exactly two mirrors: `backend/contract.py` and `src/contract.ts`. Change both in the same commit.
- Runtime must remain offline: no CDNs, hosted fonts, or first-run model downloads.

## Argmax/Swift and hardware path

Argmax is Swift-native: the [Argmax Open-Source SDK](https://github.com/argmaxinc/argmax-oss-swift) provides WhisperKit for speech-to-text, SpeakerKit for Core ML diarization, and the `argmax-cli` executable/local server. The UI does not call Swift directly; it only speaks the versioned localhost contract in `src/contract.ts`. That keeps the browser compatible whether the backend drives `argmax-cli` as a child process today or embeds the Swift SDK behind the same contract later.

The current backend runs in simulation mode. The integration path is:

1. Argmax `argmax-cli` streaming transcription from the Mac microphone.
2. Argmax SpeakerKit diarization after Stop for the refine pass.
3. Bonsai 2 2B on localhost for tags, summaries, and Q&A.
4. iPhone Continuity Camera over USB for browser vision, with Center Stage off.
