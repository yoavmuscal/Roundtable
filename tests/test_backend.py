from __future__ import annotations

import unittest

from backend.calibration import apply_homography, homography, validate_calibration
from backend.contract import DEFAULT_PEOPLE
from backend.fake_session import SCRIPT, build_events, refined_payload
from backend.heatmap import HeatMap


class CalibrationTests(unittest.TestCase):
    def test_homography_round_trip(self) -> None:
        table = [
            {"x": 0.0, "y": 0.0},
            {"x": 1.8, "y": 0.0},
            {"x": 1.8, "y": 0.9},
            {"x": 0.0, "y": 0.9},
        ]
        image = [
            {"x": 0.22, "y": 0.70},
            {"x": 0.78, "y": 0.70},
            {"x": 0.97, "y": 0.98},
            {"x": 0.03, "y": 0.98},
        ]
        h = homography(table, image)
        point = apply_homography(h, {"x": 0.9, "y": 0.45})
        self.assertAlmostEqual(point["x"], 0.5, places=6)
        self.assertGreater(point["y"], 0.7)

    def test_check_b_rejects_naive_midpoint(self) -> None:
        corners = [
            {"x": 0.22, "y": 0.55},
            {"x": 0.78, "y": 0.55},
            {"x": 0.97, "y": 0.98},
            {"x": 0.03, "y": 0.98},
        ]
        result = validate_calibration(
            {
                "corners": corners,
                "tableSize": {"width": 1.8, "height": 0.9},
                "center": {"x": 0.5, "y": 0.765},
            }
        )
        self.assertFalse(result["ok"])
        self.assertIn("Check B", result["message"])

    def test_true_projected_center_passes_check_b(self) -> None:
        corners = [
            {"x": 0.22, "y": 0.55},
            {"x": 0.78, "y": 0.55},
            {"x": 0.97, "y": 0.98},
            {"x": 0.03, "y": 0.98},
        ]
        result = validate_calibration(
            {
                "corners": corners,
                "tableSize": {"width": 1.8, "height": 0.9},
                "center": {"x": 0.5, "y": 0.7105333333},
            }
        )
        self.assertTrue(result["ok"])


class FakeSessionTests(unittest.TestCase):
    def test_fake_session_covers_accessibility_cases(self) -> None:
        events = build_events(DEFAULT_PEOPLE)
        captions = [event["caption"] for at, event in events if event["type"] == "caption" and event["caption"]["kind"] == "final"]
        self.assertEqual(len(captions), len(SCRIPT))
        self.assertTrue(any(caption.get("nameAlert") for caption in captions))
        frames = [event for at, event in events if event["type"] == "people-frame" and 59 <= at < 64]
        self.assertTrue(any(frame["people"][1]["state"] == "away" for frame in frames))
        mover_frames = [event for at, event in events if event["type"] == "people-frame" and at >= 50]
        self.assertGreater(mover_frames[-1]["people"][2]["mapPosition"]["x"], 1.45)
        answers = [event for at, event in events if event["type"] == "answer"]
        self.assertEqual(answers[0]["answer"]["citedTurnIds"], ["turn_0004"])

    def test_final_talk_shares_match_replay_target(self) -> None:
        events = build_events(DEFAULT_PEOPLE)
        stats = [event for at, event in events if event["type"] == "stats"][-1]
        shares = {item["personId"]: item["share"] for item in stats["talkShares"]}
        self.assertAlmostEqual(shares["p1"], 0.45, delta=0.03)
        self.assertAlmostEqual(shares["p2"], 0.30, delta=0.03)
        self.assertAlmostEqual(shares["p3"], 0.25, delta=0.03)

    def test_refined_payload_has_summary_and_actions(self) -> None:
        payload = refined_payload(DEFAULT_PEOPLE)["refined"]
        self.assertEqual(payload["correctedTurns"], 3)
        self.assertGreaterEqual(len(payload["actionItems"]), 3)
        self.assertEqual(len(payload["turns"]), len(SCRIPT))


class HeatMapTests(unittest.TestCase):
    def test_one_talker_owns_visible_heat(self) -> None:
        heat = HeatMap()
        for _ in range(20):
            heat.deposit("p1", {"x": 0.3, "y": -0.45}, 0.2, 0.5)
        snapshot = heat.snapshot()
        self.assertTrue(snapshot)
        self.assertTrue(all(cell["ownerId"] == "p1" for cell in snapshot))


if __name__ == "__main__":
    unittest.main()
