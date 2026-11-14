import pytest

from backend.app.bonsai import BonsaiWorker, MockBonsaiClient
from backend.app.models import Turn
from backend.app.session import SessionEngine


@pytest.mark.asyncio
async def test_bonsai_tags_refined_turns_and_answers_with_citations() -> None:
    worker = BonsaiWorker(MockBonsaiClient(failure_rate=0.0))
    engine = SessionEngine(bonsai=worker)
    turns = [Turn("turn_0001", "p1", "What should we do?", 0, 1, 0.9)]
    tagged = await engine.tag_turns(turns)
    assert tagged[0].tags == ["question"]
    engine.turns = tagged
    answer = await engine.ask("What was decided?")
    assert answer["type"] == "answer"
    assert answer["citedTurnIds"] == ["turn_0001"]
    await worker.stop()


def test_live_captions_are_attributed_when_faces_share_the_session_clock() -> None:
    from backend.app.calibration import Calibration
    from backend.app.fake_session import FAKE_CORNERS, FAKE_TABLE
    from backend.app.session import SessionEngine

    engine = SessionEngine()
    engine.set_enrolled_people(engine.people[:2])
    engine.set_calibration(Calibration(FAKE_CORNERS, FAKE_TABLE))
    engine.start()

    def face(x: float, mouth: float) -> dict:
        return {
            "faceBox": {"x": x - 0.04, "y": 0.36, "width": 0.08, "height": 0.08},
            "mouthScore": mouth,
            "jawVariation": mouth * 0.08,
            "shoulderPoint": {"x": x, "y": 0.52},
            "chestPoint": {"x": x, "y": 0.64},
            "headTopPoint": {"x": x, "y": 0.33},
            "torsoVisible": True,
            "shirtHistogram": [1.0 if i == (0 if x < 0.5 else 8) else 0.0 for i in range(32)],
        }

    messages = []
    block = "---\nUnconfirmed segment: <|startoftranscript|><|0.00|> Is this working?<|2.0|>\nCurrent text: \n"
    for step in range(40):  # 4 s at 10/s: the left person talks, the right one is still
        t = step / 10
        engine.handle_level(t, 0.05)
        messages += engine.handle_faces(t, [face(0.3, 0.8), face(0.7, 0.02)])
        if step == 20:
            messages += engine.handle_transcript_chunk(block, t)
    messages += engine.tick(6.0)
    captions = [m for m in messages if m["type"] == "caption"]
    assert captions and captions[-1]["partial"] is False
    assert captions[-1]["speakerId"] == "p1"
    assert any(m["type"] == "active_speaker" and m["personId"] == "p1" for m in messages)
    assert any(m["type"] == "map" for m in messages)


def test_uncalibrated_camera_seats_people_along_the_far_edge() -> None:
    from backend.app.calibration import Calibration
    from backend.app.fake_session import FAKE_CORNERS, FAKE_TABLE
    from backend.app.geometry import Point
    from backend.app.session import SessionEngine

    engine = SessionEngine()
    engine.set_calibration(Calibration(FAKE_CORNERS, FAKE_TABLE))
    engine.use_horizontal_seating()
    # A laptop camera sees shoulders mid-frame, where the default table projection fails.
    left = engine.tracker.seat_mapper(Point(0.25, 0.55))
    right = engine.tracker.seat_mapper(Point(0.75, 0.6))
    assert (left.x, left.y) == (0.45, -0.45)
    assert (right.x, right.y) == (1.35, -0.45)


def _face(x: float, mouth: float, shirt: int) -> dict:
    return {
        "faceBox": {"x": x - 0.04, "y": 0.36, "width": 0.08, "height": 0.08},
        "mouthScore": mouth,
        "jawVariation": mouth * 0.08,
        "shoulderPoint": {"x": x, "y": 0.52},
        "chestPoint": {"x": x, "y": 0.64},
        "headTopPoint": {"x": x, "y": 0.33},
        "torsoVisible": True,
        "shirtHistogram": [1.0 if i == shirt else 0.0 for i in range(32)],
    }


def test_enrollment_binds_names_to_the_face_that_spoke() -> None:
    from backend.app.session import SessionEngine

    engine = SessionEngine()
    # Two enrolled people, Maya removed: ids p1 and p3, never an invented p2/p4.
    engine.set_enrolled_people([
        {"id": "p1", "name": "Yoav", "aliases": [], "color": "#8B7CF6", "shape": "circle"},
        {"id": "p3", "name": "Lee", "aliases": [], "color": "#F5A524", "shape": "diamond"},
    ])
    engine.begin_enrollment(0.0)
    # Lee sits on the left but Yoav reads first: the right face's mouth moves.
    for step in range(30):
        t = step / 10
        engine.handle_faces(t, [_face(0.3, 0.02, 0), _face(0.7, 0.8, 8), _face(0.5, 0.0, 16)])
    engine.record_enrollment("p1", 3.0)
    for step in range(30, 60):
        t = step / 10
        engine.handle_faces(t, [_face(0.3, 0.8, 0), _face(0.7, 0.02, 8), _face(0.5, 0.0, 16)])
    engine.record_enrollment("p3", 6.0)
    assert set(engine.tracker.tracks) == {"p1", "p3"}  # a third face is never tracked
    assert engine.tracker.tracks["p1"].smoothed.face_box.center.x > 0.6
    assert engine.tracker.tracks["p3"].smoothed.face_box.center.x < 0.4


def test_unbound_people_take_faces_left_to_right() -> None:
    from backend.app.session import SessionEngine

    engine = SessionEngine()
    engine.set_enrolled_people(engine.people[:2])
    for step in range(5):
        engine.handle_faces(step / 10, [_face(0.7, 0.0, 8), _face(0.3, 0.0, 0)])
    engine.start()
    assert engine.tracker.tracks["p1"].smoothed.face_box.center.x < 0.5
    assert engine.tracker.tracks["p2"].smoothed.face_box.center.x > 0.5
