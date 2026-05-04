"""``list_databases`` — enumerate Metabase databases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from metabase_mcp.client import MetabaseClient


def register(mcp: "FastMCP", client: "MetabaseClient") -> None:
    @mcp.tool()
    async def list_databases() -> list[dict[str, Any]]:
        """List databases Metabase knows about.

        Returns ``[{id, name, engine}]``. Combine with
        ``list_database_tables(id)`` to navigate the schema before
        calling ``create_card_from_sql``.
        """
        return await client.list_databases()
