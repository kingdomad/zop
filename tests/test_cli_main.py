"""Smoke tests for the top-level CLI entry point (zop.cli.main)."""

from __future__ import annotations

from click.testing import CliRunner

from zop import __version__
from zop.cli import main


def test_version_flag() -> None:
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_json_and_human_are_mutually_exclusive() -> None:
    result = CliRunner().invoke(main, ["--json", "--human"])
    assert result.exit_code == 2  # click.UsageError


def test_help_flag() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    # Help lists the registered subcommands.
    assert "collection" in result.output
    assert "stats" in result.output
