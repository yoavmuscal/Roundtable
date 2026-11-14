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


def test_video_upload_and_session_artifacts(tmp_path: Path) -> None:
    session = tmp_path / "live"
    app = create_app(mode="sim", session_dir=session, sim_session_dir=tmp_path / "fake")
    client = TestClient(app)
    response = client.post(
        "/session/video",
        content=b"webm-bytes",
        headers={"x-recording-start-s": "0.125"},
    )
    assert response.status_code == 200
    assert (session / "video.webm").read_bytes() == b"webm-bytes"
    engine = app.state.engine
    engine.handle_faces(
        0.0,
        [
            {
                "faceBox": {"x": 0.2, "y": 0.2, "width": 0.1, "height": 0.1},
                "mouthScore": 0.1,
                "jawVariation": 0.0,
                "shoulderPoint": {"x": 0.25, "y": 0.4},
                "chestPoint": {"x": 0.25, "y": 0.5},
                "headTopPoint": {"x": 0.25, "y": 0.15},
                "torsoVisible": True,
                "shirtHistogram": [1.0],
            }
        ],
    )
    engine.stop(1.0)
    assert (session / "anchors.jsonl").exists()
    metadata = (session / "metadata.json").read_text(encoding="utf-8")
    assert '"videoS": 0.125' in metadata


def test_export_endpoint_writes_ass_for_recorded_session(tmp_path: Path) -> None:
    session = tmp_path / "session"
    generate_session(session, include_video=False)
    client = TestClient(create_app(mode="sim", session_dir=session, sim_session_dir=session))
    response = client.post("/export")
    assert response.status_code == 200
    payload = response.json()
    assert payload["exported"] is False
    assert (session / "captions.ass").exists()


def test_enrollment_follows_the_ui_people_list(tmp_path: Path) -> None:
    import json

    client = TestClient(create_app(mode="sim", session_dir=tmp_path / "live", sim_session_dir=tmp_path / "fake"))
    two = [
        {"id": "p1", "name": "Ana", "aliases": ["Ana"], "color": "#8B7CF6", "shape": "circle"},
        {"id": "p3", "name": "Lee", "aliases": [], "color": "#F5A524", "shape": "diamond"},
    ]
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "control", "action": "confirm-seats", "value": json.dumps(two)})
        assert socket.receive_json() == {"type": "phase", "phase": "enroll"}
        prompt = socket.receive_json()
        assert prompt["type"] == "enroll-prompt"
        assert (prompt["personId"], prompt["index"], prompt["total"]) == ("p1", 0, 2)
        assert "Ana" in prompt["prompt"]

        # A fourth seat added in the UI arrives with the next control.
        four = two + [
            {"id": "p2", "name": "Maya", "aliases": [], "color": "#2DD4A7", "shape": "square"},
            {"id": "p4", "name": "Sam", "aliases": [], "color": "#F472B6", "shape": "triangle"},
        ]
        socket.send_json({"type": "control", "action": "enroll-next", "value": json.dumps(four)})
        prompt = socket.receive_json()
        assert (prompt["personId"], prompt["index"], prompt["total"]) == ("p3", 1, 4)
    engine = client.app.state.engine
    assert [person["id"] for person in engine.people] == ["p1", "p3", "p2", "p4"]
    assert engine.tracker.expected_people == 4
    assert "p1" in engine.enrollment_intervals
