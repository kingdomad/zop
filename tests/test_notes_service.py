"""Tests for NotesService write paths (adapter mocked via AsyncMock)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from zop.adapters.zotero_api import ApiCreds
from zop.core.errors import ZopError
from zop.services.notes import NotesService


async def test_add_returns_new_note_key(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api.create_items.return_value = [{"key": "NOTE1", "version": 1}]
    monkeypatch.setattr(NotesService, "_require_api", lambda self: fake_api)
    svc = NotesService(db_path=fake_db, creds=creds)

    result = await svc.add("PARENT1", "note text")

    assert result == "NOTE1"
    payload = fake_api.create_items.call_args.args[0]
    assert payload == [{"itemType": "note", "note": "note text", "parentItem": "PARENT1"}]


async def test_add_raises_when_server_rejects(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api.create_items.return_value = []
    monkeypatch.setattr(NotesService, "_require_api", lambda self: fake_api)
    svc = NotesService(db_path=fake_db, creds=creds)

    with pytest.raises(ZopError):
        await svc.add("PARENT1", "text")
