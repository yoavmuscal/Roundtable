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


def test_argmax_block_format_commits_confirmed_segments_only() -> None:
    sample = (Path(__file__).parent / "fixtures" / "argmax-stream-sample.txt").read_text()
    parser = StreamingTranscriptParser()
    commits = []
    # Feed in small pieces to mimic raw pipe reads that split blocks anywhere.
    for index in range(0, len(sample), 37):
        commits.extend(parser.feed_chunk(sample[index:index + 37], index / 100))
    words = [word for commit in commits for word in commit.words]
    assert words == "Should we spend the credits on Kimi now? Use them now.".split()
    assert all(commit.explicit for commit in commits)
    assert parser.partial_words == ()


def test_argmax_block_partials_and_silence_flush() -> None:
    parser = StreamingTranscriptParser()
    block = (
        "---\nUnconfirmed segment: <|startoftranscript|><|en|><|transcribe|><|0.00|> >> Hello there<|1.0|>\n"
        "Current text: \n"
    )
    assert parser.feed_chunk(block, 1.0) == []
    assert parser.partial_words == ("Hello", "there")
    # Identical blocks during silence do not count as activity, so the fallback flush
    # fires; in block mode it waits 2 s because WhisperKit normally confirms first.
    parser.feed_chunk(block, 1.5)
    assert parser.flush_due(2.5) is None
    commit = parser.flush_due(3.1)
    assert commit is not None and commit.words == ("Hello", "there")
    # When the CLI later confirms the same words they are not committed twice.
    confirmed = "---\nConfirmed segment: <|0.00|> Hello there<|1.0|>\nCurrent text: \n"
    assert parser.feed_chunk(confirmed, 3.5) == []
    assert parser.committed_words == ["Hello", "there"]


def test_argmax_flush_does_not_repeat_when_whisper_revises_unconfirmed_words() -> None:
    parser = StreamingTranscriptParser()
    first = (
        "---\nUnconfirmed segment: <|0.00|> I am talking do I have to really enunciate what I say<|4.0|>\n"
        "Current text: \n"
    )
    parser.feed_chunk(first, 1.0)
    flushed = parser.flush_due(3.5)
    assert flushed is not None
    # Next stream block extends the unconfirmed line and slightly rewrites one word.
    extended = (
        "---\nUnconfirmed segment: <|0.00|> I am talking do I have to really eat non ca what I say during the demo<|6.0|>\n"
        "Current text: \n"
    )
    assert parser.feed_chunk(extended, 4.0) == []
    assert parser.partial_words == ("during", "the", "demo")
    confirmed = (
        "---\nConfirmed segment: <|0.00|> I am talking do I have to really eat non ca what I say during the demo<|6.0|>\n"
        "Current text: \n"
    )
    commits = parser.feed_chunk(confirmed, 5.0)
    assert [w for c in commits for w in c.words] == ["during", "the", "demo"]


def test_clean_whisper_text_strips_tokens_and_non_speech() -> None:
    from backend.app.transcribe import clean_whisper_text

    assert clean_whisper_text("<|startoftranscript|><|en|><|0.00|> [BLANK_AUDIO]<|7.44|>") == ""
    assert clean_whisper_text("<|7.44|> >> Okay, Yoav (laughs) let's go.<|9.0|>") == "Okay, Yoav let's go."


def test_waiting_for_speech_is_not_a_caption() -> None:
    parser = StreamingTranscriptParser()
    parser.feed_chunk("Transcribing audio stream, press Ctrl+C to stop.\n---\nCurrent text: Waiting for speech...\n", 0.0)
    assert parser.partial_words == ()
    assert parser.flush(2.0) is None


def test_baseline_skips_text_confirmed_before_the_session() -> None:
    parser = StreamingTranscriptParser()
    parser.baseline_pending = True
    earlier = "---\nConfirmed segment: <|0.00|> Roundtable keeps this conversation private.<|2.0|>\nCurrent text: \n"
    assert parser.feed_chunk(earlier, 0.0) == []
    later = (
        "---\nConfirmed segment: <|0.00|> Roundtable keeps this conversation private.<|2.0|>\n"
        "Confirmed segment: <|0.00|> Any thoughts on the demo?<|2.0|>\nCurrent text: \n"
    )
    commits = parser.feed_chunk(later, 1.0)
    assert [word for commit in commits for word in commit.words] == "Any thoughts on the demo?".split()
