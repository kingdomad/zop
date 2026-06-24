"""Bounded concurrency helper."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterable, Sequence
from typing import TypeVar

T = TypeVar("T")


async def bounded_gather[T](
    coros: Iterable[Awaitable[T]],
    *,
    concurrency: int = 8,
) -> list[T]:
    """Run async tasks with bounded concurrency.

    Args:
        coros: Iterable of awaitables (not yet started).
        concurrency: Max number of tasks running at once.

    Returns:
        List of results in the same order as input.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _run(coro: Awaitable[T]) -> T:
        async with sem:
            return await coro

    tasks = [asyncio.create_task(_run(c)) for c in coros]
    return list(await asyncio.gather(*tasks, return_exceptions=False))


def chunked[T](seq: Sequence[T], size: int) -> list[Sequence[T]]:
    """Split a sequence into chunks of `size`."""
    return [seq[i : i + size] for i in range(0, len(seq), size)]
