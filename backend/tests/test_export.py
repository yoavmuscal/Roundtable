from pathlib import Path

from backend.app.export import (
    ExportTurn,
    ass_color,
    build_ass,
    chunk_text,
    escape_ass,
    export_session_ass,
    ffmpeg_export_command,
    format_ass_time,
    push_overlaps_apart,
)


def test_ass_time_color_chunks_and_escaping() -> None:
    assert format_ass_time(3661.234) == "1:01:01.23"
    assert ass_color("#8B7CF6") == "&HF67C8B"
    assert chunk_text("one two three four five six seven eight nine ten", max_chars=12, max_lines=2)
    assert escape_ass("a\\{b}\n c") == r"a\\\{b\}\N c"


def test_overlapping_captions_are_pushed_apart() -> None:
    events = [
        {"start": 0, "end": 2, "y": 500},
        {"start": 1, "end": 3, "y": 520},
    ]
    push_overlaps_apart(events)
    assert abs(events[1]["y"] - events[0]["y"]) >= 72


def test_build_ass_uses_speaker_colors_positions_and_first_chunk_tags() -> None:
    turns = [
        ExportTurn("turn_0001", "p1", "hello world this is a long caption for export", 0, 2, ("decision",)),
        ExportTurn("turn_0002", "p2", "second speaker", 0.5, 1.5),
    ]
    anchors = [
        {"time": 0, "anchors": {"p1": {"point": {"x": 0.25, "y": 0.5}}}},
        {"time": 1, "anchors": {"p1": {"point": {"x": 0.75, "y": 0.5}}}},
    ]
    ass = build_ass(turns, anchors)
    assert "Style: p1" in ass
    assert "&HF67C8B" in ass
    assert "[decision]" in ass
    assert "\\pos(960,540)" in ass
    assert ass.count("Dialogue:") >= 2


def test_export_session_and_ffmpeg_command(tmp_path: Path) -> None:
    (tmp_path / "metadata.json").write_text(
        '{"people":[{"id":"p1","color":"#8B7CF6"}]}', encoding="utf-8"
    )
    (tmp_path / "refined_transcript.jsonl").write_text(
        '{"id":"turn_0001","speakerId":"p1","text":"hello","start":0,"end":1,"tags":[]}\n',
        encoding="utf-8",
    )
    output = export_session_ass(tmp_path)
    assert output.exists()
    command = ffmpeg_export_command(tmp_path / "video.webm", tmp_path / "audio.wav", output, tmp_path / "out.mp4", 0.25)
    assert "fps=30" in command[command.index("-vf") + 1]
    assert command[command.index("-itsoffset") + 1] == "0.250"
