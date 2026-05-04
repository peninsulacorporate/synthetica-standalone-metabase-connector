"""Unit tests for :mod:`metabase_mcp.tools`.

Verifies that :func:`register_all` registers exactly seven tools with the
expected names and that each tool delegates to the correct client method.
No real Metabase server is needed — the client is replaced with an AsyncMock.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastmcp import FastMCP

from metabase_mcp.tools import register_all


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mcp_and_client() -> tuple[FastMCP, MagicMock]:
    mcp = FastMCP("test")
    client = MagicMock()
    client.list_cards = AsyncMock(return_value=[{"id": 1}])
    client.query_card = AsyncMock(return_value={"rows": [], "cols": [], "chart_uri": "metabase://card/1"})
    client.create_dashboard = AsyncMock(return_value={"id": 1, "name": "D", "card_count": 0})
    client.list_database_tables = AsyncMock(return_value=[{"id": 1, "name": "t", "fields": []}])
    client.create_card_from_sql = AsyncMock(
        return_value={"status": "created", "id": 77, "name": "c", "chart_uri": "metabase://card/77"},
    )
    client.list_databases = AsyncMock(return_value=[{"id": 1, "name": "db", "engine": "postgres"}])
    client.list_database_tables = AsyncMock(return_value=[{"id": 1, "name": "t", "fields": []}])
    client.request_synthetic_data_generation = AsyncMock(
        return_value={"status": "accepted", "job_id": "abc", "bypassed": False},
    )
    return mcp, client


def _tool_names(mcp: FastMCP) -> set[str]:
    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegisterAll:
    def test_registers_exactly_seven_tools(self):
        mcp, client = _make_mcp_and_client()
        register_all(mcp, client)
        assert len(asyncio.run(mcp.list_tools())) == 7

    def test_tool_names(self):
        mcp, client = _make_mcp_and_client()
        register_all(mcp, client)
        assert _tool_names(mcp) == {
            "list_cards",
            "query_card",
            "list_databases",
            "list_database_tables",
            "create_dashboard",
            "create_card_from_sql",
            "request_synthetic_data_generation",
        }

    def test_register_all_single_call_count(self):
        """Single ``register_all`` registers exactly seven tools (one per file)."""
        mcp, client = _make_mcp_and_client()
        register_all(mcp, client)
        assert len(asyncio.run(mcp.list_tools())) == 7


# ---------------------------------------------------------------------------
# list_cards tool
# ---------------------------------------------------------------------------


class TestListCardsTool:
    @pytest.mark.asyncio
    async def test_delegates_to_client(self):
        mcp, client = _make_mcp_and_client()
        register_all(mcp, client)
        await mcp.call_tool("list_cards", {})
        client.list_cards.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_limit_argument(self):
        mcp, client = _make_mcp_and_client()
        register_all(mcp, client)
        await mcp.call_tool("list_cards", {"limit": 5})
        client.list_cards.assert_awaited_once_with(limit=5)

    @pytest.mark.asyncio
    async def test_default_limit_is_30(self):
        mcp, client = _make_mcp_and_client()
        register_all(mcp, client)
        await mcp.call_tool("list_cards", {})
        client.list_cards.assert_awaited_once_with(limit=30)

    @pytest.mark.asyncio
    async def test_returns_client_result(self):
        mcp, client = _make_mcp_and_client()
        client.list_cards = AsyncMock(return_value=[{"id": 7, "name": "Revenue"}])
        register_all(mcp, client)
        result = await mcp.call_tool("list_cards", {})
        assert result is not None


# ---------------------------------------------------------------------------
# query_card tool
# ---------------------------------------------------------------------------


class TestQueryCardTool:
    @pytest.mark.asyncio
    async def test_delegates_to_client(self):
        mcp, client = _make_mcp_and_client()
        register_all(mcp, client)
        await mcp.call_tool("query_card", {"card_id": 42})
        client.query_card.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_passes_card_id(self):
        mcp, client = _make_mcp_and_client()
        register_all(mcp, client)
        await mcp.call_tool("query_card", {"card_id": 99})
        client.query_card.assert_awaited_once_with(99)

    @pytest.mark.asyncio
    async def test_returns_client_result(self):
        mcp, client = _make_mcp_and_client()
        expected = {"chart_uri": "metabase://card/5", "rows": [{"x": 1}], "cols": [{"name": "x"}]}
        client.query_card = AsyncMock(return_value=expected)
        register_all(mcp, client)
        result = await mcp.call_tool("query_card", {"card_id": 5})
        assert result is not None


# ---------------------------------------------------------------------------
# create_dashboard tool
# ---------------------------------------------------------------------------


class TestCreateDashboardTool:
    @pytest.mark.asyncio
    async def test_delegates_to_client(self):
        mcp, client = _make_mcp_and_client()
        register_all(mcp, client)
        await mcp.call_tool("create_dashboard", {"name": "My Dash"})
        client.create_dashboard.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_name_only(self):
        mcp, client = _make_mcp_and_client()
        register_all(mcp, client)
        await mcp.call_tool("create_dashboard", {"name": "Sales"})
        args, kwargs = client.create_dashboard.call_args
        assert args[0] == "Sales"
        assert kwargs.get("card_ids") is None

    @pytest.mark.asyncio
    async def test_passes_optional_card_ids(self):
        mcp, client = _make_mcp_and_client()
        register_all(mcp, client)
        await mcp.call_tool("create_dashboard", {"name": "D", "card_ids": [1, 2, 3]})
        _, kwargs = client.create_dashboard.call_args
        assert kwargs.get("card_ids") == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_passes_description_and_collection_id(self):
        mcp, client = _make_mcp_and_client()
        register_all(mcp, client)
        await mcp.call_tool(
            "create_dashboard",
            {"name": "D", "description": "A dashboard", "collection_id": 7},
        )
        _, kwargs = client.create_dashboard.call_args
        assert kwargs.get("description") == "A dashboard"
        assert kwargs.get("collection_id") == 7
