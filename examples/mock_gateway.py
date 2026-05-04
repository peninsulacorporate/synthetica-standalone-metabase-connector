#!/usr/bin/env python3
"""Mock Synthetica gateway — for driving metabase-mcp in Synthetica mode.

Run with:
    pip install -e .[examples]
    python examples/mock_gateway.py     # listens on http://0.0.0.0:8000

In another terminal:
    BACKEND_API_URL=http://localhost:8000 SYNTHETICA_API_KEY=demo metabase-mcp

Then connect the MCP Inspector:
    npx @modelcontextprotocol/inspector --transport http --url http://localhost:8092/mcp

Behaviors implemented:

- The four read endpoints return canned JSON.
- ``POST /api/v1/metabase/representations/apply`` accepts both YAML and JSON
  (same shape as the real Synthetica gateway). It echoes the cards and
  dashboards from the document with ``status: created`` and synthetic ids.
- ``POST /api/v1/webhooks/sdv/trigger`` returns ``202 Accepted`` with a
  fake ``job_id``. To exercise the 402 path, send the magic
  ``num_rows=0`` body — it returns Payment Required.
"""

from __future__ import annotations

import json

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock Synthetica Gateway", version="0.0.1")

DATABASES = [
    {"id": 1, "name": "analytics"},
    {"id": 2, "name": "warehouse"},
]

DATABASE_TABLES = {
    1: [
        {
            "id": 100, "name": "orders", "schema": "public",
            "fields_count": 3,
            "fields": [
                {"name": "id", "base_type": "type/Integer"},
                {"name": "total", "base_type": "type/Float"},
                {"name": "created_at", "base_type": "type/DateTime"},
            ],
        },
        {
            "id": 101, "name": "customers", "schema": "public",
            "fields_count": 2,
            "fields": [
                {"name": "id", "base_type": "type/Integer"},
                {"name": "email", "base_type": "type/Text"},
            ],
        },
    ],
}

CARDS = [
    {"id": 42, "name": "Monthly Revenue", "display": "bar",
     "description": "Top-line revenue by month", "collection_id": None,
     "collection": None},
    {"id": 43, "name": "Active customers", "display": "scalar",
     "description": "", "collection_id": 7, "collection": "Ops"},
]


@app.get("/api/v1/metabase/databases")
def databases() -> list[dict]:
    return DATABASES


@app.get("/api/v1/metabase/database/{db_id}/tables")
def database_tables(db_id: int) -> list[dict]:
    return DATABASE_TABLES.get(db_id, [])


@app.get("/api/v1/metabase/cards")
def cards(limit: int = 30) -> list[dict]:
    return CARDS[:limit]


@app.get("/api/v1/metabase/card/{card_id}/data")
def card_data(card_id: int) -> dict:
    return {
        "name": "Monthly Revenue",
        "display": "bar",
        "cols": ["month", "revenue"],
        "data": [
            {"month": "2026-01", "revenue": 12400},
            {"month": "2026-02", "revenue": 14800},
            {"month": "2026-03", "revenue": 16100},
        ],
        "metabase_url": "https://metabase.demo/question/42",
    }


_card_seq = 9000
_dash_seq = 5000


@app.post("/api/v1/metabase/representations/apply")
async def apply_representations(request: Request) -> JSONResponse:
    """Accept JSON or YAML — same as the real Synthetica gateway."""
    global _card_seq, _dash_seq
    raw = await request.body()
    content_type = (request.headers.get("content-type") or "").lower().split(";")[0].strip()
    text = raw.decode("utf-8")
    print("\n=== MOCK GATEWAY received POST /api/v1/metabase/representations/apply ===")
    print(f"Content-Type: {content_type}")
    print("Body:")
    for line in text.rstrip().splitlines():
        print(f"  {line}")
    print("=" * 70)
    try:
        if content_type in {"application/x-yaml", "text/yaml", "application/yaml"}:
            doc = yaml.safe_load(text) or {}
        else:
            doc = json.loads(text) if text else {}
    except Exception as exc:
        return JSONResponse(
            status_code=400,
            content={"error": f"failed to parse body: {exc}"},
        )

    items = []
    for c in (doc.get("cards") or []):
        _card_seq += 1
        items.append({
            "kind": "card", "name": c.get("name", "card"),
            "status": "created", "id": _card_seq,
        })
    for d in (doc.get("dashboards") or []):
        _dash_seq += 1
        items.append({
            "kind": "dashboard", "name": d.get("name", "dash"),
            "status": "created", "id": _dash_seq,
        })

    return JSONResponse(content={
        "version": doc.get("version", "0.60"),
        "created": len(items),
        "updated": 0,
        "failed": 0,
        "skipped": 0,
        "items": items,
    })


@app.post("/api/v1/webhooks/sdv/trigger")
async def sdv_trigger(payload: dict) -> JSONResponse:
    """Headless SDV trigger.

    To exercise the 402 / payment-required path, send ``num_rows: 0``.
    """
    num_rows = (payload.get("generation_params") or {}).get("num_rows", 1000)
    if num_rows == 0:
        return JSONResponse(
            status_code=402,
            content={
                "detail": {
                    "reason": "insufficient_balance",
                    "required": "0.00",
                    "available": "0.00",
                },
            },
        )
    return JSONResponse(
        status_code=202,
        content={
            "job": {"id": "11111111-1111-1111-1111-111111111111", "status": "pending"},
            "estimated_cost_tokens": "0.05",
            "reserved_tokens": "0.05",
            "bypassed": False,
            "bypass_reason": None,
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
