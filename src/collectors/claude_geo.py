"""Claude-basert GEO-selvsjekk — spør Claude de samme spørsmålene ekte brukere ville
stilt en LLM, og sjekker om Krogsveen eller konkurrenter blir nevnt i svaret.

Erstatter IKKE Brand Radar (som dekker ChatGPT/Gemini/Perplexity/AI Overviews/AI Mode —
se src/collectors/ahrefs.py sine brand_radar-funksjoner), men er et gratis, robust,
automatiserbart supplement for nettopp Claude, uten avhengighet av at noen konfigurerer
prompts i Ahrefs UI først.

Bevisst IKKE bygget: skraping av Google/Perplexity/ChatGPT sine nettsider for kontinuerlig,
ubevoktet automatisering. Det er skjørt (bot-deteksjon stoppet et manuelt forsøk mot
Perplexity samme dag dette ble bygget) og ToS-risikofylt å basere en cron-jobb på.
"""
from __future__ import annotations

import json

import anthropic

from src.settings import Settings

NEUTRAL_SYSTEM_PROMPT = (
    "Du er en hjelpsom assistent som svarer på spørsmål om bolig og eiendomsmegling i "
    "Norge. Svar naturlig og kortfattet, slik du ville gjort for enhver bruker som "
    "spør. Ikke nevn at dette er en test."
)

SENTIMENT_SYSTEM_PROMPT = (
    "Du analyserer hvordan et bestemt merke omtales i en tekst. Svar KUN med gyldig JSON "
    'på formen {"sentiment": "positiv"|"nøytral"|"negativ", "begrunnelse": "én kort setning"}. '
    "Ingen annen tekst før eller etter JSON-en."
)

# Domenenavn gjort om til søkbare merkenavn rett fram (fjern .no/.ai) gir falske treff
# for korte, vanlige ord — "eie.no" -> "eie" ville matchet nesten enhver boligtekst
# ("når du skal eie egen bolig..."). Eksplisitt liste i stedet for automatisk utledning.
COMPETITOR_ALIASES = {
    "hjemla.no": ["hjemla"],
    "dnbeiendom.no": ["dnb eiendom"],
    "eiendomsmegler1.no": ["eiendomsmegler 1", "eiendomsmegler1"],
    "privatmegleren.no": ["privatmegleren"],
    "nordvikbolig.no": ["nordvik"],
    "bolig.ai": ["bolig.ai"],
    "eie.no": ["eie eiendomsmegling", "eie.no"],
    "meglersmart.no": ["meglersmart"],
}


def _analyze_sentiment(client: anthropic.Anthropic, model: str, response_text: str, brand: str) -> dict:
    """Kun kalt når merket faktisk er nevnt — én kort oppfølgingsspørring for
    positiv/nøytral/negativ framing og hvorfor. Feiler trygt til 'ukjent' hvis
    Claude ikke returnerer gyldig JSON (skjer sjeldent, men skal aldri krasje kjøringen)."""
    prompt = f"Hvordan omtales merket «{brand}» i denne teksten?\n\n---\n{response_text}\n---"
    try:
        response = client.messages.create(
            model=model, max_tokens=200, system=SENTIMENT_SYSTEM_PROMPT, messages=[{"role": "user", "content": prompt}]
        )
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        parsed = json.loads(text)
        return {"sentiment": parsed.get("sentiment", "ukjent"), "begrunnelse": parsed.get("begrunnelse", "")}
    except (json.JSONDecodeError, anthropic.APIError):
        return {"sentiment": "ukjent", "begrunnelse": ""}


def check_geo_visibility(settings: Settings) -> list[dict]:
    """Kjører hvert prompt i settings.geo_prompts mot Claude, logger merkenavn-treff,
    og gir en kort sentiment-analyse for nevnelser av Krogsveen."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=5)

    results = []
    for prompt in settings.geo_prompts:
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=600,
            system=NEUTRAL_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        lowered = text.lower()
        krogsveen_mentioned = "krogsveen" in lowered
        competitors_mentioned = [
            domain
            for domain, aliases in COMPETITOR_ALIASES.items()
            if domain in settings.competitors and any(alias.lower() in lowered for alias in aliases)
        ]

        sentiment, begrunnelse = None, None
        if krogsveen_mentioned:
            analysis = _analyze_sentiment(client, settings.anthropic_model, text, "Krogsveen")
            sentiment, begrunnelse = analysis["sentiment"], analysis["begrunnelse"]

        results.append(
            {
                "prompt": prompt,
                "response_excerpt": text[:300],
                "krogsveen_mentioned": krogsveen_mentioned,
                "competitors_mentioned": competitors_mentioned,
                "sentiment": sentiment,
                "sentiment_begrunnelse": begrunnelse,
            }
        )
    return results
