"""Unit tests for :mod:`metabase_mcp.client`.

We stub httpx with :class:`httpx.MockTransport` so the suite runs fully
offline — no real Metabase required.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from metabase_mcp import client as client_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_transport(
    monkeypatch: pytest.MonkeyPatch,
    client_obj: client_mod.MetabaseClient,
    routes: dict[str, Any],
) -> None:
    """Swap ``client_obj._client`` for one with an httpx ``MockTransport``."""

    async def _handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.path}"
        spec = routes.get(key)
        if spec is None:
            return httpx.Response(404, json={"error": f"no route: {key}"})
        status_code, body = spec
        return httpx.Response(status_code, json=body)

    transport = httpx.MockTransport(_handler)
    original = client_obj._client
    client_obj._client = httpx.AsyncClient(
        base_url=original.base_url,
        headers=original.headers,
        transport=transport,
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_from_env_requires_both_vars(monkeypatch):
    monkeypatch.delenv("METABASE_URL", raising=False)
    monkeypatch.setenv("METABASE_API_KEY", "mb_test")
    with pytest.raises(client_mod.ConfigError):
        client_mod.Settings.from_env()


def test_build_client_constructs_instance(monkeypatch):
    monkeypatch.setenv("METABASE_URL", "https://metabase.test")
    monkeypatch.setenv("METABASE_API_KEY", "mb_test")
    c = client_mod.build_client()
    assert isinstance(c, client_mod.MetabaseClient)
    assert c._settings.metabase_url == "https://metabase.test"


# ---------------------------------------------------------------------------
# list_cards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_cards_normalizes_response(monkeypatch):
    c = client_mod.MetabaseClient(
        client_mod.Settings(
            metabase_url="https://metabase.test", metabase_api_key="mb_test",
        ),
    )
    _patch_transport(monkeypatch, c, {
        "GET /api/card": (200, [
            {"id": 1, "name": "Daily revenue", "display": "line", "collection_id": 3},
            {"id": 2, "name": "Top products", "description": "SKUs"},
        ]),
    })
    try:
        cards = await c.list_cards(limit=10)
    finally:
        await c.aclose()
    assert [card["id"] for card in cards] == [1, 2]
    assert cards[0]["display"] == "line"
    assert cards[1]["description"] == "SKUs"
    assert cards[1]["display"] == "table"  # fallback default


# ---------------------------------------------------------------------------
# query_card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_card_emits_chart_uri(monkeypatch):
    c = client_mod.MetabaseClient(
        client_mod.Settings(
            metabase_url="https://metabase.test", metabase_api_key="mb_test",
        ),
    )
    _patch_transport(monkeypatch, c, {
        "GET /api/card/42": (200, {"name": "Revenue", "display": "bar"}),
        "POST /api/card/42/query": (200, {
            "data": {
                "cols": [{"name": "day"}, {"name": "revenue"}],
                "rows": [["2026-04-01", 100], ["2026-04-02", 120]],
            },
        }),
    })
    try:
        result = await c.query_card(42)
    finally:
        await c.aclose()
    assert result["chart_uri"] == "metabase://card/42"
    assert result["display"] == "bar"
    assert result["rows"] == [
        {"day": "2026-04-01", "revenue": 100},
        {"day": "2026-04-02", "revenue": 120},
    ]


@pytest.mark.asyncio
async def test_query_card_fallback_when_metadata_404(monkeypatch):
    c = client_mod.MetabaseClient(
        client_mod.Settings(
            metabase_url="https://metabase.test", metabase_api_key="mb_test",
        ),
    )
    _patch_transport(monkeypatch, c, {
        "GET /api/card/7": (404, {"message": "gone"}),
        "POST /api/card/7/query": (200, {
            "data": {"cols": [{"name": "x"}], "rows": [[1]]},
        }),
    })
    try:
        result = await c.query_card(7)
    finally:
        await c.aclose()
    assert result["name"] == "Card 7"
    assert result["display"] == "table"
    assert result["chart_uri"] == "metabase://card/7"


# ---------------------------------------------------------------------------
# create_dashboard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_database_tables_trims_metadata(monkeypatch):
    c = client_mod.MetabaseClient(
        client_mod.Settings(
            metabase_url="https://metabase.test", metabase_api_key="mb_test",
        ),
    )
    _patch_transport(monkeypatch, c, {
        "GET /api/database/3/metadata": (200, {
            "tables": [
                {
                    "id": 10, "name": "orders", "schema": "public",
                    "fields": [
                        {"name": "id", "base_type": "type/Integer", "semantic_type": "type/PK"},
                        {"name": "total", "base_type": "type/Float"},
                    ],
                },
                {"id": 11, "name": "hidden_t", "visibility_type": "hidden", "fields": []},
            ],
        }),
    })
    try:
        tables = await c.list_database_tables(3)
    finally:
        await c.aclose()
    # hidden table filtered out
    assert [t["name"] for t in tables] == ["orders"]
    assert tables[0]["fields_count"] == 2
    assert tables[0]["fields"][0]["semantic_type"] == "type/PK"


@pytest.mark.asyncio
async def test_create_card_from_sql_creates_new(monkeypatch):
    c = client_mod.MetabaseClient(
        client_mod.Settings(
            metabase_url="https://metabase.test", metabase_api_key="mb_test",
        ),
    )
    _patch_transport(monkeypatch, c, {
        "GET /api/card": (200, []),  # no existing card
        "POST /api/card": (200, {"id": 123, "name": "Revenue"}),
    })
    try:
        r = await c.create_card_from_sql(
            name="Revenue", database_id=2,
            sql="SELECT count(*) FROM orders", display="scalar",
        )
    finally:
        await c.aclose()
    assert r["status"] == "created"
    assert r["id"] == 123
    assert r["chart_uri"] == "metabase://card/123"


@pytest.mark.asyncio
async def test_create_card_from_sql_updates_existing_match(monkeypatch):
    c = client_mod.MetabaseClient(
        client_mod.Settings(
            metabase_url="https://metabase.test", metabase_api_key="mb_test",
        ),
    )
    _patch_transport(monkeypatch, c, {
        "GET /api/card": (200, [
            {"id": 77, "name": "Revenue", "collection_id": None},
        ]),
        "PUT /api/card/77": (200, {"id": 77, "name": "Revenue"}),
    })
    try:
        r = await c.create_card_from_sql(
            name="Revenue", database_id=2,
            sql="SELECT count(*) FROM orders",
        )
    finally:
        await c.aclose()
    assert r["status"] == "updated"
    assert r["id"] == 77


@pytest.mark.asyncio
async def test_create_card_from_sql_returns_failure_on_400(monkeypatch):
    c = client_mod.MetabaseClient(
        client_mod.Settings(
            metabase_url="https://metabase.test", metabase_api_key="mb_test",
        ),
    )
    _patch_transport(monkeypatch, c, {
        "GET /api/card": (200, []),
        "POST /api/card": (400, {"message": "invalid SQL"}),
    })
    try:
        r = await c.create_card_from_sql(
            name="Bad", database_id=2, sql="INVALID",
        )
    finally:
        await c.aclose()
    assert r["status"] == "failed"
    assert "invalid SQL" in r["error"]


@pytest.mark.asyncio
async def test_create_dashboard_attaches_cards(monkeypatch):
    c = client_mod.MetabaseClient(
        client_mod.Settings(
            metabase_url="https://metabase.test", metabase_api_key="mb_test",
        ),
    )
    _patch_transport(monkeypatch, c, {
        "POST /api/dashboard": (200, {"id": 99, "name": "Test"}),
        "POST /api/dashboard/99/cards": (200, {"ok": True}),
    })
    try:
        result = await c.create_dashboard("Test", card_ids=[1, 2, 3])
    finally:
        await c.aclose()
    assert result == {"id": 99, "name": "Test", "card_count": 3}


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------


def test_direct_mode_default(monkeypatch):
    monkeypatch.delenv("BACKEND_API_URL", raising=False)
    monkeypatch.setenv("METABASE_URL", "https://metabase.test")
    monkeypatch.setenv("METABASE_API_KEY", "mb_test")
    c = client_mod.build_client()
    assert c.mode == "direct"


def test_synthetica_mode_when_backend_url_present(monkeypatch):
    monkeypatch.setenv("BACKEND_API_URL", "http://backend:8000")
    monkeypatch.setenv("SYNTHETICA_API_KEY", "sk_test")
    c = client_mod.build_client()
    assert c.mode == "synthetica"


def test_synthetica_settings_requires_both_vars(monkeypatch):
    monkeypatch.setenv("BACKEND_API_URL", "http://backend:8000")
    monkeypatch.delenv("SYNTHETICA_API_KEY", raising=False)
    with pytest.raises(client_mod.ConfigError):
        client_mod.SyntheticaSettings.from_env()


# ---------------------------------------------------------------------------
# Synthetica-mode behavior — talks to /api/v1/* on the gateway
# ---------------------------------------------------------------------------


def _make_synthetica_client(routes: dict) -> client_mod.MetabaseClient:
    async def _handler(request):
        key = f"{request.method} {request.url.path}"
        spec = routes.get(key)
        if spec is None:
            return httpx.Response(404, json={"error": f"no route: {key}"})
        status_code, body = spec
        return httpx.Response(status_code, json=body)

    c = client_mod.MetabaseClient(
        client_mod.SyntheticaSettings(
            backend_api_url="http://backend:8000",
            synthetica_api_key="sk_test",
        ),
    )
    c._client = httpx.AsyncClient(
        base_url="http://backend:8000/api/v1",
        headers={"x-api-key": "sk_test"},
        transport=httpx.MockTransport(_handler),
    )
    return c


@pytest.mark.asyncio
async def test_synthetica_query_card_hits_backend_route():
    c = _make_synthetica_client({
        "GET /api/v1/metabase/card/7/data": (200, {
            "display": "pie",
            "name": "Categories",
            "cols": ["category", "count"],
            "data": [{"category": "A", "count": 10}],
        }),
    })
    try:
        r = await c.query_card(7)
    finally:
        await c.aclose()
    assert r["chart_uri"] == "metabase://card/7"
    assert r["rows"][0]["category"] == "A"


@pytest.mark.asyncio
async def test_synthetica_create_card_uses_representations_apply():
    """Synthetica mode posts a YAML RepresentationDoc to /metabase/representations/apply."""
    import yaml as _yaml
    captured: dict = {}

    async def _handler(request):
        if request.method == "POST" and request.url.path == "/api/v1/metabase/representations/apply":
            captured["content_type"] = request.headers.get("content-type")
            captured["raw_body"] = request.content.decode("utf-8")
            captured["body"] = _yaml.safe_load(captured["raw_body"])
            return httpx.Response(200, json={
                "version": "0.60",
                "items": [{"kind": "card", "name": "Q", "status": "created", "id": 42}],
            })
        return httpx.Response(404)

    c = client_mod.MetabaseClient(
        client_mod.SyntheticaSettings(
            backend_api_url="http://backend:8000", synthetica_api_key="sk",
        ),
    )
    c._client = httpx.AsyncClient(
        base_url="http://backend:8000/api/v1",
        headers={"x-api-key": "sk"},
        transport=httpx.MockTransport(_handler),
    )
    try:
        r = await c.create_card_from_sql(
            name="Q", database_id=2, sql="SELECT 1", display="bar",
        )
    finally:
        await c.aclose()
    assert r["status"] == "created"
    assert r["id"] == 42
    assert r["chart_uri"] == "metabase://card/42"
    # Wire format: YAML, not JSON
    assert captured["content_type"] == "application/x-yaml"
    assert captured["raw_body"].startswith("version:")  # YAML, not JSON ('{')
    # Body content: a v0.60 RepresentationDoc, not a raw /api/card payload
    assert captured["body"]["version"] == "0.60"
    assert captured["body"]["cards"][0]["sql"] == "SELECT 1"


@pytest.mark.asyncio
async def test_synthetica_request_synthetic_data_generation_accepted():
    c = _make_synthetica_client({
        "POST /api/v1/webhooks/sdv/trigger": (202, {
            "job": {"id": "11111111-1111-1111-1111-111111111111", "status": "pending"},
            "estimated_cost_tokens": "0.05",
            "reserved_tokens": "0.05",
            "bypassed": False,
        }),
    })
    try:
        r = await c.request_synthetic_data_generation(
            source_type="csv",
            source_params={"csv_url": "s3://x"},
            num_rows=100,
        )
    finally:
        await c.aclose()
    assert r["status"] == "accepted"
    assert r["job_id"] == "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_synthetica_request_synthetic_data_generation_402_payment_required():
    c = _make_synthetica_client({
        "POST /api/v1/webhooks/sdv/trigger": (402, {
            "detail": {"reason": "insufficient_balance", "required": "0.05"},
        }),
    })
    try:
        r = await c.request_synthetic_data_generation(
            source_type="csv",
            source_params={"csv_url": "s3://x"},
            num_rows=100,
        )
    finally:
        await c.aclose()
    assert r["status"] == "payment_required"
    assert r["error"] == "insufficient_balance"


@pytest.mark.asyncio
async def test_direct_mode_request_synthetic_data_generation_raises():
    c = client_mod.MetabaseClient(
        client_mod.Settings(
            metabase_url="https://metabase.test", metabase_api_key="mb_test",
        ),
    )
    try:
        with pytest.raises(RuntimeError, match="Synthetica mode"):
            await c.request_synthetic_data_generation(
                source_type="csv",
                source_params={"csv_url": "x"},
                num_rows=100,
            )
    finally:
        await c.aclose()
