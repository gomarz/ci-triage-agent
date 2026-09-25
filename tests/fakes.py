"""Scripted stand-ins for the model, so agent and judge tests need no credentials."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

from ci_triage.llm import ToolCall, Turn, Usage


class ScriptedModel:
    """Returns prepared turns in order and records what it was sent.

    A prepared turn may be a `Turn` or a callable taking the messages so far, for tests
    where the next move depends on what a tool returned.
    """

    def __init__(self, turns=(), json_answers=()):
        self.turns = list(turns)
        self.json_answers = list(json_answers)
        self.seen: list[list[dict]] = []
        self.prompts: list[str] = []

    def step(self, system, messages, tools):
        self.seen.append([dict(m) for m in messages])
        if not self.turns:
            raise AssertionError("the agent asked for more turns than the script has")
        turn = self.turns.pop(0)
        return turn(messages) if callable(turn) else turn

    def complete_json(self, system, user, schema):
        self.prompts.append(user)
        if not self.json_answers:
            raise AssertionError("the judge asked for more answers than the script has")
        answer = self.json_answers.pop(0)
        return (answer(user) if callable(answer) else answer), Usage(10, 5, 1)


def say(text: str) -> Turn:
    return Turn(text=text, tool_calls=[], assistant_content=[{"type": "text", "text": text}])


def call(*calls: tuple[str, dict], text: str = "") -> Turn:
    """A turn that makes tool calls: call(("read_file", {"path": "a.py"}), ...)."""
    tool_calls = [ToolCall(f"toolu_{i}", name, args) for i, (name, args) in enumerate(calls)]
    content = [
        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in tool_calls
    ]
    return Turn(text=text, tool_calls=tool_calls, assistant_content=content, stop_reason="tool_use")


class FakeSDK:
    """Stands in for `anthropic.Anthropic()`: records requests, returns a prepared response."""

    def __init__(self, response):
        self.response = response
        self.requests: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.requests.append(params)
        return self.response


def sdk_response(content, stop_reason="end_turn", stop_details=None, tokens=(11, 7)):
    blocks = [SimpleNamespace(**b) if isinstance(b, dict) else b for b in content]
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        stop_details=stop_details,
        usage=SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1]),
    )


Handler = Callable[[list[dict]], Turn]
