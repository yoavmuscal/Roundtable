from pathlib import Path

import pytest

from backend.app.fake_session import generate_session
from backend.app.simulation import run_simulation


@pytest.mark.asyncio
async def test_sim_mode_reprocesses_inputs_through_real_backend(tmp_path: Path) -> None:
    source = tmp_path / "source"
    generate_session(source, include_video=False)
    engine = await run_simulation(source)
    assert len(engine.turns) == 16
    assert all(turn.speaker_id in {"p1", "p2", "p3"} for turn in engine.turns)
    assert engine.turns[-1].text.endswith("acceptance list?")
    assert engine.questions.snapshot(91)["openCount"] == 1
    assert engine.name_alerts.alerted_turns
