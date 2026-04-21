from __future__ import annotations

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import (
    _convert_from_v1_to_chat_completions,
    _convert_message_to_dict,
)


_MOONSHOT_REASONING_BLOCK_TYPES = {
    "reasoning",
    "reasoning_delta",
    "reasoning_content",
    "reasoningcontent",
    "thinking",
    "thinking_delta",
}


def _stringify_reasoning(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "".join(_stringify_reasoning(item) for item in value)
    if isinstance(value, dict):
        for key in ("reasoning_content", "reasoningcontent", "reasoning", "text", "content", "value", "summary"):
            if value.get(key) is not None:
                return _stringify_reasoning(value[key])
        return ""
    return str(value)


def _normalized_moonshot_content(content: Any) -> Any:
    if not isinstance(content, list):
        return content

    normalized_blocks: list[Any] = []
    for block in content:
        if isinstance(block, str):
            if block.strip():
                normalized_blocks.append({"type": "text", "text": block})
            continue
        if not isinstance(block, dict):
            text = _stringify_reasoning(block).strip()
            if text:
                normalized_blocks.append({"type": "text", "text": text})
            continue
        normalized = dict(block)
        block_type = str(normalized.get("type") or "")
        if block_type == "reasoningcontent":
            normalized["type"] = "reasoning_content"
        if "reasoningcontent" in normalized and "reasoning_content" not in normalized:
            normalized["reasoning_content"] = normalized.pop("reasoningcontent")
        normalized_blocks.append(normalized)
    return normalized_blocks


def _extract_reasoning_content_from_message(message: AIMessage) -> str | None:
    additional_reasoning = _stringify_reasoning(
        getattr(message, "additional_kwargs", {}).get("reasoning_content")
    ).strip()
    if additional_reasoning:
        return additional_reasoning

    content = _normalized_moonshot_content(getattr(message, "content", None))
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            if block_type not in _MOONSHOT_REASONING_BLOCK_TYPES:
                continue
            text = _stringify_reasoning(block)
            if text:
                parts.append(text)
        if parts:
            return "".join(parts)
    return None


def _convert_moonshot_message_to_dict(message: Any) -> dict[str, Any]:
    converted = (
        _convert_from_v1_to_chat_completions(message)
        if isinstance(message, AIMessage)
        else message
    )
    if isinstance(converted, AIMessage):
        converted = AIMessage(
            content=_normalized_moonshot_content(getattr(converted, "content", None)),
            additional_kwargs=dict(getattr(converted, "additional_kwargs", {}) or {}),
            response_metadata=dict(getattr(converted, "response_metadata", {}) or {}),
            name=getattr(converted, "name", None),
            id=getattr(converted, "id", None),
            tool_calls=list(getattr(converted, "tool_calls", []) or []),
            invalid_tool_calls=list(getattr(converted, "invalid_tool_calls", []) or []),
            usage_metadata=getattr(converted, "usage_metadata", None),
        )
    payload = _convert_message_to_dict(converted)
    if isinstance(converted, AIMessage):
        reasoning_content = _extract_reasoning_content_from_message(converted)
        if reasoning_content:
            payload["reasoning_content"] = reasoning_content
    return payload


def _augment_reasoning_chunk(
    message_chunk: AIMessageChunk,
    *,
    reasoning_content: str,
) -> AIMessageChunk:
    return AIMessageChunk(
        content=getattr(message_chunk, "content", ""),
        additional_kwargs={
            **dict(getattr(message_chunk, "additional_kwargs", {}) or {}),
            "reasoning_content": reasoning_content,
        },
        response_metadata=dict(getattr(message_chunk, "response_metadata", {}) or {}),
        name=getattr(message_chunk, "name", None),
        id=getattr(message_chunk, "id", None),
        tool_call_chunks=list(getattr(message_chunk, "tool_call_chunks", []) or []),
        tool_calls=list(getattr(message_chunk, "tool_calls", []) or []),
        invalid_tool_calls=list(getattr(message_chunk, "invalid_tool_calls", []) or []),
        usage_metadata=getattr(message_chunk, "usage_metadata", None),
        chunk_position=getattr(message_chunk, "chunk_position", None),
    )


class MoonshotChatOpenAI(ChatOpenAI):
    """ChatOpenAI variant that preserves Moonshot's non-standard reasoning_content."""

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        messages = self._convert_input(input_).to_messages()
        if stop is not None:
            kwargs["stop"] = stop

        payload = {**self._default_params, **kwargs}
        if self._use_responses_api(payload):
            return super()._get_request_payload(input_, stop=stop, **kwargs)

        payload["messages"] = [_convert_moonshot_message_to_dict(message) for message in messages]
        return payload

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        for generation, choice in zip(result.generations, response_dict.get("choices", []) or []):
            if not isinstance(generation.message, AIMessage):
                continue
            reasoning_content = _stringify_reasoning(
                (choice.get("message") or {}).get("reasoning_content")
            ).strip()
            if reasoning_content:
                generation.message.additional_kwargs["reasoning_content"] = reasoning_content
        return result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk is None:
            return None

        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])
        if not choices:
            return generation_chunk
        delta = choices[0].get("delta") or {}
        reasoning_content = _stringify_reasoning(delta.get("reasoning_content")).strip()
        if not reasoning_content:
            return generation_chunk

        if not isinstance(generation_chunk.message, AIMessageChunk):
            return generation_chunk

        return ChatGenerationChunk(
            message=_augment_reasoning_chunk(
                generation_chunk.message,
                reasoning_content=reasoning_content,
            ),
            generation_info=generation_chunk.generation_info,
        )
