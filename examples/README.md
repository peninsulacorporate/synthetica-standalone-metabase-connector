# Examples

Three ways to verify the integration end-to-end, from fastest to most realistic.

| Path | Runtime | Real Metabase? | Use when |
|---|---|---|---|
| **1. Quickstart (mocks)** | ~5 s | no | first impression, CI check |
| **2. Real Metabase (docker)** | ~2 min | **yes** | proving the standalone actually integrates |
| **3. With MCP Inspector** | ~1 min | optional | manual exploration, demos, screencasts |

---

## 1. Quickstart — `python examples/quickstart.py`

A self-contained Python demo that uses ``httpx.MockTransport`` to fake
every backend call. Calls the seven tools in **both** modes (Direct and
Synthetica), prints each response, and shows the **YAML wire body** that
``create_card_from_sql`` posts to the gateway.

```bash
cd packages/metabase-mcp
pip install -e .
python examples/quickstart.py
```

Expected output (abridged):

```
metabase-mcp -- quickstart against in-memory mocks

================================================
  Direct mode -- talking straight to Metabase
================================================
  > list_databases()
      - id: 1, name: analytics, engine: postgres
      ...
  > query_card(42)
      chart_uri: metabase://card/42
  > request_synthetic_data_generation(...) -- expected RuntimeError

==================================================================
  Synthetica mode -- talking through the gateway (YAML wire format)
==================================================================
  > create_card_from_sql(...)
      status: created, id: 9000, chart_uri: metabase://card/9000
  > request_synthetic_data_generation(...)
      status: accepted, job_id: 11111111-...
      reserved_tokens: '0.05'

  [OK] Wire format check (Metabase v0.60 Representations)
      Content-Type: application/x-yaml
      Body (YAML):
        version: '0.60'
        cards:
        - name: Demo card
          ...

[OK] All 7 tools exercised in both modes.
```

---

## 2. Real Metabase — `docker compose up && python setup_metabase.py && python run_real_demo.py`

This is what the standalone is for: a real Metabase v0.60+ instance,
created from scratch, with a seeded Postgres the LLM can actually query.
Three commands:

```bash
cd packages/metabase-mcp/examples

# 1) Bring up Metabase (port 3000) + Postgres seeded with customers/orders (port 55432)
docker compose up -d

# 2) Wait for Metabase to boot, then auto-create the admin user, register the
#    Postgres database, generate an API key, and write examples/.env.local.
python setup_metabase.py

# 3) Drive every direct-mode tool against the real Metabase using the API key.
python run_real_demo.py
```

What `run_real_demo.py` does, step by step:

1. `list_databases()` — confirms the seeded Postgres is registered.
2. `list_database_tables(db_id)` — walks ``customers`` + ``orders`` schema.
3. `list_cards(limit=10)` — should be empty on first run.
4. `create_card_from_sql(...)` — creates a *Monthly paid revenue* line chart
   from a real SQL query against ``orders``. Idempotent: re-running updates
   the same card instead of duplicating.
5. `query_card(id)` — pulls the rows back through the Metabase API.
6. `create_dashboard("metabase-mcp demo dashboard", card_ids=[id])` —
   bundles the new card into a dashboard you can open in the UI.

After it finishes, log in at <http://localhost:3000> with
`demo@example.com` / `Demo12345!` and you'll see the dashboard + card the
LLM-equivalent code just produced.

### Cleaning up

```bash
docker compose down -v        # also wipes the H2 + Postgres volumes
rm examples/.env.local
```

### Customizing

`setup_metabase.py` honours these env vars (defaults in parens):

- `METABASE_URL` (`http://localhost:3000`)
- `DEMO_ADMIN_EMAIL` (`demo@example.com`) / `DEMO_ADMIN_PASSWORD` (`Demo12345!`)
- `DEMO_DB_NAME` (`demo_postgres`) / `DEMO_DB_HOST` (`host.docker.internal`)
- `DEMO_DB_PORT` (`55432`) / `DEMO_DB_USER` / `DEMO_DB_PASSWORD` / `DEMO_DB_DBNAME`

### Troubleshooting

- **API key creation fails with 404** — the bundled `metabase/metabase:latest`
  image must be v0.50 or newer (API keys were OSS-gated in 0.50). Pull a
  fresh image: `docker compose pull && docker compose up -d`.
- **Login fails after re-running setup** — Metabase persists state in the
  `metabase` container's H2 file. Either edit the `DEMO_ADMIN_*` env vars
  to match the real admin or run `docker compose down -v` to wipe state.
- **`run_real_demo.py` cannot find `.env.local`** — `setup_metabase.py`
  must complete successfully. Check its output for errors.

---

## 3. With MCP Inspector — drive the tools manually

For demos, screencasts, or debugging. Run the same Metabase from path 2,
point the MCP server at it, then connect with the official Inspector.

### Direct mode against the real Metabase

```bash
# Terminal 1 — Metabase already running from path 2
docker compose up -d
python setup_metabase.py
source examples/.env.local      # exports METABASE_URL + METABASE_API_KEY

# Terminal 2 — the standalone
metabase-mcp
# → metabase-mcp ready (mode=direct, target=http://localhost:3000)

# Terminal 3 — Inspector
npx @modelcontextprotocol/inspector --transport http --url http://localhost:8092/mcp
```

### Direct mode against a FastAPI mock (no Docker)

If you don't have Docker available, swap step 1 for the FastAPI mock:

```bash
pip install -e ".[examples]"     # adds fastapi + uvicorn
python examples/mock_metabase.py
# → Uvicorn running on http://0.0.0.0:3000

METABASE_URL=http://localhost:3000 METABASE_API_KEY=demo metabase-mcp
```

### Synthetica mode against a FastAPI mock

The Synthetica gateway lives in the Synthetica monorepo, but a mock is
included so the proxy mode can be exercised standalone:

```bash
python examples/mock_gateway.py
# → Uvicorn running on http://0.0.0.0:8000

BACKEND_API_URL=http://localhost:8000 SYNTHETICA_API_KEY=demo metabase-mcp
```

The mock gateway also exercises the 402 path of the SDV trigger — call
`request_synthetic_data_generation` with `num_rows=0` to see the
`payment_required` response.

---

## Files

| Path | What it does |
|---|---|
| `quickstart.py` | Path 1 — single-process demo, no servers needed. Uses `httpx.MockTransport`. |
| `docker-compose.yml` | Path 2 — Metabase v0.60+ on `:3000`, Postgres seeded on `:55432`. |
| `seed.sql` | Path 2 — `customers` + `orders` sample data loaded into Postgres on first boot. |
| `setup_metabase.py` | Path 2 — auto-creates admin, registers Postgres, generates an API key, writes `.env.local`. |
| `run_real_demo.py` | Path 2 — drives every direct-mode tool against the real Metabase. |
| `mock_metabase.py` | Path 3 — FastAPI mock of Metabase v0.60 on `:3000`. |
| `mock_gateway.py` | Path 3 — FastAPI mock of the Synthetica gateway on `:8000`. |
