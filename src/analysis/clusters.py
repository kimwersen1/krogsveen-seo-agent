"""Tagger søkeord mot cluster-definisjonene i clusters.json (regex, case-insensitive)."""
from __future__ import annotations

import re


def tag_keyword(keyword: str, clusters: dict[str, str]) -> list[str]:
    return [name for name, pattern in clusters.items() if re.search(pattern, keyword or "", re.IGNORECASE)]


def tag_rows(rows: list[dict], clusters: dict[str, str]) -> list[dict]:
    """Legger til 'clusters'-nøkkel på hver rad. Et søkeord kan havne i 0, 1 eller flere clustre."""
    return [{**row, "clusters": tag_keyword(row.get("keyword", ""), clusters)} for row in rows]


def summarize_footprint_by_cluster(tagged_rows: list[dict], cluster_names: list[str]) -> list[dict]:
    """Bredde-oppsummering (antall + snittposisjon) per cluster fra det fulle organiske
    fotavtrykket (site-explorer/organic-keywords). I motsetning til
    diffs.summarize_all_clusters (Rank Tracker) har ikke dette datasettet en
    position_prev fra Ahrefs å regne delta mot — uke-over-uke-trend bygges i stedet opp
    fra egen historikk i organic_footprint_weekly (se storage.get_organic_footprint_trend)."""
    result = []
    for name in cluster_names:
        rows = [r for r in tagged_rows if name in r.get("clusters", [])]
        positions = [r["best_position"] for r in rows if r.get("best_position") is not None]
        result.append(
            {
                "name": name,
                "keyword_count": len(rows),
                "avg_position": round(sum(positions) / len(positions), 2) if positions else None,
            }
        )
    return result
