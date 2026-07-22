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
    ahrefs_brand_radar_report_id: str
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
    gemini_api_key: str
    gemini_model: str
    perplexity_api_key: str
    perplexity_model: str
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
    def gsc_oauth_configured(self) -> bool:
        return bool(self.google_oauth_client_id and self.google_oauth_client_secret and self.google_oauth_refresh_token)


def load_settings() -> Settings:
    return Settings(
        ahrefs_api_key=_require("AHREFS_API_KEY"),
        ahrefs_project_id=int(_require("AHREFS_PROJECT_ID")),
        ahrefs_brand_radar_report_id=_require("AHREFS_BRAND_RADAR_REPORT_ID"),
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
        clusters=_load_json("clusters.json"),
        config=_load_json("config.json"),
        tiltak=_load_json("tiltak.json"),
    )
