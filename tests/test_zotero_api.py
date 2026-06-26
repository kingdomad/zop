"""Tests for ZoteroApi adapter (HTTP layer mocked via httpx.MockTransport)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from zop.adapters.zotero_api import ApiCreds, ZoteroApi
from zop.core.errors import AuthError, ConflictError, NotFoundError


@pytest.fixture
def creds() -> ApiCreds:
    return ApiCreds(library_id="12345", api_key="dummy")


# ---- update_item ----


async def test_update_item_sends_patch_with_version(creds: ApiCreds) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["iuv"] = request.headers.get("If-Unmodified-Since-Version")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"key": "K", "version": 8, "data": {"tags": []}})

    async with ZoteroApi(creds, transport=httpx.MockTransport(handler)) as api:
        result = await api.update_item("K", {"tags": [{"tag": "x"}]}, version=7)

    assert seen["method"] == "PATCH"
    assert seen["path"].endswith("/users/12345/items/K")
    assert seen["iuv"] == "7"
    assert seen["body"] == {"tags": [{"tag": "x"}]}
    assert result["key"] == "K"


async def test_update_item_without_version_omits_header(creds: ApiCreds) -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["iuv"] = request.headers.get("If-Unmodified-Since-Version")
        return httpx.Response(200, json={"key": "K"})

    async with ZoteroApi(creds, transport=httpx.MockTransport(handler)) as api:
        await api.update_item("K", {"title": "t"})

    assert seen["iuv"] is None


async def test_update_item_empty_body_returns_empty_dict(creds: ApiCreds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)  # no content

    async with ZoteroApi(creds, transport=httpx.MockTransport(handler)) as api:
        result = await api.update_item("K", {"title": "t"})

    assert result == {}


# ---- delete_item ----


async def test_delete_item_sends_delete_with_version(creds: ApiCreds) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["iuv"] = request.headers.get("If-Unmodified-Since-Version")
        return httpx.Response(204)

    async with ZoteroApi(creds, transport=httpx.MockTransport(handler)) as api:
        await api.delete_item("K", version=3)

    assert seen["method"] == "DELETE"
    assert seen["iuv"] == "3"


async def test_delete_item_raises_conflict_on_412(creds: ApiCreds) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(412, text="version mismatch")

    async with ZoteroApi(creds, transport=httpx.MockTransport(handler)) as api:
        with pytest.raises(ConflictError):
            await api.delete_item("K", version=3)


# ---- create_items ----


async def test_create_items_posts_list_and_parses_successful(creds: ApiCreds) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"successful": {"0": {"key": "NEW1", "version": 1}}, "failed": {}}
        )

    async with ZoteroApi(creds, transport=httpx.MockTransport(handler)) as api:
        result = await api.create_items([{"itemType": "journalArticle", "DOI": "10.x"}])

    assert seen["method"] == "POST"
    assert seen["body"] == [{"itemType": "journalArticle", "DOI": "10.x"}]
    successful, failed = result
    assert successful == [{"key": "NEW1", "version": 1}]
    assert failed == []


async def test_create_items_empty_input_returns_empty_without_request(
    creds: ApiCreds,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    async with ZoteroApi(creds, transport=httpx.MockTransport(handler)) as api:
        successful, failed = await api.create_items([])

    assert successful == []
    assert failed == []
    assert calls == 0  # short-circuit, no HTTP


async def test_create_items_surfaces_failed_envelope(creds: ApiCreds) -> None:
    """create_items must surface Zotero's failed envelope (BUG-15), not silently
    drop it. Each failure carries {index, code, message} so callers can map to a
    ZopError. HTTP is 200 even when entries fail.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "successful": {"1": {"key": "OK000001", "version": 1}},
                "failed": {
                    "0": {"code": 400, "message": "'parentItem' must be a valid item key"}
                },
            },
        )

    async with ZoteroApi(creds, transport=httpx.MockTransport(handler)) as api:
        successful, failed = await api.create_items([{"DOI": "bad"}, {"DOI": "good"}])

    assert [s["key"] for s in successful] == ["OK000001"]
    assert len(failed) == 1
    assert failed[0]["index"] == 0
    assert failed[0]["code"] == 400
    assert "parentItem" in failed[0]["message"]


async def test_create_items_chunks_at_write_limit(creds: ApiCreds) -> None:
    posts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        body = json.loads(request.content)
        successful = {str(i): {"key": f"K{i}"} for i in range(len(body))}
        return httpx.Response(200, json={"successful": successful})

    payloads = [{"DOI": str(i)} for i in range(51)]  # BATCH_WRITE_LIMIT=50
    async with ZoteroApi(creds, transport=httpx.MockTransport(handler)) as api:
        successful, failed = await api.create_items(payloads)

    assert posts == 2  # 50 + 1
    assert len(successful) == 51
    assert failed == []


# ---- zotero_failure_to_error ----


def test_zotero_failure_to_error_maps_codes() -> None:
    """Zotero failed-envelope codes map to ZopError subclasses; message preserved."""
    from zop.adapters.zotero_api import zotero_failure_to_error
    from zop.core.errors import ApiError, AuthError, ConflictError, ValidationError

    assert isinstance(
        zotero_failure_to_error({"code": 400, "message": "bad"}), ValidationError
    )
    assert isinstance(
        zotero_failure_to_error({"code": 409, "message": "conflict"}), ConflictError
    )
    assert isinstance(
        zotero_failure_to_error({"code": 412, "message": "precondition"}), ConflictError
    )
    assert isinstance(
        zotero_failure_to_error({"code": 401, "message": "auth"}), AuthError
    )
    # unknown code → ApiError, message still preserved
    err = zotero_failure_to_error({"code": 500, "message": "boom"})
    assert isinstance(err, ApiError)
    assert "boom" in err.message
    # missing message → sane default (non-empty)
    assert zotero_failure_to_error({"code": 400}).message


# ---- get_collection ----


async def test_get_collection_gets_single_collection(creds: ApiCreds) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(
            200, json={"key": "K", "version": 9, "data": {"name": "n"}}
        )

    async with ZoteroApi(creds, transport=httpx.MockTransport(handler)) as api:
        result = await api.get_collection("K")

    assert seen["method"] == "GET"
    assert seen["path"].endswith("/users/12345/collections/K")
    assert result["key"] == "K"
    assert result["version"] == 9


# ---- update_collection ----


async def test_update_collection_empty_body_returns_empty_dict(creds: ApiCreds) -> None:
    """BUG-11: Zotero PATCH /collections/{key} returns 204 No Content (empty
    body). update_collection must yield {} (like update_item), not None — a
    ``None`` return crashes any caller that subscripts the result (reparent).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)  # no content

    async with ZoteroApi(creds, transport=httpx.MockTransport(handler)) as api:
        result = await api.update_collection("K", parent_key="P", version=5)

    assert result == {}


# ---- _check status-code mapping ----


def _resp(status: int, *, text: str = "") -> httpx.Response:
    """Build a Response with an attached request so .url/.text are usable."""
    return httpx.Response(
        status, text=text, request=httpx.Request("GET", "https://api.zotero.org/x")
    )


async def test_check_404_raises_not_found(creds: ApiCreds) -> None:
    async with ZoteroApi(creds, transport=httpx.MockTransport(lambda r: _resp(404))) as api:
        with pytest.raises(NotFoundError):
            api._check(_resp(404))


async def test_check_401_raises_auth(creds: ApiCreds) -> None:
    async with ZoteroApi(creds, transport=httpx.MockTransport(lambda r: _resp(401))) as api:
        with pytest.raises(AuthError):
            api._check(_resp(401))


async def test_check_412_raises_conflict(creds: ApiCreds) -> None:
    async with ZoteroApi(creds, transport=httpx.MockTransport(lambda r: _resp(412, text="c"))) as api:
        with pytest.raises(ConflictError):
            api._check(_resp(412, text="c"))
