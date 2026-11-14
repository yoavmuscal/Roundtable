"""argmax-cli stream parsing and transcript turn construction."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from .contract import turn_id
from .models import Turn

ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
NOISE_RE = re.compile(
    r"^(listening|loading|model|device|whisper|speakers?|transcribing audio|waiting for speech|task:|initializing|\[argmax-cli\])",
    re.IGNORECASE,
)
# Whisper control tokens such as <|startoftranscript|>, <|en|>, <|7.44|>.
SPECIAL_TOKEN_RE = re.compile(r"<\|[^|>]*\|>")
# Non-speech annotations Whisper emits: [BLANK_AUDIO], [ Inaudible Remark ], (music), *coughs*.
NON_SPEECH_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")
# argmax-cli --stream prints blocks separated by '---' with these labelled lines.
BLOCK_LINE_RE = re.compile(r"^(Confirmed segment|Unconfirmed segment|Current text):\s?(.*)$")
CONFIRMED_RE = re.compile(r"^(?:final|confirmed|stable)\s*[:\]]\s*", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class TranscriptCommit:
    words: tuple[str, ...]
    time: float
    explicit: bool = False
    # When the words were actually spoken (Argmax confirms a few seconds later).
    spoken_start: float | None = None
    spoken_end: float | None = None


class StreamingTranscriptParser:
    """Commit words only when consecutive stream snapshots agree."""

    def __init__(self, silence_flush_s: float = 0.8) -> None:
        self.silence_flush_s = silence_flush_s
        self.previous_words: tuple[str, ...] = ()
        self.committed_words: list[str] = []
        self.partial_words: tuple[str, ...] = ()
        self.last_update: float | None = None
        self.block_mode = False
        self._buffer = ""
        # When Argmax keeps running across sessions it reprints everything it already
        # confirmed; the first block after a reset only sets the baseline.
        self.baseline_pending = False
        self._segments_seen = 0  # confirmed segments already consumed (Argmax reprints all of them)
        self._flushed: list[str] = []  # words committed by the silence flush, not yet confirmed
        self._speech_start: float | None = None
        self._speech_last: float | None = None

    def feed_chunk(self, chunk: bytes | str, time_s: float) -> list[TranscriptCommit]:
        text = chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else chunk
        if self.block_mode or "Current text:" in text or "segment:" in text:
            # argmax-cli (whisperkit-cli) --stream format: explicit confirmed segments.
            if not self.block_mode:
                # WhisperKit confirms segments itself, even through silence, so the
                # partial-word flush is only a fallback and waits longer to avoid
                # committing a hypothesis that the next window rewrites.
                self.silence_flush_s = max(self.silence_flush_s, 2.0)
            self.block_mode = True
            self._buffer += ANSI_RE.sub("", text).replace("\r", "\n")
            return self._drain_blocks(time_s)
        commits: list[TranscriptCommit] = []
        for line in re.split(r"[\r\n]+", text):
            commits.extend(self.feed_snapshot(line, time_s))
        return commits

    def _drain_blocks(self, time_s: float) -> list[TranscriptCommit]:
        parts = self._buffer.split("---\n")
        complete = parts[:-1]
        tail = parts[-1]
        # A block is also complete once its 'Current text' line has ended.
        if re.search(r"^Current text:.*\n", tail, flags=re.MULTILINE):
            complete.append(tail)
            tail = ""
        self._buffer = tail
        # Every block repeats the full confirmed history, so only the newest one matters.
        labelled = [block for block in complete if "segment:" in block or "Current text:" in block]
        return self.feed_block(labelled[-1], time_s) if labelled else []

    def feed_block(self, block: str, time_s: float) -> list[TranscriptCommit]:
        """Parse one argmax-cli stream block; confirmed segments commit immediately.

        argmax-cli reprints every confirmed segment since it started, so new text is read
        by segment count rather than re-aligned (re-alignment re-added the whole history
        whenever a flushed hypothesis differed from what Argmax later confirmed).
        """
        confirmed_raw: list[str] = []
        unconfirmed: list[str] = []
        current = ""
        seen = False
        for raw_line in block.splitlines():
            match = BLOCK_LINE_RE.match(raw_line.strip())
            if not match:
                continue
            seen = True
            label, value = match.groups()
            if label == "Confirmed segment":
                confirmed_raw.append(value)  # cleaned lazily: only new segments matter
            elif label == "Unconfirmed segment":
                unconfirmed.append(clean_whisper_text(value))
            else:
                current = clean_whisper_text(value)
        if not seen:
            return []
        if self.baseline_pending:
            # Text confirmed before this session (e.g. during enrollment) is not replayed.
            self.baseline_pending = False
            self._segments_seen = len(confirmed_raw)
        if len(confirmed_raw) < self._segments_seen:
            self._segments_seen = len(confirmed_raw)  # the CLI restarted or trimmed its window
        new_segments = [clean_whisper_text(value) for value in confirmed_raw[self._segments_seen:]]
        self._segments_seen = len(confirmed_raw)
        new_words = tuple(" ".join(new_segments).split())
        if new_words and self._flushed:
            # Skip what the silence flush already showed, if Argmax confirmed it the same way.
            matched = 0
            for flushed, confirmed in zip(self._flushed, new_words):
                if _norm(flushed) != _norm(confirmed):
                    break
                matched += 1
            new_words = new_words[matched:]
            self._flushed = []
        commits: list[TranscriptCommit] = []
        pending = " ".join(item for item in unconfirmed if item) or current
        partial = tuple(pending.split())
        if new_words:
            self.committed_words.extend(new_words)
            spoken_start = self._speech_start if self._speech_start is not None else time_s
            spoken_end = self._speech_last if self._speech_last is not None else time_s
            commits.append(TranscriptCommit(new_words, time_s, True, spoken_start, max(spoken_start, spoken_end)))
            # Anything still unconfirmed was said after the words just confirmed.
            self._speech_start = spoken_end if partial else None
        if partial != self.partial_words or new_words:
            # Only real changes count as activity, so repeated identical blocks during
            # silence let the fallback flush fire.
            self.last_update = time_s
            if partial:
                if self._speech_start is None:
                    self._speech_start = time_s
                self._speech_last = time_s
        self.partial_words = partial
        self.previous_words = tuple(self.committed_words) + partial
        return commits

    def feed_snapshot(self, line: str, time_s: float) -> list[TranscriptCommit]:
        clean = _clean_line(line)
        if not clean:
            return []
        explicit = bool(CONFIRMED_RE.match(clean))
        clean = CONFIRMED_RE.sub("", clean)
        words = tuple(clean.split())
        if not words:
            return []

        total_words = self._align_reprint(words)
        stable_count = _common_prefix_count(self.previous_words, total_words)
        if explicit:
            stable_count = len(total_words)
        stable_count = max(len(self.committed_words), stable_count)
        new_words = tuple(total_words[len(self.committed_words):stable_count])
        self.committed_words.extend(new_words)
        self.partial_words = tuple(total_words[stable_count:])
        self.previous_words = total_words
        self.last_update = time_s
        return [TranscriptCommit(new_words, time_s, explicit)] if new_words else []

    def flush_due(self, now_s: float) -> TranscriptCommit | None:
        if self.last_update is None or now_s - self.last_update < self.silence_flush_s:
            return None
        return self.flush(now_s)

    def flush(self, now_s: float) -> TranscriptCommit | None:
        if not self.partial_words:
            return None
        words = self.partial_words
        self.committed_words.extend(words)
        self.partial_words = ()
        self.previous_words = tuple(self.committed_words)
        self.last_update = now_s
        spoken_start, spoken_end = self._speech_start, self._speech_last
        if self.block_mode:
            self._flushed.extend(words)
            self._speech_start = None
            self._speech_last = None
        return TranscriptCommit(words, now_s, True, spoken_start, spoken_end)

    def _align_reprint(self, words: tuple[str, ...]) -> tuple[str, ...]:
        committed = tuple(self.committed_words)
        if words[: len(committed)] == committed:
            return committed + words[len(committed):]
        # A CLI may redraw only the active suffix. Align the largest committed
        # suffix with the snapshot prefix so each new phrase is appended once.
        max_overlap = min(len(committed), len(words))
        for overlap in range(max_overlap, -1, -1):
            if overlap == 0 or committed[-overlap:] == words[:overlap]:
                return committed + words[overlap:]
        return committed + words


class TranscriptTurnBuilder:
    """Split committed words into turns on silence gaps or fusion speaker changes."""

    def __init__(self, gap_s: float = 1.2) -> None:
        self.gap_s = gap_s
        self.current_words: list[str] = []
        self.current_speaker: str | None = None
        self.current_start: float | None = None
        self.last_word_time: float | None = None
        self.sequence = 0
        self.confidence = 0.0

    def add_words(
        self,
        words: tuple[str, ...] | list[str],
        time_s: float,
        speaker_id: str | None,
        confidence: float = 0.0,
    ) -> Turn | None:
        if not words:
            return None
        should_split = (
            self.current_words
            and (
                speaker_id != self.current_speaker
                or (self.last_word_time is not None and time_s - self.last_word_time > self.gap_s)
            )
        )
        completed = self.end_turn(time_s) if should_split else None
        if self.current_start is None:
            self.current_start = time_s
            self.current_speaker = speaker_id
            self.confidence = confidence
        self.current_words.extend(words)
        self.last_word_time = time_s
        self.confidence = max(self.confidence, confidence)
        return completed

    def end_turn(self, end_s: float | None = None) -> Turn | None:
        if not self.current_words or self.current_start is None:
            return None
        self.sequence += 1
        turn = Turn(
            id=turn_id(self.sequence),
            speaker_id=self.current_speaker,
            text=" ".join(self.current_words),
            start=self.current_start,
            end=end_s if end_s is not None else (self.last_word_time or self.current_start),
            confidence=self.confidence,
        )
        self.current_words = []
        self.current_speaker = None
        self.current_start = None
        self.last_word_time = None
        self.confidence = 0.0
        return turn


class ArgmaxTranscriberAdapter:
    """Run argmax-cli as a raw-byte child process and parse redrawn snapshots."""

    def __init__(self, command: list[str], cwd: str | Path | None = None) -> None:
        self.command = command
        self.cwd = Path(cwd) if cwd else None
        self.process: asyncio.subprocess.Process | None = None

    async def stream(self) -> AsyncIterator[tuple[float, bytes]]:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["NSUnbufferedIO"] = "YES"
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            cwd=self.cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if self.process.stdout is None:
            raise RuntimeError("argmax-cli stdout was not piped")
        loop = asyncio.get_running_loop()
        while True:
            chunk = await self.process.stdout.read(256)
            if not chunk:
                break
            yield loop.time(), chunk

    async def stop(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()


def clean_whisper_text(text: str) -> str:
    """Strip Whisper control tokens, non-speech tags and '>>' turn markers."""
    clean = SPECIAL_TOKEN_RE.sub(" ", text)
    clean = NON_SPEECH_RE.sub(" ", clean)
    # A tag still being decoded, e.g. "[ Inaudible Rem", has no closing bracket yet.
    clean = re.sub(r"[\[(*][^\])*]*$", " ", clean)
    clean = clean.replace(">>", " ")
    clean = re.sub(r"\s+", " ", clean).strip()
    # Status text the CLI prints in the 'Current text' slot before any speech.
    if clean.lower().rstrip(".…") in {"waiting for speech", "listening"}:
        return ""
    return clean


def _clean_line(line: str) -> str:
    clean = ANSI_RE.sub("", line).replace("\u001b", "").strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean or NOISE_RE.search(clean):
        return ""
    if clean in {"[", "]", "{", "}"}:
        return ""
    return clean


def _norm(word: str) -> str:
    return re.sub(r"[^\w']", "", word).lower()


def _common_prefix_count(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    count = 0
    for left, right in zip(a, b):
        if left != right:
            break
        count += 1
    return count
