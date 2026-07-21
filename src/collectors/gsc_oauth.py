"""Direkte GSC-tilgang via brukerens egen Google-konto (OAuth refresh token), i stedet
for manuell CSV-eksport (src/collectors/gsc.py) eller en service account.

Hvorfor OAuth og ikke service account: Search Console API krever at den autentiserte
identiteten har minst "Begrenset" tilgang til eiendommen i Search Console sine
"Brukere og tillatelser" — å legge til en NY bruker (som en service-konto) krever
"Full"/Eier-tilgang, som ingen hos Krogsveen kunne gi (se src/collectors/gsc.py).
Brukerens EGEN konto har derimot allerede "Begrenset" tilgang (bekreftet 21.07.2026),
og det er nok for API-lesing — ingen admin-handling nødvendig utover det som allerede
finnes.

Engangsoppsett: kjør scripts/gsc_auth_setup.py for å generere refresh-token.

Returnerer rader i SAMME form som src/collectors/gsc.py sin import_gsc_export(), slik at
pipeline.py kan bruke denne modulen som et transparent alternativ til CSV-import.
"""
from __future__ import annotations

import logging

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.settings import Settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
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


def _query(settings: Settings, date_from: str, date_to: str, dimension: str, row_limit: int) -> list[dict]:
    creds = _credentials(settings)
    service = build("webmasters", "v3", credentials=creds, cache_discovery=False)
    body = {
        "startDate": date_from,
        "endDate": date_to,
        "dimensions": [dimension],
        "rowLimit": row_limit,
    }
    response = (
        service.searchanalytics()
        .query(siteUrl=settings.google_search_console_property, body=body)
        .execute()
    )
    rows = []
    for row in response.get("rows", []):
        rows.append(
            {
                dimension: row["keys"][0],
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr": round(row.get("ctr", 0.0) * 100, 4),
                "position": round(row.get("position", 0.0), 4),
            }
        )
    logger.info("GSC OAuth: %d %s-rader (%s -> %s)", len(rows), dimension, date_from, date_to)
    return rows


def get_query_performance(settings: Settings, date_from: str, date_to: str, row_limit: int = 1000) -> list[dict]:
    """Klikk/CTR/posisjon per søkeord — direkte erstatning for gsc.import_gsc_export(dimension='query')."""
    return _query(settings, date_from, date_to, "query", row_limit)


def get_page_performance(settings: Settings, date_from: str, date_to: str, row_limit: int = 1000) -> list[dict]:
    """Klikk/CTR/posisjon per side — direkte erstatning for gsc.import_gsc_export(dimension='page')."""
    return _query(settings, date_from, date_to, "page", row_limit)
