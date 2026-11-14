"""FastAPI localhost backend for live and simulated Roundtable sessions."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shlex
import shutil
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .audio import MicrophoneLevelMonitor, pcm_between
from .bonsai import BonsaiWorker, MockBonsaiClient, RealBonsaiClient
from .calibration import Calibration, CalibrationError, calibration_from_payload
from .contract import CONTRACT_VERSION, MessageValidationError, validate_browser_message
from .export import export_session_ass, ffmpeg_export_command
from .fake_session import FAKE_CORNERS, FAKE_TABLE, generate_session
from .geometry import Point
from .models import Turn
from .refine import SpeakerKitAdapter, SpeakerSegment, match_clusters_to_people, refine_turns
from .replay import create_app as create_replay_app
from .session import SessionEngine
from .simulation import create_simulation_engine, run_simulation
from .status import status_message
from .transcribe import ArgmaxTranscriberAdapter
from .voiceid import VoiceIdentifier
from .ui_adapter import browser_to_internal, internal_to_ui


DIST_DIR = Path(__file__).resolve().parents[2] / "dist"
WHISPER_MODEL = os.environ.get("ROUNDTABLE_WHISPER_MODEL", "base")


def is_default_calibration(calibration: Calibration | None) -> bool:
    """True when nobody calibrated this camera (default demo corners)."""
    if calibration is None:
        return True
    return all(
        abs(a.x - b.x) < 1e-3 and abs(a.y - b.y) < 1e-3 for a, b in zip(calibration.corners, FAKE_CORNERS)
    )


def argmax_binary() -> str | None:
    """The Argmax open-source CLI ships as argmax-cli (newer) or whisperkit-cli (Homebrew)."""
    for name in ("argmax-cli", "whisperkit-cli"):
        if shutil.which(name):
            return name
    return None


def transcriber_command(names: list[str] | None = None) -> list[str]:
    configured = os.environ.get("ROUNDTABLE_ARGMAX_COMMAND", "")
    if configured:
        return shlex.split(configured)
    binary = argmax_binary()
    if not binary:
        return []
    # Without --word-timestamps, argmax-cli 1.1.1 streams only "No word timings found".
    command = [binary, "transcribe", "--stream", "--word-timestamps", "--model", WHISPER_MODEL]
    hint = ", ".join(name.strip() for name in (names or []) if name and name.strip())
    if hint:
        command.extend(["--prompt", hint])
    return command


def speakerkit_command() -> list[str]:
    configured = os.environ.get("ROUNDTABLE_SPEAKERKIT_COMMAND", "")
    if configured:
        return shlex.split(configured)
    binary = argmax_binary()
    if not binary:
        return []
    return [binary, "diarize", "--audio-path", "{wav}", "--num-speakers", "{speakers}", "--rttm-path", "{rttm}"]


NO_CACHE_PATHS = {"/", "/index.html", "/sw.js", "/manifest.webmanifest"}


def mount_ui(app: FastAPI) -> FastAPI:
    """Serve the production React build from the same localhost origin as the API."""
    if DIST_DIR.is_dir():

        @app.middleware("http")
        async def no_cache_entry_files(request: Request, call_next):  # noqa: ANN001, ANN202
            # Hashed /assets/* files can be cached forever; the page and service worker
            # must always be fresh or the browser keeps running an old build.
            response = await call_next(request)
            if request.url.path in NO_CACHE_PATHS:
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return response

        app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="roundtable-ui")
    return app


class ConnectionManager:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.clients.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            clients = list(self.clients)
        stale: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_json(message)
            except (RuntimeError, WebSocketDisconnect):
                stale.append(client)
        if stale:
            async with self._lock:
                for client in stale:
                    self.clients.discard(client)


def create_app(
    *,
    mode: str = "sim",
    session_dir: Path = Path("sessions/live"),
    sim_session_dir: Path = Path("sessions/fake"),
    bonsai_url: str = "http://localhost:8080",
) -> FastAPI:
    if mode == "replay":
        if not (sim_session_dir / "events.jsonl").exists():
            generate_session(sim_session_dir, include_video=True)
        return mount_ui(create_replay_app(sim_session_dir))

    @contextlib.asynccontextmanager
    async def lifespan(app_: FastAPI):
        yield
        # Ctrl+C / SIGTERM: stop Argmax and release the microphone so nothing is orphaned.
        shutdown = getattr(app_.state, "shutdown", None)
        if shutdown is not None:
            await shutdown()

    app = FastAPI(title="Roundtable Backend", version=str(CONTRACT_VERSION), lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    manager = ConnectionManager()
    bonsai_client = MockBonsaiClient(failure_rate=0.0) if mode == "sim" else RealBonsaiClient(bonsai_url)
    app.state.bonsai = BonsaiWorker(bonsai_client)
    app.state.engine = SessionEngine(session_dir=session_dir, bonsai=app.state.bonsai)
    app.state.sim_task = None
    app.state.transcriber_task = None
    app.state.tick_task = None
    app.state.voice_task = None
    app.state.transcriber_state = "off"  # off | loading | listening
    app.state.audio_monitor = None
    app.state.warmed = False
    app.state.voice_warning = None

    def model_label() -> str:
        if mode == "sim":
            return "Bonsai 2 2B (mock)"
        return "Bonsai 2 2B" if isinstance(bonsai_client, RealBonsaiClient) and bonsai_client.available() else "Bonsai offline"

    def current_status(**extra: Any) -> dict[str, Any]:
        durations = [turn.end - turn.start for turn in engine().turns]
        seconds_per_turn = sum(durations) / len(durations) if durations else None
        payload = status_message(model=model_label(), seconds_per_turn=seconds_per_turn)
        payload["backend"] = "live" if mode == "live" else "simulation"
        payload["transcriber"] = " ".join(transcriber_command()[:1]) or None
        payload["transcriberState"] = app.state.transcriber_state
        warning = getattr(app.state, "voice_warning", None)
        if warning:
            payload["voiceWarning"] = warning
        return {**payload, **extra}

    async def warm_bonsai() -> None:
        if mode == "live" and not app.state.warmed and isinstance(bonsai_client, RealBonsaiClient):
            app.state.warmed = True
            await bonsai_client.warm_up()

    async def broadcast(message: dict[str, Any]) -> None:
        external = internal_to_ui(message)
        if external is not None:
            await manager.broadcast(external)

    def engine() -> SessionEngine:
        return app.state.engine

    async def stream_transcriber() -> None:
        command = transcriber_command([str(person.get("name", "")) for person in engine().people])
        if mode != "live":
            return
        if not command:
            await broadcast(
                SessionEngine._message(
                    engine().clock(),
                    "error",
                    code="transcriber",
                    message="No Argmax CLI found (brew install whisperkit-cli) and ROUNDTABLE_ARGMAX_COMMAND is unset; captions are off.",
                )
            )
            return
        adapter = ArgmaxTranscriberAdapter(command)
        session_dir.mkdir(parents=True, exist_ok=True)
        # Raw CLI bytes are kept for debugging and as parser fixtures.
        raw_log = (session_dir / "transcriber_raw.txt").open("ab")
        app.state.transcriber_state = "loading"
        await broadcast(SessionEngine._message(engine().clock(), "status", **current_status()))
        try:
            logged = 0
            async for _, chunk in adapter.stream():
                if logged < 2_000_000:  # argmax-cli reprints its whole history; keep a sample only
                    raw_log.write(chunk)
                    raw_log.flush()
                    logged += len(chunk)
                if app.state.transcriber_state != "listening" and (b"Transcribing audio stream" in chunk or b"---" in chunk):
                    # Whisper finished loading (about 20 s): tell the UI it is safe to talk.
                    app.state.transcriber_state = "listening"
                    await broadcast(SessionEngine._message(engine().clock(), "status", **current_status()))
                current = engine()
                # Argmax keeps running between sessions; only enrollment and live sessions use its text.
                if current.phase not in {"enroll", "live"}:
                    continue
                await emit(current, current.handle_transcript_chunk(chunk, current.clock()))
        finally:
            raw_log.close()
            app.state.transcriber_state = "off"
            await adapter.stop()

    voice_ids = VoiceIdentifier(speakerkit_command(), session_dir / "voiceid") if mode == "live" and speakerkit_command() else None

    async def check_enrollment_voices(current: SessionEngine) -> None:
        """Warn when two enrollment clips fall in the same SpeakerKit voice group."""
        monitor = app.state.audio_monitor
        if voice_ids is None or monitor is None or len(current.people) < 2:
            return
        try:
            groups = await voice_ids.alike_groups(current.enrollment_audio(monitor))
        except Exception:
            return
        if current is not engine():
            return
        if not groups:
            app.state.voice_warning = None
            return
        names = current._names()
        parts = [
            " and ".join(names.get(person_id, person_id) for person_id in group) + " sound alike, please redo"
            for group in groups
        ]
        app.state.voice_warning = ". ".join(parts)
        await broadcast(SessionEngine._message(current.clock(), "status", **current_status()))

    async def emit(current: SessionEngine, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            await broadcast(message)

    async def watch_voice() -> None:
        """SpeakerKit on the last few seconds, folded into the mouth decision while speech is open."""
        while True:
            await asyncio.sleep(1.5)
            current = engine()
            monitor = app.state.audio_monitor
            if voice_ids is None or monitor is None or current.phase != "live" or current.last_rms < 0.015:
                continue
            now = current.clock()
            clip = pcm_between(monitor, current.started_monotonic + now - 3.5, current.started_monotonic + now)
            try:
                match = await voice_ids.identify(current.enrollment_audio(monitor), clip)
            except Exception:
                continue
            if current is not engine() or current.phase != "live":
                continue
            if match.person_id and match.coverage >= 0.55:
                await emit(current, current.steer_open_speaker(match.person_id, now, match.coverage))

    async def warm_speakerkit() -> None:
        """SpeakerKit's first call loads its models (~14 s); do it during enrollment."""
        if voice_ids is None:
            return
        silence = b"\x00\x00" * 16000 * 2
        with contextlib.suppress(Exception):
            await voice_ids.identify({"warm-a": silence, "warm-b": silence}, silence)

    def ensure_transcriber() -> None:
        """Start Argmax once and keep it warm, so Start never waits on the model load."""
        task = app.state.transcriber_task
        if mode == "live" and (task is None or task.done()):
            app.state.transcriber_task = asyncio.create_task(stream_transcriber())

    async def refine_after_stop() -> None:
        current = engine()
        await broadcast(SessionEngine._message(current.clock(), "refine_progress", stage="separating voices with Argmax SpeakerKit", progress=0.2))
        refined_turns = current.turns
        changed_count = 0
        cluster_mapping: dict[str, str] = {}
        command = speakerkit_command() if mode == "live" else []
        wav_path = session_dir / "audio.wav"
        if command and wav_path.exists():
            try:
                segments = await SpeakerKitAdapter(command).diarize(
                    wav_path, speaker_count=max(1, len(current.people))
                )
                offset = float(current.recording_offsets.get("audioS", 0.0))
                segments = [SpeakerSegment(seg.start - offset, seg.end - offset, seg.cluster) for seg in segments]
                cluster_mapping = match_clusters_to_people(
                    segments,
                    getattr(current, "enrollment_intervals", {}),
                    current.turns,
                )
                result = refine_turns(current.turns, segments, cluster_mapping)
                refined_turns = result.turns
                changed_count = result.changed_count
            except Exception as exc:
                await broadcast(SessionEngine._message(current.clock(), "error", code="refine", message=str(exc)))
        await broadcast(SessionEngine._message(current.clock(), "refine_progress", stage="tagging questions and decisions", progress=0.55))
        # Bonsai tags at most the 25 longest turns so Review opens in seconds, not minutes.
        to_tag = sorted(refined_turns, key=lambda turn: len(turn.text), reverse=True)[:25]
        await current.tag_turns(to_tag)
        await broadcast(SessionEngine._message(current.clock(), "refine_progress", stage="writing the summary", progress=0.75))
        try:
            summary = await current.summarize()
        except Exception as exc:
            await broadcast(SessionEngine._message(current.clock(), "error", code="summary", message=f"Bonsai summary failed: {exc}"))
            summary = {"summary": "Summary unavailable: Bonsai did not respond.", "topics": [], "actionItems": [], "perPerson": []}
        current.recorder.write_turns("refined_transcript.jsonl", refined_turns)
        current.phase = "review"
        await broadcast(
            SessionEngine._message(
                current.clock(),
                "refined",
                turns=[turn.as_dict() for turn in refined_turns],
                changedCount=changed_count,
                totalCount=len(current.turns),
                clusterToPerson=cluster_mapping,
                topics=summary.get("topics", []),
                summary=summary,
            )
        )
        await broadcast(SessionEngine._message(current.clock(), "phase", phase="review"))

    @app.get("/health")
    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "mode": mode, "phase": engine().phase}

    @app.get("/status")
    async def status() -> dict[str, Any]:
        return current_status()

    @app.get("/transcript")
    async def transcript() -> dict[str, Any]:
        return {"turns": [turn.as_dict() for turn in engine().turns]}

    @app.post("/session/video")
    async def upload_video(request: Request) -> dict[str, Any]:
        body = await request.body()
        if not body:
            raise HTTPException(status_code=400, detail="empty video upload")
        session_dir.mkdir(parents=True, exist_ok=True)
        video_path = session_dir / "video.webm"
        video_path.write_bytes(body)
        engine().recording_offsets["videoS"] = float(request.headers.get("x-recording-start-s", "0"))
        return {"ok": True, "videoPath": str(video_path), "bytes": len(body)}

    @app.post("/export")
    async def export() -> dict[str, Any]:
        ass_path = export_session_ass(session_dir)
        video_path = session_dir / "video.webm"
        audio_path = session_dir / "audio.wav"
        output_path = session_dir / "roundtable-captioned.mp4"
        exported = False
        error = None
        if video_path.exists() and audio_path.exists():
            command = ffmpeg_export_command(video_path, audio_path, ass_path, output_path)
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            exported = process.returncode == 0
            if not exported:
                error = stderr.decode("utf-8", errors="replace")[-1000:]
        return {
            "assPath": str(ass_path),
            "videoPath": str(output_path) if exported else None,
            "exported": exported,
            "error": error,
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            while True:
                message = browser_to_internal(validate_browser_message(await websocket.receive_json()))
                message_type = message["type"]
                current = engine()
                if message_type == "hello":
                    asyncio.create_task(warm_bonsai())
                    ensure_transcriber()  # Whisper takes ~20 s to load; start before anyone needs it
                    for outgoing in (
                        {"type": "phase", "time": current.clock(), "phase": current.phase},
                        {"type": "people", "time": current.clock(), "people": current.people},
                        {"type": "status", "time": current.clock(), **(await status())},
                    ):
                        external = internal_to_ui(outgoing)
                        if external is not None:
                            await websocket.send_json(external)
                elif message_type == "ping":
                    await websocket.send_json(
                        {
                            "type": "pong",
                            "nonce": str(message.get("nonce", "")),
                            "backendTime": current.clock(),
                        }
                    )
                elif message_type == "calibrate":
                    try:
                        calibration = calibration_from_payload(message)
                    except CalibrationError as exc:
                        await websocket.send_json(
                            internal_to_ui(
                                {
                                    "type": "calibration_result",
                                    "time": current.clock(),
                                    "ok": False,
                                    "message": str(exc),
                                }
                            )
                        )
                    else:
                        await broadcast(current.set_calibration(calibration))
                elif message_type == "faces":
                    # Stamp on arrival: the browser's synced offset goes stale whenever a new
                    # session resets the clock, and localhost latency is a few milliseconds.
                    time_s = current.clock() if mode == "live" else float(message.get("time", current.clock()))
                    for outgoing in current.handle_faces(time_s, message.get("people", [])):
                        await broadcast(outgoing)
                elif message_type == "ask":
                    question = str(message.get("text", ""))
                    try:
                        answer = await current.ask(question)
                    except Exception as exc:  # Bonsai offline, timeout or invalid JSON
                        answer = SessionEngine._message(
                            current.clock(),
                            "answer",
                            question=question,
                            text=f"Bonsai could not answer ({type(exc).__name__}). Is the Bonsai server running on :8080?",
                            citedTurnIds=[],
                        )
                    await broadcast(answer)
                elif message_type == "seat_drag":
                    person_id = str(message.get("personId"))
                    position = message.get("position", {})
                    track = current.tracker.tracks.get(person_id)
                    if track:
                        track.seat_position = Point(float(position.get("x", 0)), float(position.get("y", 0)))
                elif message_type == "control":
                    client = websocket.client
                    print(
                        f"roundtable: control {message['action']} from {client.host}:{client.port}"
                        f" (phase {current.phase}, {len(manager.clients)} client(s) connected)",
                        flush=True,
                    )
                    await handle_control(message)
        except WebSocketDisconnect:
            pass
        except MessageValidationError as exc:
            external = internal_to_ui(
                {"type": "error", "time": engine().clock(), "code": "contract", "message": str(exc)}
            )
            if external is not None:
                await websocket.send_json(external)
        finally:
            await manager.disconnect(websocket)

    async def live_ticker() -> None:
        """Close turns after silence and refresh RAM/model status while live."""
        beats = 0
        while True:
            await asyncio.sleep(0.25)
            current = engine()
            if current.phase != "live":
                continue
            await emit(current, current.tick(current.clock()))
            beats += 1
            if beats % 4 == 0:
                await broadcast(current.stats(current.clock()))
            if beats % 20 == 0:
                await broadcast(SessionEngine._message(current.clock(), "status", **current_status()))

    async def stop_live_tasks(stop_audio: bool = True) -> None:
        for name in ("tick_task", "voice_task"):
            task = getattr(app.state, name)
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            setattr(app.state, name, None)
        if stop_audio and app.state.audio_monitor is not None:
            await app.state.audio_monitor.stop()
            app.state.audio_monitor = None

    async def shutdown_live() -> None:
        await stop_live_tasks(stop_audio=True)
        task = app.state.transcriber_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    app.state.shutdown = shutdown_live

    async def ensure_live_audio() -> None:
        if mode != "live" or app.state.audio_monitor is not None:
            return

        async def emit_level(_wav_time: float, rms: float, peak: float) -> None:
            # Levels are stamped on the session clock so they line up with faces and captions.
            current = engine()
            await broadcast(current.handle_level(current.clock(), rms, peak))

        monitor = MicrophoneLevelMonitor(emit_level, session_dir / "audio.wav")
        try:
            await monitor.start()
            app.state.audio_monitor = monitor
        except RuntimeError as exc:
            await broadcast(
                SessionEngine._message(engine().clock(), "error", code="audio", message=str(exc))
            )

    async def handle_control(message: dict[str, Any]) -> None:
        action = message["action"]
        current = engine()
        if action == "start":
            if mode == "sim":
                if not (sim_session_dir / "events.jsonl").exists():
                    generate_session(sim_session_dir, include_video=True)
                app.state.engine = create_simulation_engine(sim_session_dir, session_dir, bonsai=app.state.bonsai)
                speed = float(message.get("speed", 1.0))

                async def emit(item: dict[str, Any]) -> None:
                    await broadcast(item)

                async def run_and_refine() -> None:
                    await run_simulation(
                        sim_session_dir,
                        emit=emit,
                        speed=speed,
                        output_dir=session_dir,
                        engine=app.state.engine,
                    )
                    # A replay that runs to its end refines exactly like a manual Stop.
                    await refine_after_stop()

                app.state.sim_task = asyncio.create_task(run_and_refine())
            else:
                ticker = app.state.tick_task
                if current.phase == "live" and ticker is not None and not ticker.done():
                    # Already running: rejoin instead of restarting (a restart reloads Whisper for ~20 s).
                    await broadcast(SessionEngine._message(current.clock(), "phase", phase="live"))
                    await broadcast(SessionEngine._message(current.clock(), "people", people=current.people))
                    return
                fresh = current.phase in {"review", "refine", "live"}
                # Keep the microphone (and its WAV) running from enrollment into the session so
                # the enrollment samples are in the same file SpeakerKit diarizes.
                await stop_live_tasks(stop_audio=fresh)
                if fresh:
                    previous = current
                    current = SessionEngine(session_dir=session_dir, bonsai=app.state.bonsai)
                    if previous.calibration is not None:
                        current.set_calibration(previous.calibration)
                    current.set_enrolled_people(previous.people)
                    app.state.engine = current
                if message.get("value"):
                    try:
                        people = json.loads(str(message["value"]))
                        if isinstance(people, list) and people:
                            current.set_enrolled_people(people)
                    except (json.JSONDecodeError, TypeError, KeyError):
                        pass
                if current.calibration is None:
                    current.set_calibration(Calibration(FAKE_CORNERS, FAKE_TABLE))
                if is_default_calibration(current.calibration):
                    current.use_horizontal_seating()
                await ensure_live_audio()
                for outgoing in current.start():
                    await broadcast(outgoing)
                monitor = app.state.audio_monitor
                if monitor is not None:
                    current.recording_offsets["audioS"] = round(current.started_monotonic - monitor.started_wall_monotonic, 3)
                ensure_transcriber()
                app.state.tick_task = asyncio.create_task(live_ticker())
                voice_task = app.state.voice_task
                if voice_task is None or voice_task.done():
                    app.state.voice_task = asyncio.create_task(watch_voice())
        elif action == "stop":
            if mode == "live" and current.phase != "live":
                return  # a second Stop click must not run refine twice
            if app.state.sim_task and not app.state.sim_task.done():
                app.state.sim_task.cancel()
                app.state.sim_task = None
            if current.phase == "review":
                return
            await stop_live_tasks()
            for outgoing in current.stop():
                await broadcast(outgoing)
            asyncio.create_task(refine_after_stop())
        elif action in {"enroll_next", "enroll_skip", "enroll_redo"}:
            if message.get("value"):
                try:
                    people = json.loads(str(message["value"]))
                    if isinstance(people, list) and people:
                        current.set_enrolled_people(people)
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass
            cursor = min(getattr(app.state, "enroll_cursor", 0), len(current.people) - 1)
            now = current.clock()
            if app.state.voice_warning:
                app.state.voice_warning = None
                await broadcast(SessionEngine._message(now, "status", **current_status()))
            if action == "enroll_next":
                current.take_enrollment_sample(current.people[cursor]["id"], now)
                cursor += 1
            elif action == "enroll_skip":
                current.enrollment_armed = False
                current.enrollment_started_at = None
                cursor += 1
            else:
                current.enrollment_armed = False
                current.enrollment_started_at = None
            app.state.enroll_cursor = min(cursor, len(current.people) - 1)
            if cursor >= len(current.people):
                await broadcast(SessionEngine._message(now, "status", enrollment="complete", **current_status()))
                asyncio.create_task(check_enrollment_voices(current))
            else:
                await broadcast(current.enroll_prompt(app.state.enroll_cursor))
        elif action == "demo_replay":
            # Failsafe: drop the live mic and show the prerecorded, already-refined session.
            if app.state.sim_task and not app.state.sim_task.done():
                app.state.sim_task.cancel()
                app.state.sim_task = None
            await stop_live_tasks(stop_audio=True)
            task = app.state.transcriber_task
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            app.state.transcriber_task = None
            app.state.transcriber_state = "off"
            if not (sim_session_dir / "events.jsonl").exists():
                generate_session(sim_session_dir, include_video=False)
            people_row: dict[str, Any] | None = None
            refined_row: dict[str, Any] | None = None
            for line in (sim_session_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("type") == "people":
                    people_row = row
                elif row.get("type") == "refined":
                    refined_row = row
            current.phase = "review"
            if people_row and isinstance(people_row.get("people"), list):
                current.set_enrolled_people(people_row["people"])
            if refined_row:
                current.turns = [
                    Turn(
                        str(item.get("id")),
                        item.get("speakerId"),
                        str(item.get("text", "")),
                        float(item.get("start", 0.0)),
                        float(item.get("end", 0.0)),
                        float(item.get("confidence", 0.0)),
                        tags=list(item.get("tags") or []),
                    )
                    for item in refined_row.get("turns", [])
                    if isinstance(item, dict)
                ]
            await broadcast(SessionEngine._message(0.0, "replay", session="Recorded this morning", speed=1))
            if people_row:
                await broadcast(people_row)
            await broadcast(SessionEngine._message(0.0, "phase", phase="review"))
            if refined_row:
                await broadcast(refined_row)
            await broadcast(SessionEngine._message(0.0, "status", **current_status()))
        elif action == "recalibrate":
            current.phase = "setup"
            await broadcast(SessionEngine._message(current.clock(), "phase", phase="setup"))
        elif action == "confirm_seats":
            if message.get("value"):
                try:
                    people = json.loads(str(message["value"]))
                    if isinstance(people, list) and people:
                        current.set_enrolled_people(people)
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass
            current.phase = "enroll"
            app.state.enroll_cursor = 0
            app.state.voice_warning = None
            current.enrollment_intervals = {}
            current.enrollment_armed = False
            current.enrollment_started_at = None
            await ensure_live_audio()
            ensure_transcriber()
            asyncio.create_task(warm_speakerkit())
            await broadcast(SessionEngine._message(current.clock(), "phase", phase="enroll"))
            await broadcast(current.enroll_prompt(0))
        elif action == "enroll_arm":
            current.arm_enrollment(current.clock())
        elif action in {"ask_begin", "ask_end"}:
            await broadcast(SessionEngine._message(current.clock(), "status", action=action, **current_status()))

    return mount_ui(app)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("sim", "live", "replay"), default="sim")
    parser.add_argument("--session", type=Path, default=Path("sessions/live"))
    parser.add_argument("--sim-session", type=Path, default=Path("sessions/fake"))
    parser.add_argument("--bonsai-url", default="http://localhost:8080")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(
        create_app(
            mode=args.mode,
            session_dir=args.session,
            sim_session_dir=args.sim_session,
            bonsai_url=args.bonsai_url,
        ),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
