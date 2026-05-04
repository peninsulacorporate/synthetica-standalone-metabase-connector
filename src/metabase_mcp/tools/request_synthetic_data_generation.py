"""``request_synthetic_data_generation`` — headless SDV trigger (Synthetica mode).

This tool does not generate data itself. It triggers the inbound SDV
webhook on a Synthetica-compatible backend
(``POST /api/v1/webhooks/sdv/trigger``); the backend validates the
caller's API token balance, queues the heavy SDV pipeline as an
asynchronous background task, and notifies the user via the existing
webhook delivery system when the job settles.

This is the "Buy" entrypoint of the Synthetica ecosystem: the LLM commits
to a job, the backend gates it on balance, and the user gets the result
out-of-band.

Available **only in Synthetica mode** (``BACKEND_API_URL`` set). In
direct mode the tool raises :class:`RuntimeError` with a clear message —
there is no backend to trigger.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from metabase_mcp.client import MetabaseClient


def register(mcp: "FastMCP", client: "MetabaseClient") -> None:
    @mcp.tool()
    async def request_synthetic_data_generation(
        source_type: str,
        source_params: dict[str, Any],
        num_rows: int = 1000,
        model: str | None = None,
        use_case: str | None = None,
    ) -> dict[str, Any]:
        """Ask the Synthetica backend to generate synthetic data.

        Returns immediately with ``{status: "accepted", job_id, ...}`` once
        the gateway validates the API-token balance and enqueues the job.
        Subscribe to the user's webhook (or poll
        ``/api/v1/synthetics/jobs/{job_id}``) for completion — do NOT
        block waiting for the heavy pipeline.

        Parameters
        ----------
        source_type:
            ``"csv"`` or ``"db"``.
        source_params:
            For ``csv``: ``{csv_url | csv_content, dataset_name?}``.
            For ``db``: ``{connection_name, table_name}``.
        num_rows:
            Target row count for the synthetic dataset.
        model:
            Optional SDV model (e.g. ``GaussianCopula``).
        use_case:
            Optional label describing the downstream use case.

        Errors
        ------
        - ``{status: "payment_required", error: "insufficient_balance"}``
          when the caller is below their token threshold and not exempt.
        - Raises ``RuntimeError`` in direct mode — set ``BACKEND_API_URL``
          + ``SYNTHETICA_API_KEY`` to enable.
        """
        return await client.request_synthetic_data_generation(
            source_type=source_type,
            source_params=source_params,
            num_rows=num_rows,
            model=model,
            use_case=use_case,
        )
