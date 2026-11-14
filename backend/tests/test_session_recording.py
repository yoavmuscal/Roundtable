import json
from pathlib import Path

from backend.app.session import SessionEngine


def _feed_stable_words(engine: SessionEngine) -> None:
    # Two agreeing snapshots commit words into the current turn.
    engine.handle_transcript_chunk("hello there\n", 0.1)
    engine.handle_transcript_chunk("hello there friend\n", 0.2)


def test_stop_records_flushed_messages_exactly_once(tmp_path: Path) -> None:
    engine = SessionEngine(session_dir=tmp_path / "live")
    _feed_stable_words(engine)
    messages = engine.stop(1.0)
    assert messages  # stop flushed a finalized turn plus the phase change

    events = [
        json.loads(line)
        for line in (tmp_path / "live" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Every flushed message must appear exactly once; stop() must not re-record
    # messages that flush_transcript() already recorded.
    serialized = [json.dumps(event, sort_keys=True) for event in events]
    assert len(serialized) == len(set(serialized))
    for message in messages:
        key = json.dumps(message, sort_keys=True)
        assert serialized.count(key) == 1


def test_stop_writes_session_artifacts(tmp_path: Path) -> None:
    session = tmp_path / "live"
    engine = SessionEngine(session_dir=session)
    _feed_stable_words(engine)
    engine.stop(1.0)
    assert (session / "live_transcript.jsonl").exists()
    assert (session / "anchors.jsonl").exists()
    assert (session / "metadata.json").exists()
