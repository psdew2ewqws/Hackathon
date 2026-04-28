"""Streaming runner for the LLM advisor.

Implements the manual agentic loop with ``AsyncAnthropic.messages.stream()``:

1. Load conversation history (Anthropic format) and append the new user message.
2. Open a stream. Yield ``text_delta`` events as text arrives.
3. When the model emits ``tool_use``, dispatch it via ``tools.dispatch``,
   append a ``tool_result`` block, and re-enter the loop.
4. Stop when ``stop_reason == "end_turn"``.

Tools and the system prompt are stable across the loop, so a top-level
``cache_control`` breakpoint caches them — repeated turns within the same
process pay the discounted rate from turn 2 onward.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from . import conversations, tools
from .client import LLMClient, LLMNotConfiguredError, get_client
from .system_prompt import build_system_prompt
from .tools import LLMContext

LOG = logging.getLogger(__name__)

MAX_TOOL_HOPS = 8  # safety cap on tool-use loop iterations per user turn
HISTORY_MESSAGES_CAP = 40  # most recent messages re-sent to the API


async def run_chat(
    *,
    user_id: int,
    username: str,
    site_id: str,
    user_message: str,
    conversation_id: str | None,
    ctx: LLMContext,
    client: LLMClient | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive a single user turn end-to-end.

    Yields events:
    - ``{type: 'conversation', conversation_id: str}``
    - ``{type: 'text_delta', text: str}``
    - ``{type: 'tool_use', tool_use_id, name, args}``
    - ``{type: 'tool_result', tool_use_id, ok: bool}``
    - ``{type: 'turn_done', stop_reason, tokens_in, tokens_out}``
    - ``{type: 'error', message: str}``
    """
    client = client or get_client()
    if not client.is_configured():
        raise LLMNotConfiguredError(
            "ANTHROPIC_API_KEY is not set or anthropic SDK is not installed."
        )

    model = client.model()
    max_tokens = client.max_tokens()

    if conversation_id is None:
        conversation_id = conversations.start_conversation(
            user_id=user_id,
            username=username,
            site_id=site_id,
            model=model,
            title=user_message[:80],
        )
    yield {"type": "conversation", "conversation_id": conversation_id}

    turn_index = conversations.next_turn_index(conversation_id)
    conversations.append_turn(
        conversation_id,
        role="user",
        content=user_message,
        turn_index=turn_index,
    )

    history = conversations.load_history_for_api(
        conversation_id, max_messages=HISTORY_MESSAGES_CAP
    )

    sdk_client = client.get_async()
    system_prompt = build_system_prompt()

    total_tokens_in = 0
    total_tokens_out = 0
    last_stop_reason: str | None = None
    tool_hops = 0

    try:
        while True:
            if tool_hops >= MAX_TOOL_HOPS:
                yield {
                    "type": "error",
                    "message": f"tool-hop limit reached ({MAX_TOOL_HOPS})",
                }
                last_stop_reason = "tool_hop_limit"
                break

            assistant_blocks: list[dict[str, Any]] = []
            current_text: list[str] = []
            current_tool_use: dict[str, Any] | None = None
            current_tool_input_json: list[str] = []

            stream_kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "system": [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "tools": tools.TOOL_SCHEMAS,
                "messages": history,
            }

            async with sdk_client.messages.stream(**stream_kwargs) as stream:
                async for event in stream:
                    et = event.type
                    if et == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            current_tool_use = {
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": {},
                            }
                            current_tool_input_json = []
                        elif block.type == "text":
                            current_text = []
                    elif et == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            current_text.append(delta.text)
                            yield {"type": "text_delta", "text": delta.text}
                        elif delta.type == "input_json_delta":
                            current_tool_input_json.append(delta.partial_json)
                    elif et == "content_block_stop":
                        if current_tool_use is not None:
                            import json as _json
                            raw = "".join(current_tool_input_json) or "{}"
                            try:
                                current_tool_use["input"] = _json.loads(raw)
                            except _json.JSONDecodeError:
                                current_tool_use["input"] = {}
                            assistant_blocks.append(current_tool_use)
                            current_tool_use = None
                            current_tool_input_json = []
                        elif current_text:
                            assistant_blocks.append(
                                {"type": "text", "text": "".join(current_text)}
                            )
                            current_text = []

                final = await stream.get_final_message()

            usage = getattr(final, "usage", None)
            if usage is not None:
                total_tokens_in += int(getattr(usage, "input_tokens", 0) or 0)
                total_tokens_in += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
                total_tokens_out += int(getattr(usage, "output_tokens", 0) or 0)

            last_stop_reason = getattr(final, "stop_reason", None)

            history.append({"role": "assistant", "content": assistant_blocks})

            tool_use_blocks = [b for b in assistant_blocks if b.get("type") == "tool_use"]
            if not tool_use_blocks:
                break

            tool_results: list[dict[str, Any]] = []
            for tu in tool_use_blocks:
                yield {
                    "type": "tool_use",
                    "tool_use_id": tu["id"],
                    "name": tu["name"],
                    "args": tu["input"],
                }
                result = tools.dispatch(tu["name"], tu["input"], ctx)
                is_error = "error" in result
                import json as _json
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": _json.dumps(result, ensure_ascii=False, sort_keys=True),
                    **({"is_error": True} if is_error else {}),
                })
                yield {
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "ok": not is_error,
                }

            history.append({"role": "user", "content": tool_results})
            tool_hops += 1

            if last_stop_reason != "tool_use":
                break

        final_assistant = history[-1] if history and history[-1]["role"] == "assistant" else None
        if final_assistant is not None:
            content = final_assistant["content"]
            persisted = content if isinstance(content, list) else str(content)
            turn_index = conversations.next_turn_index(conversation_id)
            conversations.append_turn(
                conversation_id,
                role="assistant",
                content=persisted,
                turn_index=turn_index,
                tokens_in=total_tokens_in,
                tokens_out=total_tokens_out,
            )

        yield {
            "type": "turn_done",
            "stop_reason": last_stop_reason,
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
        }
    except LLMNotConfiguredError:
        raise
    except Exception as e:  # noqa: BLE001
        LOG.exception("run_chat failed")
        yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
