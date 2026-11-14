"""Bonsai JSON reliability ladder, mock model, and single priority worker."""

from __future__ import annotations

import asyncio
import itertools
import json
import random
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


class BonsaiError(RuntimeError):
    pass


class JsonSchemaError(BonsaiError):
    pass


class BonsaiClient(Protocol):
    async def generate_json(
        self,
        task: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
        timeout_s: float,
    ) -> dict[str, Any]: ...


class RealBonsaiClient:
    """OpenAI-compatible localhost client for the Mac's Bonsai server."""

    def __init__(self, base_url: str = "http://localhost:8080", model: str = "bonsai-2-2b") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def generate_json(
        self,
        task: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
        timeout_s: float,
    ) -> dict[str, Any]:
        return await asyncio.wait_for(asyncio.to_thread(self._generate_with_retry, task, payload, schema), timeout_s)

    def _generate_with_retry(
        self, task: str, payload: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(2):
            prompt = _prompt_for(task, payload, schema, retry_error=str(last_error) if last_error else None)
            try:
                text = self._chat(prompt, use_response_format=attempt == 0)
                value = extract_json_value(text)
                validate_json_schema(value, schema)
                if not isinstance(value, dict):
                    raise JsonSchemaError("top-level JSON value must be an object")
                return value
            except Exception as exc:  # one deliberate validation retry
                last_error = exc
        raise BonsaiError(f"Bonsai did not return valid JSON: {last_error}")

    def _chat(self, prompt: str, use_response_format: bool) -> str:
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Return only valid JSON. Thinking mode is off."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        if use_response_format:
            request_body["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if use_response_format:
                raise BonsaiError("schema-constrained response was rejected") from exc
            raise
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise BonsaiError("OpenAI-compatible response did not contain message content") from exc


class MockBonsaiClient:
    """Windows-safe mock with schema-valid canned answers, delay, and optional failures."""

    def __init__(self, seed: int = 7, failure_rate: float = 0.1) -> None:
        self.random = random.Random(seed)
        self.failure_rate = failure_rate
        self.calls: list[str] = []

    async def generate_json(
        self,
        task: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
        timeout_s: float,
    ) -> dict[str, Any]:
        self.calls.append(task)
        await asyncio.sleep(self.random.uniform(0.3, min(1.5, max(0.3, timeout_s))))
        if self.random.random() < self.failure_rate:
            raise BonsaiError("deliberate mock Bonsai failure")
        result = self._canned(task, payload)
        validate_json_schema(result, schema)
        return result

    def _canned(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        if task == "name":
            return {"name": "Yoav", "aliases": []}
        if task == "tag":
            text = str(payload.get("text", ""))
            tags = ["question"] if text.strip().endswith("?") else []
            owner = payload.get("defaultActionOwner")
            return {"tags": tags, "repliesTo": None, "actionOwner": owner if "action item" in text.lower() else None}
        if task == "summary":
            turns = payload.get("turns", [])
            return {
                "summary": "The group discussed the key topics and identified follow-up work.",
                "topics": ["meeting"],
                "actionItems": [],
                "perPerson": [
                    {"personId": person, "summary": "Participated in the discussion."}
                    for person in sorted({turn.get("speakerId") for turn in turns if turn.get("speakerId")})
                ],
            }
        if task == "ask":
            turns = payload.get("turns", [])
            cited = [turn.get("id") for turn in turns[:2] if turn.get("id")]
            return {"text": "Based on the recorded turns, the answer is in the cited discussion.", "citedTurnIds": cited}
        if task == "layout":
            return {"summary": "Three speakers are seated along the far side of the table."}
        return {}


@dataclass(slots=True)
class _Job:
    task: str
    payload: dict[str, Any]
    schema: dict[str, Any]
    timeout_s: float
    future: asyncio.Future[dict[str, Any]]


class BonsaiWorker:
    """Single worker; ask > name > tag > layout."""

    PRIORITIES = {"ask": 0, "name": 1, "tag": 2, "layout": 3, "summary": 2}

    def __init__(self, client: BonsaiClient) -> None:
        self.client = client
        self.queue: asyncio.PriorityQueue[tuple[int, int, _Job]] = asyncio.PriorityQueue()
        self.counter = itertools.count()
        self.runner: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self.runner is None or self.runner.done():
            self.runner = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self.runner is not None:
            self.runner.cancel()
            try:
                await self.runner
            except asyncio.CancelledError:
                pass

    async def submit(
        self,
        task: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
        timeout_s: float,
    ) -> dict[str, Any]:
        await self.start()
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        job = _Job(task, payload, schema, timeout_s, future)
        await self.queue.put((self.PRIORITIES.get(task, 9), next(self.counter), job))
        return await future

    async def _run(self) -> None:
        while True:
            _, _, job = await self.queue.get()
            if job.future.cancelled():
                continue
            try:
                result = await self.client.generate_json(job.task, job.payload, job.schema, job.timeout_s)
                job.future.set_result(result)
            except Exception as exc:
                job.future.set_exception(exc)
            finally:
                self.queue.task_done()


def extract_json_value(text: str) -> Any:
    clean = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    clean = re.sub(r"<think>.*\Z", "", clean, flags=re.IGNORECASE | re.DOTALL)
    fence = re.search(r"```(?:json)?\s*(.*?)```", clean, flags=re.IGNORECASE | re.DOTALL)
    if fence:
        clean = fence.group(1)
    for start, character in enumerate(clean):
        if character not in "[{":
            continue
        end = _balanced_end(clean, start)
        if end is None:
            continue
        try:
            return json.loads(clean[start:end])
        except json.JSONDecodeError:
            continue
    raise JsonSchemaError("no balanced JSON value found")


def _balanced_end(text: str, start: int) -> int | None:
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    stack = [closer]
    quoted = False
    escaped = False
    for index in range(start + 1, len(text)):
        character = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == "{":
            stack.append("}")
        elif character == "[":
            stack.append("]")
        elif character in "}]":
            if not stack or character != stack[-1]:
                return None
            stack.pop()
            if not stack:
                return index + 1
    return None


def validate_json_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    expected_type = schema.get("type")
    if expected_type:
        type_map = {
            "object": dict,
            "array": list,
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "null": type(None),
        }
        expected = type_map.get(str(expected_type))
        if expected is not None and not isinstance(value, expected):
            raise JsonSchemaError(f"{path}: expected {expected_type}")
        if expected_type in {"number", "integer"} and isinstance(value, bool):
            raise JsonSchemaError(f"{path}: expected {expected_type}")
    if "enum" in schema and value not in schema["enum"]:
        raise JsonSchemaError(f"{path}: value must be one of {schema['enum']}")
    if isinstance(value, dict):
        for required in schema.get("required", []):
            if required not in value:
                raise JsonSchemaError(f"{path}: missing required field {required!r}")
        properties = schema.get("properties", {})
        for key, child_schema in properties.items():
            if key in value:
                validate_json_schema(value[key], child_schema, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            validate_json_schema(item, schema["items"], f"{path}[{index}]")


def _prompt_for(task: str, payload: dict[str, Any], schema: dict[str, Any], retry_error: str | None) -> str:
    retry = f"\nThe previous answer failed validation: {retry_error}. Correct it." if retry_error else ""
    return (
        f"Task: {task}\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}\n"
        f"Return a JSON object matching this schema:\n{json.dumps(schema, ensure_ascii=False)}"
        f"{retry}"
    )


NAME_SCHEMA = {
    "type": "object",
    "required": ["name", "aliases"],
    "properties": {"name": {"type": "string"}, "aliases": {"type": "array", "items": {"type": "string"}}},
}

TAG_SCHEMA = {
    "type": "object",
    "required": ["tags", "repliesTo", "actionOwner"],
    "properties": {
        "tags": {"type": "array", "items": {"type": "string"}},
        "repliesTo": {"type": ["null", "string"]},
        "actionOwner": {"type": ["null", "string"]},
    },
}

ANSWER_SCHEMA = {
    "type": "object",
    "required": ["text", "citedTurnIds"],
    "properties": {"text": {"type": "string"}, "citedTurnIds": {"type": "array", "items": {"type": "string"}}},
}

SUMMARY_SCHEMA = {
    "type": "object",
    "required": ["summary", "topics", "actionItems", "perPerson"],
    "properties": {
        "summary": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string"}},
        "actionItems": {"type": "array", "items": {"type": "string"}},
        "perPerson": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["personId", "summary"],
                "properties": {"personId": {"type": "string"}, "summary": {"type": "string"}},
            },
        },
    },
}
