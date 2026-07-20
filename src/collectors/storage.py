"""SQLite-historikk for ukesrader — grunnlag for trender over tid, ikke bare uke-mot-uke."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS rank_tracker_weekly (
    week_start TEXT NOT NULL,
    device TEXT NOT NULL,
    keyword TEXT NOT NULL,
    position INTEGER,
    position_prev INTEGER,
    volume INTEGER,
    url TEXT,
    serp_features TEXT,
    PRIMARY KEY (week_start, device, keyword)
);

CREATE TABLE IF NOT EXISTS gsc_weekly (
    week_start TEXT NOT NULL,
    dimension TEXT NOT NULL,
    key TEXT NOT NULL,
    clicks INTEGER,
    impressions INTEGER,
    ctr REAL,
    position REAL,
    PRIMARY KEY (week_start, dimension, key)
);

CREATE TABLE IF NOT EXISTS brand_radar_weekly (
    week_start TEXT NOT NULL,
    brand TEXT NOT NULL,
    total INTEGER,
    only_target_brand INTEGER,
    target_and_competitors_brands INTEGER,
    only_competitors_brands INTEGER,
    share_of_voice REAL,
    PRIMARY KEY (week_start, brand)
);

CREATE TABLE IF NOT EXISTS gsc_site_weekly (
    week_start TEXT NOT NULL,
    device TEXT NOT NULL,
    clicks INTEGER,
    impressions INTEGER,
    ctr REAL,
    position REAL,
    PRIMARY KEY (week_start, device)
);

CREATE TABLE IF NOT EXISTS geo_selfcheck_weekly (
    week_start TEXT NOT NULL,
    prompt TEXT NOT NULL,
    krogsveen_mentioned INTEGER,
    competitors_mentioned TEXT,
    response_excerpt TEXT,
    PRIMARY KEY (week_start, prompt)
);
"""

# Kolonner lagt til etter første utrulling — CREATE TABLE IF NOT EXISTS oppdaterer ikke
# skjemaet til en database som allerede finnes, så disse legges til eksplisitt og trygt.
_MIGRATIONS = [
    ("geo_selfcheck_weekly", "sentiment", "TEXT"),
    ("geo_selfcheck_weekly", "sentiment_begrunnelse", "TEXT"),
]


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    for table, column, col_type in _MIGRATIONS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    conn.commit()
    return conn


def save_rank_tracker_rows(conn: sqlite3.Connection, week_start: str, device: str, rows: list[dict]) -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO rank_tracker_weekly
           (week_start, device, keyword, position, position_prev, volume, url, serp_features)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                week_start,
                device,
                r.get("keyword"),
                r.get("position"),
                r.get("position_prev"),
                r.get("volume"),
                r.get("url"),
                json.dumps(r.get("serp_features", [])),
            )
            for r in rows
        ],
    )
    conn.commit()


def save_gsc_rows(conn: sqlite3.Connection, week_start: str, dimension: str, rows: list[dict]) -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO gsc_weekly
           (week_start, dimension, key, clicks, impressions, ctr, position)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                week_start,
                dimension,
                r.get(dimension),
                r.get("clicks"),
                r.get("impressions"),
                r.get("ctr"),
                r.get("position"),
            )
            for r in rows
        ],
    )
    conn.commit()


def save_brand_radar_rows(conn: sqlite3.Connection, week_start: str, rows: list[dict]) -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO brand_radar_weekly
           (week_start, brand, total, only_target_brand, target_and_competitors_brands,
            only_competitors_brands, share_of_voice)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                week_start,
                r.get("brand"),
                r.get("total"),
                r.get("only_target_brand"),
                r.get("target_and_competitors_brands"),
                r.get("only_competitors_brands"),
                r.get("share_of_voice"),
            )
            for r in rows
        ],
    )
    conn.commit()


def save_gsc_site_rows(conn: sqlite3.Connection, week_start: str, rows: list[dict]) -> None:
    """rows: [{"device": "all"|"desktop"|"mobile"|"tablet", "clicks", "impressions", "ctr", "position"}]."""
    conn.executemany(
        """INSERT OR REPLACE INTO gsc_site_weekly
           (week_start, device, clicks, impressions, ctr, position)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (week_start, r.get("device"), r.get("clicks"), r.get("impressions"), r.get("ctr"), r.get("position"))
            for r in rows
        ],
    )
    conn.commit()


def save_geo_selfcheck_rows(conn: sqlite3.Connection, week_start: str, rows: list[dict]) -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO geo_selfcheck_weekly
           (week_start, prompt, krogsveen_mentioned, competitors_mentioned, response_excerpt,
            sentiment, sentiment_begrunnelse)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                week_start,
                r.get("prompt"),
                int(bool(r.get("krogsveen_mentioned"))),
                json.dumps(r.get("competitors_mentioned", [])),
                r.get("response_excerpt"),
                r.get("sentiment"),
                r.get("sentiment_begrunnelse"),
            )
            for r in rows
        ],
    )
    conn.commit()


def get_position_trend(conn: sqlite3.Connection, weeks: int = 12) -> list[dict]:
    """Snitt-posisjon (desktop) per uke på tvers av alle sporede søkeord — for dashboard-trendgraf."""
    cur = conn.execute(
        """SELECT week_start, AVG(position) as avg_position, COUNT(*) as n
           FROM rank_tracker_weekly
           WHERE device = 'desktop' AND position IS NOT NULL
           GROUP BY week_start
           ORDER BY week_start DESC
           LIMIT ?""",
        (weeks,),
    )
    rows = [{"week_start": w, "avg_position": round(p, 2), "n": n} for w, p, n in cur.fetchall()]
    return list(reversed(rows))


def get_clicks_trend(conn: sqlite3.Connection, weeks: int = 12) -> list[dict]:
    """Site-wide klikk/visninger per uke (device='all') — for dashboard-trendgraf."""
    cur = conn.execute(
        """SELECT week_start, clicks, impressions
           FROM gsc_site_weekly
           WHERE device = 'all'
           ORDER BY week_start DESC
           LIMIT ?""",
        (weeks,),
    )
    rows = [{"week_start": w, "clicks": c, "impressions": i} for w, c, i in cur.fetchall()]
    return list(reversed(rows))


def get_history(conn: sqlite3.Connection, table: str, weeks: int = 12) -> list[dict]:
    """Siste N uker fra en av tabellene, for trendgrafer (roadmap-punkt 2)."""
    if table not in {
        "rank_tracker_weekly",
        "gsc_weekly",
        "brand_radar_weekly",
        "gsc_site_weekly",
        "geo_selfcheck_weekly",
    }:
        raise ValueError(f"Ukjent tabell: {table}")
    cur = conn.execute(
        f"SELECT DISTINCT week_start FROM {table} ORDER BY week_start DESC LIMIT ?", (weeks,)
    )
    week_starts = [row[0] for row in cur.fetchall()]
    if not week_starts:
        return []
    placeholders = ",".join("?" * len(week_starts))
    cur = conn.execute(
        f"SELECT * FROM {table} WHERE week_start IN ({placeholders}) ORDER BY week_start", week_starts
    )
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]
