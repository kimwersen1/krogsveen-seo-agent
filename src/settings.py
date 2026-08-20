"""Laster .env og de tre JSON-konfigfilene til ett Settings-objekt."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Mangler {name} i .env (se .env.example)")
    return value


def _optional(name: str, default: str = "") -> str:
    """os.environ.get(name, default) faller KUN tilbake til default hvis nøkkelen mangler
    helt — men GitHub Actions setter env-variabelen til en TOM STRENG (ikke fraværende)
    når en referert secret ikke finnes, noe som overstyrer default og feilet i praksis
    for GOOGLE_SEARCH_CONSOLE_PROPERTY (21.07.2026). Denne behandler tom streng likt med
    fraværende verdi."""
    return os.environ.get(name, "").strip() or default


def _load_json(name: str) -> dict:
    path = ROOT / name
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@dataclass(frozen=True)
class Settings:
    ahrefs_api_key: str
    ahrefs_project_id: int
    google_service_account_json: Path
    google_drive_folder_id: str
    google_report_doc_name: str
    google_dashboard_sheet_name: str
    google_content_briefs_doc_name: str
    anthropic_api_key: str
    anthropic_model: str
    openai_api_key: str
    openai_model: str
    google_oauth_client_id: str
    google_oauth_client_secret: str
    google_oauth_refresh_token: str
    google_search_console_property: str
    google_ga4_property_id: str
    google_ads_synergy_sheet_id: str
    google_gmail_address: str
    google_gmail_app_password: str
    weekly_report_email_recipient: str
    weekly_report_dashboard_url: str
    gemini_api_key: str
    gemini_model: str
    perplexity_api_key: str
    perplexity_model: str
    google_psi_api_key: str
    clusters: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    tiltak: list = field(default_factory=list)

    @property
    def competitors(self) -> list[str]:
        return self.config.get("konkurrenter", [])

    @property
    def geo_prompts(self) -> list[str]:
        return self.config.get("geo_prompts", [])

    @property
    def posisjon_terskel(self) -> int:
        return self.config.get("varsel_terskler", {}).get("posisjon_endring", 3)

    @property
    def klikk_terskel_pct(self) -> float:
        return self.config.get("varsel_terskler", {}).get("klikk_endring_pct", 20)

    @property
    def klikk_min_volum(self) -> int:
        """Minimum klikk (før eller etter) for at en prosentendring skal telle som avvik —
        uten denne blir f.eks. 1→2 klikk vist som "+100 %", som er støy, ikke signal."""
        return self.config.get("varsel_terskler", {}).get("klikk_min_volum", 10)

    @property
    def gsc_oauth_configured(self) -> bool:
        return bool(self.google_oauth_client_id and self.google_oauth_client_secret and self.google_oauth_refresh_token)

    @property
    def email_configured(self) -> bool:
        # SMTP + app-passord, ikke Gmail API/OAuth — se src/report/email_sender.py for
        # begrunnelse (unngår å legge enda en OAuth-scope-utvidelse oppå gsc_oauth.py/
        # ga4_oauth.py sin allerede skjøre historie).
        return bool(self.google_gmail_address and self.google_gmail_app_password)

    @property
    def ga4_configured(self) -> bool:
        # Bruker samme OAuth-refresh-token som GSC (scopes utvidet 29.07.2026 til å
        # dekke analytics.readonly i tillegg til webmasters.readonly) — kun property-ID-en
        # er GA4-spesifikk. Ikke bruk denne før token er reautorisert med begge scopes,
        # se scripts/gsc_auth_setup.py.
        return self.gsc_oauth_configured and bool(self.google_ga4_property_id)

    @property
    def ads_synergy_export_configured(self) -> bool:
        """SEO×Ads-synergi: rullerende 90-dagers GSC-søkeord-eksport til et delt Sheet
        Google Ads-siden (Ole/Spira Nova) leser fra. Bruker samme GSC OAuth-tilgang som
        resten av GSC-integrasjonen; kun sheet-ID-en er spesifikk for denne eksporten."""
        return self.gsc_oauth_configured and bool(self.google_ads_synergy_sheet_id)


def load_settings() -> Settings:
    return Settings(
        ahrefs_api_key=_require("AHREFS_API_KEY"),
        ahrefs_project_id=int(_require("AHREFS_PROJECT_ID")),
        google_service_account_json=Path(_require("GOOGLE_SERVICE_ACCOUNT_JSON")),
        google_drive_folder_id=_require("GOOGLE_DRIVE_FOLDER_ID"),
        google_report_doc_name=_optional("GOOGLE_REPORT_DOC_NAME", "SEO-ukentlig rapport Krogsveen"),
        google_dashboard_sheet_name=_optional("GOOGLE_DASHBOARD_SHEET_NAME", "SEO-dashboard Krogsveen"),
        google_content_briefs_doc_name=_optional("GOOGLE_CONTENT_BRIEFS_DOC_NAME", "Krogsveen SEO – Innholdsforslag"),
        anthropic_api_key=_require("ANTHROPIC_API_KEY"),
        anthropic_model=_optional("ANTHROPIC_MODEL", "claude-sonnet-5"),
        # Valgfritt — ChatGPT-selvsjekken (src/collectors/chatgpt_geo.py) hopper
        # stille over seg selv hvis denne mangler, i motsetning til Anthropic-nøkkelen.
        openai_api_key=_optional("OPENAI_API_KEY"),
        openai_model=_optional("OPENAI_MODEL", "gpt-4o-mini"),
        # Valgfritt — direkte GSC-tilgang via brukerens egen Google-konto (OAuth), i
        # stedet for manuell CSV-eksport. Se scripts/gsc_auth_setup.py for engangsoppsett.
        # Alle tre må være satt sammen for at src/collectors/gsc_oauth.py skal brukes —
        # pipeline.py faller tilbake til manuell CSV-import hvis noen mangler.
        google_oauth_client_id=_optional("GOOGLE_OAUTH_CLIENT_ID"),
        google_oauth_client_secret=_optional("GOOGLE_OAUTH_CLIENT_SECRET"),
        google_oauth_refresh_token=_optional("GOOGLE_OAUTH_REFRESH_TOKEN"),
        google_search_console_property=_optional("GOOGLE_SEARCH_CONSOLE_PROPERTY", "sc-domain:krogsveen.no"),
        # Valgfritt — GA4 Data API for AI-referral-trafikk (chatgpt.com, claude.ai osv.),
        # gjenbruker samme OAuth-refresh-token som GSC (se ga4_configured over).
        google_ga4_property_id=_optional("GOOGLE_GA4_PROPERTY_ID"),
        # Valgfritt — se ads_synergy_export_configured. Google Sheet delt med
        # seo-agent@krogsveen-seo-agent.iam.gserviceaccount.com (via arv fra en delt mappe).
        google_ads_synergy_sheet_id=_optional("GOOGLE_ADS_SYNERGY_SHEET_ID"),
        # Valgfritt — ukentlig e-postvarsel med lenker + Hovedbildet-sammendrag, se
        # src/report/email_sender.py. Krever et Gmail-app-passord (2-trinns verifisering
        # må være PÅ for avsenderkontoen), ikke OAuth.
        google_gmail_address=_optional("GOOGLE_GMAIL_ADDRESS"),
        google_gmail_app_password=_optional("GOOGLE_GMAIL_APP_PASSWORD"),
        weekly_report_email_recipient=_optional("WEEKLY_REPORT_EMAIL_RECIPIENT"),
        weekly_report_dashboard_url=_optional(
            "WEEKLY_REPORT_DASHBOARD_URL", "https://kimwersen1.github.io/krogsveen-seo-agent/"
        ),
        # Valgfrie — del av erstatningen for Ahrefs Brand Radar (21.07.2026), samme
        # mønster som ChatGPT-selvsjekken: hopper stille over seg selv uten nøkkel.
        gemini_api_key=_optional("GEMINI_API_KEY"),
        # "gemini-flash-lite-latest" i stedet for en pinnet versjon — Gemini-modeller
        # deprekeres uvanlig raskt (gemini-2.0-flash og gemini-2.5-flash-lite ble begge
        # 404 "no longer available" i løpet av samme testøkt, 21.07.2026). Alias unngår
        # at pipelinen brekker hver gang Google roterer modeller.
        gemini_model=_optional("GEMINI_MODEL", "gemini-flash-lite-latest"),
        perplexity_api_key=_optional("PERPLEXITY_API_KEY"),
        perplexity_model=_optional("PERPLEXITY_MODEL", "sonar"),
        # Valgfritt — PageSpeed Insights API for Core Web Vitals (LCP/INP/CLS/mobile-
        # friendly) per URL, se src/collectors/psi.py. Nøkkel opprettet 20.08.2026,
        # begrenset til kun PageSpeed Insights API i Google Cloud Console.
        google_psi_api_key=_optional("GOOGLE_PSI_API_KEY"),
        clusters=_load_json("clusters.json"),
        config=_load_json("config.json"),
        tiltak=_load_json("tiltak.json"),
    )
