"""Core Web Vitals per URL via PageSpeed Insights API v5 (CrUX felt-data, ikke
lab-simulering) — lukker CWV-hullet i SEO×Ads Synergy-datakontrakten (§10 Technical /
Core Web Vitals baseline, tidligere "(fill in)").

Nøkkel opprettet av Kim 20.08.2026, begrenset til kun PageSpeed Insights API i Google
Cloud Console. Testet mot ekte krogsveen.no-URL samme dag.

MERK om mobile_friendly: Google la ned den dedikerte "Mobile-Friendly Test"-APIen i 2023.
PSI v5 har ingen direkte erstattende boolean lenger — det nærmeste er en "viewport"-
relatert Lighthouse-innsikt som ikke er et rent pass/fail-signal. I stedet for å bygge
en skjør proxy returneres mobile_friendly alltid som None her; selve CWV-tallene (hentet
med strategy='mobile') ER i praksis den moderne erstatningen for "er siden god på mobil".
"""
from __future__ import annotations

import logging

import requests

from src.settings import Settings

logger = logging.getLogger(__name__)

PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# CrUX-kategoriterskler (Googles egne, se web.dev/vitals) — brukt kun til en menneskelesbar
# status ved siden av rå-tallet, ikke til å filtrere bort noe.
_LCP_GOOD_MS = 2500
_LCP_NEEDS_IMPROVEMENT_MS = 4000
_INP_GOOD_MS = 200
_INP_NEEDS_IMPROVEMENT_MS = 500
_CLS_GOOD = 0.1
_CLS_NEEDS_IMPROVEMENT = 0.25


def _status(value: float | None, good: float, needs_improvement: float) -> str | None:
    if value is None:
        return None
    if value <= good:
        return "GOOD"
    if value <= needs_improvement:
        return "NEEDS_IMPROVEMENT"
    return "POOR"


def get_core_web_vitals(settings: Settings, url: str, strategy: str = "mobile") -> dict:
    """Ett kall = én URL (PSI har ingen batch-endepunkt). CrUX feltdata (ekte brukerdata,
    siste 28 dager, Googles egen kilde for rangeringssignalet) hentes fra
    loadingExperience.metrics — IKKE lighthouseResult (som er en enkelt simulert lab-
    kjøring, mer volatil og ikke det Google faktisk rangerer på).

    Returnerer None for et felt hvis siden ikke har nok CrUX-trafikk til en offisiell
    poengsum (typisk for lavtrafikk-URL-er) — ALDRI en gjettet verdi."""
    if not settings.google_psi_api_key:
        raise ValueError("GOOGLE_PSI_API_KEY er ikke satt — kan ikke hente Core Web Vitals.")

    resp = requests.get(
        PSI_URL,
        params={"url": url, "strategy": strategy, "category": "performance", "key": settings.google_psi_api_key},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    metrics = data.get("loadingExperience", {}).get("metrics", {})

    lcp = metrics.get("LARGEST_CONTENTFUL_PAINT_MS", {}).get("percentile")
    inp = metrics.get("INTERACTION_TO_NEXT_PAINT", {}).get("percentile")
    cls_raw = metrics.get("CUMULATIVE_LAYOUT_SHIFT_SCORE", {}).get("percentile")
    cls = round(cls_raw / 100, 3) if cls_raw is not None else None

    return {
        "url": url,
        "lcp": lcp,
        "lcp_status": _status(lcp, _LCP_GOOD_MS, _LCP_NEEDS_IMPROVEMENT_MS),
        "inp": inp,
        "inp_status": _status(inp, _INP_GOOD_MS, _INP_NEEDS_IMPROVEMENT_MS),
        "cls": cls,
        "cls_status": _status(cls, _CLS_GOOD, _CLS_NEEDS_IMPROVEMENT),
        "mobile_friendly": None,
        "crux_data_available": bool(metrics),
    }


def get_core_web_vitals_for_urls(settings: Settings, urls: list[str], strategy: str = "mobile") -> dict[str, dict]:
    """Ett PSI-kall per URL — ingen batch-endepunkt finnes. Fanger enkeltfeil per URL (f.eks.
    en 404-side eller en URL uten nok CrUX-trafikk) i stedet for å la én dårlig URL stoppe
    hele settet, siden dette typisk kjøres mot en liste 'nøkkel-URL-er', ikke alle sider."""
    result: dict[str, dict] = {}
    for url in urls:
        try:
            result[url] = get_core_web_vitals(settings, url, strategy=strategy)
        except requests.HTTPError as e:
            logger.warning("PSI-kall feilet for %s: %s", url, e)
            result[url] = {"url": url, "lcp": None, "inp": None, "cls": None, "mobile_friendly": None, "error": str(e)}
    return result
