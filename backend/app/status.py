"""Cross-platform local status without any runtime network probe."""

from __future__ import annotations

import os
import platform
from ctypes import Structure, c_ulong, c_ulonglong, sizeof
from typing import Any


def memory_status() -> dict[str, float | None]:
    if platform.system() == "Windows":
        class MemoryStatus(Structure):
            _fields_ = [
                ("length", c_ulong),
                ("memory_load", c_ulong),
                ("total_physical", c_ulonglong),
                ("available_physical", c_ulonglong),
                ("total_page_file", c_ulonglong),
                ("available_page_file", c_ulonglong),
                ("total_virtual", c_ulonglong),
                ("available_virtual", c_ulonglong),
                ("available_extended_virtual", c_ulonglong),
            ]

        from ctypes import windll

        status = MemoryStatus()
        status.length = sizeof(MemoryStatus)
        if not windll.kernel32.GlobalMemoryStatusEx(status):
            return {"ramGb": None, "ramTotalGb": None}
        total = float(status.total_physical) / 1e9
        available = float(status.available_physical) / 1e9
        return {"ramGb": round(total - available, 2), "ramTotalGb": round(total, 2)}
    if platform.system() == "Darwin":
        return _macos_memory()
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        total = pages * page_size / 1e9
        available = available_pages * page_size / 1e9
        return {"ramGb": round(total - available, 2), "ramTotalGb": round(total, 2)}
    except (OSError, ValueError, AttributeError):
        return {"ramGb": None, "ramTotalGb": None}


def status_message(
    *,
    model: str,
    seconds_per_turn: float | None,
    network: str | None = None,
) -> dict[str, Any]:
    memory = memory_status()
    network_state = network or os.environ.get("ROUNDTABLE_NETWORK", "none")
    ram = memory["ramGb"]
    health = "ok" if ram is None or ram < 7.0 else "amber"
    return {
        "model": model,
        "secondsPerTurn": seconds_per_turn,
        "ramGb": ram,
        "ramTotalGb": memory["ramTotalGb"],
        "network": network_state,
        "health": health,
    }


def _macos_memory() -> dict[str, float | None]:
    """Activity Monitor's 'Memory Used' = app (active) + wired + compressed pages."""
    import re
    import subprocess

    try:
        total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2).stdout.strip())
        output = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"ramGb": None, "ramTotalGb": None}
    page_match = re.search(r"page size of (\d+) bytes", output)
    page_size = int(page_match.group(1)) if page_match else 16384

    def pages(label: str) -> int:
        match = re.search(rf"{label}:\s+(\d+)", output)
        return int(match.group(1)) if match else 0

    used = (pages("Pages active") + pages("Pages wired down") + pages("Pages occupied by compressor")) * page_size
    return {"ramGb": round(used / 1e9, 2), "ramTotalGb": round(total / 1e9, 2)}
