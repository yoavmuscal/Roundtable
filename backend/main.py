from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .calibration import validate_calibration
from .contract import CONTRACT_VERSION, DEFAULT_PEOPLE
from .fake_session import FakeReplaySession

app = FastAPI(title="Roundtable Local Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "name": "Roundtable",
        "contractVersion": CONTRACT_VERSION,
        "mode": "simulation",
        "network": "none",
    }


async def cancel_task(task: asyncio.Task[None] | None) -> None:
    if task and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    session = FakeReplaySession(websocket)
    replay_task: asyncio.Task[None] | None = None
    enroll_index = 0

    async def send(message: dict[str, Any]) -> None:
        await websocket.send_text(json.dumps(message))

    await send({"type": "phase", "phase": "setup"})
    await send({"type": "people", "people": DEFAULT_PEOPLE})
    await send(
        {
            "type": "status",
            "status": {
                "model": "Replay + mock Bonsai",
                "secondsPerTurn": 0.0,
                "ramGb": 5.8,
                "network": "none",
                "backend": "simulation",
                "connected": True,
            },
        }
    )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            message_type = message.get("type")

            if message_type == "hello":
                await send(
                    {
                        "type": "status",
                        "status": {
                            "model": "Replay + mock Bonsai",
                            "secondsPerTurn": 0.8,
                            "ramGb": 5.8,
                            "network": "none",
                            "backend": "simulation",
                            "connected": True,
                        },
                    }
                )
            elif message_type == "ping":
                await send(
                    {
                        "type": "pong",
                        "nonce": str(message.get("nonce", "")),
                        "backendTime": time.monotonic(),
                    }
                )
            elif message_type == "calibrate":
                await send({"type": "calibration", "result": validate_calibration(message["payload"])})
            elif message_type == "ask":
                await send(session.answer(str(message.get("text", ""))))
            elif message_type == "seat-drag":
                # The live backend owns final seat projection. In sim mode, acknowledge
                # immediately so the UI drag interaction is exercised end-to-end.
                await send(
                    {
                        "type": "status",
                        "status": {
                            "model": "Replay + mock Bonsai",
                            "secondsPerTurn": 0.8,
                            "ramGb": 5.8,
                            "network": "none",
                            "backend": "simulation",
                            "connected": True,
                        },
                    }
                )
            elif message_type == "control":
                action = message.get("action")
                if action == "start":
                    await cancel_task(replay_task)
                    session = FakeReplaySession(websocket, speed=2.0)
                    replay_task = asyncio.create_task(session.run(message.get("value")))
                elif action == "stop":
                    await cancel_task(replay_task)
                    await session.send_refined()
                elif action == "recalibrate":
                    await send({"type": "phase", "phase": "setup"})
                elif action == "confirm-seats":
                    await send({"type": "phase", "phase": "enroll"})
                elif action in {"enroll-next", "enroll-redo", "enroll-skip"}:
                    if action == "enroll-next":
                        enroll_index = min(enroll_index + 1, len(DEFAULT_PEOPLE) - 1)
                    person = DEFAULT_PEOPLE[enroll_index]
                    await send(
                        {
                            "type": "enroll-prompt",
                            "personId": person["id"],
                            "prompt": f"{person['name']}, please say: “Roundtable keeps this conversation private.”",
                            "index": enroll_index,
                            "total": len(DEFAULT_PEOPLE),
                        }
                    )
    except WebSocketDisconnect:
        await cancel_task(replay_task)


def main() -> None:
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False, log_level="info")


if __name__ == "__main__":
    main()
