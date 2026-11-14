# Roundtable

**Your conversation, mapped — live, offline, for everyone.**

Roundtable is an accessibility-first meeting mapper for a Deaf or hard-of-hearing person following a group conversation. It pins color- and shape-coded captions to each speaker, maps speech around the table, preserves caption history, and alerts the reader when their name is said — all locally, with no runtime cloud dependency.

## What is in this repo

- `backend/app/` — Cello's Python backend: calibration homography and Check B, seat projection, pointy-top hex grid and Gaussian heat with fairness reach caps, identity tracker, speaker fusion, open-question tracking, name-alert matching, streaming transcriber parser, Bonsai worker (real + mock), SpeakerKit refine, session recorder, fake-session generator, replay server, and the FastAPI WebSocket hub.
- `src/` — Yoav's React + Vite + Zustand UI: Setup (calibration + seat drag), Enroll, Live (speaker-pinned bubbles, room map, talk rings, who-spoke-when, open questions, on-device card) and Review (refined transcript, summary, typed Q&A with citations).
- `src/vision/` — browser MediaPipe Face + Pose Landmarker pipeline with all WASM and `.task` assets committed under `public/vision/`.
- `backend/contract.py` and `src/contract.ts` — the shared message contract. Change both in the same commit or neither.

## Run locally

```bash
npm install
python3 -m pip install -r requirements.txt
```

Development (two localhost processes):

```bash
npm run backend
```

```bash
npm run dev
```

Open <http://localhost:5173>. The backend starts in **sim mode**: pressing **Start replay** (or `R`) generates the deterministic 91-second fake session on first use and pushes its face and transcript inputs through the real tracker, fusion, heat and caption pipeline. **Stop** runs the mock refine pass and opens Review.

Offline demo build (one process, production UI served by FastAPI on the same origin):

```bash
npm start
```

Open <http://localhost:8000>.

### Live Mac path

```bash
export ROUNDTABLE_ARGMAX_COMMAND="argmax-cli transcribe --stream"
export ROUNDTABLE_SPEAKERKIT_COMMAND="argmax-cli diarize {wav} --speakers {speakers}"
npm run backend:live
```

Bonsai 2 2B is expected as an OpenAI-compatible server on `http://localhost:8080`. Argmax and Bonsai are never started on Windows; Windows uses sim mode and mock Bonsai.

### Replay-only server

```bash
npm run backend:replay
```

Streams `sessions/fake/events.jsonl` with original timing (`?speed=2` on the WebSocket URL for faster replay) and serves the silhouette video at `/video`.

## Keyboard

| Key | Action |
| --- | --- |
| `R` | Reset and start the replay session |
| `L` | Toggle large-caption mode (persists per browser) |
| `H` | Toggle caption history panel |
| Space (hold) | Voice ask (live) |
| `⌘K` / `Ctrl+K` | Typed question about the meeting |

## Checks

```bash
npm test          # vitest + pytest
npm run typecheck
npm run vision:check
```

## Offline and privacy

- No CDN, hosted font or runtime model download: Inter is bundled, MediaPipe assets are committed.
- `public/sw.js` caches the production app shell for repeat localhost launches; WebSocket and `/api` traffic are never cached.
- Argmax runs outside the browser as the native `argmax-cli` process; Bonsai runs as a local server. Nothing leaves the laptop.

## Repository workflow

- `main` stays runnable; `backend` is Cello's branch; `ui` is Yoav's branch.
- Merge `backend` first, then `ui`, only at the agreed integration points; run `npm test` and a replay before any real-hardware session.

## Accessibility MVP

Name alert, large-caption mode, caption history, off-camera speaker cue, color + shape speaker identity, typed cited Q&A and the fully offline privacy story are part of the demo path, not stretch goals.
