"""Configuration loader.

Reads zop's own config first; falls back to ``~/.config/zot/config.toml`` so
users can reuse their existing credentials. Supports TOML flat schema only
in v0.1 — profile-based schema is on the roadmap.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import platformdirs

APP_NAME = "zop"
CONFIG_FILE = Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)) / "config.toml"
ZOT_CONFIG_FILE = Path.home() / ".config" / "zot" / "config.toml"


@dataclass
class AppConfig:
    """Resolved configuration."""

    data_dir: str = ""
    library_id: str = ""
    api_key: str = ""
    semantic_scholar_api_key: str = ""

    @property
    def has_write_credentials(self) -> bool:
        return bool(self.library_id and self.api_key)


def _load_toml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from disk.

    Lookup order:
    1. ``ZOP_CONFIG`` env var (override path)
    2. ``<config_dir>/zop/config.toml`` (this app's config)
    3. ``~/.config/zot/config.toml`` (reuse existing zot config)
    """
    if path is None:
        path = Path(os.environ["ZOP_CONFIG"]) if "ZOP_CONFIG" in os.environ else None

    data: dict[str, object] = {}
    if path is not None:
        data = _load_toml(path)
    else:
        data = _load_toml(CONFIG_FILE) or _load_toml(ZOT_CONFIG_FILE)

    # Flat schema: [zotero] section (compatible with zot).
    z = data.get("zotero", {}) if isinstance(data, dict) else {}
    if not isinstance(z, dict):
        z = {}
    return AppConfig(
        data_dir=str(z.get("data_dir", "")),
        library_id=str(z.get("library_id", "")),
        api_key=str(z.get("api_key", "")),
        semantic_scholar_api_key=str(z.get("semantic_scholar_api_key", "")),
    )


__all__ = ["CONFIG_FILE", "ZOT_CONFIG_FILE", "AppConfig", "load_config"]
