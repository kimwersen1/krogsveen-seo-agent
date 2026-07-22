"""Ahrefs API v3-klient — kun de endepunktene som er validert i CLAUDE.md.

Docs: https://docs.ahrefs.com/docs/api/reference/introduction
"""
from __future__ import annotations

import json
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.settings import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.ahrefs.com/v3"

RANK_TRACKER_SELECT = "keyword,position,position_prev,volume,url,serp_features"

# I motsetning til Anthropic/OpenAI-klientene (max_retries=5) hadde disse rå requests-
# kallene ingen retry-logikk — en ren nettverksblunk (ConnectionResetError) veltet hele
# ukeskjøringen i praksis (20.07.2026). Retry på tilkoblingsfeil og forbigående 5xx,
# IKKE på 4xx (de er reelle API-feil, f.eks. ugyldig 'where'-spørring, som skal feile
# umiddelbart og ikke sløse tid på gjentatte forsøk).
_session = requests.Session()
_retry = Retry(total=3, connect=3, backoff_factor=1.5, status_forcelist=[500, 502, 503, 504])
_session.mount("https://", HTTPAdapter(max_retries=_retry))


class AhrefsError(RuntimeError):
    pass


def _get(settings: Settings, path: str, params: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {settings.ahrefs_api_key}",
        "Accept": "application/json",
    }
    resp = _session.get(f"{BASE_URL}/{path}", headers=headers, params=params, timeout=60)
    if resp.status_code >= 400:
        raise AhrefsError(f"{path} -> {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def get_subscription_usage(settings: Settings) -> dict:
    """subscription-info/limits-and-usage — gratis, sjekk før andre kall."""
    data = _get(settings, "subscription-info/limits-and-usage", {"output": "json"})
    return data["limits_and_usage"]


def usage_over_budget(usage: dict, threshold_pct: float = 80.0) -> bool:
    """Sjekker workspace-kvoten — units_limit_api_key er None på denne planen
    (ikke satt opp med egen nøkkel-kvote), så det reelle taket er workspace-nivå."""
    limit = usage.get("units_limit_api_key") or usage.get("units_limit_workspace")
    used = usage.get("units_usage_api_key") or usage.get("units_usage_workspace", 0)
    if not limit:
        return False
    return (used / limit) * 100 >= threshold_pct


def _rank_tracker_page(
    settings: Settings, date: str, date_compared: str, device: str, select: str, where: str | None
) -> list[dict]:
    params = {
        "select": select,
        "date": date,
        "date_compared": date_compared,
        "device": device,
        "project_id": settings.ahrefs_project_id,
        "output": "json",
        "limit": 1000,
        "order_by": "volume:desc",
    }
    if where:
        params["where"] = where
    try:
        data = _get(settings, "rank-tracker/overview", params)
    except AhrefsError as e:
        if "serp_features" in select:
            logger.warning("rank-tracker/overview feilet (%s), retryer uten serp_features", e)
            params["select"] = select.replace(",serp_features", "").replace("serp_features,", "").replace(
                "serp_features", ""
            )
            data = _get(settings, "rank-tracker/overview", params)
        else:
            raise
    return data.get("overviews", [])


def get_rank_tracker_overview(
    settings: Settings,
    date: str,
    date_compared: str,
    device: str = "desktop",
    max_pages: int = 30,
) -> list[dict]:
    """rank-tracker/overview — koster 0 enheter. Kjøres for desktop og mobile.

    Endepunktet hard-capper på 100 rader per kall uansett 'limit', og 'where'/'order_by'
    på selve keyword-feltet virker ikke (bekreftet mot API 2026-07-16 — matcher det kjente
    paginerings-problemet i CLAUDE.md). 'where' på numeriske felt (volume, position)
    fungerer derimot korrekt, så vi paginerer med keyset-paginering på 'volume' (desc) og
    ekskluderer allerede sette søkeord ved uavgjort volum for å unngå duplikater/hull.
    """
    all_rows: list[dict] = []
    seen: set[str] = set()
    last_volume: int | None = None
    exclude_at_boundary: list[str] = []

    for _ in range(max_pages):
        conditions = []
        if last_volume is not None:
            conditions.append({"field": "volume", "is": ["lte", last_volume]})
        conditions += [{"field": "keyword", "is": ["neq", kw]} for kw in exclude_at_boundary]

        where = None
        if len(conditions) == 1:
            where = json.dumps(conditions[0])
        elif len(conditions) > 1:
            where = json.dumps({"and": conditions})

        page = _rank_tracker_page(settings, date, date_compared, device, RANK_TRACKER_SELECT, where)
        new_rows = [r for r in page if r["keyword"] not in seen]
        if not new_rows:
            break

        all_rows.extend(new_rows)
        seen.update(r["keyword"] for r in new_rows)

        page_last_volume = page[-1].get("volume")
        if page_last_volume == last_volume:
            exclude_at_boundary.extend(r["keyword"] for r in new_rows if r.get("volume") == page_last_volume)
        else:
            exclude_at_boundary = [r["keyword"] for r in page if r.get("volume") == page_last_volume]
            last_volume = page_last_volume

        if len(page) < 100:
            break

    logger.info("rank-tracker/overview (%s): %d rader (paginert)", device, len(all_rows))
    return all_rows


def get_domain_rating(settings: Settings, date: str, target: str = "krogsveen.no") -> dict:
    """site-explorer/domain-rating — 50 enheter per kall."""
    data = _get(settings, "site-explorer/domain-rating", {"target": target, "date": date, "output": "json"})
    return data["domain_rating"]


def get_site_metrics(settings: Settings, date: str, target: str = "krogsveen.no") -> dict:
    """site-explorer/metrics — trafikkestimat, mode subdomains (default)."""
    data = _get(
        settings,
        "site-explorer/metrics",
        {"target": target, "date": date, "mode": "subdomains", "output": "json"},
    )
    return data["metrics"]


def get_site_metrics_history(
    settings: Settings, date_from: str, target: str = "krogsveen.no", history_grouping: str = "weekly"
) -> list[dict]:
    """site-explorer/metrics-history — for trend over tid."""
    data = _get(
        settings,
        "site-explorer/metrics-history",
        {
            "target": target,
            "date_from": date_from,
            "mode": "subdomains",
            "history_grouping": history_grouping,
            "output": "json",
        },
    )
    return data.get("metrics", [])


def get_gsc_performance_history(
    settings: Settings, date_from: str, date_to: str | None = None, history_grouping: str = "weekly"
) -> list[dict]:
    """gsc/performance-history — site-wide klikk/visninger/CTR/posisjon over tid.

    Fungerer uten egen GSC-tilkobling (Ahrefs har allerede en, i motsetning til
    gsc-keywords/gsc-pages som fortsatt svarer tomt — se get_gsc_performance_by_device
    og kjente fallgruver i CLAUDE.md).
    """
    params = {
        "project_id": settings.ahrefs_project_id,
        "date_from": date_from,
        "history_grouping": history_grouping,
        "output": "json",
    }
    if date_to:
        params["date_to"] = date_to
    data = _get(settings, "gsc/performance-history", params)
    return data.get("metrics", [])


def get_gsc_performance_by_device(settings: Settings, date_from: str, date_to: str) -> list[dict]:
    """gsc/performance-by-device — klikk/visninger/CTR/posisjon per enhetstype."""
    data = _get(
        settings,
        "gsc/performance-by-device",
        {"project_id": settings.ahrefs_project_id, "date_from": date_from, "date_to": date_to, "output": "json"},
    )
    return data.get("metrics", [])


def get_organic_keywords(
    settings: Settings,
    target: str,
    date: str,
    country: str = "no",
    position_max: int | None = 30,
    with_metrics: bool = False,
    limit: int = 100,
) -> list[dict]:
    """site-explorer/organic-keywords — ALLE søkeord et domene rangerer på (i motsetning
    til rank-tracker, som kun dekker de 338 manuelt sporede ordene i prosjektet).

    Brukes til å oppdage søkeord Krogsveen bør legge til i Rank Tracker, eller som
    konkurrenter rangerer på men Krogsveen ikke gjør — se src/analysis/keyword_gap.py.

    KOSTNAD: volume/sum_traffic/keyword_difficulty koster ~10 enheter PER RAD hver
    (with_metrics=True ≈ 32 enheter/rad totalt). with_metrics=False er billig
    (~2 enheter/rad) og holder til bred kartlegging. Samme 100-rader-cap som
    rank-tracker/overview — position_max bør derfor settes stramt nok til at de
    mest relevante radene havner innenfor de første 100.
    """
    select_fields = "keyword,best_position,best_position_url"
    if with_metrics:
        select_fields += ",volume,sum_traffic,keyword_difficulty"

    params = {
        "select": select_fields,
        "target": target,
        "mode": "subdomains",
        "country": country,
        "date": date,
        "order_by": "volume:desc" if with_metrics else "best_position:asc",
        "limit": limit,
        "output": "json",
    }
    if position_max is not None:
        params["where"] = json.dumps({"field": "best_position", "is": ["lte", position_max]})

    data = _get(settings, "site-explorer/organic-keywords", params)
    rows = data.get("keywords", [])
    logger.info("organic-keywords (%s, with_metrics=%s): %d rader", target, with_metrics, len(rows))
    return rows


def get_organic_keywords_for_list(
    settings: Settings, target: str, date: str, keywords: list[str], country: str = "no", with_metrics: bool = False
) -> list[dict]:
    """Slår opp target sin posisjon for en spesifikk liste søkeord (opptil ~100 av gangen).

    Brukes til å sjekke om Krogsveen rangerer i det hele tatt på søkeord en konkurrent
    rangerer på (gap-sjekk), uten å måtte hente hele domenets søkeordsunivers.
    """
    if not keywords:
        return []
    select_fields = "keyword,best_position,best_position_url"
    if with_metrics:
        select_fields += ",volume,sum_traffic,keyword_difficulty"

    where = json.dumps({"or": [{"field": "keyword", "is": ["eq", kw]} for kw in keywords]})
    params = {
        "select": select_fields,
        "target": target,
        "mode": "subdomains",
        "country": country,
        "date": date,
        "where": where,
        "limit": len(keywords),
        "output": "json",
    }
    data = _get(settings, "site-explorer/organic-keywords", params)
    return data.get("keywords", [])


def get_organic_keywords_paginated(
    settings: Settings,
    target: str,
    date: str,
    country: str = "no",
    position_max: int = 50,
    max_rows: int = 1500,
    per_position_limit: int = 100,
) -> list[dict]:
    """Som get_organic_keywords, men henter forbi den samme 100-rader-capen som
    rank-tracker/overview har (se der for detaljer om begrensningen). Alltid
    with_metrics=False — billig (~2 enheter/rad), brukt til bredde-kartlegging (hele det
    organiske fotavtrykket, ikke kun de 338 manuelt sporede Rank Tracker-ordene).

    Spør én eksakt posisjon om gangen (where best_position eq N, N = 1..position_max) i
    stedet for keyset-paginering med et voksende 'neq'-tie-break-sett — sistnevnte fikk
    Ahrefs API til å svare 500 internal server error i praksis (20.07.2026), fordi
    Krogsveen har hundrevis av adressespesifikke long-tail-søkeord som alle rangerer
    posisjon 1 (egne annonse-/prisstatistikksider), og where-klausulen ble for kompleks.
    Cappet på per_position_limit rader PER posisjon — ikke garantert uttømmende for
    svært tiede posisjoner, men gir et representativt bredde-bilde uten å krasje.
    """
    all_rows: list[dict] = []
    for pos in range(1, position_max + 1):
        if len(all_rows) >= max_rows:
            break
        params = {
            "select": "keyword,best_position,best_position_url",
            "target": target,
            "mode": "subdomains",
            "country": country,
            "date": date,
            "where": json.dumps({"field": "best_position", "is": ["eq", pos]}),
            "limit": per_position_limit,
            "output": "json",
        }
        data = _get(settings, "site-explorer/organic-keywords", params)
        all_rows.extend(data.get("keywords", []))

    logger.info("organic-keywords (%s, paginert per posisjon): %d rader", target, len(all_rows))
    return all_rows[:max_rows]
