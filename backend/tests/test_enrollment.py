from backend.app.session import SessionEngine


def test_enrollment_intervals_and_name_aliases() -> None:
    engine = SessionEngine()
    engine.begin_enrollment(1.0)
    engine.complete_enrollment(2.5)
    engine.enroll_person("Yoav", ["Yoyo"])
    engine.complete_enrollment(4.0)
    engine.enroll_person("Maya")
    assert engine.enrollment_intervals == {"p1": [(1.0, 2.5)], "p2": [(2.5, 4.0)]}
    assert engine.name_alerts.check_turn("turn_0001", "Yoyo, can you hear me?") is not None


def test_enrolled_people_payload_updates_tracker_and_alerts() -> None:
    engine = SessionEngine()
    engine.set_enrolled_people(
        [
            {"id": "p1", "name": "Cello", "aliases": ["C"], "color": "#8B7CF6", "shape": "circle"},
            {"id": "p2", "name": "Yoav", "aliases": [], "color": "#2DD4A7", "shape": "square"},
        ]
    )
    assert engine.tracker.expected_people == 2
    assert engine.name_alerts.check_turn("turn_0001", "C, ready?") is not None
