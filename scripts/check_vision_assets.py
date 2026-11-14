"""Verify all browser vision assets are present before an offline demo."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = (
    ROOT / "public/vision/wasm/vision_wasm_internal.js",
    ROOT / "public/vision/wasm/vision_wasm_internal.wasm",
    ROOT / "public/vision/models/face_landmarker.task",
    ROOT / "public/vision/models/pose_landmarker_lite.task",
)

missing = [path for path in ASSETS if not path.is_file() or path.stat().st_size < 100_000]
if missing:
    for path in missing:
        print(f"missing or too small: {path}")
    raise SystemExit(1)
print(f"vision assets ready ({len(ASSETS)} files)")
