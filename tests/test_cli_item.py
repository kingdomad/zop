"""CLI smoke tests for item commands (service mocked)."""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from zop.core.errors import NotFoundError
from zop.models.common import ItemType
from zop.models.item import Item, ItemSummary

# commands/__init__.py re-exports the `item` *group*, which shadows the
# submodule, so fetch the real module object via importlib.
item_mod = importlib.import_module("zop.commands.item")


def _mock_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    svc = MagicMock()
    monkeypatch.setattr(item_mod, "_service", lambda: svc)
    monkeypatch.setattr(item_mod, "_human", lambda: False)
    return svc


def test_item_search(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch)
    svc.search.return_value = [
        ItemSummary(key="ITEM0001", item_type=ItemType.JOURNAL_ARTICLE, title="foo")
    ]

    result = CliRunner().invoke(item_mod.search_cmd, ["foo"])

    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["ok"] is True
    assert len(out["data"]) == 1
    svc.search.assert_called_once_with("foo", limit=50)


def test_item_read_success(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch)
    svc.get.return_value = Item(
        key="ITEM0001", item_type=ItemType.JOURNAL_ARTICLE, title="t"
    )

    result = CliRunner().invoke(item_mod.read_cmd, ["ITEM0001"])

    assert result.exit_code == 0
    assert json.loads(result.output)["data"]["key"] == "ITEM0001"


def test_item_read_missing_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch)
    svc.get.side_effect = NotFoundError("missing")

    result = CliRunner().invoke(item_mod.read_cmd, ["ITEM0001"])

    assert result.exit_code == 1
    out = json.loads(result.output)
    assert out["ok"] is False
    assert out["error"]["code"] == "not_found"
