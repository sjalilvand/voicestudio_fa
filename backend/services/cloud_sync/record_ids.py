"""Stable ``sync_id``s for synced records (guide §4): filled once, never changed."""
from __future__ import annotations

from core import db as core_db
from services.cloud_sync.ids import new_sync_id

#: Record tables that carry a sync_id today (S2: voices). S3 adds takes and projects.
SYNCED_TABLES = ("voice_profiles",)


def ensure_sync_ids(table: str = "voice_profiles") -> int:
    """Give every row without a ``sync_id`` a new one; returns how many were filled."""
    if table not in SYNCED_TABLES:
        raise ValueError(f"not a synced table: {table}")
    filled = 0
    with core_db.db_conn() as conn:
        missing = [r[0] for r in conn.execute(f"SELECT id FROM {table} WHERE sync_id IS NULL OR sync_id = ''")]
        for row_id in missing:
            conn.execute(f"UPDATE {table} SET sync_id=? WHERE id=? AND (sync_id IS NULL OR sync_id='')",
                         (new_sync_id(), row_id))
            filled += 1
    return filled
