"""Configuration loader.

Reads config from the first existing of: an explicit path, the
``ZOP_CONFIG`` env var, the platform-specific user config dir
(``platformdirs``), or ``~/.config/zop/config.toml`` as a fallback.
Supports a flat TOML schema only in v0.1 — a profile-based schema is on
the roadmap.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import platformdirs

APP_NAME = "zop"
CONFIG_FILE = Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)) / "config.toml"


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

    Lookup order (first existing file wins):
    1. explicit ``path`` argument
    2. ``ZOP_CONFIG`` env var (explicit override)
    3. platform-specific user config dir (``platformdirs``: on Windows
       ``%LOCALAPPDATA%\\zop``, on macOS ``~/Library/Application Support/zop``,
       on Linux ``~/.config/zop``)
    4. ``~/.config/zop/config.toml`` fallback (Unix convention, cross-platform)
    """
    if path is not None:
        data = _load_toml(path)
    else:
        candidates: list[Path] = []
        if "ZOP_CONFIG" in os.environ:
            candidates.append(Path(os.environ["ZOP_CONFIG"]))
        candidates.append(CONFIG_FILE)
        candidates.append(Path.home() / ".config" / "zop" / "config.toml")
        data = {}
        for candidate in candidates:
            if candidate.exists():
                data = _load_toml(candidate)
                break

    # Flat schema: [zotero] section.
    z = data.get("zotero", {}) if isinstance(data, dict) else {}
    if not isinstance(z, dict):
        z = {}
    return AppConfig(
        data_dir=str(z.get("data_dir", "")),
        library_id=str(z.get("library_id", "")),
        api_key=str(z.get("api_key", "")),
        semantic_scholar_api_key=str(z.get("semantic_scholar_api_key", "")),
    )


__all__ = ["CONFIG_FILE", "AppConfig", "load_config"]
