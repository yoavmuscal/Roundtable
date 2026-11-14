from backend.app.ui_adapter import browser_to_internal, internal_to_ui


def test_browser_calibration_faces_and_controls_translate() -> None:
    calibration = browser_to_internal(
        {
            "type": "calibrate",
            "payload": {
                "corners": [
                    {"x": 0.22, "y": 0.7},
                    {"x": 0.78, "y": 0.7},
                    {"x": 0.97, "y": 0.98},
                    {"x": 0.03, "y": 0.98},
                ],
                "tableSize": {"width": 1.8, "height": 0.9},
                "center": {"x": 0.5, "y": 0.8045},
            },
        }
    )
    assert calibration["tableSize"] == {"widthM": 1.8, "heightM": 0.9}
    assert calibration["centerClick"] == {"x": 0.5, "y": 0.8045}
    faces = browser_to_internal(
        {
            "type": "faces",
            "at": 1.2,
            "faces": [
                {
                    "faceBox": {"x": 0.1, "y": 0.2, "width": 0.1, "height": 0.1},
                    "mouth": 0.7,
                    "jawVariation": 0.04,
                    "shoulder": {"x": 0.15, "y": 0.4},
                    "chest": {"x": 0.15, "y": 0.52},
                    "headTop": {"x": 0.15, "y": 0.1},
                    "torsoVisible": True,
                    "shirtHistogram": [1.0],
                }
            ],
        }
    )
    assert faces["people"][0]["mouthScore"] == 0.7
    assert browser_to_internal({"type": "control", "action": "enroll-next"})["action"] == "enroll_next"
    assert browser_to_internal({"type": "seat-drag", "personId": "p1", "mapPosition": {"x": 1, "y": -0.45}})["type"] == "seat_drag"


def test_backend_events_match_yoav_ui_wire_contract() -> None:
    caption = internal_to_ui(
        {
            "type": "caption",
            "time": 2.0,
            "turnId": "turn_0001",
            "speakerId": "p1",
            "text": "Yoav, what do you think?",
            "partial": False,
            "confidence": 0.9,
            "nameAlert": {"personId": "p1"},
            "start": 1.0,
            "end": 2.0,
        }
    )
    assert caption == {
        "type": "caption",
        "caption": {
            "id": "turn_0001:final",
            "turnId": "turn_0001",
            "personId": "p1",
            "text": "Yoav, what do you think?",
            "start": 1.0,
            "end": 2.0,
            "kind": "final",
            "confidence": 0.9,
            "nameAlert": True,
        },
    }
    map_message = internal_to_ui(
        {
            "type": "map",
            "time": 2.0,
            "hexes": [{"axial": {"q": 1, "r": -2}, "owner": "p1", "opacity": 0.5, "share": 0.8, "contested": False}],
        }
    )
    assert map_message["hexes"] == [{"q": 1, "r": -2, "ownerId": "p1", "opacity": 0.5, "share": 0.8, "contested": False}]
    assert internal_to_ui({"type": "phase", "phase": "refine"}) is None
    refined = internal_to_ui(
        {
            "type": "refined",
            "changedCount": 1,
            "totalCount": 2,
            "topics": ["demo"],
            "summary": {"summary": "Done", "actionItems": ["Ship"]},
            "turns": [{"id": "turn_0001", "speakerId": "p1", "text": "Hi", "start": 0, "end": 1, "confidence": 1, "tags": []}],
        }
    )
    assert refined["refined"]["correctedTurns"] == 1
    assert refined["refined"]["turns"][0]["personId"] == "p1"
