"""CLI smoke tests for the export command (service mocked)."""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from zop.models.common import ItemType
from zop.models.item import Item

export_mod = importlib.import_module("zop.commands.export")


def _mock_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    svc = MagicMock()
    monkeypatch.setattr(export_mod, "_service", lambda: svc)
    monkeypatch.setattr(export_mod, "_human", lambda: False)
    return svc


def test_export_bibtex(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch)
    svc._reader.get_item.return_value = Item(
        key="ITEM0001", item_type=ItemType.JOURNAL_ARTICLE, title="t"
    )
    svc.to_bibtex.return_value = "@article{ITEM0001,...}"

    result = CliRunner().invoke(export_mod.export_cmd, ["ITEM0001"])

    assert result.exit_code == 0
    # bibtex is written as raw text, not wrapped in a JSON envelope.
    assert "@article" in result.output


def test_export_csl_json(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch)
    svc._reader.get_item.return_value = Item(
        key="ITEM0001", item_type=ItemType.JOURNAL_ARTICLE, title="t"
    )
    svc.to_csl_json.return_value = [{"id": "ITEM0001", "type": "article-journal"}]

    result = CliRunner().invoke(export_mod.export_cmd, ["ITEM0001", "--format", "csl-json"])

    assert result.exit_code == 0
    # csl-json is emitted as a raw JSON array (no envelope).
    data = json.loads(result.output)
    assert data[0]["id"] == "ITEM0001"
