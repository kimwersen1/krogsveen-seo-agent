"""Tagger søkeord mot cluster-definisjonene i clusters.json (regex, case-insensitive)."""
from __future__ import annotations

import re


def tag_keyword(keyword: str, clusters: dict[str, str]) -> list[str]:
    return [name for name, pattern in clusters.items() if re.search(pattern, keyword or "", re.IGNORECASE)]


def tag_rows(rows: list[dict], clusters: dict[str, str]) -> list[dict]:
    """Legger til 'clusters'-nøkkel på hver rad. Et søkeord kan havne i 0, 1 eller flere clustre."""
    return [{**row, "clusters": tag_keyword(row.get("keyword", ""), clusters)} for row in rows]
