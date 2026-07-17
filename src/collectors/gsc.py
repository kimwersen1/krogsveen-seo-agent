"""Import av manuelt eksportert GSC Performance-rapport (CSV).

Ahrefs' egen GSC-integrasjon dekker site-wide trender (se ahrefs.get_gsc_performance_history/
get_gsc_performance_by_device — ingen egen tilkobling nødvendig), men gsc-keywords og
gsc-pages svarer fortsatt tomt, og direkte GSC API krever Owner-tilgang på
Search Console-eiendommen som ingen hos Krogsveen kunne gi oss (verifisert 16.07.2026).

Løsning: den som har vanlig (ikke-Owner) GSC-tilgang eksporterer Performance-rapporten
som CSV fra search.google.com/search-console → Performance → Export → Download CSV,
og denne modulen leser den inn i samme radform som en direkte API-kobling ville gitt.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_COLUMN_ALIASES = {
    "top queries": "query",
    "query": "query",
    "queries": "query",
    "top pages": "page",
    "page": "page",
    "pages": "page",
    "clicks": "clicks",
    "impressions": "impressions",
    "ctr": "ctr",
    "position": "position",
    "average position": "position",
}


def _normalize_row(raw: dict) -> dict:
    row = {}
    for key, value in raw.items():
        canonical = _COLUMN_ALIASES.get(key.strip().lower())
        if not canonical:
            continue
        if canonical in ("clicks", "impressions"):
            row[canonical] = int(str(value).replace(",", "").replace("\xa0", "").strip() or 0)
        elif canonical == "ctr":
            row[canonical] = float(str(value).replace("%", "").replace(",", ".").strip() or 0)
        elif canonical == "position":
            row[canonical] = float(str(value).replace(",", ".").strip() or 0)
        else:
            row[canonical] = value.strip()
    return row


def import_gsc_export(csv_path: Path, dimension: str) -> list[dict]:
    """Leser en GSC UI-eksportert CSV (Queries.csv eller Pages.csv) til rader
    formet som {"query"|"page": ..., "clicks": ..., "impressions": ..., "ctr": ..., "position": ...}.
    """
    if dimension not in ("query", "page"):
        raise ValueError(f"dimension må være 'query' eller 'page', fikk {dimension!r}")

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [_normalize_row(raw) for raw in reader]

    rows = [r for r in rows if dimension in r]
    logger.info("Importerte %d GSC-%s-rader fra %s", len(rows), dimension, csv_path)
    return rows
