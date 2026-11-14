from pathlib import Path

import pytest

from backend.app.transcribe import StreamingTranscriptParser, TranscriptTurnBuilder


def committed(parser: StreamingTranscriptParser) -> str:
    return " ".join(parser.committed_words)


def test_cr_redraws_and_ansi_are_cleaned_with_local_agreement() -> None:
    parser = StreamingTranscriptParser()
    assert parser.feed_chunk("\x1b[2Khello\r", 0.0) == []
    commits = parser.feed_chunk("\x1b[2Khello world\n", 0.1)
    assert [word for commit in commits for word in commit.words] == ["hello"]
    commits = parser.feed_chunk("hello world again\r", 0.2)
    assert [word for commit in commits for word in commit.words] == ["world"]
    assert committed(parser) == "hello world"
    assert parser.partial_words == ("again",)


def test_full_transcript_reprint_commits_stable_prefix() -> None:
    parser = StreamingTranscriptParser()
    parser.feed_snapshot("hello", 0.0)
    parser.feed_snapshot("hello there", 0.1)
    parser.feed_snapshot("hello there team", 0.2)
    parser.feed_snapshot("hello there team", 0.3)
    assert committed(parser) == "hello there team"


def test_flush_after_silence_and_stop() -> None:
    parser = StreamingTranscriptParser(silence_flush_s=0.8)
    parser.feed_snapshot("one two", 0.0)
    assert parser.flush_due(0.7) is None
    commit = parser.flush_due(0.9)
    assert commit is not None
    assert commit.words == ("one", "two")
    parser.feed_snapshot("tail", 2.0)
    assert parser.flush(3.0).words == ("tail",)  # type: ignore[union-attr]


@pytest.mark.skipif(
    not (Path(__file__).parent / "fixtures" / "argmax-stream-sample.txt").exists(),
    reason="waiting for Yoav's raw argmax-cli streaming sample",
)
def test_real_argmax_stream_sample() -> None:
    sample = (Path(__file__).parent / "fixtures" / "argmax-stream-sample.txt").read_bytes()
    parser = StreamingTranscriptParser()
    commits = parser.feed_chunk(sample, 0.0)
    parser.flush(1.0)
    assert parser.committed_words or commits


def test_turn_builder_splits_12_second_gap_and_speaker_change() -> None:
    builder = TranscriptTurnBuilder()
    assert builder.add_words(("hello",), 0.0, "p1", 0.8) is None
    turn = builder.add_words(("after",), 1.3, "p1", 0.8)
    assert turn is not None
    assert turn.text == "hello"
    turn = builder.add_words(("speaker",), 1.5, "p2", 0.8)
    assert turn is not None
    assert turn.text == "after"
    final = builder.end_turn(2.0)
    assert final is not None
    assert final.speaker_id == "p2"
    assert final.id == "turn_0003"
