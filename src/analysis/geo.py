"""GEO-signaler: ai_overview i SERP per søkeord, share-of-voice og omtaler fra Brand Radar."""
from __future__ import annotations

AI_OVERVIEW_FEATURES = {"ai_overview", "ai_overview_sitelink", "ai_overview_found"}


def keywords_with_ai_overview(tagged_rows: list[dict]) -> list[dict]:
    result = []
    for row in tagged_rows:
        features = set(row.get("serp_features") or [])
        hits = features & AI_OVERVIEW_FEATURES
        if hits:
            result.append(
                {
                    "keyword": row.get("keyword"),
                    "clusters": row.get("clusters", []),
                    "serp_features": sorted(hits),
                }
            )
    return result


def summarize_share_of_voice(sov_rows: list[dict]) -> dict[str, float]:
    return {r["brand"]: r.get("share_of_voice", 0.0) for r in sov_rows}


def summarize_mentions(mentions_rows: list[dict]) -> dict[str, dict]:
    return {r["brand"]: r for r in mentions_rows}
