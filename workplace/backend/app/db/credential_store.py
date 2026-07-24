"""User-entered model API credentials (owner 2026-07-23, settings page).

Two slots: "text" — an OpenAI-compatible endpoint that overrides the .env
DeepSeek default when present — and "vision", reserved so a hosted
image-reading model can plug into the `VisionClient` seam later without a
schema change. Keys stay in the local sqlite file (same trust level as .env);
read endpoints only ever expose the last 4 characters.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

API_SLOTS = ("text", "vision")


@dataclass(frozen=True)
class ApiCredential:
    slot: str
    base_url: str
    model: str
    api_key: str


def get_credential(conn: sqlite3.Connection, slot: str) -> ApiCredential | None:
    row = conn.execute(
        "SELECT slot, base_url, model, api_key FROM api_credentials WHERE slot = ?",
        (slot,),
    ).fetchone()
    if row is None:
        return None
    return ApiCredential(
        slot=row["slot"], base_url=row["base_url"], model=row["model"], api_key=row["api_key"]
    )


def set_credential(
    conn: sqlite3.Connection,
    slot: str,
    *,
    base_url: str,
    model: str,
    api_key: str,
    now: datetime,
) -> None:
    conn.execute(
        "INSERT INTO api_credentials (slot, base_url, model, api_key, updated_at)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(slot) DO UPDATE SET base_url = excluded.base_url,"
        " model = excluded.model, api_key = excluded.api_key,"
        " updated_at = excluded.updated_at",
        (slot, base_url, model, api_key, now.isoformat()),
    )
    conn.commit()


def clear_credential(conn: sqlite3.Connection, slot: str) -> None:
    conn.execute("DELETE FROM api_credentials WHERE slot = ?", (slot,))
    conn.commit()
