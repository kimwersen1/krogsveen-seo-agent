"""Claude-basert GEO-selvsjekk — spør Claude de samme spørsmålene ekte brukere ville
stilt en LLM, og sjekker om Krogsveen eller konkurrenter blir nevnt i svaret.

Erstatter IKKE Brand Radar (som dekker ChatGPT/Gemini/Perplexity/AI Overviews/AI Mode —
se src/collectors/ahrefs.py sine brand_radar-funksjoner, men krever en Ahrefs-plan
Krogsveen ikke har per 20.07.2026), men er et gratis, robust, automatiserbart supplement
for nettopp Claude. Se src/collectors/chatgpt_geo.py for samme sjekk mot ChatGPT.

Bevisst IKKE bygget: skraping av Google/Perplexity sine nettsider for kontinuerlig,
ubevoktet automatisering. Det er skjørt (bot-deteksjon stoppet et manuelt forsøk mot
Perplexity samme dag dette ble bygget) og ToS-risikofylt å basere en cron-jobb på.
"""
from __future__ import annotations

import json

import anthropic

from src.collectors.geo_shared import NEUTRAL_SYSTEM_PROMPT, SENTIMENT_SYSTEM_PROMPT, detect_mentions, sentiment_prompt
from src.settings import Settings


def _analyze_sentiment(client: anthropic.Anthropic, model: str, response_text: str, brand: str) -> dict:
    """Kun kalt når merket faktisk er nevnt — én kort oppfølgingsspørring for
    positiv/nøytral/negativ framing og hvorfor. Feiler trygt til 'ukjent' hvis
    Claude ikke returnerer gyldig JSON (skjer sjeldent, men skal aldri krasje kjøringen)."""
    try:
        response = client.messages.create(
            model=model,
            max_tokens=200,
            system=SENTIMENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": sentiment_prompt(response_text, brand)}],
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
        krogsveen_mentioned, competitors_mentioned = detect_mentions(text, settings.competitors)

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
