"""Dual-mode async client for the metabase-mcp standalone server.

Two operational modes are supported and selected automatically from the
environment:

- **Direct mode** (default) — talks to a Metabase instance using
  ``METABASE_URL`` + ``METABASE_API_KEY``. Zero infrastructure, the LLM
  reaches Metabase straight through the server.

- **Synthetica / Proxy mode** — when ``BACKEND_API_URL`` is set, the
  server routes every request through a Synthetica-compatible FastAPI
  gateway and authenticates with ``SYNTHETICA_API_KEY``. Raw Metabase
  credentials never reach the LLM (they live encrypted server-side and
  are decrypted only inside the gateway). This mode also unlocks the
  ``request_synthetic_data_generation`` tool, which triggers the
  backend's headless SDV inbound webhook for asynchronous dataset jobs.

The selected mode is exposed via :attr:`MetabaseClient.mode`. The public
tool surface (``list_databases``, ``list_database_tables``, ``list_cards``,
``query_card``, ``create_card_from_sql``, ``create_dashboard``,
``request_synthetic_data_generation``) is identical in both modes — each
method dispatches internally to the right HTTP shape.

Card creation in Synthetica mode uses Metabase v0.60's declarative
"Representations" format: a ``RepresentationDoc`` is POSTed to the
gateway, which applies it idempotently. In direct mode the same operation
falls back to the classic ``POST /api/card`` flow.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import yaml

Mode = Literal["direct", "synthetica"]


class ConfigError(RuntimeError):
    """Raised when neither mode's required env vars are set."""


@dataclass(frozen=True)
class Settings:
    """Direct-mode settings: talk to a Metabase instance directly."""

    metabase_url: str
    metabase_api_key: str

    @classmethod
    def from_env(cls) -> "Settings":
        url = os.environ.get("METABASE_URL", "").rstrip("/")
        key = os.environ.get("METABASE_API_KEY", "")
        if not url or not key:
            raise ConfigError(
                "Direct mode requires METABASE_URL and METABASE_API_KEY",
            )
        return cls(metabase_url=url, metabase_api_key=key)


@dataclass(frozen=True)
class SyntheticaSettings:
    """Synthetica/proxy-mode settings: talk to the FastAPI gateway."""

    backend_api_url: str
    synthetica_api_key: str

    @classmethod
    def from_env(cls) -> "SyntheticaSettings":
        url = os.environ.get("BACKEND_API_URL", "").rstrip("/")
        key = os.environ.get("SYNTHETICA_API_KEY", "")
        if not url or not key:
            raise ConfigError(
                "Synthetica mode requires BACKEND_API_URL and SYNTHETICA_API_KEY",
            )
        return cls(backend_api_url=url, synthetica_api_key=key)


def _detect_settings() -> "Settings | SyntheticaSettings":
    """Pick mode from env: ``BACKEND_API_URL`` wins (Synthetica), else Direct."""
    if os.environ.get("BACKEND_API_URL"):
        return SyntheticaSettings.from_env()
    return Settings.from_env()


class MetabaseClient:
    """Dual-mode async client.

    Construct directly from settings (used by tests) or via
    :func:`build_client` (used by the CLI entrypoint).
    """

    mode: Mode

    def __init__(self, settings: Settings | SyntheticaSettings) -> None:
        self._settings = settings
        if isinstance(settings, SyntheticaSettings):
            self.mode = "synthetica"
            self._client = httpx.AsyncClient(
                base_url=f"{settings.backend_api_url}/api/v1",
                headers={"x-api-key": settings.synthetica_api_key},
                timeout=30.0,
            )
        else:
            self.mode = "direct"
            self._client = httpx.AsyncClient(
                base_url=settings.metabase_url,
                headers={"x-api-key": settings.metabase_api_key},
                timeout=30.0,
            )

    @property
    def display_url(self) -> str:
        """Human-readable URL for log lines (does not leak the API key)."""
        if isinstance(self._settings, SyntheticaSettings):
            return f"{self._settings.backend_api_url} (Synthetica gateway)"
        return self._settings.metabase_url

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # list_databases
    # ------------------------------------------------------------------

    async def list_databases(self) -> list[dict[str, Any]]:
        if self.mode == "synthetica":
            r = await self._client.get("/metabase/databases")
            r.raise_for_status()
            return r.json()
        r = await self._client.get("/api/database")
        r.raise_for_status()
        payload = r.json()
        dbs = payload if isinstance(payload, list) else payload.get("data", [])
        return [
            {"id": d.get("id"), "name": d.get("name", ""), "engine": d.get("engine")}
            for d in dbs
        ]

    # ------------------------------------------------------------------
    # list_database_tables
    # ------------------------------------------------------------------

    async def list_database_tables(self, database_id: int) -> list[dict[str, Any]]:
        if self.mode == "synthetica":
            r = await self._client.get(f"/metabase/database/{database_id}/tables")
            r.raise_for_status()
            return r.json()
        r = await self._client.get(f"/api/database/{database_id}/metadata")
        r.raise_for_status()
        body = r.json()
        tables = body.get("tables", [])
        return [
            {
                "id": t.get("id"),
                "name": t.get("name", ""),
                "schema": t.get("schema"),
                "description": t.get("description"),
                "fields_count": len(t.get("fields", [])),
                "fields": [
                    {
                        "name": f.get("name"),
                        "base_type": f.get("base_type"),
                        "semantic_type": f.get("semantic_type"),
                    }
                    for f in t.get("fields", [])
                ],
            }
            for t in tables
            if not t.get("visibility_type")
        ]

    # ------------------------------------------------------------------
    # list_cards
    # ------------------------------------------------------------------

    async def list_cards(self, *, limit: int = 30) -> list[dict[str, Any]]:
        if self.mode == "synthetica":
            r = await self._client.get("/metabase/cards", params={"limit": limit})
            r.raise_for_status()
            return r.json()
        r = await self._client.get(
            "/api/card", params={"f": "all", "page_size": limit},
        )
        r.raise_for_status()
        payload = r.json()
        cards = payload if isinstance(payload, list) else payload.get("data", [])
        return [
            {
                "id": c.get("id"),
                "name": c.get("name", ""),
                "description": c.get("description") or "",
                "display": c.get("display", "table"),
                "collection_id": c.get("collection_id"),
            }
            for c in cards
        ]

    # ------------------------------------------------------------------
    # query_card
    # ------------------------------------------------------------------

    async def query_card(self, card_id: int) -> dict[str, Any]:
        if self.mode == "synthetica":
            r = await self._client.get(f"/metabase/card/{card_id}/data")
            r.raise_for_status()
            body = r.json()
            return {
                "card_id": card_id,
                "name": body.get("name", f"Card {card_id}"),
                "display": body.get("display", "table"),
                "cols": body.get("cols", []),
                "rows": body.get("data", []),
                "chart_uri": f"metabase://card/{card_id}",
            }

        card_resp = await self._client.get(f"/api/card/{card_id}")
        card_info = card_resp.json() if card_resp.status_code == 200 else {}
        q = await self._client.post(
            f"/api/card/{card_id}/query", json={"parameters": []},
        )
        q.raise_for_status()
        result = q.json()
        cols = [c["name"] for c in result.get("data", {}).get("cols", [])]
        rows = result.get("data", {}).get("rows", [])
        return {
            "card_id": card_id,
            "name": card_info.get("name", f"Card {card_id}"),
            "display": card_info.get("display", "table"),
            "cols": cols,
            "rows": [dict(zip(cols, row, strict=False)) for row in rows],
            "chart_uri": f"metabase://card/{card_id}",
        }

    # ------------------------------------------------------------------
    # create_card_from_sql — uses Representations YAML in Synthetica mode
    # ------------------------------------------------------------------

    async def create_card_from_sql(
        self,
        *,
        name: str,
        database_id: int,
        sql: str,
        display: str = "table",
        description: str | None = None,
        collection_id: int | None = None,
    ) -> dict[str, Any]:
        if self.mode == "synthetica":
            return await self._create_card_via_representations(
                name=name,
                database_id=database_id,
                sql=sql,
                display=display,
                description=description,
                collection_id=collection_id,
            )
        return await self._create_card_direct(
            name=name,
            database_id=database_id,
            sql=sql,
            display=display,
            description=description,
            collection_id=collection_id,
        )

    async def _create_card_via_representations(
        self,
        *,
        name: str,
        database_id: int,
        sql: str,
        display: str,
        description: str | None,
        collection_id: int | None,
    ) -> dict[str, Any]:
        """Synthetica mode — POST a v0.60 RepresentationDoc as YAML.

        The Metabase v0.60 Representations format is YAML-first; the
        Synthetica gateway accepts both YAML and JSON, but we emit YAML
        on the wire to match the spec and make the request body
        copy-paste compatible with ``metabase`` CLI tooling.
        """
        doc: dict[str, Any] = {
            "version": "0.60",
            "databases": [],
            "dashboards": [],
            "cards": [
                {
                    "name": name,
                    "database_id": database_id,
                    "sql": sql,
                    "display": display,
                    "description": description,
                    "collection_id": collection_id,
                },
            ],
        }
        try:
            resp = await self._client.post(
                "/metabase/representations/apply",
                content=_dump_yaml(doc),
                headers={"content-type": "application/x-yaml"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return {
                "status": "failed",
                "name": name,
                "error": f"Gateway {exc.response.status_code}: {exc.response.text[:200]}",
            }

        report = resp.json()
        item = next(
            (
                i
                for i in report.get("items", [])
                if i.get("kind") == "card" and i.get("name") == name
            ),
            None,
        )
        if item is None:
            return {
                "status": "failed",
                "name": name,
                "error": "card not present in apply report",
            }
        if item.get("status") == "failed":
            return {
                "status": "failed",
                "name": name,
                "error": item.get("error") or "Metabase rejected the SQL",
            }
        card_id = item.get("id")
        return {
            "status": item.get("status", "created"),
            "id": card_id,
            "name": name,
            "chart_uri": f"metabase://card/{card_id}" if card_id else None,
        }

    async def _create_card_direct(
        self,
        *,
        name: str,
        database_id: int,
        sql: str,
        display: str,
        description: str | None,
        collection_id: int | None,
    ) -> dict[str, Any]:
        """Direct mode — classic Metabase /api/card flow, idempotent by name."""
        existing_id: int | None = None
        try:
            r_list = await self._client.get(
                "/api/card", params={"f": "all", "page_size": 500},
            )
            r_list.raise_for_status()
            payload = r_list.json()
            existing = payload if isinstance(payload, list) else payload.get("data", [])
            for c in existing:
                if c.get("name") == name and c.get("collection_id") == collection_id:
                    existing_id = c.get("id")
                    break
        except Exception:
            existing_id = None

        body = {
            "name": name,
            "description": description,
            "display": display,
            "collection_id": collection_id,
            "dataset_query": {
                "type": "native",
                "native": {"query": sql, "template-tags": {}},
                "database": database_id,
            },
            "visualization_settings": {},
        }
        try:
            if existing_id is None:
                resp = await self._client.post("/api/card", json=body)
            else:
                resp = await self._client.put(
                    f"/api/card/{existing_id}", json=body,
                )
            resp.raise_for_status()
            card = resp.json()
            card_id = card.get("id", existing_id)
            return {
                "status": "updated" if existing_id else "created",
                "id": card_id,
                "name": name,
                "chart_uri": f"metabase://card/{card_id}" if card_id else None,
            }
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                bd = exc.response.json()
                detail = bd.get("message") if isinstance(bd, dict) else ""
            except Exception:
                detail = exc.response.text[:200]
            return {
                "status": "failed",
                "name": name,
                "error": f"Metabase {exc.response.status_code}: {detail}",
            }

    # ------------------------------------------------------------------
    # create_dashboard
    # ------------------------------------------------------------------

    async def create_dashboard(
        self,
        name: str,
        *,
        description: str | None = None,
        collection_id: int | None = None,
        card_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        if self.mode == "synthetica":
            # YAML-first wire format, matching v0.60 Representations.
            doc: dict[str, Any] = {
                "version": "0.60",
                "databases": [],
                "dashboards": [
                    {
                        "name": name,
                        "description": description,
                        "collection_id": collection_id,
                        "cards": [],
                    },
                ],
                "cards": [],
            }
            r = await self._client.post(
                "/metabase/representations/apply",
                content=_dump_yaml(doc),
                headers={"content-type": "application/x-yaml"},
            )
            r.raise_for_status()
            report = r.json()
            dash_item = next(
                (i for i in report.get("items", []) if i.get("kind") == "dashboard"),
                None,
            )
            return {
                "id": dash_item.get("id") if dash_item else None,
                "name": name,
                "card_count": len(card_ids or []),
                "note": (
                    "Synthetica mode: dashboard scaffolded empty. To attach "
                    "existing cards by id, POST a full RepresentationDoc YAML "
                    "to /metabase/representations/apply with a populated "
                    "dashboards[].cards list."
                ),
            }

        # direct mode
        r = await self._client.post(
            "/api/dashboard",
            json={
                "name": name,
                "description": description,
                "collection_id": collection_id,
            },
        )
        r.raise_for_status()
        dashboard = r.json()
        dashboard_id = dashboard.get("id")
        for idx, card_id in enumerate(card_ids or []):
            await self._client.post(
                f"/api/dashboard/{dashboard_id}/cards",
                json={
                    "cardId": card_id,
                    "row": idx * 4,
                    "col": 0,
                    "size_x": 12,
                    "size_y": 4,
                },
            )
        return {"id": dashboard_id, "name": name, "card_count": len(card_ids or [])}

    # ------------------------------------------------------------------
    # request_synthetic_data_generation — Synthetica mode only
    # ------------------------------------------------------------------

    async def request_synthetic_data_generation(
        self,
        *,
        source_type: str,
        source_params: dict[str, Any],
        num_rows: int,
        model: str | None = None,
        use_case: str | None = None,
    ) -> dict[str, Any]:
        if self.mode != "synthetica":
            raise RuntimeError(
                "request_synthetic_data_generation requires Synthetica mode. "
                "Set BACKEND_API_URL and SYNTHETICA_API_KEY to enable it.",
            )
        generation_params: dict[str, Any] = {"num_rows": num_rows}
        if model:
            generation_params["model"] = model
        if use_case:
            generation_params["use_case"] = use_case
        payload = {
            "source_type": source_type,
            "source_params": source_params,
            "generation_params": generation_params,
        }
        r = await self._client.post("/webhooks/sdv/trigger", json=payload)
        if r.status_code == 402:
            body: dict[str, Any] = {}
            try:
                body = r.json()
            except Exception:
                body = {}
            return {
                "status": "payment_required",
                "error": "insufficient_balance",
                "detail": body.get("detail"),
            }
        r.raise_for_status()
        body = r.json()
        job = body.get("job") or {}
        return {
            "status": "accepted",
            "job_id": job.get("id"),
            "job_status": job.get("status"),
            "estimated_cost_tokens": body.get("estimated_cost_tokens"),
            "reserved_tokens": body.get("reserved_tokens"),
            "bypassed": body.get("bypassed", False),
            "bypass_reason": body.get("bypass_reason"),
        }


def build_client() -> MetabaseClient:
    """Construct the client, picking the mode from env vars.

    ``BACKEND_API_URL`` set → Synthetica mode.
    Otherwise → Direct mode (requires ``METABASE_URL`` + ``METABASE_API_KEY``).
    """
    return MetabaseClient(_detect_settings())


def _dump_yaml(doc: dict[str, Any]) -> bytes:
    """Serialize a RepresentationDoc to YAML bytes.

    Output is human-readable (``sort_keys=False``, ``allow_unicode=True``) so
    the body that travels on the wire is the same a developer would write
    by hand and can be inspected in any HTTP debugger.
    """
    return yaml.safe_dump(
        doc, sort_keys=False, allow_unicode=True,
    ).encode("utf-8")
