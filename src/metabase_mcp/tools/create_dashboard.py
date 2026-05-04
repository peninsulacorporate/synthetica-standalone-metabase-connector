"""``create_dashboard`` — create a Metabase dashboard, optionally with cards."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from metabase_mcp.client import MetabaseClient


def register(mcp: "FastMCP", client: "MetabaseClient") -> None:
    @mcp.tool()
    async def create_dashboard(
        name: str,
        description: str | None = None,
        collection_id: int | None = None,
        card_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Create a Metabase dashboard.

        When ``card_ids`` is provided, the cards are attached in a simple
        vertical grid layout (one card per row, full width).
        """
        return await client.create_dashboard(
            name,
            description=description,
            collection_id=collection_id,
            card_ids=card_ids,
        )
