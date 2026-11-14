import pytest

from backend.app.accessibility import NameAlert
from backend.app.fusion import ActiveSpeakerGate, SpeakerFusion
from backend.app.models import Turn
from backend.app.questions import OpenQuestionTracker, talk_shares


def test_fusion_clear_winner() -> None:
    fusion = SpeakerFusion()
    for t in (0.0, 0.1, 0.2):
        fusion.add_sample(t, "p1", 0.8)
        fusion.add_sample(t, "p2", 0.1)
    result = fusion.attribute(0.1, 0.2)
    assert result.speaker_id == "p1"
    assert result.confidence == pytest.approx(0.8)
    assert not result.dashed


def test_fusion_ambiguous_continues_previous_at_04() -> None:
    fusion = SpeakerFusion()
    fusion.add_sample(0.0, "p1", 0.8)
    assert fusion.attribute(0.0, 0.1).speaker_id == "p1"
    fusion.add_sample(1.0, "p1", 0.31)
    fusion.add_sample(1.0, "p2", 0.30)
    result = fusion.attribute(1.0, 1.2)
    assert result.speaker_id == "p1"
    assert result.confidence == 0.4
    assert result.reason == "previous"


def test_fusion_fallback_025_is_dashed() -> None:
    fusion = SpeakerFusion()
    fusion.add_sample(0.0, "p1", 0.27)
    fusion.add_sample(0.0, "p2", 0.20)
    result = fusion.attribute(0.0, 0.2)
    assert result.speaker_id == "p1"
    assert result.dashed


def test_glow_needs_sound_and_hysteresis() -> None:
    gate = ActiveSpeakerGate()
    assert gate.update(0.0, "p1", 0.0) is None
    assert gate.update(0.1, "p1", 0.05) is None
    assert gate.update(0.39, "p1", 0.05) is None
    assert gate.update(0.41, "p1", 0.05) == "p1"
    assert gate.update(0.45, "p2", 0.05) == "p1"
    assert gate.update(0.8, "p2", 0.05) == "p2"


def test_open_questions_and_overdue_counter() -> None:
    tracker = OpenQuestionTracker(overdue_after_s=60)
    question = Turn("turn_0001", "p1", "What time is the demo?", 0, 2, 0.9)
    assert tracker.process_turn(question) == ["question"]
    snapshot = tracker.snapshot(62.1)
    assert snapshot["openCount"] == 1
    assert snapshot["overdueCount"] == 1
    reply = Turn("turn_0002", "p2", "The demo is at noon.", 62, 64, 0.9)
    assert tracker.process_turn(reply) == ["answer"]
    assert tracker.snapshot(65)["openCount"] == 0


def test_talk_shares() -> None:
    turns = [
        Turn("turn_0001", "p1", "a", 0, 45, 1),
        Turn("turn_0002", "p2", "b", 45, 76, 1),
        Turn("turn_0003", "p3", "c", 76, 101, 1),
    ]
    shares = talk_shares(turns)
    assert shares["p1"] == pytest.approx(45 / 101)
    assert shares["p2"] == pytest.approx(31 / 101)
    assert shares["p3"] == pytest.approx(25 / 101)


def test_name_alert_word_boundary_and_once_per_turn() -> None:
    alerts = NameAlert()
    alerts.set_names("p1", "Yoav")
    alert = alerts.check_turn("turn_0001", "Yoav, what do you think?")
    assert alert is not None
    assert alerts.check_turn("turn_0001", "Yoav again") is None
    assert alerts.check_turn("turn_0002", "yoavian is not the same") is None
