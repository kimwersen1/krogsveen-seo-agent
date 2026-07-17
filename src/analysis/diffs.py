"""Uke-mot-uke delta per cluster + avviksdeteksjon (>3 posisjoner / >20 % klikk)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ClusterSummary:
    name: str
    keyword_count: int
    avg_position_delta: float
    improved: int
    declined: int
    unchanged: int
    top_gainers: list[dict]
    top_losers: list[dict]


def _position_delta(row: dict) -> int | None:
    """Positivt tall = forbedring (lavere posisjon er bedre)."""
    pos, prev = row.get("position"), row.get("position_prev")
    if pos is None or prev is None:
        return None
    return prev - pos


def summarize_cluster(name: str, rows: list[dict], top_n: int = 3) -> ClusterSummary:
    with_delta = [(r, _position_delta(r)) for r in rows]
    with_delta = [(r, d) for r, d in with_delta if d is not None]
    deltas = [d for _, d in with_delta]

    ranked = sorted(with_delta, key=lambda x: x[1], reverse=True)
    top_gainers = [r for r, d in ranked[:top_n] if d > 0]
    top_losers = [r for r, d in reversed(ranked[-top_n:]) if d < 0] if ranked else []

    return ClusterSummary(
        name=name,
        keyword_count=len(rows),
        avg_position_delta=sum(deltas) / len(deltas) if deltas else 0.0,
        improved=sum(1 for d in deltas if d > 0),
        declined=sum(1 for d in deltas if d < 0),
        unchanged=sum(1 for d in deltas if d == 0),
        top_gainers=top_gainers,
        top_losers=top_losers,
    )


def summarize_all_clusters(tagged_rows: list[dict], cluster_names: list[str]) -> list[ClusterSummary]:
    summaries = []
    for name in cluster_names:
        rows = [r for r in tagged_rows if name in r.get("clusters", [])]
        if rows:
            summaries.append(summarize_cluster(name, rows))
    return summaries


def detect_anomalies(
    tagged_rows: list[dict],
    gsc_by_keyword: dict[str, dict],
    position_threshold: int,
    click_pct_threshold: float,
) -> list[dict]:
    """gsc_by_keyword: {søkeord (lowercase): {"clicks": int, "clicks_prev": int}}."""
    anomalies = []
    for row in tagged_rows:
        keyword = row.get("keyword", "")
        delta = _position_delta(row)
        if delta is not None and abs(delta) > position_threshold:
            anomalies.append(
                {
                    "type": "posisjon",
                    "keyword": keyword,
                    "delta": delta,
                    "position": row.get("position"),
                    "position_prev": row.get("position_prev"),
                }
            )
        gsc = gsc_by_keyword.get(keyword.strip().lower())
        if gsc and gsc.get("clicks_prev"):
            pct = (gsc["clicks"] - gsc["clicks_prev"]) / gsc["clicks_prev"] * 100
            if abs(pct) > click_pct_threshold:
                anomalies.append(
                    {
                        "type": "klikk",
                        "keyword": keyword,
                        "pct_change": round(pct, 1),
                        "clicks": gsc["clicks"],
                        "clicks_prev": gsc["clicks_prev"],
                    }
                )
    return anomalies
