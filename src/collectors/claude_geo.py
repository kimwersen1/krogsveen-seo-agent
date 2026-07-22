"""Claude-basert GEO-selvsjekk — spør Claude de samme spørsmålene ekte brukere ville
stilt en LLM, og sjekker om Krogsveen eller konkurrenter blir nevnt i svaret.

Gratis, robust, automatiserbart — en av fire selvsjekk-kilder (se også chatgpt_geo.py,
gemini_geo.py, perplexity_geo.py). Disse fire erstattet Ahrefs Brand Radar helt
(21.07.2026) — Brand Radar var begrenset til 5 prompts totalt med skrivebeskyttet API
(ingen automatisk rotasjon mulig), mens denne egne selvsjekken kjører alle 36 GEO-prompts
mot fire reelle LLM-er.

Bevisst IKKE bygget: skraping av Google/Perplexity sine nettsider for kontinuerlig,
ubevoktet automatisering. Det er skjørt (bot-deteksjon stoppet et manuelt forsøk mot
Perplexity samme dag dette ble bygget) og ToS-risikofylt å basere en cron-jobb på —
Perplexity dekkes i stedet via deres offisielle API (se perplexity_geo.py).
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
