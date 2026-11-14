# Roundtable

**Your conversation, mapped — live, offline, for everyone.**

Roundtable is an accessibility-first meeting mapper for a Deaf or hard-of-hearing person following a group conversation. It pins color- and shape-coded captions to each speaker, maps speech around the table, preserves caption history, and alerts the reader when their name is said — locally, with no runtime cloud dependency.

## Current backend milestone

The `backend` branch contains Cello's offline foundation:

- Shared Python/TypeScript message contract at `backend/contract.py` and `src/contract.ts`.
- Pure Python calibration homography, Check B validation, seat projection, pointy-top hex grid, Gaussian heat, fairness reach caps, identity tracker, speaker fusion, active-speaker hysteresis, open-question tracking, and name-alert matching.
- A 90-second fake session generator that pushes synthetic detections through the real tracker/fusion/heat pipeline and records about 2,500 timed events.
- Replay server with original timing, clock ping/pong, and local silhouette animation support.
- Sim-mode FastAPI backend that replays browser face and transcriber inputs through the real backend pipeline.
- Live WebSocket hub with calibration, faces, controls, typed Q&A, seat drag, local status, Argmax transcription hooks, SpeakerKit refine hooks, and Bonsai worker priority/timeouts.
- Mock Bonsai with schema-valid responses, configurable delay, and deterministic test mode.
- Browser MediaPipe Face Landmarker + Pose Landmarker module with local WASM/model assets, alternating video inference, `jawOpen` mouth scores, face↔pose matching, chest/head anchors, shirt histograms, and a small bridge for the UI WebSocket client.
- Contract adapter for Yoav's React UI wire format.

## Run locally

Install dependencies:

```bash
npm ci
python -m pip install -r requirements.txt
```

Generate the deterministic fake session:

```bash
python -m backend.app.fake_session --output sessions/fake
```

Start the simulation backend:

```bash
npm run backend
```

In a second terminal, after the UI branch is integrated:

```bash
npm run dev
```

Open <http://127.0.0.1:5173> and press **Start** or `R` for replay.

### Replay-only server

```bash
python -m backend.app.replay sessions/fake --port 8000
```

Use `?speed=2` on the WebSocket URL for faster replay.

### Live Mac integration path

On Yoav's M2 Mac, run the backend in live mode and provide the local Argmax commands:

```bash
export ROUNDTABLE_ARGMAX_COMMAND="argmax-cli transcribe --stream"
export ROUNDTABLE_SPEAKERKIT_COMMAND="argmax-cli diarize {wav} --speakers {speakers}"
python -m backend.app.server --mode live --session sessions/live
```

Bonsai 2 2B remains on `http://localhost:8080`. Argmax and Bonsai are never started on Windows; Windows uses simulation and mock Bonsai.

## Offline browser vision assets

MediaPipe WASM and both `.task` models are committed under `public/vision/` so the browser never downloads vision assets at runtime:

- `face_landmarker.task`
- `pose_landmarker_lite.task`
- MediaPipe vision WASM loader/runtime

Verify them with:

```bash
npm run vision:check
```

## Checks

```bash
npm test
npm run typecheck
npm run vision:check
```

The backend suite covers calibration rejection and round-trips, seat projection, hex geometry, heat ownership/decay/fairness, tracker identity and away/standing/newcomer states, fusion and active-speaker hysteresis, transcript redraw/local-agreement parsing, Bonsai JSON extraction/schema retries, SpeakerKit matching/refine splitting, fake replay, sim mode, and the UI wire contract.

## Repository workflow

- `main` stays runnable.
- `backend` is Cello's branch.
- `ui` is Yoav's branch.
- Merge `backend` first, then `ui`, only at the agreed integration points.
- The external message contract has exactly two mirrors: `backend/contract.py` and `src/contract.ts`. Change both in the same commit.
- Runtime must remain offline: no CDNs, hosted fonts, cloud transcription, or first-run model downloads.

## Accessibility MVP

Name alert, large-caption mode, caption history, off-camera speaker cue, color+shape speaker identity, typed cited Q&A, and the fully offline privacy story are not stretch goals; they are part of the demo path.
