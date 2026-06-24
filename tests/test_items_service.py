"""Tests for ItemsService write paths (adapter mocked via AsyncMock)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from zop.adapters.zotero_api import ApiCreds
from zop.core.errors import AuthError, ZopError
from zop.models.common import ItemType
from zop.models.item import Item
from zop.services.items import ItemsService

# Real Zotero keys are 8 uppercase alphanumerics (ID_PATTERN).
KEY = "ITEM0001"


async def test_update_merges_payload_and_strips_system_fields(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api.get_item.return_value = {
        "version": 5,
        "data": {"title": "old", "itemType": "journalArticle", "key": KEY},
    }
    fake_api.update_item.return_value = {}
    monkeypatch.setattr(ItemsService, "_require_api", lambda self: fake_api)
    svc = ItemsService(db_path=fake_db, creds=creds)
    # Re-fetch after PATCH must not hit the empty DB.
    fake_item = Item(key=KEY, item_type=ItemType.JOURNAL_ARTICLE, title="New")
    monkeypatch.setattr(svc._reader, "get_item", lambda *a, **k: fake_item)

    await svc.update(KEY, title="New")

    fake_api.update_item.assert_awaited_once()
    args, kwargs = fake_api.update_item.call_args
    assert args[0] == KEY
    payload = args[1]
    assert payload["title"] == "New"
    assert "key" not in payload  # stripped before PATCH
    assert "version" not in payload
    assert kwargs["version"] == 5


async def test_delete_passes_current_version(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api.get_item.return_value = {"version": 9, "data": {}}
    monkeypatch.setattr(ItemsService, "_require_api", lambda self: fake_api)
    svc = ItemsService(db_path=fake_db, creds=creds)

    await svc.delete(KEY)

    fake_api.delete_item.assert_awaited_once_with(KEY, version=9)


async def test_add_by_doi_returns_created_item(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new_key = "NEW00001"
    fake_api.create_items.return_value = [{"key": new_key, "version": 1}]
    monkeypatch.setattr(ItemsService, "_require_api", lambda self: fake_api)
    svc = ItemsService(db_path=fake_db, creds=creds)
    monkeypatch.setattr(
        svc._reader,
        "get_item",
        lambda *a, **k: Item(key=new_key, item_type=ItemType.JOURNAL_ARTICLE, title="t"),
    )

    result = await svc.add_by_doi("10.1234/x")

    assert result.key == new_key
    payload = fake_api.create_items.call_args.args[0]
    assert payload == [
        {"itemType": "journalArticle", "DOI": "10.1234/x", "collections": []}
    ]


async def test_add_by_doi_raises_when_rejected(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api.create_items.return_value = []
    monkeypatch.setattr(ItemsService, "_require_api", lambda self: fake_api)
    svc = ItemsService(db_path=fake_db, creds=creds)

    with pytest.raises(ZopError):
        await svc.add_by_doi("bad")


async def test_add_many_returns_item_per_created_key(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = ["AAAA0001", "BBBB0002"]
    fake_api.create_items.return_value = [{"key": k} for k in keys]
    monkeypatch.setattr(ItemsService, "_require_api", lambda self: fake_api)
    svc = ItemsService(db_path=fake_db, creds=creds)
    monkeypatch.setattr(
        svc._reader,
        "get_item",
        lambda key, **_: Item(key=key, item_type=ItemType.JOURNAL_ARTICLE, title=key),
    )

    result = await svc.add_many(["10.1", "10.2"])

    assert [it.key for it in result] == keys


async def test_update_requires_credentials(fake_db: Path) -> None:
    svc = ItemsService(db_path=fake_db, creds=None)
    with pytest.raises(AuthError):
        await svc.update(KEY, title="x")
