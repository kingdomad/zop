"""CLI smoke tests for collection commands (service mocked)."""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from zop.models.collection import CollectionSummary

# commands/__init__.py re-exports the `collection` *group*, which shadows the
# submodule, so fetch the real module object via importlib.
coll_mod = importlib.import_module("zop.commands.collection")


def _mock_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Collection _service takes a ctx arg; the mock ignores it."""
    svc = MagicMock()
    monkeypatch.setattr(coll_mod, "_service", lambda ctx: svc)
    monkeypatch.setattr(coll_mod, "_human", lambda: False)
    return svc


def test_collection_list_flat(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch)
    svc.list_all.return_value = [CollectionSummary(key="COLL0001", name="Topic A")]

    result = CliRunner().invoke(coll_mod.list_cmd, [])

    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["ok"] is True
    assert out["data"][0]["name"] == "Topic A"
    svc.list_all.assert_called_once()


def test_collection_list_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch)
    svc.list_tree.return_value = []

    result = CliRunner().invoke(coll_mod.list_cmd, ["--tree"])

    assert result.exit_code == 0
    svc.list_tree.assert_called_once()
