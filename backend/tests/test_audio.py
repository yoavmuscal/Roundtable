import wave
from pathlib import Path

import pytest

from backend.app.audio import WavRecorder, pcm16_levels


def test_pcm16_levels() -> None:
    silence = b"\x00\x00" * 100
    assert pcm16_levels(silence) == (0.0, 0.0)
    alternating = b"".join((16384).to_bytes(2, "little", signed=True) for _ in range(100))
    rms, peak = pcm16_levels(alternating)
    assert rms == pytest.approx(0.5)
    assert peak == pytest.approx(0.5)


def test_wav_recorder_writes_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "audio.wav"
    recorder = WavRecorder(path)
    recorder.write(b"\x00\x00" * 160)
    recorder.close()
    with wave.open(str(path), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 1
        assert wav.getnframes() == 160
