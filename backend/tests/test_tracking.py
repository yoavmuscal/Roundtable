import pytest

from backend.app.geometry import Point
from backend.app.models import Box, FaceObservation
from backend.app.tracking import PersonTracker, histogram_similarity


def hist(index: int) -> tuple[float, ...]:
    values = [0.0] * 32
    values[index] = 1.0
    return tuple(values)


def obs(x: float, color_bin: int, y: float = 0.40, torso: bool = True, shoulder_y: float | None = None) -> FaceObservation:
    shoulder = shoulder_y if shoulder_y is not None else y + 0.12
    return FaceObservation(
        face_box=Box(x - 0.04, y - 0.04, 0.08, 0.08),
        mouth_score=0.0,
        jaw_variation=0.0,
        shoulder_point=Point(x, shoulder),
        chest_point=Point(x, shoulder + 0.12),
        head_top_point=Point(x, y - 0.07),
        torso_visible=torso,
        shirt_histogram=hist(color_bin),
    )


def test_shuffled_order_and_drift_keep_identity() -> None:
    tracker = PersonTracker(expected_people=3)
    tracker.update(0.0, [obs(0.30, 0), obs(0.50, 8), obs(0.70, 16)])
    frame = tracker.update(0.1, [obs(0.705, 16), obs(0.305, 0), obs(0.505, 8)])
    positions = {item["id"]: item["faceBox"]["x"] + item["faceBox"]["width"] / 2 for item in frame}
    assert positions["p1"] == pytest.approx(0.305, abs=0.02)
    assert positions["p2"] == pytest.approx(0.505, abs=0.02)
    assert positions["p3"] == pytest.approx(0.705, abs=0.02)


def test_chair_swap_after_absence_reidentifies_by_shirt() -> None:
    tracker = PersonTracker(expected_people=2)
    tracker.update(0.0, [obs(0.45, 0), obs(0.55, 8)])
    tracker.update(1.0, [obs(0.55, 8)])
    tracker.update(3.2, [obs(0.55, 8)])
    frame = tracker.update(3.3, [obs(0.55, 0), obs(0.45, 8)])
    positions = {
        person_id: track.observation.face_box.center.x
        for person_id, track in tracker.tracks.items()
    }
    assert positions["p1"] == pytest.approx(0.55, abs=0.01)
    assert positions["p2"] == pytest.approx(0.45, abs=0.01)


def test_enrolled_return_matches_closest_missing_person() -> None:
    tracker = PersonTracker(expected_people=2)
    tracker.lock_to_expected = True
    tracker.allowed_ids = ["p1", "p2"]
    tracker.update(0.0, [obs(0.30, 0), obs(0.70, 8)])
    tracker.update(6.0, [])
    frame = tracker.update(6.2, [obs(0.34, 20)])
    positions = {item["id"]: item["faceBox"]["x"] + item["faceBox"]["width"] / 2 for item in frame}
    assert positions["p1"] == pytest.approx(0.34, abs=0.03)
    assert tracker.tracks["p2"].state == "away"


def test_away_after_five_seconds() -> None:
    tracker = PersonTracker(expected_people=2)
    tracker.update(0.0, [obs(0.3, 0), obs(0.6, 8)])
    frame = tracker.update(4.9, [obs(0.6, 8)])
    states = {item["id"]: item["state"] for item in frame}
    assert states["p1"] == "seated"
    frame = tracker.update(5.1, [obs(0.6, 8)])
    states = {item["id"]: item["state"] for item in frame}
    assert states["p1"] == "away"
    assert states["p2"] == "seated"


def test_standing_detection() -> None:
    tracker = PersonTracker(expected_people=1)
    tracker.update(0.0, [obs(0.4, 0, shoulder_y=0.52)])
    frame = tracker.update(0.5, [obs(0.4, 0, shoulder_y=0.36)])
    assert frame[0]["state"] == "standing"


def test_newcomer_flagged_after_three_seconds_unmatched() -> None:
    tracker = PersonTracker(expected_people=3)
    base = [obs(0.25, 0), obs(0.50, 8), obs(0.75, 16)]
    tracker.update(0.0, base)
    for t in (1.0, 2.0, 3.9):
        frame = tracker.update(t, [*base, obs(0.90, 24)])
        assert len(frame) == 3
    frame = tracker.update(4.1, [*base, obs(0.90, 24)])
    assert len(frame) == 4
    assert frame[-1]["id"] == "p4"


def test_anchor_mode_hysteresis() -> None:
    tracker = PersonTracker(expected_people=1)
    tracker.update(0.0, [obs(0.4, 0, torso=True)])
    frame = tracker.update(0.4, [obs(0.4, 0, torso=False)])
    assert frame[0]["captionAnchor"]["mode"] == "chest"
    frame = tracker.update(0.9, [obs(0.4, 0, torso=False)])
    assert frame[0]["captionAnchor"]["mode"] == "head"


def test_red_vs_blue_shirt_similarity_is_low() -> None:
    assert histogram_similarity(hist(0), hist(24)) < 0.1
