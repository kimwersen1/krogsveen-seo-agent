"""Orkestrerer hele ukesjobben: collect -> store -> analyze -> generate -> upload."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

from googleapiclient.errors import HttpError

from src.analysis import clusters as cluster_analysis
from src.analysis import diffs as diff_analysis
from src.analysis import geo as geo_analysis
from src.analysis import tiltak as tiltak_analysis
from src.collectors import ahrefs, claude_geo, gsc, storage
from src.report.dashboard import build_dashboard_payload, build_sheet_payload, render_dashboard
from src.report.drive_writer import prepend_report_section, report_title
from src.report.generate import generate_report
from src.report.sheets_writer import DashboardSheetNotFound, update_dashboard_sheet
from src.settings import Settings, load_settings

logger = logging.getLogger(__name__)

# Bruker hele konkurrentlisten fra config.json (var tidligere begrenset til 3 av
# kostnadshensyn — domain-rating/site-metrics er billige nok flate kall til at alle
# 8 er trygt innenfor ukentlig budsjett, se usage_over_budget-sjekken under).
DASHBOARD_COMPETITORS_FALLBACK = ["hjemla.no", "dnbeiendom.no", "eiendomsmegler1.no"]


def _date_windows(today: date) -> dict:
    ahrefs_date = today - timedelta(days=1)
    ahrefs_date_compared = ahrefs_date - timedelta(days=7)
    week_end = ahrefs_date
    week_start = week_end - timedelta(days=6)
    prev_week_end = week_start - timedelta(days=1)
    prev_week_start = prev_week_end - timedelta(days=6)
    return {
        "ahrefs_date": ahrefs_date,
        "ahrefs_date_compared": ahrefs_date_compared,
        "week_start": week_start,
        "week_end": week_end,
        "prev_week_start": prev_week_start,
        "prev_week_end": prev_week_end,
    }


def _gsc_by_keyword_from_export(query_rows: list[dict]) -> dict[str, dict]:
    """Bygger {søkeord (lowercase): {"clicks": ...}} fra én CSV-eksport.

    CSV-eksporten gir kun én periode om gangen (ikke uke-mot-uke), så 'clicks_prev'
    fylles først når to påfølgende ukers eksporter er importert (se get_history).
    """
    return {r["query"].strip().lower(): {"clicks": r["clicks"]} for r in query_rows if r.get("query")}


def run_pipeline(
    dry_run: bool = False,
    today: date | None = None,
    gsc_query_export: Path | None = None,
    gsc_page_export: Path | None = None,
) -> dict:
    settings = load_settings()
    today = today or date.today()
    windows = _date_windows(today)
    week_start_label = windows["week_start"].isoformat()

    data_gaps: list[str] = []

    usage = ahrefs.get_subscription_usage(settings)
    over_budget = ahrefs.usage_over_budget(usage)
    if over_budget:
        used = usage.get("units_usage_api_key") or usage.get("units_usage_workspace")
        limit = usage.get("units_limit_api_key") or usage.get("units_limit_workspace")
        data_gaps.append(
            f"Ahrefs-kvote >80% brukt ({used}/{limit} enheter) "
            "— enhets-kostende kall (domain rating, metrics, brand radar) ble hoppet over denne uken."
        )

    rank_desktop = ahrefs.get_rank_tracker_overview(
        settings, windows["ahrefs_date"].isoformat(), windows["ahrefs_date_compared"].isoformat(), device="desktop"
    )
    rank_mobile = ahrefs.get_rank_tracker_overview(
        settings, windows["ahrefs_date"].isoformat(), windows["ahrefs_date_compared"].isoformat(), device="mobile"
    )

    domain_rating, site_metrics, brand_mentions, brand_sov, cited_pages = None, None, [], [], []
    competitor_benchmark: list[dict] = []
    if not over_budget:
        domain_rating = ahrefs.get_domain_rating(settings, windows["ahrefs_date"].isoformat())
        site_metrics = ahrefs.get_site_metrics(settings, windows["ahrefs_date"].isoformat())
        brand_mentions = ahrefs.get_brand_radar_mentions(settings)
        brand_sov = ahrefs.get_brand_radar_sov(settings)
        cited_pages = ahrefs.get_brand_radar_cited_pages(settings)
        if not brand_mentions:
            data_gaps.append("Brand Radar: tomt svar — prompts er trolig ikke konfigurert i Ahrefs UI ennå.")

        for competitor in (settings.competitors or DASHBOARD_COMPETITORS_FALLBACK):
            comp_dr = ahrefs.get_domain_rating(settings, windows["ahrefs_date"].isoformat(), target=competitor)
            comp_metrics = ahrefs.get_site_metrics(settings, windows["ahrefs_date"].isoformat(), target=competitor)
            competitor_benchmark.append(
                {
                    "domain": competitor,
                    "domain_rating": comp_dr.get("domain_rating"),
                    "org_traffic": comp_metrics.get("org_traffic"),
                }
            )

    # GSC-data hos Ahrefs kan ha noen dagers etterslep fra Google — spør om et vindu
    # som slutter noen dager tilbake i tid i stedet for i går, og degrader til en
    # notert datamangel (ikke krasj) hvis selv det mangler denne uken.
    gsc_available_end = min(windows["week_end"], today - timedelta(days=3))
    try:
        gsc_site_history = ahrefs.get_gsc_performance_history(
            settings, windows["prev_week_start"].isoformat(), gsc_available_end.isoformat()
        )
        gsc_site_by_device = ahrefs.get_gsc_performance_by_device(
            settings, windows["week_start"].isoformat(), gsc_available_end.isoformat()
        )
    except ahrefs.AhrefsError as e:
        logger.warning("GSC-data (via Ahrefs) ikke tilgjengelig denne uken: %s", e)
        data_gaps.append("GSC-data (via Ahrefs) var ikke tilgjengelig for perioden denne uken — trolig etterslep hos Google/Ahrefs.")
        gsc_site_history, gsc_site_by_device = [], []
    gsc_site_rows = list(gsc_site_by_device)
    if gsc_site_history:
        latest = gsc_site_history[-1]
        gsc_site_rows.append(
            {
                "device": "all",
                "clicks": latest.get("clicks"),
                "impressions": latest.get("impressions"),
                "ctr": latest.get("ctr"),
                "position": latest.get("position"),
            }
        )

    gsc_query_rows = gsc.import_gsc_export(gsc_query_export, "query") if gsc_query_export else []
    gsc_page_rows = gsc.import_gsc_export(gsc_page_export, "page") if gsc_page_export else []
    gsc_by_keyword = _gsc_by_keyword_from_export(gsc_query_rows)
    if not gsc_query_export:
        data_gaps.append(
            "Ingen GSC-eksport oppgitt — klikk/CTR per søkeord mangler (kun posisjonsavvik fanges opp denne uken). "
            "Se scripts/run_weekly.py --gsc-query-export."
        )

    conn = storage.get_connection()
    storage.save_rank_tracker_rows(conn, week_start_label, "desktop", rank_desktop)
    storage.save_rank_tracker_rows(conn, week_start_label, "mobile", rank_mobile)
    storage.save_gsc_site_rows(conn, week_start_label, gsc_site_rows)
    if gsc_query_rows:
        storage.save_gsc_rows(conn, week_start_label, "query", gsc_query_rows)
        prev_rows = conn.execute(
            "SELECT key, clicks FROM gsc_weekly WHERE week_start = ? AND dimension = 'query'",
            (windows["prev_week_start"].isoformat(),),
        ).fetchall()
        prev_by_query = {key.strip().lower(): clicks for key, clicks in prev_rows}
        for keyword, entry in gsc_by_keyword.items():
            entry["clicks_prev"] = prev_by_query.get(keyword, 0)
    if gsc_page_rows:
        storage.save_gsc_rows(conn, week_start_label, "page", gsc_page_rows)
    if brand_mentions:
        merged_brand_rows = {r["brand"]: dict(r) for r in brand_mentions}
        for r in brand_sov:
            merged_brand_rows.setdefault(r["brand"], {"brand": r["brand"]})
            merged_brand_rows[r["brand"]]["share_of_voice"] = r.get("share_of_voice")
        storage.save_brand_radar_rows(conn, week_start_label, list(merged_brand_rows.values()))

    geo_selfcheck = claude_geo.check_geo_visibility(settings)
    storage.save_geo_selfcheck_rows(conn, week_start_label, geo_selfcheck)

    tagged_desktop = cluster_analysis.tag_rows(rank_desktop, settings.clusters)
    cluster_summaries = diff_analysis.summarize_all_clusters(tagged_desktop, list(settings.clusters.keys()))
    anomalies = diff_analysis.detect_anomalies(
        tagged_desktop, gsc_by_keyword, settings.posisjon_terskel, settings.klikk_terskel_pct
    )
    ai_overview_keywords = geo_analysis.keywords_with_ai_overview(tagged_desktop)
    sov_summary = geo_analysis.summarize_share_of_voice(brand_sov)
    mentions_summary = geo_analysis.summarize_mentions(brand_mentions)

    history_rows = storage.get_history(conn, "rank_tracker_weekly", weeks=8)
    tiltak_status = tiltak_analysis.classify_all(settings.tiltak, history_rows, today)

    position_trend = storage.get_position_trend(conn, weeks=12)
    clicks_trend = storage.get_clicks_trend(conn, weeks=12)

    conn.close()

    analysis = {
        "uke": today.isocalendar()[1],
        "ar": today.year,
        "periode": {"fra": week_start_label, "til": windows["week_end"].isoformat()},
        "domain_rating": domain_rating,
        "site_metrics": site_metrics,
        "gsc_site": gsc_site_rows,
        "cluster_summaries": [vars(c) for c in cluster_summaries],
        "avvik": anomalies,
        "geo": {
            "ai_overview_sokeord": ai_overview_keywords,
            "brand_radar_share_of_voice": sov_summary,
            "brand_radar_omtaler": mentions_summary,
            "brand_radar_siterte_sider": cited_pages,
            "claude_selvsjekk": geo_selfcheck,
        },
        "tiltak": tiltak_status,
        "konkurrenter": settings.competitors,
        "datamangler": data_gaps,
    }

    dashboard_payload = build_dashboard_payload(analysis, position_trend, clicks_trend, competitor_benchmark, today)
    dashboard_path = render_dashboard(dashboard_payload)

    report_markdown = generate_report(settings, analysis)
    title = report_title(today)

    result = {
        "analysis": analysis,
        "report_markdown": report_markdown,
        "title": title,
        "report_url": None,
        "dashboard_path": str(dashboard_path),
        "sheet_url": None,
    }

    if dry_run:
        logger.info("Dry-run: laster ikke opp til Drive.")
    else:
        result["report_url"] = prepend_report_section(settings, title, report_markdown)
        try:
            sheet_payload = build_sheet_payload(dashboard_payload)
            result["sheet_url"] = update_dashboard_sheet(settings, sheet_payload)
        except (DashboardSheetNotFound, HttpError) as e:
            # Rapporten til Drive-dokumentet er allerede lagret på dette tidspunktet —
            # en feil her (manglende ark, API ikke aktivert, forbigående Google-feil)
            # skal aldri få hele kjøringen til å se ut som en fiasko i loggen/exit-koden.
            logger.warning("Dashboard-arket kunne ikke oppdateres denne uken: %s", e)
            data_gaps.append(f"Dashboard-ark (Google Sheets) ble ikke oppdatert denne uken: {e}")

    return result
