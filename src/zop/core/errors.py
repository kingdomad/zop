"""Error types and structured Result."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TypeVar

from zop.models.envelope import ErrorBlock

T = TypeVar("T")


class ZopError(Exception):
    """Base error for all zop errors."""

    code: str = "zop_error"
    retryable: bool = False
    hint: str | None = None

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if hint is not None:
            self.hint = hint

    def to_block(self) -> ErrorBlock:
        return ErrorBlock(
            code=self.code,
            message=self.message,
            hint=self.hint,
            retryable=self.retryable,
        )


class AuthError(ZopError):
    code = "auth_missing"
    hint = "Run 'zop config init' or set ZOP_LIBRARY_ID + ZOP_API_KEY env vars"


class NotFoundError(ZopError):
    code = "not_found"


class ConflictError(ZopError):
    """Resource already exists, or operation would create a conflict."""

    code = "conflict"


class ApiError(ZopError):
    code = "api_error"
    retryable = True

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class ValidationError(ZopError):
    code = "validation_error"


class NetworkError(ZopError):
    code = "network_error"
    retryable = True


@dataclass
class BatchResult[T]:
    """Result of a batch operation: successes + per-item failures."""

    successes: list[T] = field(default_factory=list)
    failures: list[tuple[str, ErrorBlock]] = field(default_factory=list)  # (key, error)

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def count(self) -> int:
        return len(self.successes) + len(self.failures)

    def add_failure(self, key: str, err: ZopError) -> None:
        self.failures.append((key, err.to_block()))

    def merge(self, other: BatchResult[T]) -> None:
        self.successes.extend(other.successes)
        self.failures.extend(other.failures)

    def iter_failures(self) -> Iterable[tuple[str, ErrorBlock]]:
        return iter(self.failures)
