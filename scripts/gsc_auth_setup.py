#!/usr/bin/env python3
"""Engangsoppsett: genererer en OAuth refresh-token for src/collectors/gsc_oauth.py OG
src/collectors/ga4_oauth.py — samme token dekker begge scopene under ett samtykke.

Må kjøres av deg selv, interaktivt, med DIN egen Google-konto (den som allerede har
"Begrenset" tilgang til sc-domain:krogsveen.no i Search Console, og tilgang til
GA4-eiendommen "krogsveen.no – GA4" i Analytics). Åpner en nettleser for
innlogging/samtykke — kan ikke automatiseres eller kjøres på dine vegne.

Forutsetning: en OAuth-klient (type "Desktop app") opprettet i Google Cloud Console
(samme prosjekt som service-kontoen), med "Search Console API" (webmasters) OG
"Google Analytics Data API" begge aktivert. Se README/chat-instruks for nøyaktige steg.

Kjør denne på nytt (samme client-id/secret) hvis du trenger å UTVIDE et eksisterende
GSC-only-token med GA4-scopet — refresh-tokens er scope-bundet, så en tidligere
generert token uten analytics.readonly kan ikke brukes til GA4 uten å regenereres slik.

Bruk:
    python scripts/gsc_auth_setup.py --client-id <ID> --client-secret <SECRET>

Output: en refresh-token du limer inn i .env som GOOGLE_OAUTH_REFRESH_TOKEN (og de to
andre verdiene som GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET), samt evt.
GitHub-secrets for skykjøringen.
"""
from __future__ import annotations

import argparse

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Engangs OAuth-samtykke for GSC- og GA4-tilgang")
    parser.add_argument("--client-id", required=True, help="OAuth-klient-ID fra Google Cloud Console")
    parser.add_argument("--client-secret", required=True, help="OAuth-klienthemmelighet fra Google Cloud Console")
    args = parser.parse_args()

    client_config = {
        "installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    print("Åpner nettleseren din — logg inn med kontoen som har tilgang til Search Console og GA4.\n")
    credentials = flow.run_local_server(port=0)

    print("\nFerdig! Legg disse i .env (og som GitHub-secrets for skykjøringen):\n")
    print(f"GOOGLE_OAUTH_CLIENT_ID={args.client_id}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={args.client_secret}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={credentials.refresh_token}")


if __name__ == "__main__":
    main()
