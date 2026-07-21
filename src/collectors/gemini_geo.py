"""Gemini-basert GEO-selvsjekk — samme metode som src/collectors/claude_geo.py, mot
Googles Gemini API i stedet for Anthropic sin. Krever GEMINI_API_KEY (se .env.example) —
gratis å komme i gang med via aistudio.google.com/apikey (generøs gratis kvote).

Del av erstatningen for Ahrefs Brand Radar (kun 5 prompts, ingen skriv-API for rotasjon,
se beslutning 21.07.2026) — Brand Radar sin "gemini"-datakilde dekkes nå direkte her,
med alle 36 GEO-prompts i stedet for 5.
"""
from __future__ import annotations

import json

from google import genai
from google.genai.errors import APIError

from src.collectors.geo_shared import NEUTRAL_SYSTEM_PROMPT, SENTIMENT_SYSTEM_PROMPT, detect_mentions, sentiment_prompt
from src.settings import Settings


def _analyze_sentiment(client: genai.Client, model: str, response_text: str, brand: str) -> dict:
    try:
        response = client.models.generate_content(
            model=model,
            contents=sentiment_prompt(response_text, brand),
            config={"system_instruction": SENTIMENT_SYSTEM_PROMPT, "max_output_tokens": 200},
        )
        text = (response.text or "").strip()
        parsed = json.loads(text)
        return {"sentiment": parsed.get("sentiment", "ukjent"), "begrunnelse": parsed.get("begrunnelse", "")}
    except (json.JSONDecodeError, APIError):
        return {"sentiment": "ukjent", "begrunnelse": ""}


def check_geo_visibility(settings: Settings) -> list[dict]:
    """Kjører hvert prompt i settings.geo_prompts mot Gemini, logger merkenavn-treff,
    og gir en kort sentiment-analyse for nevnelser av Krogsveen.

    Returnerer tom liste (ikke feil) hvis GEMINI_API_KEY ikke er satt — valgfri, som
    ChatGPT-sjekken."""
    if not settings.gemini_api_key:
        return []

    client = genai.Client(api_key=settings.gemini_api_key)

    results = []
    for prompt in settings.geo_prompts:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config={"system_instruction": NEUTRAL_SYSTEM_PROMPT, "max_output_tokens": 600},
        )
        text = response.text or ""
        krogsveen_mentioned, competitors_mentioned = detect_mentions(text, settings.competitors)

        sentiment, begrunnelse = None, None
        if krogsveen_mentioned:
            analysis = _analyze_sentiment(client, settings.gemini_model, text, "Krogsveen")
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
