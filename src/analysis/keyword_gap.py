"""Finner søkeord Krogsveen ikke sporer i dag, men som bør vurderes lagt til.

To kilder til blindsoner i det som kun er basert på de 338 sporede Rank Tracker-ordene:
1. Krogsveen rangerer allerede på ordet (noen andre har skrevet innhold som treffer),
   men det er ikke lagt til i Rank Tracker — vi ser det ikke i ukesrapporten.
2. En konkurrent rangerer godt på et relevant ord, Krogsveen har ingen synlighet
   der i det hele tatt — et reelt innholdshull.
"""
from __future__ import annotations

from src.analysis.clusters import tag_keyword

# Konkurrenters egne merkenavn/navigasjonssøk — aldri reelle innholdshull, bare støy.
# Manuelt vedlikeholdt: legg til her hvis flere dukker opp i fremtidige kjøringer.
COMPETITOR_BRAND_TOKENS = {
    "hjemla",
    "dnb",
    "eiendomsmegler 1",
    "eiendomsmegler1",
    "privatmegleren",
    "nordvikbolig",
    "nordvik",
    "bolig.ai",
    "meglersmart",
}


def _is_brand_noise(keyword: str) -> bool:
    lowered = keyword.lower()
    return any(token in lowered for token in COMPETITOR_BRAND_TOKENS)


def find_untracked_ranking_keywords(
    organic_keywords: list[dict], tracked_keywords: set[str], clusters: dict
) -> list[dict]:
    """Søkeord Krogsveen allerede rangerer på (Site Explorer), som matcher et cluster,
    men som ikke står i Rank Tracker sin liste over sporede ord."""
    tracked_lower = {k.strip().lower() for k in tracked_keywords}
    result = []
    for row in organic_keywords:
        keyword = (row.get("keyword") or "").strip()
        if not keyword or keyword.lower() in tracked_lower:
            continue
        matched = tag_keyword(keyword, clusters)
        if matched:
            result.append({**row, "clusters": matched})
    return sorted(result, key=lambda r: r.get("best_position") if r.get("best_position") is not None else 999)


def find_competitor_gap_keywords(
    competitor_keywords: list[dict],
    krogsveen_positions: dict[str, int | None],
    clusters: dict,
    min_volume: int = 200,
) -> list[dict]:
    """Søkeord en konkurrent rangerer godt på (topp 10) som Krogsveen enten ikke
    rangerer på i det hele tatt, eller kun rangerer svakt på (>50).

    krogsveen_positions: {søkeord (lowercase): best_position eller None hvis ingen rangering}
    (fra get_organic_keywords_for_list mot krogsveen.no for samme søkeordsliste).
    """
    result = []
    for row in competitor_keywords:
        keyword = (row.get("keyword") or "").strip()
        if not keyword or (row.get("volume") or 0) < min_volume:
            continue
        if _is_brand_noise(keyword):
            continue
        krogsveen_position = krogsveen_positions.get(keyword.lower())
        if krogsveen_position is not None and krogsveen_position <= 50:
            continue  # Krogsveen har allerede rimelig synlighet — ikke et reelt hull
        matched = tag_keyword(keyword, clusters)
        result.append(
            {
                **row,
                "clusters": matched,
                "krogsveen_position": krogsveen_position,
            }
        )
    return sorted(result, key=lambda r: r.get("volume") or 0, reverse=True)
