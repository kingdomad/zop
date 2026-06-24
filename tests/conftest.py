"""Shared pytest fixtures."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from zop.adapters.zotero_api import ApiCreds, ZoteroApi


@pytest.fixture
def fake_db(tmp_path: Path) -> Path:
    """An empty SQLite file.

    SqliteReader.__init__ only checks the path exists, so services construct
    without needing a real schema. Tests that trigger DB reads monkeypatch the
    specific reader methods they exercise.
    """
    db = tmp_path / "zotero.sqlite"
    sqlite3.connect(db).close()
    return db


@pytest.fixture
def creds() -> ApiCreds:
    return ApiCreds(library_id="12345", api_key="dummy")


@pytest.fixture
def fake_api() -> AsyncMock:
    """A ZoteroApi-shaped AsyncMock usable as ``async with api:``."""
    api = AsyncMock(spec=ZoteroApi)
    api.__aenter__ = AsyncMock(return_value=api)
    api.__aexit__ = AsyncMock(return_value=None)
    return api
