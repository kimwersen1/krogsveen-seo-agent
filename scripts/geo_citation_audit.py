#!/usr/bin/env python3
"""GEO-siteringsrevisjon — kjøres on-demand (ukentlig/månedlig), ikke del av den
automatiske ukesrapporten. Adresserer to svakheter i den eksisterende ukentlige
GEO-selvsjekken (src/collectors/*_geo.py):

1. Prompt-settet der (config.json sine geo_prompts) er i praksis allerede stort sett
   ubrandede kategori-/lokal-spørsmål, MEN mangler en eksplisitt "branded"-kategori
   (spør aldri "hva synes du om krogsveen.no") og "sammenlign X vs Y"-spørsmål — begge
   lagt til her, i tillegg til noen nye ubrandede spørsmål seedet fra ekte GSC-søketermer
   (nærmeste proxy vi har til Google Ads-søketermer).
2. Viktigst: Claude/ChatGPT/Gemini svarer i dag fra treningsdata, ikke live søk — kun
   Perplexity (Sonar) gjør faktisk web-augmentert søk. Og selv der sjekket vi kun om
   merkenavnet "krogsveen" står i svarteksten (brand-string-match), ikke om
   krogsveen.no faktisk ble sitert som kilde. Dette scriptet bruker web-søk-verktøy på
   alle fire (Claude web_search, OpenAI Responses API web_search, Gemini Google Search
   grounding, Perplexity sonar er allerede live-søkende), henter ALLE siterte URL-er
   fra hver, og matcher på normalisert domene — ikke merkenavn-tekst i svaret.

Bruk:
    python scripts/geo_citation_audit.py                 # alle prompts, alle motorer
    python scripts/geo_citation_audit.py --limit 5        # rask test, 5 prompts
    python scripts/geo_citation_audit.py --engines claude,perplexity

Output: appender rader til data/geo_citation_audit.csv (prompt, type, engine, cited,
matched_urls, all_citations, timestamp) — periodisk re-kjøring bygger en trend, ikke
bare et øyeblikksbilde.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)

TARGET_DOMAIN = "krogsveen.no"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "geo_citation_audit.csv"
CSV_FIELDS = ["timestamp", "engine", "prompt_type", "prompt", "cited", "matched_urls", "all_citations"]


@dataclass
class TypedPrompt:
    prompt: str
    type: str  # branded | unbranded-category | comparison | local | buyer-stage


# Retagget fra config.json sine eksisterende 36 geo_prompts (alle var allerede
# ubrandet — ingen inneholdt "krogsveen") + nye branded/comparison-prompts, som var
# den reelt manglende kategorien.
BASE_PROMPTS: list[TypedPrompt] = [
    TypedPrompt("hva er boligen min verdt", "unbranded-category"),
    TypedPrompt("hvordan finne ut hva boligen er verdt", "unbranded-category"),
    TypedPrompt("beste eiendomsmegler i Norge", "unbranded-category"),
    TypedPrompt("anbefal eiendomsmegler i Oslo", "local"),
    TypedPrompt("anbefal eiendomsmegler i Bergen", "local"),
    TypedPrompt("anbefal eiendomsmegler i Trondheim", "local"),
    TypedPrompt("anbefal eiendomsmegler i Stavanger", "local"),
    TypedPrompt("anbefal eiendomsmegler i Kristiansand", "local"),
    TypedPrompt("anbefal eiendomsmegler i Drammen", "local"),
    TypedPrompt("hva koster det å selge bolig", "unbranded-category"),
    TypedPrompt("hvordan selge bolig", "unbranded-category"),
    TypedPrompt("hva er boligprisene i Norge nå", "unbranded-category"),
    TypedPrompt("boligprisutvikling Oslo", "unbranded-category"),
    TypedPrompt("hva er e-takst", "unbranded-category"),
    TypedPrompt("trenger jeg boligselgerforsikring", "unbranded-category"),
    TypedPrompt("hvordan få finansieringsbevis", "unbranded-category"),
    TypedPrompt("hva ble naboens bolig solgt for", "unbranded-category"),
    TypedPrompt("hvilken eiendomsmegler har lavest provisjon", "comparison"),
    TypedPrompt("hvordan fungerer en budrunde", "unbranded-category"),
    TypedPrompt("hva bør jeg vite før jeg kjøper leilighet", "buyer-stage"),
    TypedPrompt("hvor mye koster en verdivurdering av bolig", "unbranded-category"),
    TypedPrompt("hvordan finner jeg solgte boliger i mitt område", "unbranded-category"),
    TypedPrompt("er det verdt det å bruke eiendomsmegler eller selge selv", "buyer-stage"),
    TypedPrompt("hva er forskjellen på de store eiendomsmeglerkjedene i Norge", "comparison"),
    TypedPrompt("hvordan velger jeg riktig eiendomsmegler", "buyer-stage"),
    TypedPrompt("bør jeg pusse opp før jeg selger boligen", "buyer-stage"),
    TypedPrompt("hvordan selge dødsbo eller arvet bolig", "unbranded-category"),
    TypedPrompt("hvordan selge bolig ved skilsmisse eller samlivsbrudd", "unbranded-category"),
    TypedPrompt("hva er en tilstandsrapport og trenger jeg det", "unbranded-category"),
    TypedPrompt("hvor lang tid tar det å selge en bolig", "unbranded-category"),
    TypedPrompt("hva er forskjellen på prisantydning og markedsverdi", "unbranded-category"),
    TypedPrompt("hvordan verdsette en hytte eller fritidsbolig", "unbranded-category"),
    TypedPrompt("trenger jeg boligkjøperforsikring", "unbranded-category"),
    TypedPrompt("hva bør jeg spørre eiendomsmegleren om før jeg signerer oppdragsavtale", "buyer-stage"),
    TypedPrompt("hva koster det å kjøpe bolig i Norge inkludert gebyrer", "unbranded-category"),
    TypedPrompt("hvordan påvirker boligrenten boligmarkedet nå", "unbranded-category"),
    # Nye: branded (manglet helt før)
    TypedPrompt("hva synes du om krogsveen.no som eiendomsmegler", "branded"),
    TypedPrompt("er krogsveen en god eiendomsmegler", "branded"),
    TypedPrompt("hva koster det å bruke krogsveen til å selge bolig", "branded"),
    TypedPrompt("hvordan er krogsveen sin e-takst-tjeneste", "branded"),
    # Nye: eksplisitt sammenligning
    TypedPrompt("sammenlign krogsveen og dnb eiendom", "comparison"),
    TypedPrompt("eiendomsmegler1 eller krogsveen, hvem er best", "comparison"),
]


def normalize_domain(url: str) -> str:
    """Strip protocol/www/path/query — sammenlignbar netloc for domenematching.
    Tåler også bare domenenavn uten skjema (f.eks. Gemini sin grounding_chunk.web.title,
    som er "trustpilot.com" uten "https://" — urlparse legger da alt i .path, ikke
    .netloc, med mindre vi selv legger på et skjema først)."""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        netloc = parsed.netloc.lower()
    except ValueError:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def domain_matches(url: str, target: str = TARGET_DOMAIN) -> bool:
    domain = normalize_domain(url)
    return domain == target or domain.endswith("." + target)


def seed_prompts_from_gsc(settings, n: int = 8) -> list[TypedPrompt]:
    """Henter topp ikke-brandede GSC-søketermer som ekstra unbranded-category-prompts —
    nærmeste proxy vi har til ekte Google Ads-søketermer (anbefalt seed-kilde), siden vi
    ikke har Ads-data. Feiler stille (tom liste) hvis GSC OAuth ikke er konfigurert."""
    if not settings.gsc_oauth_configured:
        return []
    try:
        from datetime import date, timedelta

        from src.collectors import gsc_oauth

        date_to = (date.today() - timedelta(days=3)).isoformat()
        date_from = (date.today() - timedelta(days=30)).isoformat()
        rows = gsc_oauth.get_query_performance(settings, date_from, date_to, row_limit=200)
    except Exception as exc:  # noqa: BLE001 — skal aldri stoppe resten av scriptet
        logger.warning("Kunne ikke hente GSC-seed-søkeord: %s", exc)
        return []

    rows = sorted(rows, key=lambda r: r.get("clicks", 0), reverse=True)
    seeded: list[TypedPrompt] = []
    for row in rows:
        query = (row.get("query") or "").strip()
        if not query or "krogsveen" in query.lower():
            continue
        seeded.append(TypedPrompt(query, "unbranded-category"))
        if len(seeded) >= n:
            break
    logger.info("Seedet %d ekstra unbranded-category-prompts fra GSC-søketermer", len(seeded))
    return seeded


# ---- Per-motor citation-henting (ekte web-søk/grounding, ikke statisk trenings-kunnskap) ----


def get_citations_claude(settings, prompt: str) -> list[str]:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=5)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
    )
    urls = []
    for block in response.content:
        if block.type == "text" and block.citations:
            for c in block.citations:
                if getattr(c, "url", None):
                    urls.append(c.url)
    return urls


def get_citations_openai(settings, prompt: str) -> list[str]:
    import openai

    client = openai.OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=settings.openai_model,
        tools=[{"type": "web_search"}],
        input=prompt,
    )
    urls = []
    for item in response.output:
        if getattr(item, "type", None) != "message":
            continue
        for block in item.content:
            for annotation in getattr(block, "annotations", None) or []:
                if getattr(annotation, "type", None) == "url_citation":
                    urls.append(annotation.url)
    return urls


def get_citations_gemini(settings, prompt: str) -> list[str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        max_output_tokens=1024,
    )
    response = client.models.generate_content(model=settings.gemini_model, contents=prompt, config=config)
    urls = []
    candidates = response.candidates or []
    if candidates:
        grounding = getattr(candidates[0], "grounding_metadata", None)
        for chunk in getattr(grounding, "grounding_chunks", None) or []:
            web = getattr(chunk, "web", None)
            if not web:
                continue
            # web.uri er en opak vertexaisearch.cloud.google.com/grounding-api-redirect/...
            # proxy-URL — domenet der er alltid Google sitt, aldri den faktiske kilden, så
            # domenematching mot den vil aldri kunne treffe krogsveen.no. web.title er
            # derimot allerede det faktiske kildedomenet som ren tekst (f.eks. "bytt.no"),
            # ubrukelig som klikkbar lenke men riktig for domenematching.
            if getattr(web, "title", None):
                urls.append(web.title)
            elif getattr(web, "uri", None):
                urls.append(web.uri)
    return urls


def get_citations_perplexity(settings, prompt: str) -> list[str]:
    import openai

    client = openai.OpenAI(api_key=settings.perplexity_api_key, base_url="https://api.perplexity.ai", max_retries=5)
    response = client.chat.completions.create(
        model=settings.perplexity_model,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.model_dump()
    return [c for c in (raw.get("citations") or []) if c]


ENGINES = {
    "claude": (get_citations_claude, lambda s: bool(s.anthropic_api_key)),
    "chatgpt": (get_citations_openai, lambda s: bool(s.openai_api_key)),
    "gemini": (get_citations_gemini, lambda s: bool(s.gemini_api_key)),
    "perplexity": (get_citations_perplexity, lambda s: bool(s.perplexity_api_key)),
}


def run_audit(settings, prompts: list[TypedPrompt], engine_names: list[str]) -> list[dict]:
    rows = []
    timestamp = datetime.now(timezone.utc).isoformat()
    for engine_name in engine_names:
        fetch_fn, is_configured = ENGINES[engine_name]
        if not is_configured(settings):
            logger.warning("%s: hoppet over, API-nøkkel ikke konfigurert", engine_name)
            continue
        for tp in prompts:
            try:
                citations = fetch_fn(settings, tp.prompt)
            except Exception as exc:  # noqa: BLE001 — én feilet prompt skal ikke stoppe resten
                logger.warning("%s / %r feilet: %s", engine_name, tp.prompt[:50], exc)
                continue
            matched = [u for u in citations if domain_matches(u)]
            rows.append(
                {
                    "timestamp": timestamp,
                    "engine": engine_name,
                    "prompt_type": tp.type,
                    "prompt": tp.prompt,
                    "cited": bool(matched),
                    "matched_urls": "; ".join(matched),
                    "all_citations": "; ".join(citations),
                }
            )
            logger.info(
                "%s / %s / %r -> %d siteringer, %s",
                engine_name,
                tp.type,
                tp.prompt[:40],
                len(citations),
                "TREFF" if matched else "ingen treff",
            )
    return rows


def write_csv(rows: list[dict], output_path: Path = OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = output_path.exists()
    with open(output_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
    logger.info("Skrev %d rader til %s", len(rows), output_path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="GEO-siteringsrevisjon mot fire LLM-er med ekte web-søk")
    parser.add_argument("--limit", type=int, default=None, help="Begrens til N prompts (for rask testing)")
    parser.add_argument(
        "--engines",
        default="claude,chatgpt,gemini,perplexity",
        help="Kommaseparert liste over motorer å kjøre (default: alle)",
    )
    parser.add_argument("--no-gsc-seed", action="store_true", help="Ikke hent ekstra prompts fra GSC-søketermer")
    args = parser.parse_args()

    from src.settings import load_settings

    settings = load_settings()

    prompts = list(BASE_PROMPTS)
    if not args.no_gsc_seed:
        prompts += seed_prompts_from_gsc(settings)
    if args.limit:
        prompts = prompts[: args.limit]

    engine_names = [e.strip() for e in args.engines.split(",") if e.strip()]
    unknown = set(engine_names) - set(ENGINES)
    if unknown:
        raise SystemExit(f"Ukjent(e) motor(er): {unknown}. Gyldige: {list(ENGINES)}")

    logger.info("Kjører %d prompts mot %d motorer (%s)", len(prompts), len(engine_names), ", ".join(engine_names))
    rows = run_audit(settings, prompts, engine_names)
    write_csv(rows)

    total = len(rows)
    cited = sum(1 for r in rows if r["cited"])
    print(f"\n{cited} / {total} prompt-motor-kombinasjoner siterte {TARGET_DOMAIN}")
    print(f"Resultater lagt til: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
