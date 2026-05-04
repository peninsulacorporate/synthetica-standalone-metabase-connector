"""``list_database_tables`` — enumerate tables in a Metabase database."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from metabase_mcp.client import MetabaseClient


def register(mcp: "FastMCP", client: "MetabaseClient") -> None:
    @mcp.tool()
    async def list_database_tables(database_id: int) -> list[dict[str, Any]]:
        """List tables (with their fields) in a Metabase database.

        Calls ``/api/database/{id}/metadata`` and returns a trimmed
        structure suitable for LLM reasoning: ``{id, name, schema,
        fields_count, fields: [{name, base_type, semantic_type}]}``.
        Hidden tables (``visibility_type`` set) are filtered out.
        """
        return await client.list_database_tables(database_id)
