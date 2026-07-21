#!/usr/bin/env python3
"""Søkeordsoppdagelse utenfor de 338 sporede ordene i Rank Tracker.

Tre ting sjekkes:
  1. Søkeord Krogsveen allerede rangerer på, men ikke sporer (bør legges til Rank Tracker).
  2. Søkeord konkurrenter rangerer godt på som Krogsveen ikke har synlighet på (innholdshull).
  3. Ved --to-drive: Claude foreslår 2-3 grundige artikkelforslag (SEO + GEO) basert på 1+2
     (src/report/content_suggestions.py), skrevet til et EGET Google Doc («Krogsveen SEO –
     Innholdsforslag», overskrevet hver gang — ikke en punktliste i det løpende
     rapport-dokumentet, brukeren fant det uoversiktlig 21.07.2026) — ikke kjørt ved
     konsoll-only-kjøring, siden det koster en ekstra Anthropic-samtale uten at noen leser
     resultatet.

KOSTNAD: en full kjøring med alle 8 konkurrenter fra config.json (standard) bruker typisk
12 000–16 000 Ahrefs-enheter (se subscription-info før/etter i output) — fortsatt under
20 % av den månedlige kvoten på 100 000. Dette er IKKE del av den ukentlige pipelinen —
kjør manuelt eller via .github/workflows/keyword-discovery.yml, anbefalt månedlig, ikke oftere.

VIKTIG BEGRENSNING: Ahrefs API har ingen endepunkt for å legge søkeord til i Rank Tracker
(kun lesbar management-project-keywords). Denne jobben kan aldri gjøre siste steg selv —
den leverer en ferdig liste du limer inn i Ahrefs UI selv (Rank Tracker → prosjektet → Add
keywords).

Bruk:
    python scripts/keyword_discovery.py                    # skriver kun til konsoll
    python scripts/keyword_discovery.py --to-drive          # skriver også inn i det løpende Drive-dokumentet
    python scripts/keyword_discovery.py --competitors hjemla.no dnbeiendom.no eiendomsmegler1.no
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis.keyword_gap import find_competitor_gap_keywords, find_untracked_ranking_keywords  # noqa: E402
from src.collectors import ahrefs, storage  # noqa: E402
from src.report.content_suggestions import format_content_briefs_markdown, generate_content_briefs  # noqa: E402
from src.report.drive_writer import prepend_report_section, replace_content_briefs_doc  # noqa: E402
from src.settings import load_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_COMPETITORS_FALLBACK = ["hjemla.no", "dnbeiendom.no", "eiendomsmegler1.no"]


def run_discovery(settings, competitors: list[str], min_volume: int) -> dict:
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    tracked = ahrefs.get_rank_tracker_overview(settings, yesterday, yesterday, device="desktop")
    tracked_keywords = {r["keyword"] for r in tracked if r.get("keyword")}

    krogsveen_broad = ahrefs.get_organic_keywords(
        settings, "krogsveen.no", yesterday, position_max=30, with_metrics=False
    )
    untracked = find_untracked_ranking_keywords(krogsveen_broad, tracked_keywords, settings.clusters)

    if untracked:
        shortlist = [r["keyword"] for r in untracked[:40]]
        with_volume = ahrefs.get_organic_keywords_for_list(
            settings, "krogsveen.no", yesterday, shortlist, with_metrics=True
        )
        volume_by_keyword = {r["keyword"].lower(): r.get("volume") for r in with_volume}
        for row in untracked:
            row["volume"] = volume_by_keyword.get(row["keyword"].lower())

    all_competitor_rows: list[dict] = []
    for competitor in competitors:
        rows = ahrefs.get_organic_keywords(
            settings, competitor, yesterday, position_max=10, with_metrics=True, limit=50
        )
        for r in rows:
            r["_competitor"] = competitor
        all_competitor_rows.extend(rows)

    candidate_keywords = list({r["keyword"] for r in all_competitor_rows if r.get("keyword")})
    krogsveen_lookup = ahrefs.get_organic_keywords_for_list(
        settings, "krogsveen.no", yesterday, candidate_keywords, with_metrics=False
    )
    krogsveen_positions = {r["keyword"].lower(): r.get("best_position") for r in krogsveen_lookup}
    for kw in candidate_keywords:
        krogsveen_positions.setdefault(kw.lower(), None)

    gaps = find_competitor_gap_keywords(all_competitor_rows, krogsveen_positions, settings.clusters, min_volume)

    return {"untracked": untracked, "gaps": gaps, "competitors": competitors}


def format_console(result: dict) -> None:
    print(f"\n=== 1. Søkeord Krogsveen allerede rangerer på, men ikke sporer ===")
    print(f"{len(result['untracked'])} cluster-relevante søkeord:")
    for row in result["untracked"]:
        vol = row.get("volume")
        print(f"  pos {row.get('best_position'):>3}  vol {vol or '?':>6}  {row['keyword']}  [{', '.join(row['clusters'])}]")

    print(f"\n=== 2. Innholdshull mot konkurrenter: {', '.join(result['competitors'])} ===")
    print(f"{len(result['gaps'])} søkeord der Krogsveen mangler synlighet:")
    for row in result["gaps"][:40]:
        clusters_label = ", ".join(row["clusters"]) if row["clusters"] else "utenfor definerte clustre"
        print(
            f"  vol {row.get('volume'):>6}  {row['_competitor']:<20} pos {row.get('best_position'):>3}  "
            f"krogsveen: {row['krogsveen_position'] or 'ingen rangering':<16}  {row['keyword']}  [{clusters_label}]"
        )


def format_markdown(result: dict, briefs_doc_url: str | None = None) -> str:
    lines = [
        "## Søkeord Krogsveen allerede rangerer på, men ikke sporer",
        "Kandidater for å legges til manuelt i Ahrefs Rank Tracker "
        "(prosjektet → Add keywords — dette kan ikke gjøres via API).",
        "",
    ]
    if not result["untracked"]:
        lines.append("- Ingen nye kandidater denne runden.")
    for row in result["untracked"][:30]:
        vol = row.get("volume")
        lines.append(f"- **{row['keyword']}** (pos {row.get('best_position')}, vol {vol or 'ukjent'}) — {', '.join(row['clusters'])}")

    lines += [
        "",
        f"## Innholdshull mot konkurrenter ({', '.join(result['competitors'])})",
        "Søkeord konkurrenter rangerer godt på (topp 10) som Krogsveen ikke er synlig på. "
        "Vurder som innholds-/landingsside-kandidater, ikke bare Rank Tracker-tillegg.",
        "",
    ]
    if not result["gaps"]:
        lines.append("- Ingen tydelige hull denne runden.")
    for row in result["gaps"][:30]:
        clusters_label = ", ".join(row["clusters"]) if row["clusters"] else "utenfor definerte clustre"
        lines.append(
            f"- **{row['keyword']}** (vol {row.get('volume')}, {row['_competitor']} pos {row.get('best_position')}, "
            f"Krogsveen: {row['krogsveen_position'] or 'ingen rangering'}) — {clusters_label}"
        )

    if briefs_doc_url:
        lines += [
            "",
            "## Innholdsforslag",
            f"2-3 grundige artikkelforslag (SEO + GEO) er skrevet til et eget dokument: {briefs_doc_url}",
        ]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Søkeordsoppdagelse utenfor Rank Tracker-listen")
    parser.add_argument(
        "--competitors", nargs="+", default=None, help="Standard: alle konkurrenter fra config.json (8 stk)"
    )
    parser.add_argument("--min-volume", type=int, default=200, help="Minimum søkevolum for konkurrent-hull")
    parser.add_argument("--to-drive", action="store_true", help="Skriv funnene inn i det løpende Drive-dokumentet")
    args = parser.parse_args()

    settings = load_settings()
    competitors = args.competitors or settings.competitors or DEFAULT_COMPETITORS_FALLBACK
    usage_before = ahrefs.get_subscription_usage(settings)
    used_before = usage_before.get("units_usage_api_key") or usage_before.get("units_usage_workspace", 0)
    print(f"Enheter brukt før kjøring: {used_before}")
    print(f"Konkurrenter denne kjøringen: {', '.join(competitors)}")

    result = run_discovery(settings, competitors, args.min_volume)
    format_console(result)

    usage_after = ahrefs.get_subscription_usage(settings)
    used_after = usage_after.get("units_usage_api_key") or usage_after.get("units_usage_workspace", 0)
    print(f"\nEnheter brukt i denne kjøringen: ~{used_after - used_before}")

    if args.to_drive:
        print("\nBer Claude om 2-3 grundige innholdsforslag (SEO + GEO) basert på gap-listen...")
        briefs = generate_content_briefs(settings, result["untracked"], result["gaps"])
        briefs_doc_url = None
        if briefs:
            today_label = date.today().isoformat()
            briefs_markdown = format_content_briefs_markdown(briefs, today_label)
            briefs_doc_url = replace_content_briefs_doc(settings, briefs_markdown)
            conn = storage.get_connection()
            storage.save_content_briefs_meta(conn, briefs_doc_url, today_label, len(briefs))
            conn.close()
            print(f"Innholdsforslag skrevet til: {briefs_doc_url}")

        title = f"Søkeordsoppdagelse – {date.today().strftime('%B %Y')}"
        url = prepend_report_section(settings, title, format_markdown(result, briefs_doc_url))
        print(f"\nSkrevet til Drive-dokument: {url}")


if __name__ == "__main__":
    main()
