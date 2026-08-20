"""Bygger den stående, maskinlesbare SEO×Ads Synergy-datafeeden (ett Google Sheet per
klient, delt med Ole) beskrevet i data-kontrakten fra Notion Customer Context §10 /
SEO×Ads Synergy-planen.

Erstatter den forrige tilnærmingen — et 25 000-rads rå GSC-eksport-ark uten avgrensning,
delt med "alle med lenken" i stedet for navngitt med ole@spiranova.ai, og uten de fire
andre datasettene (pages/keyword_gap/ai_visibility/organic_conversions) — som gjorde at
Ole 12.08.2026 kun kunne joine mot de 28 søkeordene publisert i selve rapportteksten.

VIKTIG: Denne modulen bygger fanene fra det som faktisk er tilgjengelig i dag.
- queries: bygges fra GSC OAuth (gratis, ingen Ahrefs-enheter), inkl. landingsside via
  gsc_oauth.get_query_page_performance_paginated() (join-nøkkel #2, bekreftet fungerende
  18.08.2026). aio_present er derimot KUN kjent for de 338 Rank Tracker-sporede ordene
  (Ahrefs serp_features) — ukjent (None) for resten av GSC-universet med mindre man
  kjører Ahrefs serp-overview per søkeord (koster ~4 enheter/rad, upraktisk i skala for
  tusenvis av rader).
- pages: klikk/posisjon fra GSC. lcp/inp/cls/mobile_friendly er ALLTID None her — ingen
  PSI/CrUX-kilde er koblet til denne kodebasen ennå. Se cwv_source-parameteren.
- keyword_gap: reshapet fra src.analysis.keyword_gap (Ahrefs), men i "vår posisjon 11-20"-
  formen spesifisert i kontrakten, ikke dagens "vi mangler helt/rangerer svakt (>50)"-form.
- ai_visibility: fra GEO-selvsjekkene (Claude/ChatGPT/Gemini/Perplexity), aggregert per
  prompt. aio_fires er None (ukjent) med mindre prompten også er et Ahrefs-sporet søkeord.
- organic_conversions: INGEN kilde koblet ennå (krever GA4 conversions-metric per
  landingPage/query, ikke bygget — se conversions_source-parameteren). Tabellen skrives
  tom med en eksplisitt "ikke tilgjengelig"-note, ALDRI stille utelatt.
"""
from __future__ import annotations

from dataclasses import dataclass, field

QUERIES_COLUMNS = ["query", "clicks", "impressions", "ctr", "avg_position", "top_landing_page", "aio_present", "date_start", "date_end"]
PAGES_COLUMNS = ["url", "organic_clicks", "organic_impressions", "avg_position", "lcp", "inp", "cls", "mobile_friendly"]
KEYWORD_GAP_COLUMNS = ["term", "our_position", "best_competitor", "competitor_position", "search_volume", "source"]
AI_VISIBILITY_COLUMNS = ["query_or_topic", "aio_fires", "we_are_cited", "llms_citing_us"]
ORGANIC_CONVERSIONS_COLUMNS = ["landing_page_or_query", "conversions", "conversion_value", "source"]

# Volum-kutt (se data-kontrakten): Ole målte ekvivalent hale i Krogsveens Ads search terms
# — bunn-5%-impresjoner var 2634 termer (58% av alle unike termer) med null konverteringer.
MIN_IMPRESSIONS_DEFAULT = 10
FALLBACK_CUMULATIVE_IMPRESSIONS_PCT = 95.0


@dataclass
class CutResult:
    kept: list[dict]
    dropped_count: int
    total_before: int
    cut_description: str


def apply_volume_cut(
    rows: list[dict],
    conversions_by_query: dict[str, float] | None = None,
    min_impressions: int = MIN_IMPRESSIONS_DEFAULT,
) -> CutResult:
    """Datakontraktens kutt-regel: behold søkeord med >= min_impressions impresjoner i
    vinduet, MEN behold alltid et søkeord med en registrert organisk konvertering uansett
    impresjoner. Returnerer også antall droppede rader og en menneskelesbar
    kutt-beskrivelse — kontrakten krever at dette står i selve arket og i hver rapport,
    aldri stille avkuttet slik det 25 000-rads rå eksporten gjorde."""
    conversions_by_query = conversions_by_query or {}
    total_before = len(rows)
    kept = [
        row
        for row in rows
        if row.get("impressions", 0) >= min_impressions or conversions_by_query.get(row.get("query", ""), 0) > 0
    ]
    dropped = total_before - len(kept)
    cut_description = (
        f"Kutt: søkeord med <{min_impressions} impresjoner i vinduet er utelatt, med unntak av "
        f"søkeord med minst én registrert organisk konvertering (alltid beholdt uansett volum). "
        f"{dropped} av {total_before} rader ({dropped / total_before * 100:.1f}%) droppet av denne regelen."
        if total_before
        else "Ingen rader å kutte."
    )
    return CutResult(kept=kept, dropped_count=dropped, total_before=total_before, cut_description=cut_description)


def build_queries_rows(
    query_page_rows: list[dict],
    aio_lookup: dict[str, bool] | None,
    date_start: str,
    date_end: str,
) -> list[dict]:
    """query_page_rows: fra gsc_oauth.get_query_page_performance_paginated() (én rad per
    query+page-par — flere sider kan dele samme query). Slås sammen til én rad per query
    med topp-landingsside (flest klikk) via gsc_oauth.top_landing_page_by_query(), og
    query-nivå klikk/impresjoner/ctr/posisjon summeres/vektes på nytt her siden kilde-
    dataen er per query+page.

    aio_lookup: {query.lower(): bool} — kun kjent for Ahrefs Rank Tracker sine 338 sporede
    ord. None (ikke False) for alt annet — se modul-docstring."""
    aio_lookup = aio_lookup or {}
    from src.collectors.gsc_oauth import top_landing_page_by_query

    top_page = top_landing_page_by_query(query_page_rows)

    by_query: dict[str, dict] = {}
    for row in query_page_rows:
        q = row["query"]
        agg = by_query.setdefault(q, {"clicks": 0, "impressions": 0, "position_sum": 0.0, "position_n": 0})
        agg["clicks"] += row["clicks"]
        agg["impressions"] += row["impressions"]
        agg["position_sum"] += row["position"] * row["impressions"]
        agg["position_n"] += row["impressions"]

    result = []
    for q, agg in by_query.items():
        avg_position = round(agg["position_sum"] / agg["position_n"], 2) if agg["position_n"] else None
        ctr = round(agg["clicks"] / agg["impressions"] * 100, 4) if agg["impressions"] else 0.0
        result.append(
            {
                "query": q,
                "clicks": agg["clicks"],
                "impressions": agg["impressions"],
                "ctr": ctr,
                "avg_position": avg_position,
                "top_landing_page": top_page.get(q),
                "aio_present": aio_lookup.get(q.lower()),
                "date_start": date_start,
                "date_end": date_end,
            }
        )
    return result


def build_pages_rows(page_rows: list[dict], cwv_lookup: dict[str, dict] | None = None) -> list[dict]:
    """page_rows: fra gsc_oauth.get_page_performance(). cwv_lookup: {url: {lcp, inp, cls,
    mobile_friendly}} — None (ikke 0) for alle felt hvis cwv_lookup ikke er gitt, se
    modul-docstring om at ingen PSI/CrUX-kilde er koblet inn ennå."""
    cwv_lookup = cwv_lookup or {}
    result = []
    for row in page_rows:
        cwv = cwv_lookup.get(row["page"], {})
        result.append(
            {
                "url": row["page"],
                "organic_clicks": row["clicks"],
                "organic_impressions": row["impressions"],
                "avg_position": row["position"],
                "lcp": cwv.get("lcp"),
                "inp": cwv.get("inp"),
                "cls": cwv.get("cls"),
                "mobile_friendly": cwv.get("mobile_friendly"),
            }
        )
    return result


def build_keyword_gap_rows(gap_rows: list[dict], our_position_min: int = 11, our_position_max: int = 20) -> list[dict]:
    """Reshapet fra src.analysis.keyword_gap.find_competitor_gap_keywords() (Ahrefs) til
    kontraktens term/our_position/best_competitor/competitor_position/search_volume/source-
    form. MERK: dagens keyword_gap.py-logikk finner søkeord der Krogsveen enten mangler helt
    (>50 eller ingen rangering) eller rangerer svakt — ikke spesifikt kontraktens
    "posisjon 11-20 med kommersiell intensjon"-vindu (nærmest treffbar for en innholds-
    oppdatering, ikke en helt ny side). Filteret under henter kun de radene som faktisk
    faller i 11-20-vinduet av det find_competitor_gap_keywords() allerede har funnet —
    bekreft med Kim/Ole om 11-20 er riktig vindu, eller om hele det bredere settet
    (inkl. 'ingen rangering') også skal med under en annen kolonne-betydning."""
    result = []
    for row in gap_rows:
        our_position = row.get("krogsveen_position")
        if our_position is None or not (our_position_min <= our_position <= our_position_max):
            continue
        result.append(
            {
                "term": row["keyword"],
                "our_position": our_position,
                "best_competitor": row.get("_competitor"),
                "competitor_position": row.get("best_position"),
                "search_volume": row.get("volume"),
                "source": "Ahrefs",
            }
        )
    return result


def build_ai_visibility_rows(geo_results_by_source: dict[str, list[dict]]) -> list[dict]:
    """geo_results_by_source: {"claude": [...], "chatgpt": [...], "gemini": [...],
    "perplexity": [...]} — hver liste i formatet fra src.collectors.*_geo.check_geo_visibility().
    Aggregerer per prompt (query_or_topic) på tvers av kilder. aio_fires er ALLTID None her
    — GEO-promptene er ikke nødvendigvis ekte søkeord i Ahrefs Rank Tracker, så AI Overview-
    tilstedeværelse for dem er ukjent uten en egen Ahrefs SERP-sjekk per prompt (kost:
    se modul-docstring)."""
    by_prompt: dict[str, dict] = {}
    for source, results in geo_results_by_source.items():
        for r in results:
            prompt = r["prompt"]
            entry = by_prompt.setdefault(prompt, {"cited_by": set(), "mentioned_by": set()})
            cited = r.get("krogsveen_cited", r.get("krogsveen_mentioned", False))
            if r.get("krogsveen_mentioned"):
                entry["mentioned_by"].add(source)
            if cited:
                entry["cited_by"].add(source)

    result = []
    for prompt, entry in by_prompt.items():
        result.append(
            {
                "query_or_topic": prompt,
                "aio_fires": None,
                "we_are_cited": bool(entry["cited_by"] or entry["mentioned_by"]),
                "llms_citing_us": sorted(entry["mentioned_by"] | entry["cited_by"]),
            }
        )
    return result


def build_organic_conversions_rows(ga4_conversion_rows: list[dict] | None = None) -> list[dict]:
    """ga4_conversion_rows: forventet {"landing_page_or_query", "conversions",
    "conversion_value", "source"} per rad, IKKE bygget ennå — ingen GA4-samler i denne
    kodebasen henter konverteringer per landingsside/søkeord i dag (kun
    ga4_oauth.get_ai_referral_sessions(), som er site-wide per sessionSource, ikke per
    side/søkeord). Returnerer tom liste med mindre data faktisk er gitt — ALDRI fyll ut
    med gjettede tall. Uten denne fanen er ingen blandet CPA mulig, se data-kontrakten."""
    return list(ga4_conversion_rows or [])
