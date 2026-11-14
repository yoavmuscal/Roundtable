import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.fake_session import generate_session
from backend.app.replay import ReplaySession, create_app


def test_fake_session_matches_expected_replay_behavior(tmp_path: Path) -> None:
    metadata = generate_session(tmp_path, include_video=False)
    assert metadata["eventCount"] >= 2500
    assert metadata["attributionAccuracy"] == 1.0
    assert metadata["actualTalkShares"]["p1"] == pytest.approx(0.4455, abs=0.002)
    assert metadata["actualTalkShares"]["p2"] == pytest.approx(0.3069, abs=0.002)
    assert metadata["actualTalkShares"]["p3"] == pytest.approx(0.2475, abs=0.002)
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert any(item["type"] == "answer" and item["time"] == 84.0 for item in events)
    final_captions = [item for item in events if item["type"] == "caption" and not item.get("partial")]
    assert len(final_captions) == 16
    assert any(item.get("nameAlert") for item in final_captions)
    away_frames = [
        item for item in events
        if item["type"] == "people_frame" and item["time"] >= 61.1
    ]
    assert any(
        person["id"] == "p2" and person["state"] == "away"
        for person in away_frames[0]["people"]
    )
    map_events = [item for item in events if item["type"] == "map" and 45 <= item["time"] <= 50]
    assert map_events


def test_replay_session_and_http_app(tmp_path: Path) -> None:
    generate_session(tmp_path, include_video=False)
    replay = ReplaySession(tmp_path)
    assert replay.replay_message()["session"] == "fake-accessibility-session"
    client = TestClient(create_app(tmp_path))
    assert client.get("/health").json()["ok"] is True
    assert client.get("/metadata").json()["eventCount"] >= 2500
    assert client.get("/video").status_code == 404


def test_replay_websocket_answers_ping_and_streams(tmp_path: Path) -> None:
    generate_session(tmp_path, include_video=False)
    client = TestClient(create_app(tmp_path))
    with client.websocket_connect("/ws?speed=1000") as socket:
        first = socket.receive_json()
        assert first["type"] == "replay"
        socket.send_json({"type": "ping", "sentAt": 12.5, "sequence": 1})
        replies = [socket.receive_json() for _ in range(20)]
        assert any(item["type"] == "pong" and item["sequence"] == 1 for item in replies)
        assert any(item["type"] == "phase" for item in replies)
