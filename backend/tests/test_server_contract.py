from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.fake_session import generate_session
from backend.app.server import create_app


def test_backend_websocket_speaks_ui_contract(tmp_path: Path) -> None:
    app = create_app(mode="sim", session_dir=tmp_path / "live", sim_session_dir=tmp_path / "fake")
    client = TestClient(app)
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "hello", "client": "test", "version": 1})
        phase = socket.receive_json()
        people = socket.receive_json()
        status = socket.receive_json()
        assert phase == {"type": "phase", "phase": "setup"}
        assert people["people"][0]["name"] == "Yoav"
        assert status["status"]["network"] == "none"

        socket.send_json({"type": "ping", "nonce": "1.0:1", "sentAt": 1.0})
        pong = socket.receive_json()
        assert pong["type"] == "pong"
        assert pong["nonce"] == "1.0:1"
        assert isinstance(pong["backendTime"], float)

        socket.send_json(
            {
                "type": "calibrate",
                "payload": {
                    "corners": [
                        {"x": 0.22, "y": 0.70},
                        {"x": 0.78, "y": 0.70},
                        {"x": 0.97, "y": 0.98},
                        {"x": 0.03, "y": 0.98},
                    ],
                    "tableSize": {"width": 1.8, "height": 0.9},
                    "center": {"x": 0.5, "y": 0.8045333333},
                },
            }
        )
        calibration = socket.receive_json()
        assert calibration["type"] == "calibration"
        assert calibration["result"]["ok"] is True
        assert calibration["result"]["centerError"] < 0.05
        assert calibration["result"]["gridLines"]

        socket.send_json({"type": "ask", "text": "What happened?"})
        answer = socket.receive_json()
        assert answer["type"] == "answer"
        assert answer["answer"]["text"]


def test_export_endpoint_writes_ass_for_recorded_session(tmp_path: Path) -> None:
    session = tmp_path / "session"
    generate_session(session, include_video=False)
    client = TestClient(create_app(mode="sim", session_dir=session, sim_session_dir=session))
    response = client.post("/export")
    assert response.status_code == 200
    payload = response.json()
    assert payload["exported"] is False
    assert (session / "captions.ass").exists()
