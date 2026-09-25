"""The one place this project talks to a model.

Everything that needs a model (the patch-proposing agent, the patch judge) takes a
`Model`, a two-method protocol, and never imports the SDK. That is what lets both be
tested against a scripted fake with no credentials and no spend, and it keeps the SDK's
request shapes, which have changed twice this year, in a single file.

`AnthropicModel` is the real implementation. Defaults follow the API guidance for the
current models: adaptive thinking, an explicit effort, and server-side fallbacks so a
request a safety classifier declines is re-run on another model instead of stopping the
loop. A refusal that survives the fallback raises `ModelRefused` rather than returning
an empty turn the caller would read as "done".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = "claude-opus-5"

#: Beta header for `fallbacks="default"`. Not interchangeable with the -2026-06-01
#: header, which belongs to the array form of the same parameter.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ModelRefused(RuntimeError):
    """The model, and any fallback, declined the request."""


class ModelTruncated(RuntimeError):
    """Output hit max_tokens, so a tool call or JSON answer may be cut off."""


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Turn:
    """One model response, reduced to what the callers use."""

    text: str
    tool_calls: list[ToolCall]
    #: What to send back as this turn's assistant content. Opaque to callers: with
    #: thinking on, the blocks must be replayed unchanged, so they are not rebuilt.
    assistant_content: Any
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add(self, turn_input: int, turn_output: int) -> None:
        self.input_tokens += turn_input
        self.output_tokens += turn_output
        self.calls += 1


class Model(Protocol):
    def step(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        """One turn of a tool-using conversation."""

    def complete_json(self, system: str, user: str, schema: dict) -> tuple[dict, Usage]:
        """A single answer constrained to `schema`, and what it cost."""


@dataclass
class AnthropicModel:
    """`Model` over the Anthropic SDK. Construct with no arguments to read credentials
    from the environment (ANTHROPIC_API_KEY, or a profile)."""

    model: str = DEFAULT_MODEL
    effort: str = "high"
    max_tokens: int = 16000
    client: Any = None
    _fallbacks: bool = field(default=True, repr=False)

    def __post_init__(self) -> None:
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic()

    def _request(self, **fields: Any) -> Any:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "thinking": {"type": "adaptive"},
            **fields,
        }
        params["output_config"] = {"effort": self.effort, **params.get("output_config", {})}
        if self._fallbacks:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        response = self.client.beta.messages.create(**params)
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            raise ModelRefused(f"declined by the model and its fallbacks (category: {category})")
        if response.stop_reason == "max_tokens":
            raise ModelTruncated(f"hit max_tokens={self.max_tokens}")
        return response

    def step(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        response = self._request(system=system, messages=messages, tools=tools)
        blocks = response.content
        return Turn(
            text="".join(b.text for b in blocks if b.type == "text"),
            tool_calls=[ToolCall(b.id, b.name, b.input) for b in blocks if b.type == "tool_use"],
            assistant_content=blocks,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason,
        )

    def complete_json(self, system: str, user: str, schema: dict) -> tuple[dict, Usage]:
        response = self._request(
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        usage = Usage()
        usage.add(response.usage.input_tokens, response.usage.output_tokens)
        return json.loads(text), usage
