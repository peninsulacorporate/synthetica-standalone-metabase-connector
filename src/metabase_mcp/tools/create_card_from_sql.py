"""``create_card_from_sql`` — create or update a Metabase card from SQL.

The behavior depends on the active mode of :class:`MetabaseClient`:

- **Direct mode**: classic ``POST /api/card`` with native SQL, idempotent
  by name within the target collection (existing card with the same
  ``name`` + ``collection_id`` is updated via ``PUT /api/card/{id}``).

- **Synthetica mode**: the SQL is wrapped in a Metabase v0.60
  declarative *Representation* document and POSTed to the gateway at
  ``/api/v1/metabase/representations/apply``. The gateway applies the
  YAML-equivalent payload, deduplicates by name, runs the SQL inside
  Metabase (never on the LLM side), and returns the resulting card id.

Either mode returns the same shape on success:
``{status, id, name, chart_uri}``. On failure, both modes return
``{status: "failed", name, error}`` instead of raising — this lets the
LLM read the error and retry with a different query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from metabase_mcp.client import MetabaseClient


def register(mcp: "FastMCP", client: "MetabaseClient") -> None:
    @mcp.tool()
    async def create_card_from_sql(
        name: str,
        database_id: int,
        sql: str,
        display: str = "table",
        description: str | None = None,
        collection_id: int | None = None,
    ) -> dict[str, Any]:
        """Create (or update, if a card with the same ``name`` already
        exists in the target collection) a Metabase question that runs
        ``sql`` against ``database_id``.

        In Synthetica mode the SQL is sent through the backend gateway
        as a Metabase v0.60 Representation document — the gateway
        executes via Metabase's API on behalf of the LLM, so raw
        credentials never leave the server side. In direct mode the
        SQL is POSTed straight to ``/api/card``.

        Returns ``{status, id, name, chart_uri}`` on success, where
        ``chart_uri`` is ``metabase://card/{id}``. Returns
        ``{status: "failed", error}`` on rejection (syntax error,
        unknown column, gateway error, etc.).
        """
        return await client.create_card_from_sql(
            name=name,
            database_id=database_id,
            sql=sql,
            display=display,
            description=description,
            collection_id=collection_id,
        )
