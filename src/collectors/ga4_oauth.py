"""GA4 Data API via brukerens egen Google-konto (samme OAuth-refresh-token som
src/collectors/gsc_oauth.py, utvidet med analytics.readonly-scope 29.07.2026).

Hvorfor OAuth og ikke service account: Kim har kun direkte tilgang (ikke Administrator-
rolle) på GA4-kontoen, og kan derfor ikke selv legge til service-kontoen som bruker på
eiendommen — samme situasjon som gjorde OAuth nødvendig for GSC (se gsc_oauth.py).
Brukerens egen konto har allerede lesetilgang, og det er nok for API-lesing.

Brukes til å hente AI-referral-trafikk (chatgpt.com, claude.ai, gemini.google.com osv.)
som sesjonskilde — se konteksten i chat 29.07.2026: en Looker Studio-rapport Krogsveen
allerede har viste denne fordelingen manuelt, dette er den samme dataen hentet direkte
fra GA4 Data API i stedet.

Engangsoppsett / reautorisering: kjør scripts/gsc_auth_setup.py (dekker nå begge
scopes). Krever GOOGLE_GA4_PROPERTY_ID i .env (numerisk GA4-property-ID, IKKE
Measurement-ID-en som starter med G-).
"""
from __future__ import annotations

import logging

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.settings import Settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"

# Kjente AI-chat-domener som dukker opp som sessionSource når noen klikker en lenke
# Krogsveen fra et AI-svar. Ikke uttømmende — utvid ved behov fremfor å query'e og
# filtrere i etterkant på en antakelse om hva som "teller" som AI-kilde.
AI_REFERRAL_SOURCES = {
    "chatgpt.com",
    "chat.openai.com",
    "gemini.google.com",
    "claude.ai",
    "perplexity",
    "perplexity.ai",
    "copilot.com",
    "copilot.microsoft.com",
    "you.com",
    "grok.com",
}


def _credentials(settings: Settings) -> Credentials:
    return Credentials(
        token=None,
        refresh_token=settings.google_oauth_refresh_token,
        token_uri=TOKEN_URI,
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        scopes=SCOPES,
    )


def _metric_value(row: dict, metric_index: int) -> str:
    return row["metricValues"][metric_index]["value"]


def get_ai_referral_sessions(settings: Settings, date_from: str, date_to: str) -> list[dict]:
    """Sesjoner/engasjement/konverteringer per sessionSource, filtrert til kjente
    AI-chat-kilder (se AI_REFERRAL_SOURCES). Henter alle kilder sortert på sesjoner
    og filtrerer i Python i stedet for en API-side dimensionFilter, slik at nye
    AI-kilder som dukker opp bare krever en oppdatering av settet over, ikke ny kode."""
    creds = _credentials(settings)
    service = build("analyticsdata", "v1beta", credentials=creds, cache_discovery=False)

    body = {
        "dateRanges": [{"startDate": date_from, "endDate": date_to}],
        "dimensions": [{"name": "sessionSource"}],
        "metrics": [
            {"name": "sessions"},
            {"name": "engagementRate"},
            {"name": "averageSessionDuration"},
            {"name": "conversions"},
        ],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": 100,
    }
    response = (
        service.properties()
        .runReport(property=f"properties/{settings.google_ga4_property_id}", body=body)
        .execute()
    )

    rows = []
    for row in response.get("rows", []):
        source = row["dimensionValues"][0]["value"]
        if source not in AI_REFERRAL_SOURCES:
            continue
        rows.append(
            {
                "source": source,
                "sessions": int(float(_metric_value(row, 0))),
                "engagement_rate": round(float(_metric_value(row, 1)) * 100, 2),
                "avg_session_duration_sec": round(float(_metric_value(row, 2)), 1),
                "conversions": float(_metric_value(row, 3)),
            }
        )
    logger.info(
        "GA4 OAuth: %d AI-referral-kilder med trafikk (%s -> %s)", len(rows), date_from, date_to
    )
    return rows
