# metabase-mcp-server

> ⚡ **Powered by Synthetica** — built and maintained by the
> [Synthetica](https://synthetica.peninsula.co/) team. Use it standalone,
> or pair it with Synthetica's gateway to keep your Metabase API keys
> out of the LLM.

An MCP (Model Context Protocol) server that connects any MCP-compatible LLM
client to a Metabase instance.

The LLM can explore your databases, read existing charts, write SQL questions,
and build dashboards through natural language. Two operational modes ship out
of the box:

```
                          ┌─ Direct mode ──────────────────────┐
                          │                                    │
LLM client  ──MCP──►  metabase-mcp  ──REST──►  Metabase
                          │                                    │
                          └─ Synthetica mode (Proxy Security) ─┘
                                          │
                                          ▼
                              Synthetica gateway  ──REST──►  Metabase
                                  (holds the encrypted API key)
```

Works with **Metabase v0.60 and newer**. Card creation in Synthetica mode uses
v0.60's declarative *Representations* format.

---

## ✨ Why Synthetica mode? The Proxy Security Pattern

Most MCP servers either ship raw credentials inside their config or hand them
to the LLM context. That works for solo developers — it does not scale to a
team, and it does not pass a security review.

**The Proxy Security Pattern**, baked in by Synthetica, separates the LLM from
the credentials it consumes:

1. **Credentials live encrypted in the gateway** — your Metabase API key is
   stored once, encrypted at rest, in the Synthetica backend. The MCP server
   process never sees it.
2. **The LLM authenticates to the gateway, not to Metabase** — the MCP
   server uses a per-tenant `SYNTHETICA_API_KEY`. If it leaks, you rotate
   the key without touching Metabase.
3. **Every request is audited and metered** — the gateway records who asked
   for what, gates expensive jobs (e.g. synthetic data generation) on token
   balance, and emits structured audit events.
4. **One key, many users** — issue a `SYNTHETICA_API_KEY` per workspace; the
   gateway maps it to the right organization, allowlists, and quotas.

| | Direct mode | Synthetica mode |
|---|---|---|
| Setup | env vars + Metabase | env vars + Synthetica gateway |
| Credentials seen by MCP server | `METABASE_API_KEY` | `SYNTHETICA_API_KEY` only |
| Credentials seen by the LLM | none (they stay in the MCP server) | none (they stay in the gateway) |
| Card creation API | `POST /api/card` | `POST /metabase/representations/apply` (v0.60 YAML) |
| Audit trail | Metabase activity log only | Centralized through Synthetica |
| `request_synthetic_data_generation` tool | not available (no backend) | available |
| Designed for | solo developers, prototypes | teams, production |

Use direct mode to evaluate quickly. Move to Synthetica mode when you need
multi-tenant isolation, credential rotation, or central auditing.

---

## Install

```bash
pip install metabase-mcp-server
```

Or from source:

```bash
git clone <repository-url>
cd metabase-mcp-server
pip install -e .
```

---

## Try it

Three paths, fastest to most realistic:

```bash
# 1) In-memory mocks — ~5 seconds, no setup
pip install -e .
python examples/quickstart.py

# 2) Real Metabase via Docker — ~2 minutes, proves the standalone actually integrates
cd examples
docker compose up -d                     # Metabase v0.60+ + seeded Postgres
python ../setup_metabase.py              # auto-creates admin, API key, DB connection
python ../run_real_demo.py               # drives every tool against the real Metabase

# 3) Manual exploration with the official MCP Inspector
npx @modelcontextprotocol/inspector --transport http --url http://localhost:8092/mcp
```

Path 2 is the canonical test for the standalone: real Metabase, real
Postgres with sample `customers` + `orders` data, real card created via
SQL, real dashboard. Full walkthrough and troubleshooting in
[examples/README.md](examples/).

---

## Quick start

### Direct mode (zero infrastructure)

```bash
export METABASE_URL=https://metabase.yourcompany.com
export METABASE_API_KEY=mb_xxxxxxxxxxxx

metabase-mcp
# metabase-mcp ready (mode=direct, target=https://metabase.yourcompany.com)
# serving at http://0.0.0.0:8092/mcp
```

### Synthetica mode (Proxy Security)

```bash
export BACKEND_API_URL=https://gateway.yourcompany.com
export SYNTHETICA_API_KEY=sk_xxxxxxxxxxxx

metabase-mcp
# metabase-mcp ready (mode=synthetica, target=https://gateway.yourcompany.com (Synthetica gateway))
```

**Mode is auto-detected**: setting `BACKEND_API_URL` switches into Synthetica
mode automatically. No flag, no config file.

Point your MCP client at `http://localhost:8092/mcp`. Inspect the tools:

```bash
npx @modelcontextprotocol/inspector --transport http --url http://localhost:8092/mcp
```

---

## Docker

Direct mode:

```bash
docker run --rm \
  -e METABASE_URL=https://metabase.yourcompany.com \
  -e METABASE_API_KEY=mb_xxxxxxxxxxxx \
  -p 8092:8092 \
  peninsula/metabase-mcp-server
```

Synthetica mode:

```bash
docker run --rm \
  -e BACKEND_API_URL=https://gateway.yourcompany.com \
  -e SYNTHETICA_API_KEY=sk_xxxxxxxxxxxx \
  -p 8092:8092 \
  peninsula/metabase-mcp-server
```

---

## Environment variables

The server picks the mode based on which variables are set.

### Direct mode

| Variable | Required | Default | Description |
|---|---|---|---|
| `METABASE_URL` | ✅ | — | Base URL of your Metabase instance |
| `METABASE_API_KEY` | ✅ | — | API key sent as `x-api-key` to Metabase |

### Synthetica mode

| Variable | Required | Default | Description |
|---|---|---|---|
| `BACKEND_API_URL` | ✅ | — | Base URL of the Synthetica gateway (e.g. `https://api.synthetica.example`) |
| `SYNTHETICA_API_KEY` | ✅ | — | Gateway API key (per-tenant) sent as `x-api-key` |

### Common (both modes)

| Variable | Default | Description |
|---|---|---|
| `METABASE_MCP_HOST` | `0.0.0.0` | Bind host |
| `METABASE_MCP_PORT` | `8092` | Bind port |
| `LOG_LEVEL` | `INFO` | Python logging level |

A `.env.example` is included. If the required variables for the chosen mode
are missing the server exits immediately with code `2` and a clear error
message — it never starts silently with a broken configuration.

---

## Tools

The server exposes **7 tools**. Their schemas are visible to the LLM through
the MCP protocol — descriptions and arguments are read automatically.

### `list_databases`

Lists every database connection Metabase knows about.

```
list_databases()
→ [{id, name, engine}, …]
```

Use this first to find the `id` of the database you want to query.

---

### `list_database_tables(database_id)`

Lists all tables in a database, including field names and types.
Hidden tables are excluded automatically.

```
list_database_tables(database_id=2)
→ [{
     id, name, schema, fields_count,
     fields: [{name, base_type, semantic_type}, …]
   }, …]
```

This gives the LLM everything it needs to write correct SQL — column names,
types, and semantic annotations — without guessing.

---

### `list_cards(limit=30)`

Lists existing Metabase questions (cards).

```
list_cards(limit=50)
→ [{id, name, description, display, collection_id}, …]
```

Useful to check what already exists before creating duplicates, or to find
the `id` to pass to `query_card`.

---

### `query_card(card_id)`

Executes a Metabase card and returns the full result as structured data.

```
query_card(card_id=42)
→ {
    card_id: 42,
    name: "Monthly Revenue",
    display: "bar",
    cols: ["month", "revenue"],
    rows: [{"month": "2026-01", "revenue": 12400}, …],
    chart_uri: "metabase://card/42"
  }
```

Rows are returned as named dictionaries so the LLM can read and reason about
the data by column name. `chart_uri` is a `metabase://card/{id}` URI any
frontend understanding this scheme can use to render the chart natively.

---

### `create_card_from_sql(name, database_id, sql, display, description, collection_id)`

Creates a native SQL question in Metabase. If a card with the same `name`
already exists in the same collection, it **updates** it instead of creating
a duplicate — safe to call repeatedly.

In **Synthetica mode** the SQL is wrapped in a Metabase v0.60
*Representation* document and POSTed to `/metabase/representations/apply` on
the gateway, which executes it via Metabase's API on behalf of the LLM. In
**direct mode** the SQL is POSTed straight to `/api/card`.

```
create_card_from_sql(
  name="Orders by month",
  database_id=2,
  sql="SELECT date_trunc('month', created_at) m, SUM(total) t FROM orders GROUP BY 1",
  display="bar"
)
→ {status: "created", id: 101, name: "Orders by month", chart_uri: "metabase://card/101"}
```

On a second call with the same name:

```
→ {status: "updated", id: 101, name: "Orders by month", chart_uri: "metabase://card/101"}
```

If Metabase rejects the SQL (syntax error, unknown column, etc.) the tool
returns a structured error instead of raising — the LLM can read it and retry:

```
→ {status: "failed", name: "Orders by month", error: "Metabase 400: Unknown column 'xyz'"}
```

The `display` argument controls the chart type. Common values: `table`,
`bar`, `line`, `pie`, `area`, `row`, `scalar`.

---

### `create_dashboard(name, description, collection_id, card_ids)`

Creates a Metabase dashboard.

```
create_dashboard(
  name="Sales Overview",
  card_ids=[101, 102, 103]
)
→ {id: 55, name: "Sales Overview", card_count: 3}
```

In direct mode, cards are arranged in a simple vertical grid (each takes the
full width and is stacked one below the other; rearrange in the Metabase UI
if needed). In Synthetica mode, the dashboard is scaffolded empty — to
attach existing cards by id, post a full `RepresentationDoc` directly to the
gateway's `/metabase/representations/apply` endpoint.

---

### `request_synthetic_data_generation(source_type, source_params, num_rows, model, use_case)` *(Synthetica mode only)*

The "Buy" button of the Synthetica ecosystem.

This tool **does not generate data itself**. It triggers the gateway's
inbound webhook (`POST /api/v1/webhooks/sdv/trigger`); the gateway:

1. validates the caller's API token balance,
2. queues the heavy SDV pipeline as an asynchronous background task,
3. returns immediately with `{status: "accepted", job_id, …}`,
4. notifies the user via the existing webhook delivery system when the
   job settles.

```
request_synthetic_data_generation(
  source_type="csv",
  source_params={"csv_url": "https://example.com/orders.csv"},
  num_rows=10000,
  model="GaussianCopula",
)
→ {status: "accepted", job_id: "uuid…", estimated_cost_tokens: "5.0",
   reserved_tokens: "5.0", bypassed: false}
```

If the caller is below their token threshold and not exempt, the gateway
responds with `402 Payment Required` and the tool returns:

```
→ {status: "payment_required", error: "insufficient_balance", detail: {…}}
```

In direct mode the tool **raises** `RuntimeError` — there is no backend to
gate the job on. Set `BACKEND_API_URL` + `SYNTHETICA_API_KEY` to enable.

---

## Example: from zero to a dashboard in one conversation

```
User: "Build me a sales dashboard for the analytics database"

LLM:
  1. list_databases()
     → finds database id=2 "analytics"

  2. list_database_tables(2)
     → finds "orders" table with columns: id, customer_id, total, created_at, status

  3. create_card_from_sql(
       name="Revenue by month", database_id=2,
       sql="SELECT date_trunc('month', created_at) m, SUM(total) t FROM orders GROUP BY 1 ORDER BY 1",
       display="line"
     )
     → {status: "created", id: 101, chart_uri: "metabase://card/101"}

  4. create_card_from_sql(
       name="Orders by status", database_id=2,
       sql="SELECT status, COUNT(*) n FROM orders GROUP BY 1 ORDER BY 2 DESC",
       display="pie"
     )
     → {status: "created", id: 102, chart_uri: "metabase://card/102"}

  5. create_dashboard(name="Sales Overview", card_ids=[101, 102])
     → {id: 55, name: "Sales Overview", card_count: 2}

LLM response to user:
  "Done. I created two charts and grouped them in a new dashboard:
   - metabase://card/101 (Revenue by month — line chart)
   - metabase://card/102 (Orders by status — pie chart)
   Dashboard: https://metabase.yourcompany.com/dashboard/55"
```

---

## How it works

### Configuration and startup

At startup, `_detect_settings()` reads the environment. If `BACKEND_API_URL`
is set, `SyntheticaSettings.from_env()` runs and the server binds to
Synthetica mode. Otherwise `Settings.from_env()` runs (direct mode). If
neither mode's required variables are complete, `ConfigError` is raised and
the process exits with code `2` before any network connection is attempted —
the error message tells you exactly what is missing.

### The HTTP client

`MetabaseClient` wraps an `httpx.AsyncClient` configured with the right
`base_url` and `x-api-key` header for the active mode. Every tool method is
a thin async function that dispatches on `self.mode`:

- **direct** → talks to Metabase's REST API (`/api/database`, `/api/card`, …)
- **synthetica** → talks to the gateway (`/api/v1/metabase/*` and
  `/api/v1/webhooks/sdv/trigger`)

The public surface (method names and return shapes) is identical, so tools
do not branch on mode.

### Tool registration

Each tool lives in its own file under `tools/`. Every file exposes a
`register(mcp, client)` function that uses the `@mcp.tool()` decorator to
wire the tool against the shared FastMCP instance. The `client` is captured
in a closure — all calls share the same HTTP session.

`register_all(mcp, client)` calls all seven in order. This is the only thing
`server.py` needs to know about the tools layer.

The `request_synthetic_data_generation` tool is registered in **both** modes;
in direct mode it raises `RuntimeError` at call time with a clear, actionable
message rather than disappearing from the catalog.

### Server lifecycle

```
main()
 ├─ _configure_logging()
 ├─ _build()             reads env, detects mode, builds client, registers 7 tools
 └─ mcp.run(transport="http", host, port)
      └─ serves at http://<host>:<port>/mcp

SIGINT / SIGTERM → _shutdown(client) → httpx.AsyncClient.aclose()
```

`_shutdown` is best-effort: if the client is already closed, the exception
is swallowed and the process exits cleanly.

---

## Development

```bash
# Install with dev extras
pip install -e ".[dev]"

# Lint
ruff check src tests

# Test
pytest -q
# 66 passed in ~6s  (fully offline — no Metabase, no gateway needed)

# Build wheel + sdist
python -m build
```

### Running the tests

Tests use `httpx.MockTransport` to intercept every HTTP call — no Metabase
instance, no gateway, no network, no Docker required. Coverage:

- `Settings` / `SyntheticaSettings` — missing vars, trailing slashes, `ConfigError` is `RuntimeError`
- Mode detection — `BACKEND_API_URL` switches to Synthetica; absence falls back to direct
- `MetabaseClient` (direct mode) — all 7 methods, both Metabase response shapes, `null` fields normalized, HTTP errors propagated
- `MetabaseClient` (Synthetica mode) — `query_card`, `create_card_from_sql` posting v0.60 RepresentationDocs, `request_synthetic_data_generation` happy path + 402 payment required, direct mode raises `RuntimeError` on SDV
- Tools — exactly 7 registered, correct names, each delegates to the right client method
- Server — exit code `2` on missing config, both modes built correctly, graceful shutdown

---

## Project layout

```
src/metabase_mcp/
├── __init__.py              __version__ = "0.1.0"
├── client.py                MetabaseClient, Settings, SyntheticaSettings, ConfigError
├── server.py                CLI entrypoint, _build(), _shutdown()
└── tools/
    ├── __init__.py          register_all(mcp, client) — 7 tools
    ├── list_databases.py
    ├── list_database_tables.py
    ├── list_cards.py
    ├── query_card.py
    ├── create_card_from_sql.py
    ├── create_dashboard.py
    └── request_synthetic_data_generation.py    (Synthetica mode only)

tests/
├── test_client.py
├── test_client_extended.py
├── test_tools.py
└── test_server.py
```

---

## License

MIT — see [LICENSE](LICENSE).

---

<sub>Powered by [Synthetica](https://synthetica.peninsula.co/). Synthetica is a
data platform for AI-driven analytics on top of Metabase, with built-in
credential isolation, audit trails, and a synthetic data engine.</sub>
