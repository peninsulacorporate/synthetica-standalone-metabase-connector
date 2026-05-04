"""Unit tests for :mod:`metabase_mcp.server`.

Covers the CLI entrypoint and internal helpers without launching a real HTTP
server or hitting Metabase.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from metabase_mcp import client as client_mod
from metabase_mcp import server as server_mod


# ---------------------------------------------------------------------------
# main() — ConfigError path
# ---------------------------------------------------------------------------


class TestMainConfigError:
    def test_returns_2_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("METABASE_URL", raising=False)
        monkeypatch.delenv("METABASE_API_KEY", raising=False)
        exit_code = server_mod.main()
        assert exit_code == 2

    def test_returns_2_when_api_key_missing(self, monkeypatch):
        monkeypatch.setenv("METABASE_URL", "https://mb.test")
        monkeypatch.delenv("METABASE_API_KEY", raising=False)
        exit_code = server_mod.main()
        assert exit_code == 2

    def test_returns_2_when_url_missing(self, monkeypatch):
        monkeypatch.delenv("METABASE_URL", raising=False)
        monkeypatch.setenv("METABASE_API_KEY", "key")
        exit_code = server_mod.main()
        assert exit_code == 2

    def test_logs_error_on_config_error(self, monkeypatch, caplog):
        monkeypatch.delenv("METABASE_URL", raising=False)
        monkeypatch.delenv("METABASE_API_KEY", raising=False)
        import logging
        with caplog.at_level(logging.ERROR, logger="metabase_mcp"):
            server_mod.main()
        assert any("configuration error" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# _build()
# ---------------------------------------------------------------------------


class TestBuild:
    def test_returns_fastmcp_instance(self, monkeypatch):
        from fastmcp import FastMCP

        monkeypatch.delenv("BACKEND_API_URL", raising=False)
        monkeypatch.setenv("METABASE_URL", "https://mb.test")
        monkeypatch.setenv("METABASE_API_KEY", "mb_key")
        mcp, client = server_mod._build()
        assert isinstance(mcp, FastMCP)

    def test_returns_metabase_client(self, monkeypatch):
        monkeypatch.delenv("BACKEND_API_URL", raising=False)
        monkeypatch.setenv("METABASE_URL", "https://mb.test")
        monkeypatch.setenv("METABASE_API_KEY", "mb_key")
        mcp, client = server_mod._build()
        assert isinstance(client, client_mod.MetabaseClient)
        assert client.mode == "direct"

    def test_registers_seven_tools(self, monkeypatch):
        import asyncio
        monkeypatch.setenv("METABASE_URL", "https://mb.test")
        monkeypatch.setenv("METABASE_API_KEY", "mb_key")
        monkeypatch.delenv("BACKEND_API_URL", raising=False)
        mcp, _client = server_mod._build()
        tools = asyncio.run(mcp.list_tools())
        assert len(tools) == 7

    def test_registered_tool_names(self, monkeypatch):
        import asyncio
        monkeypatch.setenv("METABASE_URL", "https://mb.test")
        monkeypatch.setenv("METABASE_API_KEY", "mb_key")
        monkeypatch.delenv("BACKEND_API_URL", raising=False)
        mcp, _client = server_mod._build()
        names = {t.name for t in asyncio.run(mcp.list_tools())}
        assert names == {
            "list_cards",
            "query_card",
            "list_databases",
            "list_database_tables",
            "create_dashboard",
            "create_card_from_sql",
            "request_synthetic_data_generation",
        }

    def test_raises_config_error_without_env(self, monkeypatch):
        monkeypatch.delenv("METABASE_URL", raising=False)
        monkeypatch.delenv("METABASE_API_KEY", raising=False)
        monkeypatch.delenv("BACKEND_API_URL", raising=False)
        monkeypatch.delenv("SYNTHETICA_API_KEY", raising=False)
        with pytest.raises(client_mod.ConfigError):
            server_mod._build()

    def test_synthetica_mode_when_backend_api_url_set(self, monkeypatch):
        """If BACKEND_API_URL is set, _build() must pick Synthetica mode."""
        monkeypatch.delenv("METABASE_URL", raising=False)
        monkeypatch.delenv("METABASE_API_KEY", raising=False)
        monkeypatch.setenv("BACKEND_API_URL", "http://backend:8000")
        monkeypatch.setenv("SYNTHETICA_API_KEY", "sk_test")
        _mcp, client = server_mod._build()
        assert client.mode == "synthetica"
        assert "(Synthetica gateway)" in client.display_url

    def test_synthetica_mode_missing_api_key_raises(self, monkeypatch):
        monkeypatch.setenv("BACKEND_API_URL", "http://backend:8000")
        monkeypatch.delenv("SYNTHETICA_API_KEY", raising=False)
        with pytest.raises(client_mod.ConfigError):
            server_mod._build()


# ---------------------------------------------------------------------------
# _shutdown()
# ---------------------------------------------------------------------------


class TestShutdown:
    @pytest.mark.asyncio
    async def test_calls_aclose_when_present(self):
        client = MagicMock()
        client.aclose = AsyncMock()
        await server_mod._shutdown(client)
        client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_error_when_aclose_missing(self):
        client = object()  # no aclose attribute
        await server_mod._shutdown(client)  # must not raise

    @pytest.mark.asyncio
    async def test_tolerates_aclose_exception(self):
        client = MagicMock()
        client.aclose = AsyncMock(side_effect=RuntimeError("closed"))
        # _shutdown is best-effort — should not propagate
        await server_mod._shutdown(client)
