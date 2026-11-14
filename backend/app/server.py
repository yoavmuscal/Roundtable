"""FastAPI localhost backend for live and simulated Roundtable sessions."""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .bonsai import BonsaiWorker, MockBonsaiClient, RealBonsaiClient
from .calibration import CalibrationError, calibration_from_payload
from .contract import CONTRACT_VERSION, MessageValidationError, validate_browser_message
from .fake_session import generate_session
from .geometry import Point
from .refine import SpeakerKitAdapter, match_clusters_to_people, refine_turns
from .replay import create_app as create_replay_app
from .session import SessionEngine
from .simulation import create_simulation_engine, run_simulation
from .status import status_message
from .transcribe import ArgmaxTranscriberAdapter


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
        return create_replay_app(sim_session_dir)

    app = FastAPI(title="Roundtable Backend", version=str(CONTRACT_VERSION))
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

    async def broadcast(message: dict[str, Any]) -> None:
        await manager.broadcast(message)

    def engine() -> SessionEngine:
        return app.state.engine

    async def stream_transcriber() -> None:
        command_text = os.environ.get("ROUNDTABLE_ARGMAX_COMMAND", "")
        if mode != "live" or not command_text:
            return
        adapter = ArgmaxTranscriberAdapter(shlex.split(command_text))
        try:
            async for _, chunk in adapter.stream():
                for message in engine().handle_transcript_chunk(chunk, engine().clock()):
                    await broadcast(message)
        finally:
            await adapter.stop()

    async def refine_after_stop() -> None:
        current = engine()
        await broadcast(SessionEngine._message(current.clock(), "refine_progress", stage="diarize", progress=0.2))
        refined_turns = current.turns
        changed_count = 0
        cluster_mapping: dict[str, str] = {}
        command_text = os.environ.get("ROUNDTABLE_SPEAKERKIT_COMMAND", "")
        wav_path = session_dir / "audio.wav"
        if command_text and wav_path.exists():
            try:
                segments = await SpeakerKitAdapter(shlex.split(command_text)).diarize(
                    wav_path, speaker_count=max(1, current.tracker.expected_people)
                )
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
        await broadcast(SessionEngine._message(current.clock(), "refine_progress", stage="summary", progress=0.7))
        summary = await current.summarize()
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
    async def health() -> dict[str, Any]:
        return {"ok": True, "mode": mode, "phase": engine().phase}

    @app.get("/status")
    async def status() -> dict[str, Any]:
        durations = [turn.end - turn.start for turn in engine().turns]
        seconds_per_turn = sum(durations) / len(durations) if durations else None
        return status_message(
            model="mock-bonsai" if mode == "sim" else "bonsai-2-2b",
            seconds_per_turn=seconds_per_turn,
        )

    @app.get("/transcript")
    async def transcript() -> dict[str, Any]:
        return {"turns": [turn.as_dict() for turn in engine().turns]}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            while True:
                message = validate_browser_message(await websocket.receive_json())
                message_type = message["type"]
                current = engine()
                if message_type == "hello":
                    await websocket.send_json(
                        {
                            "type": "phase",
                            "version": CONTRACT_VERSION,
                            "time": current.clock(),
                            "phase": current.phase,
                        }
                    )
                    await websocket.send_json(
                        {
                            "type": "people",
                            "version": CONTRACT_VERSION,
                            "time": current.clock(),
                            "people": current.people,
                        }
                    )
                    await websocket.send_json(
                        {"type": "status", "version": CONTRACT_VERSION, "time": current.clock(), **(await status())}
                    )
                elif message_type == "ping":
                    await websocket.send_json(
                        {
                            "type": "pong",
                            "version": CONTRACT_VERSION,
                            "time": current.clock(),
                            "sentAt": message.get("sentAt"),
                            "sequence": message.get("sequence"),
                        }
                    )
                elif message_type == "calibrate":
                    try:
                        calibration = calibration_from_payload(message)
                    except CalibrationError as exc:
                        await websocket.send_json(
                            {
                                "type": "calibration_result",
                                "version": CONTRACT_VERSION,
                                "time": current.clock(),
                                "ok": False,
                                "message": str(exc),
                            }
                        )
                    else:
                        await broadcast(current.set_calibration(calibration))
                elif message_type == "faces":
                    time_s = float(message.get("time", current.clock()))
                    for outgoing in current.handle_faces(time_s, message.get("people", [])):
                        await broadcast(outgoing)
                elif message_type == "ask":
                    await broadcast(await current.ask(str(message.get("text", ""))))
                elif message_type == "seat_drag":
                    person_id = str(message.get("personId"))
                    position = message.get("position", {})
                    track = current.tracker.tracks.get(person_id)
                    if track:
                        track.seat_position = Point(float(position.get("x", 0)), float(position.get("y", 0)))
                elif message_type == "control":
                    await handle_control(message)
        except WebSocketDisconnect:
            pass
        except MessageValidationError as exc:
            await websocket.send_json(
                {"type": "error", "version": CONTRACT_VERSION, "time": engine().clock(), "code": "contract", "message": str(exc)}
            )
        finally:
            await manager.disconnect(websocket)

    async def handle_control(message: dict[str, Any]) -> None:
        action = message["action"]
        current = engine()
        if action == "start":
            if mode == "sim":
                if not (sim_session_dir / "events.jsonl").exists():
                    generate_session(sim_session_dir, include_video=True)
                app.state.engine = create_simulation_engine(sim_session_dir, session_dir)
                speed = float(message.get("speed", 1.0))

                async def emit(item: dict[str, Any]) -> None:
                    await broadcast(item)

                app.state.sim_task = asyncio.create_task(
                    run_simulation(sim_session_dir, emit=emit, speed=speed, output_dir=session_dir)
                )
            else:
                for outgoing in current.start():
                    await broadcast(outgoing)
                app.state.transcriber_task = asyncio.create_task(stream_transcriber())
        elif action == "stop":
            if app.state.sim_task and not app.state.sim_task.done():
                app.state.sim_task.cancel()
            for outgoing in current.stop():
                await broadcast(outgoing)
            asyncio.create_task(refine_after_stop())
        elif action == "enroll_next":
            outgoing = current.enroll_person(
                str(message.get("name", f"Person {current.tracker.expected_people + 1}")),
                list(message.get("aliases", [])),
            )
            await broadcast(outgoing)
            await broadcast(
                SessionEngine._message(
                    current.clock(),
                    "enroll_prompt",
                    personId=f"p{min(current.tracker.expected_people + 1, 4)}",
                    instruction="Say your name clearly.",
                )
            )
        elif action == "recalibrate":
            current.phase = "setup"
            await broadcast(SessionEngine._message(current.clock(), "phase", phase="setup"))
        elif action == "confirm_seats":
            current.phase = "enroll"
            await broadcast(SessionEngine._message(current.clock(), "phase", phase="enroll"))
        elif action in {"ask_begin", "ask_end", "enroll_redo", "enroll_skip"}:
            await broadcast(SessionEngine._message(current.clock(), "status", action=action, **status_message(model="mock-bonsai" if mode == "sim" else "bonsai-2-2b", seconds_per_turn=None)))

    return app


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
