#!/usr/bin/env python3
"""Mock Metabase server — for driving metabase-mcp in Direct mode.

Run with:
    pip install -e .[examples]
    python examples/mock_metabase.py     # listens on http://0.0.0.0:3000

In another terminal:
    METABASE_URL=http://localhost:3000 METABASE_API_KEY=demo metabase-mcp

Then connect the MCP Inspector:
    npx @modelcontextprotocol/inspector --transport http --url http://localhost:8092/mcp

Every tool will work end-to-end against this fake.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Mock Metabase v0.60", version="0.0.1")

DATABASES = [
    {"id": 1, "name": "analytics", "engine": "postgres"},
    {"id": 2, "name": "warehouse", "engine": "snowflake"},
]

DATABASE_METADATA = {
    1: {
        "tables": [
            {
                "id": 100, "name": "orders", "schema": "public",
                "fields": [
                    {"name": "id", "base_type": "type/Integer", "semantic_type": "type/PK"},
                    {"name": "total", "base_type": "type/Float", "semantic_type": None},
                    {"name": "created_at", "base_type": "type/DateTime",
                     "semantic_type": "type/CreationTimestamp"},
                ],
            },
            {
                "id": 101, "name": "customers", "schema": "public",
                "fields": [
                    {"name": "id", "base_type": "type/Integer", "semantic_type": "type/PK"},
                    {"name": "email", "base_type": "type/Text", "semantic_type": "type/Email"},
                ],
            },
        ],
    },
}

CARDS = [
    {"id": 42, "name": "Monthly Revenue", "description": "Top-line revenue by month",
     "display": "bar", "collection_id": None},
    {"id": 43, "name": "Active customers", "description": "",
     "display": "scalar", "collection_id": 7},
]

_card_seq = 999


@app.get("/api/database")
def list_databases() -> list[dict]:
    return DATABASES


@app.get("/api/database/{db_id}/metadata")
def database_metadata(db_id: int) -> dict:
    return DATABASE_METADATA.get(db_id, {"tables": []})


@app.get("/api/card")
def list_cards() -> list[dict]:
    return CARDS


@app.get("/api/card/{card_id}")
def get_card(card_id: int) -> dict:
    for c in CARDS:
        if c["id"] == card_id:
            return c
    return {"id": card_id, "name": f"Card {card_id}", "display": "table"}


@app.post("/api/card/{card_id}/query")
def query_card(card_id: int) -> dict:
    return {
        "data": {
            "cols": [{"name": "month"}, {"name": "revenue"}],
            "rows": [
                ["2026-01", 12400],
                ["2026-02", 14800],
                ["2026-03", 16100],
            ],
        },
    }


@app.post("/api/card")
def create_card(payload: dict) -> dict:
    global _card_seq
    _card_seq += 1
    new = {
        "id": _card_seq,
        "name": payload.get("name", f"Card {_card_seq}"),
        "display": payload.get("display", "table"),
        "collection_id": payload.get("collection_id"),
    }
    CARDS.append(new)
    return new


@app.put("/api/card/{card_id}")
def update_card(card_id: int, payload: dict) -> dict:
    for c in CARDS:
        if c["id"] == card_id:
            c.update({k: v for k, v in payload.items() if k in {"name", "display", "collection_id"}})
            return c
    return {"id": card_id, **payload}


@app.post("/api/dashboard")
def create_dashboard(payload: dict) -> dict:
    return {"id": 555, "name": payload.get("name", "Dashboard")}


@app.post("/api/dashboard/{dash_id}/cards")
def attach_card(dash_id: int, payload: dict) -> dict:
    return {"ok": True, "dashboard_id": dash_id, "card_id": payload.get("cardId")}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=3000)
