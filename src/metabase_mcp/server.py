"""Entrypoint for the ``metabase-mcp`` CLI.

Builds the dual-mode :class:`MetabaseClient` from environment variables,
registers tools, and runs FastMCP over HTTP so MCP-compatible clients
(Inspector, LLM hosts, etc.) can connect.

Environment variables — pick a mode
-----------------------------------

**Direct mode** (zero infrastructure):
    METABASE_URL           base URL of the Metabase instance
    METABASE_API_KEY       Metabase API key (``x-api-key`` header)

**Synthetica / Proxy mode** (Powered by Synthetica):
    BACKEND_API_URL        base URL of the Synthetica-compatible gateway
    SYNTHETICA_API_KEY     gateway API key (raw Metabase credentials
                           never reach this process)

Common:
    METABASE_MCP_HOST      bind host (default 0.0.0.0)
    METABASE_MCP_PORT      bind port (default 8092)
    LOG_LEVEL              logging level (default INFO)

The selected mode is detected automatically: if ``BACKEND_API_URL`` is
set, Synthetica mode is used; otherwise Direct mode.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from fastmcp import FastMCP

from metabase_mcp.client import ConfigError, build_client
from metabase_mcp.tools import register_all

logger = logging.getLogger("metabase_mcp")


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build() -> tuple[FastMCP, object]:
    """Build a FastMCP server and its backing Metabase client."""
    client = build_client()
    mcp = FastMCP("metabase-mcp")
    register_all(mcp, client)
    logger.info(
        "metabase-mcp ready (mode=%s, target=%s)",
        client.mode, client.display_url,
    )
    return mcp, client


async def _shutdown(client: object) -> None:
    close = getattr(client, "aclose", None)
    if close is not None:
        try:
            await close()
        except Exception as exc:  # pragma: no cover — best-effort
            logger.warning("client aclose failed: %s", exc)


def main() -> int:
    """CLI entrypoint — ``metabase-mcp``."""
    _configure_logging()
    try:
        mcp, client = _build()
    except ConfigError as exc:
        logger.error("configuration error: %s", exc)
        return 2

    host = os.environ.get("METABASE_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("METABASE_MCP_PORT", "8092"))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_sig(_sig: int, _frame: object) -> None:
        logger.info("received shutdown signal")
        loop.create_task(_shutdown(client))

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_sig)
        except (ValueError, OSError):
            # Windows: SIGTERM may not be settable in some contexts.
            pass

    try:
        mcp.run(transport="http", host=host, port=port)
        return 0
    finally:
        loop.run_until_complete(_shutdown(client))
        loop.close()


if __name__ == "__main__":
    sys.exit(main())
