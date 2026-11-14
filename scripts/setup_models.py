"""One-time Mac setup for the on-device models (Argmax WhisperKit/SpeakerKit + Bonsai 2 2B).

Run with `npm run setup:models`. Safe to re-run: every step is skipped when already done.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BONSAI_REPO = "prism-ml/Ternary-Bonsai-2-2B-mlx-2bit"
BONSAI_DIR = ROOT / "models" / "bonsai2-2b-mlx"
WHISPER_MODEL = "base"


def step(title: str) -> None:
    print(f"\n== {title}")


def main() -> int:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        print("Argmax and Bonsai run only on the Apple Silicon demo Mac. Use `npm run backend` (sim mode) here.")
        return 0

    step("Argmax CLI (WhisperKit + SpeakerKit)")
    binary = shutil.which("argmax-cli") or shutil.which("whisperkit-cli")
    if not binary:
        if not shutil.which("brew"):
            print("Homebrew is missing. Install it, then run: brew install whisperkit-cli")
            return 1
        subprocess.run(["brew", "install", "whisperkit-cli"], check=True)
        binary = shutil.which("whisperkit-cli")
    print(f"using {binary}")

    step(f"Whisper '{WHISPER_MODEL}' model (downloads once, ~150 MB)")
    probe = ROOT / "sessions" / "setup-probe.wav"
    probe.parent.mkdir(exist_ok=True)
    with wave.open(str(probe), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    subprocess.run([binary, "transcribe", "--model", WHISPER_MODEL, "--audio-path", str(probe)], check=True, capture_output=True)
    step("SpeakerKit diarization model")
    subprocess.run([binary, "diarize", "--audio-path", str(probe)], check=True, capture_output=True)
    probe.unlink(missing_ok=True)
    print("ready")

    step("Python packages (mlx-vlm, sounddevice)")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")], check=True)

    step(f"Bonsai 2 2B weights -> {BONSAI_DIR.relative_to(ROOT)} (~1.2 GB)")
    if (BONSAI_DIR / "model.safetensors").exists():
        print("already downloaded")
    else:
        from huggingface_hub import snapshot_download

        snapshot_download(BONSAI_REPO, local_dir=str(BONSAI_DIR))
        print("downloaded")

    print("\nAll on-device models are ready. Start everything with: npm run live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
