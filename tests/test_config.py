"""Tests for config loading (BUG-2: ~/.config fallback + platform paths)."""

from __future__ import annotations

from pathlib import Path

import pytest

from zop.core import config as config_mod
from zop.core.config import load_config


def test_load_config_explicit_path_wins(tmp_path: Path) -> None:
    cfg = tmp_path / "c.toml"
    cfg.write_text('[zotero]\napi_key = "k"\nlibrary_id = "1"\n', encoding="utf-8")

    result = load_config(cfg)

    assert result.api_key == "k"
    assert result.library_id == "1"


def test_load_config_falls_back_to_home_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # platformdirs path missing; ~/.config/zop/config.toml present.
    home = tmp_path / "home"
    cfg_dir = home / ".config" / "zop"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text(
        '[zotero]\ndata_dir = "/data"\nlibrary_id = "999"\n', encoding="utf-8"
    )

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "missing.toml")
    monkeypatch.delenv("ZOP_CONFIG", raising=False)

    cfg = load_config()

    assert cfg.library_id == "999"
    assert cfg.data_dir == "/data"


def test_load_config_missing_everywhere_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "missing.toml")
    monkeypatch.delenv("ZOP_CONFIG", raising=False)

    cfg = load_config()

    assert cfg.library_id == ""
    assert cfg.data_dir == ""
