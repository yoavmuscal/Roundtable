"""Microphone RMS monitoring and WAV recording for the live Mac path."""

from __future__ import annotations

import asyncio
import math
import wave
from pathlib import Path
from typing import Awaitable, Callable

LevelCallback = Callable[[float, float, float], Awaitable[None]]  # session time, RMS, peak


class WavRecorder:
    def __init__(self, path: Path, sample_rate: int = 16_000, channels: int = 1) -> None:
        self.path = path
        self.sample_rate = sample_rate
        self.channels = channels
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = wave.open(str(path), "wb")
        self._file.setnchannels(channels)
        self._file.setsampwidth(2)
        self._file.setframerate(sample_rate)
        self.frames_written = 0

    def write(self, pcm: bytes) -> None:
        self._file.writeframesraw(pcm)
        self.frames_written += len(pcm) // (2 * self.channels)

    def close(self) -> None:
        self._file.close()


class MicrophoneLevelMonitor:
    """20 Hz microphone RMS/peak callback plus optional WAV recording."""

    def __init__(
        self,
        callback: LevelCallback,
        wav_path: Path | None = None,
        sample_rate: int = 16_000,
    ) -> None:
        self.callback = callback
        self.sample_rate = sample_rate
        self.recorder = WavRecorder(wav_path, sample_rate) if wav_path else None
        self.stream = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.started_monotonic = 0.0

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.started_monotonic = self.loop.time()
        # time.monotonic() matches asyncio's loop clock on macOS/Linux; kept for WAV alignment.
        self.started_wall_monotonic = __import__('time').monotonic()
        try:
            import sounddevice as sd
        except ImportError as exc:
            if self.recorder:
                self.recorder.close()
            raise RuntimeError("sounddevice is required for live microphone capture") from exc

        def audio_callback(indata, frames: int, _time_info, status) -> None:  # noqa: ANN001
            if status:
                # Keep processing; PortAudio status is often an overflow warning.
                pass
            pcm = bytes(indata)
            if self.recorder:
                self.recorder.write(pcm)
            rms, peak = pcm16_levels(pcm)
            if self.loop:
                session_time = self.loop.time() - self.started_monotonic
                self.loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self.callback(session_time, rms, peak))
                )

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.sample_rate // 20,
            callback=audio_callback,
        )
        self.stream.start()

    async def stop(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None


def pcm16_levels(pcm: bytes) -> tuple[float, float]:
    if len(pcm) < 2:
        return 0.0, 0.0
    count = len(pcm) // 2
    sum_squares = 0
    peak = 0
    for offset in range(0, count * 2, 2):
        value = int.from_bytes(pcm[offset:offset + 2], "little", signed=True)
        magnitude = abs(value)
        peak = max(peak, magnitude)
        sum_squares += value * value
    return math.sqrt(sum_squares / count) / 32768.0, peak / 32768.0
