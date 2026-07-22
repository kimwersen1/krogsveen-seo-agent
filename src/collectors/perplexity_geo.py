"""Perplexity-basert GEO-selvsjekk — samme metode som src/collectors/claude_geo.py, mot
Perplexitys API i stedet for Anthropic sin. Perplexity har et OpenAI-kompatibelt API
(base_url https://api.perplexity.ai), så vi gjenbruker openai-klienten i stedet for et
eget SDK. Krever PERPLEXITY_API_KEY (se .env.example) — betalt, men billig per kall
(perplexity.ai/settings/api).

Del av erstatningen for Ahrefs Brand Radar (kun 5 prompts, ingen skriv-API for rotasjon,
se beslutning 21.07.2026) — Brand Radar sin "perplexity"-datakilde dekkes nå direkte her.

STERKERE SIGNAL enn de andre selvsjekkene: Perplexity-modellene (sonar/sonar-pro) gjør
alltid live websøk og returnerer en citations-liste (kildeurl-er) sammen med svaret. Vi
sjekker derfor ikke bare om Krogsveen NEVNES i teksten, men om krogsveen.no faktisk er
SITERT som kilde — det er et mye sterkere GEO-signal enn tekstmatch alene.
"""
from __future__ import annotations

import json

import openai

from src.collectors.geo_shared import NEUTRAL_SYSTEM_PROMPT, SENTIMENT_SYSTEM_PROMPT, detect_mentions, sentiment_prompt
from src.settings import Settings

BASE_URL = "https://api.perplexity.ai"


def _client(settings: Settings) -> openai.OpenAI:
    return openai.OpenAI(api_key=settings.perplexity_api_key, base_url=BASE_URL, max_retries=5)


def _analyze_sentiment(client: openai.OpenAI, model: str, response_text: str, brand: str) -> dict:
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=200,
            messages=[
                {"role": "system", "content": SENTIMENT_SYSTEM_PROMPT},
                {"role": "user", "content": sentiment_prompt(response_text, brand)},
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        parsed = json.loads(text)
        return {"sentiment": parsed.get("sentiment", "ukjent"), "begrunnelse": parsed.get("begrunnelse", "")}
    except (json.JSONDecodeError, openai.OpenAIError):
        return {"sentiment": "ukjent", "begrunnelse": ""}


def check_geo_visibility(settings: Settings) -> list[dict]:
    """Kjører hvert prompt i settings.geo_prompts mot Perplexity, logger merkenavn-treff
    OG om krogsveen.no er sitert som kilde, med sentiment-analyse for nevnelser.

    Returnerer tom liste (ikke feil) hvis PERPLEXITY_API_KEY ikke er satt — valgfri,
    som ChatGPT- og Gemini-sjekken."""
    if not settings.perplexity_api_key:
        return []

    client = _client(settings)

    results = []
    for prompt in settings.geo_prompts:
        response = client.chat.completions.create(
            model=settings.perplexity_model,
            max_tokens=600,
            messages=[
                {"role": "system", "content": NEUTRAL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        krogsveen_mentioned, competitors_mentioned = detect_mentions(text, settings.competitors)

        # citations er ikke del av OpenAI-skjemaet openai-klienten forventer, men
        # Perplexity legger det på toppnivå i responsen — pydantic-modellen i SDK-et
        # tillater ekstra felt, så vi henter det via model_extra i stedet for en
        # typed attributt.
        raw = response.model_dump()
        citations = raw.get("citations") or []
        krogsveen_cited = any("krogsveen.no" in (url or "").lower() for url in citations)

        sentiment, begrunnelse = None, None
        if krogsveen_mentioned:
            analysis = _analyze_sentiment(client, settings.perplexity_model, text, "Krogsveen")
            sentiment, begrunnelse = analysis["sentiment"], analysis["begrunnelse"]

        results.append(
            {
                "prompt": prompt,
                "response_excerpt": text[:300],
                "krogsveen_mentioned": krogsveen_mentioned,
                "krogsveen_cited": krogsveen_cited,
                "competitors_mentioned": competitors_mentioned,
                "sentiment": sentiment,
                "sentiment_begrunnelse": begrunnelse,
            }
        )
    return results
