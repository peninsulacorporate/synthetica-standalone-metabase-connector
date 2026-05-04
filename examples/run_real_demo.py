#!/usr/bin/env python3
"""Drive the six direct-mode tools against a real Metabase instance.

Prerequisites:

    docker compose up -d         # in this directory
    python setup_metabase.py     # writes .env.local with METABASE_URL + METABASE_API_KEY

Then:

    python run_real_demo.py

This script imports :class:`MetabaseClient` from the standalone package
and calls every direct-mode tool against the Metabase started by
``docker-compose.yml``. The Postgres seed (``seed.sql``) gives the LLM a
small sales schema (``customers`` + ``orders``) to play with.

The Synthetica-mode SDV tool is *not* exercised here — it depends on the
gateway, which lives in the Synthetica monorepo. See
``examples/quickstart.py`` for the in-memory Synthetica-mode demo.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import yaml

from metabase_mcp.client import MetabaseClient, Settings


def _load_env_local() -> None:
    env_file = Path(__file__).parent / ".env.local"
    if not env_file.exists():
        sys.exit(
            "examples/.env.local missing. Run `python setup_metabase.py` first.",
        )
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


def _print(label: str, result: object) -> None:
    print(f"\n  > {label}")
    rendered = yaml.safe_dump(
        json.loads(json.dumps(result, default=str)),
        sort_keys=False, allow_unicode=False,
    ).rstrip()
    for line in rendered.splitlines():
        print(f"      {line}")


async def main() -> int:
    _load_env_local()

    url = os.environ["METABASE_URL"]
    key = os.environ["METABASE_API_KEY"]
    db_id = int(os.environ.get("DEMO_DATABASE_ID", "0") or 0)

    print(f"Driving metabase-mcp against {url}\n")

    client = MetabaseClient(Settings(metabase_url=url, metabase_api_key=key))
    try:
        databases = await client.list_databases()
        _print("list_databases()", databases)

        if not db_id:
            demo_db = next(
                (d for d in databases if d.get("name") == "demo_postgres"), None,
            )
            if demo_db is None:
                sys.exit("'demo_postgres' database missing — re-run setup_metabase.py.")
            db_id = demo_db["id"]

        _print(f"list_database_tables({db_id})", await client.list_database_tables(db_id))
        _print("list_cards(limit=10)", await client.list_cards(limit=10))

        # Create (or update if it already exists) a card from native SQL.
        sql = (
            "SELECT date_trunc('month', created_at) AS month, "
            "SUM(total) AS revenue "
            "FROM orders "
            "WHERE status = 'paid' "
            "GROUP BY 1 "
            "ORDER BY 1"
        )
        card_result = await client.create_card_from_sql(
            name="Monthly paid revenue",
            database_id=db_id,
            sql=sql,
            display="line",
            description="Sum of paid orders per month — created by run_real_demo.py",
        )
        _print('create_card_from_sql("Monthly paid revenue", display="line")', card_result)

        if card_result.get("status") in {"created", "updated"} and card_result.get("id"):
            _print(f"query_card({card_result['id']})", await client.query_card(card_result["id"]))

            dash = await client.create_dashboard(
                "metabase-mcp demo dashboard",
                description="Built by run_real_demo.py",
                card_ids=[card_result["id"]],
            )
            _print(
                'create_dashboard("metabase-mcp demo dashboard", card_ids=[…])',
                dash,
            )
        else:
            print("\n  ! create_card_from_sql failed; skipping query_card + create_dashboard.")

        print("\n[OK] Real-Metabase demo complete.")
        print(f"     Visit {url} (login {os.environ.get('DEMO_ADMIN_EMAIL', 'demo@example.com')}) to see the card + dashboard.\n")
    finally:
        await client.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
