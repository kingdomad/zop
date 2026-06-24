"""Tests for TagsService write paths (adapter mocked via AsyncMock)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from zop.adapters.zotero_api import ApiCreds
from zop.core.errors import NotFoundError
from zop.services.tags import TagsService


async def test_add_merges_existing_tags(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api.get_item.return_value = {"version": 1, "data": {"tags": [{"tag": "a"}]}}
    fake_api.update_item.return_value = {}
    monkeypatch.setattr(TagsService, "_require_api", lambda self: fake_api)
    svc = TagsService(db_path=fake_db, creds=creds)

    ok, fail = await svc.add(["KEY1"], ["x"])

    assert ok == ["KEY1"]
    assert fail == []
    payload = fake_api.update_item.call_args.args[1]
    assert payload["tags"] == [{"tag": "a"}, {"tag": "x"}]
    assert fake_api.update_item.call_args.kwargs["version"] == 1


async def test_add_empty_inputs_short_circuits(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TagsService, "_require_api", lambda self: fake_api)
    svc = TagsService(db_path=fake_db, creds=creds)

    ok, fail = await svc.add([], ["x"])

    assert ok == []
    assert fail == []
    fake_api.update_item.assert_not_awaited()


async def test_add_isolates_per_item_failure(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api.get_item.side_effect = NotFoundError("missing")
    monkeypatch.setattr(TagsService, "_require_api", lambda self: fake_api)
    svc = TagsService(db_path=fake_db, creds=creds)

    ok, fail = await svc.add(["KEY1"], ["x"])

    assert ok == []
    assert len(fail) == 1
    assert fail[0][0] == "KEY1"


async def test_remove_filters_out_tags(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api.get_item.return_value = {
        "version": 1,
        "data": {"tags": [{"tag": "a"}, {"tag": "b"}, {"tag": "c"}]},
    }
    fake_api.update_item.return_value = {}
    monkeypatch.setattr(TagsService, "_require_api", lambda self: fake_api)
    svc = TagsService(db_path=fake_db, creds=creds)

    ok, fail = await svc.remove(["KEY1"], ["b"])

    assert ok == ["KEY1"]
    assert fail == []
    payload = fake_api.update_item.call_args.args[1]
    assert payload["tags"] == [{"tag": "a"}, {"tag": "c"}]
