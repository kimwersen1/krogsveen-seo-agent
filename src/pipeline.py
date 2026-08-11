"""Orkestrerer hele ukesjobben: collect -> store -> analyze -> generate -> upload."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import anthropic
import openai
from google.genai.errors import APIError as GeminiAPIError
from googleapiclient.errors import HttpError

from src.analysis import clusters as cluster_analysis
from src.analysis import diffs as diff_analysis
from src.analysis import geo as geo_analysis
from src.analysis import tiltak as tiltak_analysis
from src.collectors import ahrefs, chatgpt_geo, claude_geo, ga4_oauth, gemini_geo, gsc, gsc_oauth, perplexity_geo, storage
from src.report.dashboard import build_dashboard_payload, build_sheet_payload, render_dashboard
from src.report.drive_writer import prepend_report_section, report_title
from src.report.email_sender import send_weekly_report_email
from src.report.generate import extract_hovedbildet, extract_recommendations, generate_report
from src.report.sheets_writer import DashboardSheetNotFound, update_dashboard_sheet, write_query_export
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
            "— enhets-kostende kall (domain rating, metrics) ble hoppet over denne uken."
        )

    rank_desktop = ahrefs.get_rank_tracker_overview(
        settings, windows["ahrefs_date"].isoformat(), windows["ahrefs_date_compared"].isoformat(), device="desktop"
    )
    rank_mobile = ahrefs.get_rank_tracker_overview(
        settings, windows["ahrefs_date"].isoformat(), windows["ahrefs_date_compared"].isoformat(), device="mobile"
    )

    domain_rating, site_metrics, ai_responses_count = None, None, None
    competitor_benchmark: list[dict] = []
    footprint_rows: list[dict] = []
    if not over_budget:
        domain_rating = ahrefs.get_domain_rating(settings, windows["ahrefs_date"].isoformat())
        site_metrics = ahrefs.get_site_metrics(settings, windows["ahrefs_date"].isoformat())
        # Domenevidt antall AI-siteringer av Krogsveen (Ahrefs' nye ai-responses-count-
        # endepunkt, 10.08.2026) — dekker HELE domenet, ikke bare de 338 sporede Rank
        # Tracker-ordene som geo_analysis.keywords_with_ai_overview() under er begrenset
        # til. Bruker etterspurte dette selv etter å ha sammenlignet mot Ahrefs' eget UI.
        ai_responses_count = ahrefs.get_ai_responses_count(settings, windows["ahrefs_date"].isoformat())

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

        # Bredere søkeordsdekning enn de 338 manuelt sporede Rank Tracker-ordene — billig
        # (with_metrics=False, ~2 enheter/rad) bredde-kartlegging, se ahrefs.py for detaljer.
        footprint_rows = ahrefs.get_organic_keywords_paginated(settings, "krogsveen.no", windows["ahrefs_date"].isoformat())

    # GSC-data kan ha noen dagers etterslep fra Google — spør om et vindu som slutter
    # noen dager tilbake i tid i stedet for i går.
    gsc_available_end = min(windows["week_end"], today - timedelta(days=3))

    gsc_source = "ingen"
    gsc_site_rows: list[dict] = []
    if settings.gsc_oauth_configured:
        # Direkte tilgang via brukerens egen Google-konto — se src/collectors/gsc_oauth.py
        # for hvorfor dette virker uten admin-tilgang. Dekker nå også site-wide-tallene
        # (gsc_site_rows), ikke bare per-søkeord/per-side — Ahrefs sin egen, separate
        # GSC-integrasjon (tidligere eneste kilde for site-wide-tallene) hadde
        # etterslep-problemer uavhengig av at OAuth-tilkoblingen fungerte fint
        # (28.07.2026: "GSC-data via Ahrefs ikke tilgjengelig" samme uke som OAuth-dataen
        # under fungerte helt fint) — ingen grunn til en ekstra, mindre pålitelig
        # mellomting når den direkte kilden allerede er konfigurert.
        try:
            gsc_query_rows = gsc_oauth.get_query_performance(
                settings, windows["week_start"].isoformat(), gsc_available_end.isoformat()
            )
            gsc_page_rows = gsc_oauth.get_page_performance(
                settings, windows["week_start"].isoformat(), gsc_available_end.isoformat()
            )
            gsc_site_rows = gsc_oauth.get_site_performance(
                settings, windows["week_start"].isoformat(), gsc_available_end.isoformat()
            )
            gsc_source = "oauth"
        except HttpError as e:
            logger.warning("GSC OAuth-henting feilet denne uken: %s", e)
            data_gaps.append(f"GSC OAuth-henting feilet denne uken ({e}) — klikk/CTR per søkeord og site-wide-tall mangler.")
            gsc_query_rows, gsc_page_rows = [], []
    elif gsc_query_export or gsc_page_export:
        gsc_query_rows = gsc.import_gsc_export(gsc_query_export, "query") if gsc_query_export else []
        gsc_page_rows = gsc.import_gsc_export(gsc_page_export, "page") if gsc_page_export else []
        gsc_source = "csv"
    else:
        gsc_query_rows, gsc_page_rows = [], []
        data_gaps.append(
            "Ingen GSC-tilgang konfigurert — klikk/CTR per søkeord mangler (kun posisjonsavvik fanges opp denne uken). "
            "Se scripts/gsc_auth_setup.py (automatisk, anbefalt) eller scripts/run_weekly.py --gsc-query-export (manuelt)."
        )
    gsc_by_keyword = _gsc_by_keyword_from_export(gsc_query_rows)

    if not gsc_site_rows:
        # Reserveløsning for site-wide-tallene: Ahrefs sin egen GSC-integrasjon, brukt
        # kun når OAuth ikke er konfigurert/feilet, eller ved CSV-import (som ikke har
        # noen site-wide-ekvivalent).
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

    # AI-referral-trafikk (sesjoner fra chatgpt.com/claude.ai/gemini.google.com/perplexity/
    # copilot.com som sessionSource i GA4) — se src/collectors/ga4_oauth.py. Gjenbruker
    # samme OAuth-refresh-token som GSC (utvidet med analytics.readonly-scope 29.07.2026).
    #
    # Kjøres over et rullerende 28-dagersvindu, IKKE ukens strenge periode (i motsetning
    # til alt annet i denne pipelinen). Grunn: dette er lavvolum (typisk noen titalls
    # økter totalt per kilde), og en streng uke-periode gir ustabile/misvisende tall —
    # verifisert 29.07.2026 mot brukerens egen Looker Studio-rapport: en enkelt økt i et
    # 7-dagersvindu ga f.eks. 100 % engasjement for claude.ai (ren tilfeldighet ved n=1),
    # mens samme kilde over 28 dager (n=4) ga et langt mer troverdig 50 %. 28 dager valgt
    # fordi det er standard Looker Studio-vindu og ga tall som stemte tett med brukerens
    # egen rapport (chatgpt.com: 243 mot Lookers 270, 5 konverteringer identisk).
    #
    # VIKTIG: dette gjør ga4_ai_referral til det eneste feltet i analysis som IKKE
    # dekker rapportens uke — periode_dager under må alltid leses med, og
    # prompt_builder.py/dashboardet må omtale det som "siste 28 dager", ikke "denne uken".
    ga4_ai_referral_rows: list[dict] = []
    if settings.ga4_configured:
        try:
            ga4_window_end = today
            ga4_window_start = ga4_window_end - timedelta(days=28)
            ga4_ai_referral_rows = ga4_oauth.get_ai_referral_sessions(
                settings, ga4_window_start.isoformat(), ga4_window_end.isoformat()
            )
        except HttpError as e:
            logger.warning("GA4 AI-referral-henting feilet denne uken: %s", e)
            data_gaps.append(f"GA4 AI-referral-henting feilet denne uken ({e}) — AI-referral-trafikk mangler.")

    conn = storage.get_connection()
    storage.save_rank_tracker_rows(conn, week_start_label, "desktop", rank_desktop)
    storage.save_rank_tracker_rows(conn, week_start_label, "mobile", rank_mobile)
    storage.save_gsc_site_rows(conn, week_start_label, gsc_site_rows)
    if ga4_ai_referral_rows:
        storage.save_ga4_ai_referral_rows(conn, week_start_label, ga4_ai_referral_rows)
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

    # Samme robusthetsmønster som ChatGPT/Gemini/Perplexity under — en Claude-selvsjekk-
    # feil (f.eks. tom kredittsaldo, se 27.07.2026-hendelsen) skal degradere til et
    # notert datahull, ikke velte HELE ukesrapporten. Rapportgenereringen lenger ned
    # bruker også Claude og vil fortsatt feile hardt hvis kontoen fortsatt er uten
    # kreditt da — det er forventet og riktig (ingen rapporttekst uten Claude), men denne
    # selvsjekken alene skal ikke være det som stopper alt tidlig i kjøringen.
    try:
        geo_selfcheck = claude_geo.check_geo_visibility(settings)
    except anthropic.APIError as exc:
        geo_selfcheck = []
        data_gaps.append(f"Claude-selvsjekk feilet ({exc}). Sjekk API-nøkkel/fakturering på console.anthropic.com.")
    else:
        if geo_selfcheck:
            storage.save_geo_selfcheck_rows(conn, week_start_label, geo_selfcheck, source="claude")

    try:
        chatgpt_selfcheck = chatgpt_geo.check_geo_visibility(settings)
    except openai.OpenAIError as exc:
        # F.eks. manglende fakturering (insufficient_quota) eller rate-limit — dette skal
        # aldri velte hele ukesrapporten, kun noteres som et datahull (se 20.07.2026-hendelsen).
        chatgpt_selfcheck = []
        data_gaps.append(f"ChatGPT-selvsjekk feilet ({exc}). Sjekk API-nøkkel/fakturering på platform.openai.com.")
    else:
        if chatgpt_selfcheck:
            storage.save_geo_selfcheck_rows(conn, week_start_label, chatgpt_selfcheck, source="chatgpt")
        elif not settings.openai_api_key:
            data_gaps.append("ChatGPT-selvsjekk hoppet over — OPENAI_API_KEY er ikke satt i .env.")

    # Gemini + Perplexity dekker to av Brand Radar sine fem datakilder direkte (Ahrefs
    # sin versjon var begrenset til 5 prompts totalt uten skriv-API for rotasjon —
    # besluttet erstattet 21.07.2026). Samme robusthetsmønster som ChatGPT over.
    try:
        gemini_selfcheck = gemini_geo.check_geo_visibility(settings)
    except GeminiAPIError as exc:
        gemini_selfcheck = []
        data_gaps.append(f"Gemini-selvsjekk feilet ({exc}). Sjekk API-nøkkel på aistudio.google.com.")
    else:
        if gemini_selfcheck:
            storage.save_geo_selfcheck_rows(conn, week_start_label, gemini_selfcheck, source="gemini")
        elif not settings.gemini_api_key:
            data_gaps.append("Gemini-selvsjekk hoppet over — GEMINI_API_KEY er ikke satt i .env.")

    try:
        perplexity_selfcheck = perplexity_geo.check_geo_visibility(settings)
    except openai.OpenAIError as exc:
        perplexity_selfcheck = []
        data_gaps.append(f"Perplexity-selvsjekk feilet ({exc}). Sjekk API-nøkkel/fakturering på perplexity.ai.")
    else:
        if perplexity_selfcheck:
            storage.save_geo_selfcheck_rows(conn, week_start_label, perplexity_selfcheck, source="perplexity")
        elif not settings.perplexity_api_key:
            data_gaps.append("Perplexity-selvsjekk hoppet over — PERPLEXITY_API_KEY er ikke satt i .env.")

    # Mobil er primærkilden for all posisjonsanalyse (cluster, avvik, tiltak, AI Overview),
    # ikke desktop — ~70 % av søkevolumet er mobil, og desktop har mange null-posisjoner
    # (kjent forhold, se CLAUDE.md). Tidligere brukte hele analysen desktop, som ga en
    # skjev/noen ganger motsatt konklusjon av mobil for samme søkeord (f.eks. "eiendomspriser
    # kart": desktop 19→30, mobil 18→11 samme uke — oppdaget 03.08.2026). Desktop lagres
    # fortsatt til historikk, men brukes ikke lenger i analysen.
    tagged_mobile = cluster_analysis.tag_rows(rank_mobile, settings.clusters)
    cluster_summaries = diff_analysis.summarize_all_clusters(tagged_mobile, list(settings.clusters.keys()))
    anomalies = diff_analysis.detect_anomalies(
        tagged_mobile, gsc_by_keyword, settings.posisjon_terskel, settings.klikk_terskel_pct, settings.klikk_min_volum
    )
    ai_overview_keywords = geo_analysis.keywords_with_ai_overview(tagged_mobile)

    history_rows_all = storage.get_history(conn, "rank_tracker_weekly", weeks=8)
    history_rows_mobil = [r for r in history_rows_all if r.get("device") == "mobile"]
    history_rows_desktop = [r for r in history_rows_all if r.get("device") == "desktop"]
    tiltak_status = tiltak_analysis.classify_all(settings.tiltak, history_rows_mobil, history_rows_desktop, today)

    position_trend = storage.get_position_trend(conn, weeks=12, device="mobile")
    position_trend_desktop = storage.get_position_trend(conn, weeks=12, device="desktop")
    clicks_trend = storage.get_clicks_trend(conn, weeks=12)

    tagged_footprint = cluster_analysis.tag_rows(footprint_rows, settings.clusters)
    if tagged_footprint:
        storage.save_organic_footprint_rows(conn, week_start_label, tagged_footprint)
    footprint_cluster_summary = cluster_analysis.summarize_footprint_by_cluster(
        tagged_footprint, list(settings.clusters.keys())
    )
    footprint_trend = storage.get_organic_footprint_trend(conn, weeks=12)

    # Innholdsforslag genereres kun to ganger i måneden (scripts/keyword_discovery.py
    # --to-drive, dyrere konkurrent-gap-data gir bedre forslag enn den ukentlige gratis
    # untracked-only-dataen gjorde) — dashboardet leser bare siste kjente lenke her, slik
    # at det viser noe selv de ukene den bi-ukentlige jobben ikke kjører.
    content_briefs_meta = storage.get_content_briefs_meta(conn)

    conn.close()

    analysis = {
        "uke": today.isocalendar()[1],
        "ar": today.year,
        "periode": {"fra": week_start_label, "til": windows["week_end"].isoformat()},
        "domain_rating": domain_rating,
        "site_metrics": site_metrics,
        "gsc_site": gsc_site_rows,
        "gsc_kilde": gsc_source,
        "cluster_summaries": [vars(c) for c in cluster_summaries],
        "avvik": anomalies,
        "organisk_fotavtrykk": {
            "total_sokeord": len(footprint_rows),
            "cluster_summary": footprint_cluster_summary,
        },
        "geo": {
            "ai_overview_sokeord": ai_overview_keywords,
            "claude_selvsjekk": geo_selfcheck,
            "chatgpt_selvsjekk": chatgpt_selfcheck,
            "gemini_selvsjekk": gemini_selfcheck,
            "perplexity_selvsjekk": perplexity_selfcheck,
            "ga4_ai_referral": ga4_ai_referral_rows,
            "ga4_ai_referral_periode_dager": 28,
            # Domenevidt (ikke bare de 338 sporede ordene) — se ahrefs.get_ai_responses_count.
            "ai_responses_count": ai_responses_count,
        },
        "tiltak": tiltak_status,
        "konkurrenter": settings.competitors,
        "innholdsforslag_dokument": content_briefs_meta,
        "datamangler": data_gaps,
    }

    report_markdown = generate_report(settings, analysis)
    analysis["anbefaling"] = extract_recommendations(report_markdown)
    title = report_title(today)

    dashboard_payload = build_dashboard_payload(
        analysis, position_trend, clicks_trend, competitor_benchmark, today, footprint_trend, position_trend_desktop
    )
    dashboard_path = render_dashboard(dashboard_payload)

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

        # SEO×Ads-synergi: rullerende 90-dagers GSC-søkeord-eksport til et delt Sheet Ads-
        # siden (Ole/Spira Nova) leser fra — se samtale 06.08.2026. Overskriver hele arket
        # hvert kjøring (rullerende vindu, ikke voksende historikk). Valgfritt — hopper
        # stille over hvis sheet-ID ikke er konfigurert, akkurat som GA4/e-post.
        if settings.ads_synergy_export_configured:
            try:
                synergy_date_to = today - timedelta(days=1)
                synergy_date_from = synergy_date_to - timedelta(days=89)
                synergy_rows = gsc_oauth.get_query_performance_paginated(
                    settings, synergy_date_from.isoformat(), synergy_date_to.isoformat()
                )
                write_query_export(settings, settings.google_ads_synergy_sheet_id, synergy_rows)
            except HttpError as e:
                logger.warning("SEO×Ads synergi-eksport feilet denne uken: %s", e)
                data_gaps.append(f"SEO×Ads synergi Sheet-eksport feilet denne uken ({e}).")

        if settings.email_configured:
            try:
                send_weekly_report_email(
                    settings,
                    title,
                    result["report_url"],
                    result["sheet_url"],
                    extract_hovedbildet(report_markdown),
                )
            except Exception as e:  # smtplib kaster flere ulike feiltyper (auth, tilkobling, timeout)
                logger.warning("Ukesrapport-e-post kunne ikke sendes denne uken: %s", e)
                data_gaps.append(f"Ukesrapport-e-post ble ikke sendt denne uken: {e}")

    return result
