"""Output envelope helper."""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from zop.core.errors import ZopError
from zop.models.envelope import Envelope, Meta


def emit(
    data: Any = None,
    *,
    error: ZopError | None = None,
    human: bool = False,
    count: int | None = None,
) -> None:
    """Emit a JSON envelope to stdout.

    Args:
        data: Payload (will be JSON-serialized).
        error: If provided, the envelope is marked as failed and `error` is
            rendered as the error block.
        human: If True, pretty-print; if False (default), compact JSON.
        count: Optional item count for the meta block.
    """
    start = time.perf_counter_ns()
    if error is not None:
        env = Envelope(ok=False, error=error.to_block())
    else:
        env = Envelope(ok=True, data=data, meta=Meta(count=count))
    latency_ms = int((time.perf_counter_ns() - start) / 1_000_000)
    env = env.model_copy(update={"meta": env.meta.model_copy(update={"latency_ms": latency_ms})})

    if human:
        sys.stdout.write(env.to_human())
    else:
        sys.stdout.write(env.to_json())
    sys.stdout.write("\n")
    sys.stdout.flush()


def emit_error(err: ZopError, *, human: bool = False) -> None:
    """Emit a top-level error envelope."""
    emit(error=err, human=human)


def emit_batch(
    successes: list[Any],
    failures: list[tuple[str, ZopError]],
    *,
    human: bool = False,
) -> None:
    """Emit a batch result with both successes and per-item failures."""
    data: dict[str, Any] = {
        "succeeded": [s.model_dump() if hasattr(s, "model_dump") else s for s in successes],
        "failed": [
            {"key": k, "error": e.to_block().model_dump()}
            for k, e in failures
        ],
    }
    env = Envelope(ok=not failures, data=data, meta=Meta(count=len(successes) + len(failures)))
    if human:
        sys.stdout.write(json.dumps(env.model_dump(), indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(env.to_json())
    sys.stdout.write("\n")
    sys.stdout.flush()
