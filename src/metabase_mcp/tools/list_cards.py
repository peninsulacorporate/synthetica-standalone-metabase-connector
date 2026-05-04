"""``list_cards`` — enumerate Metabase questions available to the caller."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from metabase_mcp.client import MetabaseClient


def register(mcp: "FastMCP", client: "MetabaseClient") -> None:
    @mcp.tool()
    async def list_cards(limit: int = 30) -> list[dict[str, Any]]:
        """List available Metabase questions/cards.

        Returns a list of ``{id, name, description, display, collection_id}``
        entries. Use ``query_card(id)`` to fetch the actual data for a given
        card.
        """
        return await client.list_cards(limit=limit)
