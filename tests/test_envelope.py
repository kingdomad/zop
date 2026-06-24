"""Tests for the JSON output envelope (emit / emit_error / emit_batch)."""

from __future__ import annotations

import json

import pytest

from zop.core.envelope import emit, emit_batch, emit_error
from zop.core.errors import (
    ApiError,
    AuthError,
    ConflictError,
    NotFoundError,
    ZopError,
)
from zop.models.common import ItemType
from zop.models.item import ItemSummary

# ---- emit() ----


def test_emit_ok_json(capsys: pytest.CaptureFixture[str]) -> None:
    emit({"a": 1}, count=1)
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["data"] == {"a": 1}
    assert out["meta"]["count"] == 1
    assert "error" not in out  # exclude_none drops the None error


def test_emit_ok_no_count_omits_field(capsys: pytest.CaptureFixture[str]) -> None:
    emit({"a": 1})
    meta = json.loads(capsys.readouterr().out)["meta"]
    assert "count" not in meta  # None is excluded by to_json
    assert "latency_ms" in meta  # 0 is not None, kept


def test_emit_ok_human_is_indented(capsys: pytest.CaptureFixture[str]) -> None:
    emit({"a": 1}, human=True)
    raw = capsys.readouterr().out
    assert json.loads(raw)["ok"] is True
    assert "\n  " in raw  # indent=2 from to_human()


def test_emit_error_json(capsys: pytest.CaptureFixture[str]) -> None:
    emit(error=ZopError("boom"))
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["error"]["code"] == "zop_error"
    assert out["error"]["message"] == "boom"
    assert out["error"]["retryable"] is False


def test_emit_error_subclass_preserves_code_and_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit(error=AuthError("no key"))
    err = json.loads(capsys.readouterr().out)["error"]
    assert err["code"] == "auth_missing"
    assert "config init" in err["hint"]


def test_emit_error_retryable_flag(capsys: pytest.CaptureFixture[str]) -> None:
    emit(error=ApiError(500, "oops"))
    err = json.loads(capsys.readouterr().out)["error"]
    assert err["code"] == "api_error"
    assert err["retryable"] is True


def test_emit_error_human_prefix(capsys: pytest.CaptureFixture[str]) -> None:
    emit(error=ZopError("bad"), human=True)
    assert capsys.readouterr().out.startswith("Error [zop_error]: bad")


def test_emit_latency_ms_is_nonneg_int(capsys: pytest.CaptureFixture[str]) -> None:
    emit({"a": 1})
    latency = json.loads(capsys.readouterr().out)["meta"]["latency_ms"]
    assert isinstance(latency, int)
    assert latency >= 0


# ---- emit_error() ----


def test_emit_error_delegates_to_emit(capsys: pytest.CaptureFixture[str]) -> None:
    emit_error(NotFoundError("missing"))
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["error"]["code"] == "not_found"


# ---- emit_batch() ----


def test_emit_batch_all_success(capsys: pytest.CaptureFixture[str]) -> None:
    emit_batch([{"key": "A"}, {"key": "B"}], [])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert len(out["data"]["succeeded"]) == 2
    assert out["data"]["failed"] == []
    assert out["meta"]["count"] == 2


def test_emit_batch_has_failures(capsys: pytest.CaptureFixture[str]) -> None:
    emit_batch([{"key": "A"}], [("B", ConflictError("dup"))])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["data"]["failed"][0]["key"] == "B"
    assert out["data"]["failed"][0]["error"]["code"] == "conflict"


def test_emit_batch_empty(capsys: pytest.CaptureFixture[str]) -> None:
    emit_batch([], [])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["data"]["succeeded"] == []
    assert out["meta"]["count"] == 0


def test_emit_batch_human_is_indented(capsys: pytest.CaptureFixture[str]) -> None:
    emit_batch([{"k": 1}], [], human=True)
    raw = capsys.readouterr().out
    assert json.loads(raw)["ok"] is True
    assert "\n  " in raw


def test_emit_batch_dumps_pydantic_models(capsys: pytest.CaptureFixture[str]) -> None:
    item = ItemSummary(key="ITEM0001", item_type=ItemType.JOURNAL_ARTICLE, title="t")
    emit_batch([item], [])
    succeeded = json.loads(capsys.readouterr().out)["data"]["succeeded"]
    assert isinstance(succeeded[0], dict)  # model_dump() applied, not the model
    assert succeeded[0]["key"] == "ITEM0001"
