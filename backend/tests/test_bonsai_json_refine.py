import asyncio

import pytest

from backend.app.bonsai import BonsaiWorker, JsonSchemaError, TAG_SCHEMA, extract_json_value, validate_json_schema
from backend.app.models import Turn
from backend.app.refine import (
    match_clusters_to_people,
    parse_speakerkit_output,
    refine_turns,
    SpeakerSegment,
)


def test_json_plain_think_fences_prose_and_escaped_quotes() -> None:
    schema = {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}
    value = extract_json_value(
        '<think>ignore {"bad": true}</think> prose { "text": "hello {\\"quoted\\"} world" } tail'
    )
    assert value == {"text": 'hello {"quoted"} world'}
    validate_json_schema(value, schema)
    fenced = extract_json_value('```json\n{"text":"ok"}\n```')
    assert fenced["text"] == "ok"


def test_unterminated_think_and_no_json_fail_cleanly() -> None:
    with pytest.raises(JsonSchemaError):
        extract_json_value('<think>never ends')
    with pytest.raises(JsonSchemaError):
        extract_json_value("no object here")


def test_schema_validation() -> None:
    with pytest.raises(JsonSchemaError):
        validate_json_schema({"tags": [], "repliesTo": None}, TAG_SCHEMA)
    with pytest.raises(JsonSchemaError):
        validate_json_schema({"tags": [], "repliesTo": 3, "actionOwner": None}, TAG_SCHEMA)


@pytest.mark.asyncio
async def test_bonsai_worker_prioritizes_ask_name_tag_layout() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    class BlockingClient:
        async def generate_json(self, task, payload, schema, timeout_s):
            calls.append(task)
            if task == "blocking":
                started.set()
                await release.wait()
            return {}

    worker = BonsaiWorker(BlockingClient())
    first = asyncio.create_task(worker.submit("blocking", {}, {}, 1))
    await started.wait()
    layout = asyncio.create_task(worker.submit("layout", {}, {}, 1))
    tag = asyncio.create_task(worker.submit("tag", {}, {}, 1))
    name = asyncio.create_task(worker.submit("name", {}, {}, 1))
    ask = asyncio.create_task(worker.submit("ask", {}, {}, 1))
    release.set()
    await asyncio.gather(first, layout, tag, name, ask)
    await worker.stop()
    assert calls == ["blocking", "ask", "name", "tag", "layout"]


def test_parse_speakerkit_jsonl_and_plain_lines() -> None:
    output = '{"start":0,"end":2,"speaker":"A"}\n2.5 4.0 B\n'
    assert parse_speakerkit_output(output) == [SpeakerSegment(0, 2, "A"), SpeakerSegment(2.5, 4, "B")]


def test_cluster_matching_by_enrollment_then_refine_and_split() -> None:
    segments = [SpeakerSegment(0, 2, "A"), SpeakerSegment(2, 4, "B")]
    mapping = match_clusters_to_people(
        segments,
        {"p1": [(0, 1)], "p2": [(2.5, 3)]},
    )
    assert mapping == {"A": "p1", "B": "p2"}
    live = [Turn("turn_0001", "p1", "one two three four", 0, 4, 0.9)]
    result = refine_turns(live, segments, mapping)
    assert result.changed_count == 1
    assert len(result.turns) == 2
    assert result.turns[0].speaker_id == "p1"
    assert result.turns[1].speaker_id == "p2"
    assert result.turns[0].text.split() == ["one", "two"]
    assert result.turns[1].text.split() == ["three", "four"]
