"""CLI smoke tests for library commands (service mocked)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from zop.commands import library as lib_mod
from zop.core.config import AppConfig
from zop.core.errors import ZopError
from zop.models.common import ItemType
from zop.models.item import ItemSummary


def _mock_service(monkeypatch: pytest.MonkeyPatch, module: object) -> MagicMock:
    """Inject a MagicMock service into a command module (no-arg _service)."""
    svc = MagicMock()
    monkeypatch.setattr(module, "_service", lambda: svc)
    monkeypatch.setattr(module, "_human", lambda: False)
    return svc


def test_stats_command(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch, lib_mod)
    svc.stats.return_value = {"total_items": 4, "pdf_attachments": 1}

    result = CliRunner().invoke(lib_mod.stats_cmd, [])

    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["ok"] is True
    assert out["data"]["total_items"] == 4


def test_recent_command(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch, lib_mod)
    svc.recent.return_value = [
        ItemSummary(key="ITEM0001", item_type=ItemType.JOURNAL_ARTICLE, title="t")
    ]

    result = CliRunner().invoke(lib_mod.recent_cmd, ["--days", "30"])

    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["ok"] is True
    assert len(out["data"]) == 1


def test_duplicates_command(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch, lib_mod)
    svc.duplicates.return_value = {"10.x": ["ITEM0001"]}

    result = CliRunner().invoke(lib_mod.duplicates_cmd, ["--by", "doi"])

    assert result.exit_code == 0
    assert json.loads(result.output)["ok"] is True


def test_stats_zop_error_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch, lib_mod)
    svc.stats.side_effect = ZopError("boom")

    result = CliRunner().invoke(lib_mod.stats_cmd, [])

    assert result.exit_code == 1
    assert json.loads(result.output)["ok"] is False


def test_stats_no_config_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lib_mod, "load_config", lambda: AppConfig())

    result = CliRunner().invoke(lib_mod.stats_cmd, [])

    assert result.exit_code == 2  # click.UsageError
