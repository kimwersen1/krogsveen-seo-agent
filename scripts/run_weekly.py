#!/usr/bin/env python3
"""CLI-entrypoint for ukesjobben.

Bruk:
    python scripts/run_weekly.py            # kjører hele pipelinen og laster opp til Drive
    python scripts/run_weekly.py --dry-run  # skriver rapporten lokalt i stedet for å laste opp

    # med søkeord-/side-nivå GSC-data (eksportert manuelt fra
    # search.google.com/search-console -> Performance -> Export -> Download CSV):
    python scripts/run_weekly.py --gsc-query-export data/Queries.csv --gsc-page-export data/Pages.csv
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import run_pipeline  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Kjør ukentlig SEO/GEO-rapport for krogsveen.no")
    parser.add_argument("--dry-run", action="store_true", help="Skriv rapporten lokalt i stedet for å laste opp til Drive")
    parser.add_argument("--gsc-query-export", type=Path, help="CSV eksportert fra GSC Performance-rapporten (søkeord)")
    parser.add_argument("--gsc-page-export", type=Path, help="CSV eksportert fra GSC Performance-rapporten (sider)")
    args = parser.parse_args()

    result = run_pipeline(
        dry_run=args.dry_run,
        gsc_query_export=args.gsc_query_export,
        gsc_page_export=args.gsc_page_export,
    )

    if args.dry_run:
        out_dir = Path(__file__).resolve().parent.parent / "data"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"rapport-{date.today().isoformat()}.md"
        out_path.write_text(result["report_markdown"], encoding="utf-8")
        print(f"Dry-run fullført. Rapport skrevet til {out_path}")
    else:
        print(f"Rapport lastet opp: {result['report_url']}")
        print(f"Dashboard (lokal fil): {result['dashboard_path']}")
        print(f"Dashboard (Google Sheet): {result['sheet_url'] or 'ikke oppdatert — se logg'}")


if __name__ == "__main__":
    main()
