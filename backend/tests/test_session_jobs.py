import pytest

from backend.app.bonsai import BonsaiWorker, MockBonsaiClient
from backend.app.models import Turn
from backend.app.session import SessionEngine


@pytest.mark.asyncio
async def test_bonsai_tags_refined_turns_and_answers_with_citations() -> None:
    worker = BonsaiWorker(MockBonsaiClient(failure_rate=0.0))
    engine = SessionEngine(bonsai=worker)
    turns = [Turn("turn_0001", "p1", "What should we do?", 0, 1, 0.9)]
    tagged = await engine.tag_turns(turns)
    assert tagged[0].tags == ["question"]
    engine.turns = tagged
    answer = await engine.ask("What was decided?")
    assert answer["type"] == "answer"
    assert answer["citedTurnIds"] == ["turn_0001"]
    await worker.stop()
