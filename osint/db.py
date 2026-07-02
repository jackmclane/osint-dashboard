"""SQLite storage. Deliberately small — plain SQL, no ORM.

Phase 1 used a single `events` table. The full build adds three more:
  - market_history : one row per market per run, so we can measure swings
  - signals        : cross-source alerts surfaced at the top of the dashboard
  - ais_positions  : latest vessel position per watched maritime zone

Everything still lives in one committed SQLite file so the free GitHub Actions
writer and the free Streamlit reader can share it. Swap this module for a free
Postgres tier (Supabase/Neon) later without touching the rest of the code.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Event

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "osint.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    source_type  TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT,
    summary      TEXT,
    published_at TEXT,
    region       TEXT,
    topics       TEXT,
    raw          TEXT,
    collected_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_published ON events(published_at);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(source_type);

-- Time series of market probabilities. Append-only; one row per market per run.
CREATE TABLE IF NOT EXISTS market_history (
    market_id   TEXT NOT NULL,
    platform    TEXT NOT NULL,
    question    TEXT NOT NULL,
    probability REAL NOT NULL,      -- 0..1 for the tracked outcome
    url         TEXT,
    ts          TEXT NOT NULL       -- ISO 8601, when we recorded it
);
CREATE INDEX IF NOT EXISTS idx_mh_market ON market_history(market_id, ts);

-- Cross-source alerts. De-duplicated by id (kind + ref + day bucket).
CREATE TABLE IF NOT EXISTS signals (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,       -- "market_swing" | "news_spike"
    title      TEXT NOT NULL,
    detail     TEXT,
    magnitude  REAL,
    url        TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);

-- Latest AIS position per vessel per watched zone (upserted, not history).
CREATE TABLE IF NOT EXISTS ais_positions (
    mmsi TEXT NOT NULL,
    name TEXT,
    zone TEXT NOT NULL,
    lat  REAL,
    lon  REAL,
    sog  REAL,                       -- speed over ground (knots)
    cog  REAL,                       -- course over ground (degrees)
    ts   TEXT NOT NULL,
    PRIMARY KEY (mmsi, zone)
);
CREATE INDEX IF NOT EXISTS idx_ais_zone ON ais_positions(zone);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# --------------------------------------------------------------------------- #
# events
# --------------------------------------------------------------------------- #
def upsert_events(conn: sqlite3.Connection, events: list[Event]) -> int:
    """Insert events, ignoring ones already seen (same id). Returns new count."""
    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO events
            (id, source, source_type, title, url, summary,
             published_at, region, topics, raw, collected_at)
        VALUES
            (:id, :source, :source_type, :title, :url, :summary,
             :published_at, :region, :topics, :raw, :collected_at)
        """,
        [e.as_row() for e in events],
    )
    conn.commit()
    return conn.total_changes - before


def recent_events(
    conn: sqlite3.Connection,
    limit: int = 200,
    source_type: str | None = None,
) -> list[sqlite3.Row]:
    q = "SELECT * FROM events"
    params: list = []
    if source_type:
        q += " WHERE source_type = ?"
        params.append(source_type)
    q += " ORDER BY COALESCE(published_at, collected_at) DESC LIMIT ?"
    params.append(limit)
    return conn.execute(q, params).fetchall()


def events_since(conn: sqlite3.Connection, since_iso: str) -> list[sqlite3.Row]:
    """All events whose best-known timestamp is >= since_iso. Used by signals."""
    return conn.execute(
        """
        SELECT * FROM events
        WHERE COALESCE(published_at, collected_at) >= ?
        ORDER BY COALESCE(published_at, collected_at) DESC
        """,
        (since_iso,),
    ).fetchall()


# --------------------------------------------------------------------------- #
# market history
# --------------------------------------------------------------------------- #
def record_market_snapshots(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Append a probability reading for each market. rows: market_id, platform,
    question, probability, url."""
    ts = _now()
    conn.executemany(
        """
        INSERT INTO market_history (market_id, platform, question, probability, url, ts)
        VALUES (:market_id, :platform, :question, :probability, :url, :ts)
        """,
        [{**r, "ts": ts} for r in rows],
    )
    conn.commit()
    return len(rows)


def latest_probability(conn: sqlite3.Connection, market_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM market_history WHERE market_id = ? ORDER BY ts DESC LIMIT 1",
        (market_id,),
    ).fetchone()


def probability_at_or_before(
    conn: sqlite3.Connection, market_id: str, cutoff_iso: str
) -> sqlite3.Row | None:
    """The most recent reading at or before cutoff — i.e. 'where was it ~24h ago'."""
    return conn.execute(
        """
        SELECT * FROM market_history
        WHERE market_id = ? AND ts <= ?
        ORDER BY ts DESC LIMIT 1
        """,
        (market_id, cutoff_iso),
    ).fetchone()


def distinct_market_ids(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT market_id FROM market_history")]


# --------------------------------------------------------------------------- #
# signals
# --------------------------------------------------------------------------- #
def signal_id(kind: str, ref: str, bucket: str) -> str:
    return hashlib.sha256(f"{kind}:{ref}:{bucket}".encode()).hexdigest()[:16]


def add_signals(conn: sqlite3.Connection, signals: list[dict]) -> int:
    """Insert signals, ignoring duplicates (same id). Returns new count."""
    before = conn.total_changes
    ts = _now()
    conn.executemany(
        """
        INSERT OR IGNORE INTO signals (id, kind, title, detail, magnitude, url, created_at)
        VALUES (:id, :kind, :title, :detail, :magnitude, :url, :created_at)
        """,
        [{**s, "created_at": s.get("created_at", ts)} for s in signals],
    )
    conn.commit()
    return conn.total_changes - before


def recent_signals(conn: sqlite3.Connection, limit: int = 25) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM signals ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()


# --------------------------------------------------------------------------- #
# AIS
# --------------------------------------------------------------------------- #
def upsert_ais_positions(conn: sqlite3.Connection, rows: list[dict]) -> int:
    ts = _now()
    conn.executemany(
        """
        INSERT INTO ais_positions (mmsi, name, zone, lat, lon, sog, cog, ts)
        VALUES (:mmsi, :name, :zone, :lat, :lon, :sog, :cog, :ts)
        ON CONFLICT(mmsi, zone) DO UPDATE SET
            name=excluded.name, lat=excluded.lat, lon=excluded.lon,
            sog=excluded.sog, cog=excluded.cog, ts=excluded.ts
        """,
        [{**r, "ts": r.get("ts", ts)} for r in rows],
    )
    conn.commit()
    return len(rows)


def ais_zone_summary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT zone,
               COUNT(*)        AS vessels,
               AVG(sog)        AS avg_speed,
               MAX(ts)         AS last_seen
        FROM ais_positions
        GROUP BY zone
        ORDER BY zone
        """
    ).fetchall()


def ais_positions_for_zone(conn: sqlite3.Connection, zone: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM ais_positions WHERE zone = ? ORDER BY ts DESC", (zone,)
    ).fetchall()
