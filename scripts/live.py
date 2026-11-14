"""Start the full on-device stack: Bonsai 2 2B on :8080 and the live backend + UI on :8000.

`npm run live` builds the UI first; `npm run live:dev` skips the build so you can use
`npm run dev` on :5173 alongside it. Ctrl+C stops every child process.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BONSAI_DIR = ROOT / "models" / "bonsai2-2b-mlx"


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_for(url: str, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--whisper-model", default=os.environ.get("ROUNDTABLE_WHISPER_MODEL", "base"))
    parser.add_argument("--session", default="sessions/live")
    args = parser.parse_args()

    if not (shutil.which("argmax-cli") or shutil.which("whisperkit-cli")):
        print("Argmax CLI not found. Run `npm run setup:models` first.")
        return 1
    if port_open(8000):
        print("Port 8000 is already in use (another backend is running). Stop it first.")
        return 1

    children: list[subprocess.Popen[bytes]] = []
    if port_open(8080):
        print("Bonsai: reusing the server already on :8080")
    elif not (BONSAI_DIR / "model.safetensors").exists():
        print("Bonsai weights missing. Run `npm run setup:models` first.")
        return 1
    else:
        print("Bonsai: starting Bonsai 2 2B on :8080 …")
        children.append(
            subprocess.Popen(
                [sys.executable, "-m", "mlx_vlm.server", "--model", str(BONSAI_DIR), "--host", "127.0.0.1", "--port", "8080"],
                cwd=ROOT,
            )
        )
        if not wait_for("http://127.0.0.1:8080/v1/models", 90):
            print("Bonsai did not come up within 90 s; continuing (Q&A and summaries will report it offline).")

    env = dict(os.environ, ROUNDTABLE_WHISPER_MODEL=args.whisper_model)
    print("Backend: live mode — open http://localhost:8000 (Argmax WhisperKit streaming + SpeakerKit refine)")
    children.append(
        subprocess.Popen(
            [sys.executable, "-m", "backend.app.server", "--mode", "live", "--session", args.session],
            cwd=ROOT,
            env=env,
        )
    )

    def shutdown(*_: object) -> None:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    while True:
        for child in children:
            if child.poll() is not None:
                print(f"{child.args[2] if len(child.args) > 2 else child.args} exited; stopping.")
                shutdown()
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
