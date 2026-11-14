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


def test_fusion_prefers_mouth_that_tracks_mic() -> None:
    """Nodding/chewing (constant high jaw) loses to the mouth that rises with the mic."""
    fusion = SpeakerFusion()
    for t in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        # Mic and talker mouth rise together in the middle of the window.
        rms = 0.01 + (0.06 if 0.2 <= t <= 0.5 else 0.0)
        talker_mouth = 0.1 + (0.75 if 0.2 <= t <= 0.5 else 0.0)
        nodder_mouth = 0.85  # always "moving"
        fusion.add_level(t, rms)
        fusion.add_sample(t, "talker", talker_mouth)
        fusion.add_sample(t, "nodder", nodder_mouth)
    result = fusion.attribute(0.0, 0.7)
    assert result.speaker_id == "talker"
    assert result.reason == "clear"


def test_fusion_chewing_in_silence_is_ambiguous() -> None:
    fusion = SpeakerFusion()
    for t in (0.0, 0.1, 0.2, 0.3, 0.4):
        fusion.add_level(t, 0.004)
        fusion.add_sample(t, "chewer", 0.9)
        fusion.add_sample(t, "still", 0.05)
    result = fusion.attribute(0.0, 0.4)
    assert result.speaker_id is None or result.dashed or result.reason != "clear"


def test_fusion_handles_syllable_dips_against_smoothed_mouth_score() -> None:
    """Real mic RMS dips between syllables while 0.6s jawOpen std-dev stays elevated."""
    fusion = SpeakerFusion()
    rms_pattern = (0.045, 0.007, 0.052, 0.006, 0.048, 0.008, 0.041, 0.009)
    for idx, rms in enumerate(rms_pattern):
        t = idx * 0.1
        fusion.add_level(t, rms)
        fusion.add_sample(t, "p1", 0.0)
        fusion.add_sample(t, "p2", 0.42)
    result = fusion.attribute(0.0, 0.7)
    assert result.speaker_id == "p2"
    assert result.reason == "clear"


def test_voice_hint_inside_the_sentence_can_break_a_tie() -> None:
    fusion = SpeakerFusion()
    for t in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5):
        fusion.add_sample(t, "covered", 0.2)
        fusion.add_sample(t, "other", 0.22)
    fusion.add_voice(0.3, "covered", 0.9)
    assert fusion.attribute(0.0, 0.5).speaker_id == "covered"


def test_voice_hint_after_the_sentence_does_not_relabel_it() -> None:
    fusion = SpeakerFusion()
    for t in (0.0, 0.1, 0.2):
        fusion.add_sample(t, "p1", 0.8)
        fusion.add_sample(t, "p2", 0.1)
    fusion.add_voice(4.0, "p2", 0.95)
    result = fusion.attribute(0.0, 0.2)
    assert result.speaker_id == "p1"
    assert result.reason == "clear"


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
