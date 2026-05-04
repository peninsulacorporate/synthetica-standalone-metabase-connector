"""Extended unit tests for :mod:`metabase_mcp.client`.

Covers edge cases not in test_client.py: missing env vars, paginated
Metabase responses, empty results, HTTP errors, and dashboard metadata.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from metabase_mcp import client as client_mod


# ---------------------------------------------------------------------------
# Shared helper (same pattern as test_client.py)
# ---------------------------------------------------------------------------


def _make_client(routes: dict[str, Any]) -> client_mod.MetabaseClient:
    async def _handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.path}"
        spec = routes.get(key)
        if spec is None:
            return httpx.Response(404, json={"error": f"no mock route: {key}"})
        status, body = spec
        return httpx.Response(status, json=body)

    c = client_mod.MetabaseClient(
        client_mod.Settings(metabase_url="https://mb.test", metabase_api_key="mb_key"),
    )
    c._client = httpx.AsyncClient(
        base_url="https://mb.test",
        headers={"x-api-key": "mb_key"},
        transport=httpx.MockTransport(_handler),
    )
    return c


# ---------------------------------------------------------------------------
# Settings — edge cases
# ---------------------------------------------------------------------------


class TestSettings:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.setenv("METABASE_URL", "https://mb.test")
        monkeypatch.delenv("METABASE_API_KEY", raising=False)
        with pytest.raises(client_mod.ConfigError):
            client_mod.Settings.from_env()

    def test_missing_url_raises(self, monkeypatch):
        monkeypatch.delenv("METABASE_URL", raising=False)
        monkeypatch.setenv("METABASE_API_KEY", "mb_key")
        with pytest.raises(client_mod.ConfigError):
            client_mod.Settings.from_env()

    def test_both_missing_raises(self, monkeypatch):
        monkeypatch.delenv("METABASE_URL", raising=False)
        monkeypatch.delenv("METABASE_API_KEY", raising=False)
        with pytest.raises(client_mod.ConfigError):
            client_mod.Settings.from_env()

    def test_trailing_slash_stripped(self, monkeypatch):
        monkeypatch.setenv("METABASE_URL", "https://mb.test/")
        monkeypatch.setenv("METABASE_API_KEY", "mb_key")
        s = client_mod.Settings.from_env()
        assert not s.metabase_url.endswith("/")

    def test_config_error_is_runtime_error(self):
        assert issubclass(client_mod.ConfigError, RuntimeError)


# ---------------------------------------------------------------------------
# list_cards — edge cases
# ---------------------------------------------------------------------------


class TestListCards:
    @pytest.mark.asyncio
    async def test_paginated_envelope_unwrapped(self):
        """Metabase sometimes returns ``{"data": [...]}`` instead of a bare list."""
        c = _make_client({
            "GET /api/card": (200, {"data": [
                {"id": 5, "name": "Sales", "display": "bar"},
            ]}),
        })
        try:
            cards = await c.list_cards()
        finally:
            await c.aclose()
        assert len(cards) == 1
        assert cards[0]["id"] == 5

    @pytest.mark.asyncio
    async def test_empty_list(self):
        c = _make_client({"GET /api/card": (200, [])})
        try:
            cards = await c.list_cards()
        finally:
            await c.aclose()
        assert cards == []

    @pytest.mark.asyncio
    async def test_null_description_becomes_empty_string(self):
        c = _make_client({
            "GET /api/card": (200, [{"id": 1, "name": "X", "description": None}]),
        })
        try:
            cards = await c.list_cards()
        finally:
            await c.aclose()
        assert cards[0]["description"] == ""

    @pytest.mark.asyncio
    async def test_http_error_propagates(self):
        c = _make_client({"GET /api/card": (500, {"message": "internal error"})})
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await c.list_cards()
        finally:
            await c.aclose()

    @pytest.mark.asyncio
    async def test_all_expected_keys_present(self):
        c = _make_client({
            "GET /api/card": (200, [{"id": 3, "name": "X", "display": "pie", "collection_id": 7}]),
        })
        try:
            cards = await c.list_cards()
        finally:
            await c.aclose()
        assert set(cards[0].keys()) == {"id", "name", "description", "display", "collection_id"}


# ---------------------------------------------------------------------------
# query_card — edge cases
# ---------------------------------------------------------------------------


class TestQueryCard:
    @pytest.mark.asyncio
    async def test_empty_result_set(self):
        c = _make_client({
            "GET /api/card/1": (200, {"name": "Empty", "display": "table"}),
            "POST /api/card/1/query": (200, {"data": {"cols": [], "rows": []}}),
        })
        try:
            result = await c.query_card(1)
        finally:
            await c.aclose()
        assert result["rows"] == []
        assert result["cols"] == []
        assert result["chart_uri"] == "metabase://card/1"

    @pytest.mark.asyncio
    async def test_chart_uri_always_uses_card_id(self):
        c = _make_client({
            "GET /api/card/99": (200, {"name": "Q", "display": "line"}),
            "POST /api/card/99/query": (200, {
                "data": {"cols": [{"name": "x"}], "rows": [[1]]},
            }),
        })
        try:
            result = await c.query_card(99)
        finally:
            await c.aclose()
        assert result["chart_uri"] == "metabase://card/99"

    @pytest.mark.asyncio
    async def test_rows_are_dicts_not_lists(self):
        """Rows must be zipped with column names, not returned as raw arrays."""
        c = _make_client({
            "GET /api/card/2": (200, {"name": "T", "display": "table"}),
            "POST /api/card/2/query": (200, {
                "data": {
                    "cols": [{"name": "a"}, {"name": "b"}],
                    "rows": [[1, 2], [3, 4]],
                },
            }),
        })
        try:
            result = await c.query_card(2)
        finally:
            await c.aclose()
        assert result["rows"] == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]

    @pytest.mark.asyncio
    async def test_query_http_error_propagates(self):
        c = _make_client({
            "GET /api/card/3": (200, {"name": "Q", "display": "table"}),
            "POST /api/card/3/query": (500, {"message": "query failed"}),
        })
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await c.query_card(3)
        finally:
            await c.aclose()

    @pytest.mark.asyncio
    async def test_name_and_display_in_response(self):
        c = _make_client({
            "GET /api/card/10": (200, {"name": "Revenue", "display": "area"}),
            "POST /api/card/10/query": (200, {
                "data": {"cols": [{"name": "day"}], "rows": [["2026-01-01"]]},
            }),
        })
        try:
            result = await c.query_card(10)
        finally:
            await c.aclose()
        assert result["name"] == "Revenue"
        assert result["display"] == "area"


# ---------------------------------------------------------------------------
# create_dashboard — edge cases
# ---------------------------------------------------------------------------


class TestCreateDashboard:
    @pytest.mark.asyncio
    async def test_no_cards_creates_empty_dashboard(self):
        c = _make_client({"POST /api/dashboard": (200, {"id": 1, "name": "Dash"})})
        try:
            result = await c.create_dashboard("Dash")
        finally:
            await c.aclose()
        assert result == {"id": 1, "name": "Dash", "card_count": 0}

    @pytest.mark.asyncio
    async def test_empty_card_ids_list(self):
        c = _make_client({"POST /api/dashboard": (200, {"id": 2, "name": "D"})})
        try:
            result = await c.create_dashboard("D", card_ids=[])
        finally:
            await c.aclose()
        assert result["card_count"] == 0

    @pytest.mark.asyncio
    async def test_cards_attached_in_order(self):
        """Each card must POST to /api/dashboard/{id}/cards."""
        calls: list[str] = []

        async def _handler(request: httpx.Request) -> httpx.Response:
            calls.append(f"{request.method} {request.url.path}")
            if request.url.path == "/api/dashboard":
                return httpx.Response(200, json={"id": 5, "name": "D"})
            return httpx.Response(200, json={})

        c = client_mod.MetabaseClient(
            client_mod.Settings(metabase_url="https://mb.test", metabase_api_key="k"),
        )
        c._client = httpx.AsyncClient(
            base_url="https://mb.test",
            transport=httpx.MockTransport(_handler),
        )
        try:
            result = await c.create_dashboard("D", card_ids=[10, 20])
        finally:
            await c.aclose()

        assert result["card_count"] == 2
        assert calls.count("POST /api/dashboard/5/cards") == 2

    @pytest.mark.asyncio
    async def test_http_error_propagates(self):
        c = _make_client({"POST /api/dashboard": (400, {"message": "bad request"})})
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await c.create_dashboard("Bad")
        finally:
            await c.aclose()

    @pytest.mark.asyncio
    async def test_description_and_collection_id_sent(self):
        """Verify that optional fields are included in the request body."""
        received: dict = {}

        async def _handler(request: httpx.Request) -> httpx.Response:
            import json
            received.update(json.loads(request.content))
            return httpx.Response(200, json={"id": 1, "name": "D"})

        c = client_mod.MetabaseClient(
            client_mod.Settings(metabase_url="https://mb.test", metabase_api_key="k"),
        )
        c._client = httpx.AsyncClient(
            base_url="https://mb.test",
            transport=httpx.MockTransport(_handler),
        )
        try:
            await c.create_dashboard("D", description="My dash", collection_id=7)
        finally:
            await c.aclose()

        assert received.get("description") == "My dash"
        assert received.get("collection_id") == 7
