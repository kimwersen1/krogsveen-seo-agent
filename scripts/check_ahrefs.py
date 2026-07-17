#!/usr/bin/env python3
"""Smoke-test av Ahrefs-halvparten av pipelinen, uten Google-oppsett.

Verifiserer at AHREFS_API_KEY fungerer, henter rank-tracker-data, og kjører
cluster-tagging/oppsummering på ekte data. Rører ikke GSC, Drive eller Anthropic.

Bruk: python scripts/check_ahrefs.py
"""
from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis import clusters as cluster_analysis  # noqa: E402
from src.analysis import diffs as diff_analysis  # noqa: E402
from src.analysis import geo as geo_analysis  # noqa: E402
from src.collectors import ahrefs  # noqa: E402
from src.settings import load_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    settings = load_settings()

    print("\n=== Ahrefs-kvote ===")
    usage = ahrefs.get_subscription_usage(settings)
    print(usage)
    if ahrefs.usage_over_budget(usage):
        print("ADVARSEL: >80% av kvoten er brukt.")

    ahrefs_date = date.today() - timedelta(days=1)
    ahrefs_date_compared = ahrefs_date - timedelta(days=7)

    print(f"\n=== rank-tracker/overview (desktop), {ahrefs_date_compared} -> {ahrefs_date} ===")
    rank_desktop = ahrefs.get_rank_tracker_overview(
        settings, ahrefs_date.isoformat(), ahrefs_date_compared.isoformat(), device="desktop"
    )
    print(f"{len(rank_desktop)} rader hentet. Eksempel:")
    for row in rank_desktop[:5]:
        print(" ", row)

    print("\n=== rank-tracker/overview (mobile) ===")
    rank_mobile = ahrefs.get_rank_tracker_overview(
        settings, ahrefs_date.isoformat(), ahrefs_date_compared.isoformat(), device="mobile"
    )
    print(f"{len(rank_mobile)} rader hentet.")

    print("\n=== Cluster-tagging (desktop) ===")
    tagged = cluster_analysis.tag_rows(rank_desktop, settings.clusters)
    untagged = [r for r in tagged if not r["clusters"]]
    print(f"{len(tagged) - len(untagged)} av {len(tagged)} søkeord matchet minst ett cluster.")

    summaries = diff_analysis.summarize_all_clusters(tagged, list(settings.clusters.keys()))
    for s in summaries:
        print(
            f"  {s.name}: {s.keyword_count} ord, snittdelta {s.avg_position_delta:.1f}, "
            f"opp {s.improved} / ned {s.declined} / uendret {s.unchanged}"
        )

    print("\n=== Søkeord med AI Overview i SERP ===")
    ai_kw = geo_analysis.keywords_with_ai_overview(tagged)
    print(f"{len(ai_kw)} søkeord")
    for kw in ai_kw[:10]:
        print(" ", kw)

    print("\nFerdig. Ahrefs-nøkkelen og cluster-analysen fungerer.")


if __name__ == "__main__":
    main()
