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
    source TEXT NOT NULL DEFAULT 'claude',
    prompt TEXT NOT NULL,
    krogsveen_mentioned INTEGER,
    krogsveen_cited INTEGER,
    competitors_mentioned TEXT,
    response_excerpt TEXT,
    sentiment TEXT,
    sentiment_begrunnelse TEXT,
    PRIMARY KEY (week_start, source, prompt)
);

CREATE TABLE IF NOT EXISTS organic_footprint_weekly (
    week_start TEXT NOT NULL,
    keyword TEXT NOT NULL,
    position INTEGER,
    url TEXT,
    clusters TEXT,
    PRIMARY KEY (week_start, keyword)
);

CREATE TABLE IF NOT EXISTS content_briefs_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    url TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    antall_forslag INTEGER
);
"""


def _migrate_geo_selfcheck_source_column(conn: sqlite3.Connection) -> None:
    """geo_selfcheck_weekly sin PRIMARY KEY måtte utvides til å inkludere 'source' for å
    støtte flere LLM-leverandører (Claude, ChatGPT, ...) uten kollisjon på samme prompt
    samme uke. SQLite kan ikke endre en PRIMARY KEY via ALTER TABLE, så eksisterende
    tabell (fra før ChatGPT-støtte, alle rader var Claude) migreres via ny tabell + kopi.
    Databasen hadde kun noen få dagers testdata da dette ble skrevet — trygt å migrere."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(geo_selfcheck_weekly)").fetchall()}
    if "source" in columns or not columns:
        return  # allerede ny, eller tabellen finnes ikke ennå (frisk database)
    conn.executescript(
        """
        ALTER TABLE geo_selfcheck_weekly RENAME TO geo_selfcheck_weekly_old;
        CREATE TABLE geo_selfcheck_weekly (
            week_start TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'claude',
            prompt TEXT NOT NULL,
            krogsveen_mentioned INTEGER,
            competitors_mentioned TEXT,
            response_excerpt TEXT,
            sentiment TEXT,
            sentiment_begrunnelse TEXT,
            PRIMARY KEY (week_start, source, prompt)
        );
        INSERT INTO geo_selfcheck_weekly
            (week_start, source, prompt, krogsveen_mentioned, competitors_mentioned, response_excerpt)
        SELECT week_start, 'claude', prompt, krogsveen_mentioned, competitors_mentioned, response_excerpt
        FROM geo_selfcheck_weekly_old;
        DROP TABLE geo_selfcheck_weekly_old;
        """
    )


def _migrate_geo_selfcheck_cited_column(conn: sqlite3.Connection) -> None:
    """krogsveen_cited (kun brukt av Perplexity-selvsjekken — sitat-URL, ikke bare
    tekstnevnelse) lagt til 21.07.2026. Enkel ADD COLUMN holder siden dette ikke
    rører PRIMARY KEY (i motsetning til source-migreringen over)."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(geo_selfcheck_weekly)").fetchall()}
    if not columns or "krogsveen_cited" in columns:
        return
    conn.execute("ALTER TABLE geo_selfcheck_weekly ADD COLUMN krogsveen_cited INTEGER")


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    _migrate_geo_selfcheck_source_column(conn)
    conn.executescript(SCHEMA)
    _migrate_geo_selfcheck_cited_column(conn)
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


def save_geo_selfcheck_rows(conn: sqlite3.Connection, week_start: str, rows: list[dict], source: str = "claude") -> None:
    conn.executemany(
        """INSERT OR REPLACE INTO geo_selfcheck_weekly
           (week_start, source, prompt, krogsveen_mentioned, krogsveen_cited, competitors_mentioned,
            response_excerpt, sentiment, sentiment_begrunnelse)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                week_start,
                source,
                r.get("prompt"),
                int(bool(r.get("krogsveen_mentioned"))),
                int(bool(r.get("krogsveen_cited"))) if "krogsveen_cited" in r else None,
                json.dumps(r.get("competitors_mentioned", [])),
                r.get("response_excerpt"),
                r.get("sentiment"),
                r.get("sentiment_begrunnelse"),
            )
            for r in rows
        ],
    )
    conn.commit()


def save_organic_footprint_rows(conn: sqlite3.Connection, week_start: str, rows: list[dict]) -> None:
    """rows: tagget output fra ahrefs.get_organic_keywords_paginated (keyword, best_position,
    best_position_url, clusters)."""
    conn.executemany(
        """INSERT OR REPLACE INTO organic_footprint_weekly
           (week_start, keyword, position, url, clusters)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (
                week_start,
                r.get("keyword"),
                r.get("best_position"),
                r.get("best_position_url"),
                json.dumps(r.get("clusters", [])),
            )
            for r in rows
        ],
    )
    conn.commit()


def get_organic_footprint_trend(conn: sqlite3.Connection, weeks: int = 12) -> list[dict]:
    """Antall søkeord og snittposisjon i det fulle organiske fotavtrykket per uke —
    bredde-trend uavhengig av de 338 manuelt sporede Rank Tracker-ordene."""
    cur = conn.execute(
        """SELECT week_start, COUNT(*) as n, AVG(position) as avg_position
           FROM organic_footprint_weekly
           WHERE position IS NOT NULL
           GROUP BY week_start
           ORDER BY week_start DESC
           LIMIT ?""",
        (weeks,),
    )
    rows = [{"week_start": w, "keyword_count": n, "avg_position": round(p, 2)} for w, n, p in cur.fetchall()]
    return list(reversed(rows))


def save_content_briefs_meta(conn: sqlite3.Connection, url: str, updated_at: str, antall_forslag: int) -> None:
    """Lagrer kun siste kjente lenke til innholdsforslag-dokumentet (singleton-rad, id=1)
    — dashboardet trenger bare å vite hvor det ligger og når det sist ble oppdatert, ikke
    en historikk. Skrives av scripts/keyword_discovery.py --to-drive, leses av
    src/pipeline.py (ukentlig) slik at dashboardet viser lenken selv de ukene den
    dyrere bi-ukentlige jobben ikke kjører."""
    conn.execute(
        "INSERT OR REPLACE INTO content_briefs_meta (id, url, updated_at, antall_forslag) VALUES (1, ?, ?, ?)",
        (url, updated_at, antall_forslag),
    )
    conn.commit()


def get_content_briefs_meta(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT url, updated_at, antall_forslag FROM content_briefs_meta WHERE id = 1").fetchone()
    if not row:
        return None
    return {"url": row[0], "updated_at": row[1], "antall_forslag": row[2]}


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
        "organic_footprint_weekly",
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
