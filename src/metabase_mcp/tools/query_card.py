"""``query_card`` — execute a Metabase card and return its normalized data."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from metabase_mcp.client import MetabaseClient


def register(mcp: "FastMCP", client: "MetabaseClient") -> None:
    @mcp.tool()
    async def query_card(card_id: int) -> dict[str, Any]:
        """Execute a Metabase card by ID and return the result.

        The response contains ``cols``, ``rows`` (list of dicts), plus a
        ``chart_uri`` of the form ``metabase://card/{id}`` that a frontend
        can dispatch on to render the chart natively.
        """
        return await client.query_card(card_id)
