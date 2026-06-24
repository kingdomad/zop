"""CLI smoke tests for tag commands (service mocked)."""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

tag_mod = importlib.import_module("zop.commands.tag")


def _mock_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    svc = MagicMock()
    monkeypatch.setattr(tag_mod, "_service", lambda: svc)
    monkeypatch.setattr(tag_mod, "_human", lambda: False)
    return svc


def test_tag_list(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _mock_service(monkeypatch)
    svc.list_all.return_value = [{"name": "to-read", "count": 3}]

    result = CliRunner().invoke(tag_mod.list_cmd, [])

    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["ok"] is True
    assert len(out["data"]) == 1
