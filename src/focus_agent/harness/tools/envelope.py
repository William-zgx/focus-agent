from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from langchain.messages import ToolMessage


ToolResultContent: TypeAlias = str | list[str | dict[str, Any]]
ToolResultStatus: TypeAlias = Literal["success", "error"]
TOOL_RESULT_ENVELOPE_VERSION = "focus_agent.tool_result.v1"


class ToolResultEnvelope(BaseModel):
    """Portable harness representation of a LangChain ToolMessage result."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["focus_agent.tool_result.v1"] = TOOL_RESULT_ENVELOPE_VERSION
    tool_call_id: str
    tool_name: str = ""
    content: ToolResultContent = ""
    status: ToolResultStatus = "success"
    runtime: dict[str, Any] = Field(default_factory=dict)
    prompt_observation: str | None = None
    artifact: dict[str, Any] = Field(default_factory=dict)
    message_id: str | None = None
    name: str | None = None
    additional_kwargs: dict[str, Any] = Field(default_factory=dict)
    response_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("runtime", "artifact", "additional_kwargs", "response_metadata", mode="before")
    @classmethod
    def _coerce_mapping(cls, value: object) -> object:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return {str(key): nested for key, nested in value.items()}
        return value

    @classmethod
    def from_tool_message(
        cls,
        message: ToolMessage,
        *,
        tool_name: str | None = None,
    ) -> Self:
        from .messages import tool_message_to_envelope

        return tool_message_to_envelope(message, tool_name=tool_name)

    def to_tool_message(self) -> ToolMessage:
        from .messages import envelope_to_tool_message

        return envelope_to_tool_message(self)
