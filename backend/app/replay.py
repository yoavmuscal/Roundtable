"""Timed WebSocket replay server for generated sessions."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .contract import CONTRACT_VERSION
from .ui_adapter import internal_to_ui


class ReplaySession:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.events_path = session_dir / "events.jsonl"
        self.metadata_path = session_dir / "metadata.json"
        if not self.events_path.exists() or not self.metadata_path.exists():
            raise FileNotFoundError(f"{session_dir} does not contain a generated replay session")
        self.metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        self.events = [
            json.loads(line)
            for line in self.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.events.sort(key=lambda item: float(item.get("time", 0.0)))
        video_name = self.metadata.get("videoFile")
        self.video_path = session_dir / str(video_name) if video_name else None

    def replay_message(self) -> dict[str, Any]:
        return {
            "type": "replay",
            "session": self.metadata.get("name", self.session_dir.name),
            "videoUrl": "/video" if self.video_path and self.video_path.exists() else None,
            "speed": 1.0,
        }


def create_app(session_dir: Path) -> FastAPI:
    replay = ReplaySession(session_dir)
    app = FastAPI(title="Roundtable Replay", version=str(CONTRACT_VERSION))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"ok": True, "mode": "replay", "events": len(replay.events)}

    @app.get("/metadata")
    async def metadata() -> dict[str, object]:
        return replay.metadata

    @app.get("/video")
    async def video() -> FileResponse:
        if replay.video_path is None or not replay.video_path.exists():
            raise HTTPException(status_code=404, detail="No silhouette video was generated")
        return FileResponse(replay.video_path, media_type="image/gif")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        speed = max(0.1, float(websocket.query_params.get("speed", "1")))
        clock = 0.0
        stopped = asyncio.Event()

        async def receive_control() -> None:
            nonlocal clock
            try:
                while not stopped.is_set():
                    message = await websocket.receive_json()
                    if message.get("type") == "ping":
                        await websocket.send_json(
                            {
                                "type": "pong",
                                "nonce": str(message.get("nonce", "")),
                                "backendTime": clock,
                            }
                        )
                    elif message.get("type") == "hello":
                        await websocket.send_json(replay.replay_message())
            except WebSocketDisconnect:
                stopped.set()

        receiver = asyncio.create_task(receive_control())
        try:
            await websocket.send_json(replay.replay_message())
            previous_time = 0.0
            for item in replay.events:
                event_time = float(item.get("time", 0.0))
                await asyncio.sleep(max(0.0, event_time - previous_time) / speed)
                clock = event_time
                external = internal_to_ui(item)
                if external is not None:
                    await websocket.send_json(external)
                previous_time = event_time
        except WebSocketDisconnect:
            pass
        finally:
            stopped.set()
            receiver.cancel()
            try:
                await receiver
            except asyncio.CancelledError:
                pass

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session", type=Path, nargs="?", default=Path("sessions/fake"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(create_app(args.session), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
