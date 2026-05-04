#!/usr/bin/env python3
"""Quickstart — run every tool in both modes against in-memory mocks.

Usage:
    pip install -e .         # from packages/metabase-mcp/
    python examples/quickstart.py

The script uses ``httpx.MockTransport`` to fake a Metabase server (Direct
mode) and a Synthetica gateway (Synthetica mode), then drives every tool
through :class:`MetabaseClient` and pretty-prints the response. No
network, no Docker, no real credentials.

The Synthetica section also intercepts the wire body to confirm that
``create_card_from_sql`` posts a YAML ``RepresentationDoc`` exactly as
specified by Metabase v0.60.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import yaml

from metabase_mcp import client as cm

# ---------------------------------------------------------------------------
# Mock data — same set used in both modes so output is comparable
# ---------------------------------------------------------------------------

DATABASES = [
    {"id": 1, "name": "analytics", "engine": "postgres"},
    {"id": 2, "name": "warehouse", "engine": "snowflake"},
]

TABLES_DB1 = [
    {
        "id": 100,
        "name": "orders",
        "schema": "public",
        "fields": [
            {"name": "id", "base_type": "type/Integer", "semantic_type": "type/PK"},
            {"name": "total", "base_type": "type/Float", "semantic_type": None},
            {"name": "created_at", "base_type": "type/DateTime", "semantic_type": "type/CreationTimestamp"},
        ],
    },
    {
        "id": 101,
        "name": "customers",
        "schema": "public",
        "fields": [
            {"name": "id", "base_type": "type/Integer", "semantic_type": "type/PK"},
            {"name": "email", "base_type": "type/Text", "semantic_type": "type/Email"},
        ],
    },
]

CARDS = [
    {"id": 42, "name": "Monthly Revenue", "description": "Top-line revenue by month",
     "display": "bar", "collection_id": None},
    {"id": 43, "name": "Active customers", "description": "",
     "display": "scalar", "collection_id": 7},
]

CARD_42_QUERY_RESULT = {
    "data": {
        "cols": [{"name": "month"}, {"name": "revenue"}],
        "rows": [
            ["2026-01", 12400],
            ["2026-02", 14800],
            ["2026-03", 16100],
        ],
    },
}


# ---------------------------------------------------------------------------
# Direct-mode mock — simulates a Metabase v0.60 instance
# ---------------------------------------------------------------------------


def _direct_handler(request: httpx.Request) -> httpx.Response:
    p, m = request.url.path, request.method
    if (m, p) == ("GET", "/api/database"):
        return httpx.Response(200, json=DATABASES)
    if (m, p) == ("GET", "/api/database/1/metadata"):
        return httpx.Response(200, json={"tables": TABLES_DB1})
    if (m, p) == ("GET", "/api/card"):
        return httpx.Response(200, json=CARDS)
    if (m, p) == ("GET", "/api/card/42"):
        return httpx.Response(200, json={"name": "Monthly Revenue", "display": "bar"})
    if (m, p) == ("POST", "/api/card/42/query"):
        return httpx.Response(200, json=CARD_42_QUERY_RESULT)
    if (m, p) == ("POST", "/api/card"):
        return httpx.Response(200, json={"id": 999, "name": "Demo card"})
    if (m, p) == ("POST", "/api/dashboard"):
        return httpx.Response(200, json={"id": 555, "name": "Demo dashboard"})
    if m == "POST" and p.startswith("/api/dashboard/") and p.endswith("/cards"):
        return httpx.Response(200, json={"ok": True})
    return httpx.Response(404, json={"error": f"no mock route: {m} {p}"})


# ---------------------------------------------------------------------------
# Synthetica-mode mock — simulates the gateway. Captures the YAML wire body.
# ---------------------------------------------------------------------------


_yaml_capture: dict[str, str] = {}


def _synthetica_handler(request: httpx.Request) -> httpx.Response:
    p, m = request.url.path, request.method
    if (m, p) == ("GET", "/api/v1/metabase/databases"):
        return httpx.Response(200, json=DATABASES)
    if (m, p) == ("GET", "/api/v1/metabase/database/1/tables"):
        return httpx.Response(200, json=TABLES_DB1)
    if (m, p) == ("GET", "/api/v1/metabase/cards"):
        return httpx.Response(200, json=CARDS)
    if (m, p) == ("GET", "/api/v1/metabase/card/42/data"):
        return httpx.Response(200, json={
            "name": "Monthly Revenue",
            "display": "bar",
            "cols": ["month", "revenue"],
            "data": [
                {"month": "2026-01", "revenue": 12400},
                {"month": "2026-02", "revenue": 14800},
                {"month": "2026-03", "revenue": 16100},
            ],
        })
    if (m, p) == ("POST", "/api/v1/metabase/representations/apply"):
        # Capture for the wire-format proof printed below.
        _yaml_capture["content_type"] = request.headers.get("content-type", "")
        _yaml_capture["body"] = request.content.decode("utf-8")
        doc = yaml.safe_load(_yaml_capture["body"])
        items = []
        for c in doc.get("cards") or []:
            items.append({"kind": "card", "name": c["name"], "status": "created", "id": 9000})
        for d in doc.get("dashboards") or []:
            items.append({"kind": "dashboard", "name": d["name"], "status": "created", "id": 5000})
        return httpx.Response(200, json={
            "version": "0.60",
            "created": len(items),
            "items": items,
        })
    if (m, p) == ("POST", "/api/v1/webhooks/sdv/trigger"):
        return httpx.Response(202, json={
            "job": {"id": "11111111-1111-1111-1111-111111111111", "status": "pending"},
            "estimated_cost_tokens": "0.05",
            "reserved_tokens": "0.05",
            "bypassed": False,
            "bypass_reason": None,
        })
    return httpx.Response(404, json={"error": f"no mock route: {m} {p}"})


# ---------------------------------------------------------------------------
# Pretty printer — keeps the output small and readable for a CTO demo
# ---------------------------------------------------------------------------


def _print_step(label: str, result: object) -> None:
    print(f"\n  > {label}")
    rendered = yaml.safe_dump(
        json.loads(json.dumps(result, default=str)),
        sort_keys=False, allow_unicode=False,
    ).rstrip()
    for line in rendered.splitlines():
        print(f"      {line}")


def _section(title: str) -> None:
    border = "=" * (len(title) + 4)
    print(f"\n{border}\n  {title}\n{border}")


# ---------------------------------------------------------------------------
# Demos
# ---------------------------------------------------------------------------


async def demo_direct() -> None:
    _section("Direct mode — talking straight to Metabase")
    c = cm.MetabaseClient(
        cm.Settings(metabase_url="https://demo.metabase", metabase_api_key="mb_demo"),
    )
    c._client = httpx.AsyncClient(
        base_url="https://demo.metabase",
        headers={"x-api-key": "mb_demo"},
        transport=httpx.MockTransport(_direct_handler),
    )
    try:
        _print_step("list_databases()", await c.list_databases())
        _print_step("list_database_tables(1)", await c.list_database_tables(1))
        _print_step("list_cards(limit=10)", await c.list_cards(limit=10))
        _print_step("query_card(42)", await c.query_card(42))
        _print_step(
            'create_card_from_sql(name="Demo card", database_id=1, sql="SELECT 1", display="bar")',
            await c.create_card_from_sql(
                name="Demo card", database_id=1, sql="SELECT 1", display="bar",
            ),
        )
        _print_step(
            'create_dashboard(name="Demo dash", card_ids=[999])',
            await c.create_dashboard("Demo dash", card_ids=[999]),
        )
        # Direct mode raises for the SDV tool — show the error
        try:
            await c.request_synthetic_data_generation(
                source_type="csv", source_params={"csv_url": "x"}, num_rows=100,
            )
        except RuntimeError as exc:
            _print_step(
                'request_synthetic_data_generation(...)  -- expected RuntimeError',
                {"error": str(exc)},
            )
    finally:
        await c.aclose()


async def demo_synthetica() -> None:
    _section("Synthetica mode — talking through the gateway (YAML wire format)")
    c = cm.MetabaseClient(
        cm.SyntheticaSettings(
            backend_api_url="http://gateway.demo", synthetica_api_key="sk_demo",
        ),
    )
    c._client = httpx.AsyncClient(
        base_url="http://gateway.demo/api/v1",
        headers={"x-api-key": "sk_demo"},
        transport=httpx.MockTransport(_synthetica_handler),
    )
    try:
        _print_step("list_databases()", await c.list_databases())
        _print_step("list_database_tables(1)", await c.list_database_tables(1))
        _print_step("list_cards(limit=10)", await c.list_cards(limit=10))
        _print_step("query_card(42)", await c.query_card(42))
        _print_step(
            'create_card_from_sql(name="Demo card", database_id=1, sql="SELECT 1", display="bar")',
            await c.create_card_from_sql(
                name="Demo card", database_id=1, sql="SELECT 1", display="bar",
            ),
        )
        _print_step(
            'create_dashboard(name="Demo dash")',
            await c.create_dashboard("Demo dash"),
        )
        _print_step(
            "request_synthetic_data_generation(source_type='csv', num_rows=1000)",
            await c.request_synthetic_data_generation(
                source_type="csv",
                source_params={"csv_url": "https://example.com/orders.csv"},
                num_rows=1000,
            ),
        )

        # Wire-format proof — what actually went on the wire for the apply call
        print("\n  [OK] Wire format check (Metabase v0.60 Representations)")
        print(f"      Content-Type: {_yaml_capture.get('content_type')}")
        print("      Body (YAML):")
        for line in _yaml_capture.get("body", "").rstrip().splitlines():
            print(f"        {line}")
    finally:
        await c.aclose()


async def main() -> None:
    print("metabase-mcp -- quickstart against in-memory mocks\n")
    await demo_direct()
    await demo_synthetica()
    print("\n[OK] All 7 tools exercised in both modes.\n")


if __name__ == "__main__":
    asyncio.run(main())
