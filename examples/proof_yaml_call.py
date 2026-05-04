"""One-shot client: connects via fastmcp to a running metabase-mcp on :8092
and invokes create_card_from_sql so we can watch the YAML body land at the
gateway logs."""
from __future__ import annotations

import asyncio
import json

from fastmcp.client import Client


async def main() -> None:
    async with Client("http://localhost:8092/mcp") as client:
        tools = await client.list_tools()
        print(f"[ok] {len(tools)} tools registered: {sorted(t.name for t in tools)}")
        result = await client.call_tool(
            "create_card_from_sql",
            {
                "name": "Proof of YAML",
                "database_id": 1,
                "sql": "SELECT 'YAML round-trip works' AS proof",
                "display": "scalar",
            },
        )
        # FastMCP returns CallToolResult — pull the structured content
        try:
            content = result.structured_content or {}
            if not content and result.content:
                for block in result.content:
                    if hasattr(block, "text"):
                        content = json.loads(block.text)
                        break
        except Exception:
            content = {}
        print("\n[ok] create_card_from_sql returned:")
        print(json.dumps(content, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
