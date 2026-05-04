#!/usr/bin/env python3
"""Auto-setup Metabase for the demo.

Run *after* ``docker compose up -d`` brings Metabase + Postgres online.

What it does (idempotent — re-running is safe):

1. Polls ``/api/health`` until Metabase is ready (~30-60 s on first boot).
2. If Metabase is unconfigured, creates the admin user via ``/api/setup``.
3. Logs in (or reuses the setup session) to obtain a session id.
4. Adds the seeded Postgres database (``demo_postgres``).
5. Creates an API key bound to the admin group.
6. Prints two ``export`` lines so the user can drive metabase-mcp:

       export METABASE_URL=http://localhost:3000
       export METABASE_API_KEY=mb_xxx...

The script writes the API key to ``examples/.env.local`` so
``run_real_demo.py`` can pick it up without manual copying.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

METABASE_URL = os.environ.get("METABASE_URL", "http://localhost:3000")
ADMIN_EMAIL = os.environ.get("DEMO_ADMIN_EMAIL", "demo@example.com")
ADMIN_PASSWORD = os.environ.get("DEMO_ADMIN_PASSWORD", "Demo12345!")
DB_NAME = os.environ.get("DEMO_DB_NAME", "demo_postgres")
DB_HOST = os.environ.get("DEMO_DB_HOST", "host.docker.internal")
DB_PORT = int(os.environ.get("DEMO_DB_PORT", "55432"))
DB_USER = os.environ.get("DEMO_DB_USER", "demo")
DB_PASSWORD = os.environ.get("DEMO_DB_PASSWORD", "demo")
DB_DBNAME = os.environ.get("DEMO_DB_DBNAME", "demo")

ENV_FILE = Path(__file__).parent / ".env.local"


def _wait_for_metabase(client: httpx.Client, max_seconds: int = 180) -> None:
    print(f"Waiting for Metabase at {METABASE_URL} ...", end="", flush=True)
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        try:
            r = client.get(f"{METABASE_URL}/api/health", timeout=3.0)
            if r.status_code == 200:
                print(" ready.")
                return
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(2)
    print()
    sys.exit("Metabase did not become ready in time. Is `docker compose up -d` running?")


def _setup_or_login(client: httpx.Client) -> str:
    """Run ``/api/setup`` if needed; return a session id."""
    props = client.get(f"{METABASE_URL}/api/session/properties").json()
    setup_token = props.get("setup-token")

    if setup_token:
        print("Metabase is unconfigured. Creating admin user ...")
        r = client.post(
            f"{METABASE_URL}/api/setup",
            json={
                "token": setup_token,
                "user": {
                    "first_name": "Demo",
                    "last_name": "Admin",
                    "email": ADMIN_EMAIL,
                    "password": ADMIN_PASSWORD,
                    "site_name": "metabase-mcp demo",
                },
                "prefs": {
                    "site_name": "metabase-mcp demo",
                    "site_locale": "en",
                    "allow_tracking": False,
                },
                "database": None,
            },
            timeout=30.0,
        )
        if r.status_code != 200:
            sys.exit(f"Setup failed: {r.status_code} {r.text}")
        session_id = r.json().get("id") or r.cookies.get("metabase.SESSION", "")
        if not session_id:
            sys.exit("Setup succeeded but no session id was returned.")
        print(f"  ok (session {session_id[:8]}...)")
        return session_id

    print("Metabase already configured. Logging in ...")
    r = client.post(
        f"{METABASE_URL}/api/session",
        json={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30.0,
    )
    if r.status_code != 200:
        sys.exit(
            f"Login failed: {r.status_code} {r.text}\n"
            f"Hint: edit DEMO_ADMIN_EMAIL / DEMO_ADMIN_PASSWORD to match the existing admin.",
        )
    session_id = r.json()["id"]
    print(f"  ok (session {session_id[:8]}...)")
    return session_id


def _ensure_database(client: httpx.Client, session_id: str) -> int:
    headers = {"X-Metabase-Session": session_id}
    r = client.get(f"{METABASE_URL}/api/database", headers=headers, timeout=15.0)
    r.raise_for_status()
    data = r.json()
    rows = data if isinstance(data, list) else data.get("data", [])
    for db in rows:
        if db.get("name") == DB_NAME:
            print(f"Database '{DB_NAME}' already registered (id={db['id']}).")
            return db["id"]

    print(f"Adding database '{DB_NAME}' ({DB_HOST}:{DB_PORT}/{DB_DBNAME}) ...")
    r = client.post(
        f"{METABASE_URL}/api/database",
        headers=headers,
        json={
            "name": DB_NAME,
            "engine": "postgres",
            "details": {
                "host": DB_HOST,
                "port": DB_PORT,
                "dbname": DB_DBNAME,
                "user": DB_USER,
                "password": DB_PASSWORD,
                "ssl": False,
                "tunnel-enabled": False,
            },
        },
        timeout=30.0,
    )
    if r.status_code not in (200, 201):
        sys.exit(f"Could not register Postgres: {r.status_code} {r.text}")
    db_id = r.json()["id"]
    print(f"  ok (id={db_id}). Triggering metadata sync ...")
    client.post(
        f"{METABASE_URL}/api/database/{db_id}/sync_schema",
        headers=headers,
        timeout=30.0,
    )
    return db_id


def _ensure_api_key(client: httpx.Client, session_id: str) -> str:
    headers = {"X-Metabase-Session": session_id}
    # Group 2 is "All Users" by default; pick the first admin group instead so
    # the key has full read permissions on the new database.
    groups = client.get(f"{METABASE_URL}/api/permissions/group", headers=headers).json()
    admin_group = next(
        (g for g in groups if g.get("name", "").lower() == "administrators"),
        None,
    )
    group_id = admin_group["id"] if admin_group else 1

    name = "metabase-mcp demo"
    existing = client.get(f"{METABASE_URL}/api/api-key", headers=headers).json()
    for key in existing if isinstance(existing, list) else []:
        if key.get("name") == name:
            print(f"API key '{name}' already exists — Metabase only shows the value at creation.")
            print("Delete it in Admin > API Keys and re-run this script to obtain a fresh value,")
            print("or set METABASE_API_KEY manually if you stored it.")
            return ""

    print(f"Creating API key '{name}' (group_id={group_id}) ...")
    r = client.post(
        f"{METABASE_URL}/api/api-key",
        headers=headers,
        json={"name": name, "group_id": group_id},
        timeout=30.0,
    )
    if r.status_code not in (200, 201):
        sys.exit(
            f"Could not create API key: {r.status_code} {r.text}\n"
            f"Note: API keys require Metabase v0.50+. If your image is older, "
            f"upgrade ``metabase/metabase:latest`` in docker-compose.yml.",
        )
    api_key = r.json().get("unmasked_key") or r.json().get("key")
    if not api_key:
        sys.exit(f"API key created but no value returned: {r.json()}")
    print("  ok")
    return api_key


def _write_env_file(api_key: str, db_id: int) -> None:
    ENV_FILE.write_text(
        f"# auto-generated by setup_metabase.py — re-run to refresh\n"
        f"METABASE_URL={METABASE_URL}\n"
        f"METABASE_API_KEY={api_key}\n"
        f"DEMO_DATABASE_ID={db_id}\n",
        encoding="utf-8",
    )
    print(f"Wrote {ENV_FILE.name} (consumed by run_real_demo.py).")


def main() -> int:
    with httpx.Client() as client:
        _wait_for_metabase(client)
        session_id = _setup_or_login(client)
        db_id = _ensure_database(client, session_id)
        api_key = _ensure_api_key(client, session_id)

    if api_key:
        _write_env_file(api_key, db_id)
        print("\nDone. Drive metabase-mcp with:\n")
        print(f"  export METABASE_URL={METABASE_URL}")
        print(f"  export METABASE_API_KEY={api_key}")
        print("  metabase-mcp\n")
        print("Or run the integration demo straight away:\n")
        print("  python examples/run_real_demo.py")
    else:
        print("\nAn existing API key was detected. Re-create it in Metabase if you need a new value.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
