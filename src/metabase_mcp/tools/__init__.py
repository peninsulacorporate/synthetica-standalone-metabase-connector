"""MCP tool registrations.

Each module here exposes a :func:`register` function that wires one tool
against a shared FastMCP instance. :func:`register_all` is the aggregate
entrypoint used by :mod:`metabase_mcp.server`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metabase_mcp.tools import (
    create_card_from_sql,
    create_dashboard,
    list_cards,
    list_database_tables,
    list_databases,
    query_card,
    request_synthetic_data_generation,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from metabase_mcp.client import MetabaseClient


def register_all(mcp: "FastMCP", client: "MetabaseClient") -> None:
    """Register every tool in this package against ``mcp``.

    The ``request_synthetic_data_generation`` tool is registered in both
    modes; in direct mode it raises :class:`RuntimeError` at call time
    rather than disappearing — the LLM gets a clear, actionable error.
    """
    list_cards.register(mcp, client)
    query_card.register(mcp, client)
    list_databases.register(mcp, client)
    list_database_tables.register(mcp, client)
    create_dashboard.register(mcp, client)
    create_card_from_sql.register(mcp, client)
    request_synthetic_data_generation.register(mcp, client)
