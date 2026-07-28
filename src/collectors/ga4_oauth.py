"""GA4 Data API-tilgang via brukerens egen Google-konto (samme OAuth refresh-token som
src/collectors/gsc_oauth.py, utvidet med analytics.readonly-scope — se
scripts/gsc_auth_setup.py).

Bruker den generiske googleapiclient-discoveryen (analyticsdata v1beta) i stedet for
det dedikerte google-analytics-data-pakken, for å unngå en ny avhengighet — samme
mønster som gsc_oauth.py bruker for Search Console.

Formål: koble faktiske konverteringer (GA4 "key events" — kontaktskjemaer, budforespørsler,
e-takst-bestillinger) til SEO/GEO-arbeidet, i stedet for kun å måle synlighet (klikk,
posisjon, AI-nevnelser) uten å vite om det faktisk gir forretningsverdi.
"""
from __future__ import annotations

import logging

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.settings import Settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _credentials(settings: Settings) -> Credentials:
    return Credentials(
        token=None,
        refresh_token=settings.google_oauth_refresh_token,
        token_uri=TOKEN_URI,
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        scopes=SCOPES,
    )


def _run_report(settings: Settings, body: dict) -> dict:
    creds = _credentials(settings)
    service = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)
    property_path = f"properties/{settings.google_analytics_property_id}"
    return service.properties().runReport(property=property_path, body=body).execute()


def _rows_to_dicts(response: dict, dimension_names: list[str], metric_names: list[str]) -> list[dict]:
    rows = []
    for row in response.get("rows", []):
        entry = {}
        for i, name in enumerate(dimension_names):
            entry[name] = row["dimensionValues"][i]["value"]
        for i, name in enumerate(metric_names):
            raw = row["metricValues"][i]["value"]
            entry[name] = float(raw) if "." in raw else int(raw)
        rows.append(entry)
    return rows


def get_key_events_by_name(settings: Settings, date_from: str, date_to: str) -> list[dict]:
    """Hvilke GA4 key events (konverteringer) som faktisk trigget i perioden, og hvor mange
    ganger — brukes både til å oppdage hvilke mål som er konfigurert (contact_form_submit,
    generate_lead, e-takst-bestilling e.l.) og som selve rapport-dataen."""
    body = {
        "dateRanges": [{"startDate": date_from, "endDate": date_to}],
        "dimensions": [{"name": "eventName"}],
        "metrics": [{"name": "eventCount"}],
        "dimensionFilter": {
            "filter": {"fieldName": "isKeyEvent", "stringFilter": {"value": "true"}}
        },
        "orderBys": [{"metric": {"metricName": "eventCount"}, "desc": True}],
        "limit": 50,
    }
    response = _run_report(settings, body)
    rows = _rows_to_dicts(response, ["eventName"], ["eventCount"])
    logger.info("GA4: %d key event-typer trigget %s -> %s", len(rows), date_from, date_to)
    return rows


def get_conversions_by_landing_page(settings: Settings, date_from: str, date_to: str, row_limit: int = 200) -> list[dict]:
    """Sesjoner og key events (konverteringer) per landingsside — grunnlaget for å koble
    cluster/side-nivå SEO/GEO-arbeid til faktisk konverteringseffekt, ikke bare trafikk."""
    body = {
        "dateRanges": [{"startDate": date_from, "endDate": date_to}],
        "dimensions": [{"name": "landingPage"}],
        "metrics": [{"name": "sessions"}, {"name": "keyEvents"}],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": row_limit,
    }
    response = _run_report(settings, body)
    rows = _rows_to_dicts(response, ["landingPage"], ["sessions", "keyEvents"])
    logger.info("GA4: %d landingssider %s -> %s", len(rows), date_from, date_to)
    return rows


def get_site_totals(settings: Settings, date_from: str, date_to: str) -> dict:
    """Site-wide sesjoner/brukere/key events for perioden — enkel oppsummering til dashboardet."""
    body = {
        "dateRanges": [{"startDate": date_from, "endDate": date_to}],
        "metrics": [{"name": "sessions"}, {"name": "activeUsers"}, {"name": "keyEvents"}],
    }
    response = _run_report(settings, body)
    rows = _rows_to_dicts(response, [], ["sessions", "activeUsers", "keyEvents"])
    return rows[0] if rows else {"sessions": 0, "activeUsers": 0, "keyEvents": 0}
