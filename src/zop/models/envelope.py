"""JSON envelope for all CLI output."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from zop import __version__


class Meta(BaseModel):
    """Response metadata."""

    model_config = ConfigDict(frozen=True)

    cli_version: str = __version__
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    latency_ms: int = 0
    count: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ErrorBlock(BaseModel):
    """Error information block."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    hint: str | None = None
    retryable: bool = False


class Envelope(BaseModel):
    """Top-level response envelope.

    All CLI output (success or error) is wrapped in this structure so that
    agents can rely on a stable shape.
    """

    model_config = ConfigDict(frozen=True)

    ok: bool
    data: Any = None
    error: ErrorBlock | None = None
    meta: Meta = Field(default_factory=Meta)

    def to_json(self) -> str:
        """Serialize to JSON string (compact, deterministic)."""
        return self.model_dump_json(exclude_none=True)

    def to_human(self) -> str:
        """Serialize to human-readable text (best-effort)."""
        if not self.ok and self.error:
            return f"Error [{self.error.code}]: {self.error.message}"
        return self.model_dump_json(indent=2, exclude_none=True)
