"""CLI smoke tests for note commands (service mocked)."""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

note_mod = importlib.import_module("zop.commands.note")


def _mock_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    svc = MagicMock()
    monkeypatch.setattr(note_mod, "_service", lambda: svc)
    monkeypatch.setattr(note_mod, "_human", lambda: False)
    return svc


def test_note_list(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch)
    svc.list_for_item.return_value = [{"key": "NOTE0001", "text": "n"}]

    result = CliRunner().invoke(note_mod.list_cmd, ["ITEM0001"])

    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["ok"] is True
    assert len(out["data"]) == 1
