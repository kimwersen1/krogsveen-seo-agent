"""ChatGPT-basert GEO-selvsjekk — samme metode som src/collectors/claude_geo.py, mot
OpenAI sin API i stedet for Anthropic sin. Krever OPENAI_API_KEY (se .env.example) —
en vanlig chatgpt.com-innlogging er IKKE det samme som en API-nøkkel; API-bruk
faktureres separat (pay-as-you-go) fra en ChatGPT-abonnement.

Bruker en billig, rask modell (default gpt-4o-mini) siden dette er en enkel
tilstedeværelse-sjekk, ikke en oppgave som trenger toppmodellens kvalitet.
"""
from __future__ import annotations

import json

import openai

from src.collectors.geo_shared import NEUTRAL_SYSTEM_PROMPT, SENTIMENT_SYSTEM_PROMPT, detect_mentions, sentiment_prompt
from src.settings import Settings


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
    """Kjører hvert prompt i settings.geo_prompts mot ChatGPT, logger merkenavn-treff,
    og gir en kort sentiment-analyse for nevnelser av Krogsveen.

    Returnerer tom liste (ikke feil) hvis OPENAI_API_KEY ikke er satt — ChatGPT-sjekken
    er valgfri, i motsetning til Claude-sjekken som alltid kjører."""
    if not settings.openai_api_key:
        return []

    client = openai.OpenAI(api_key=settings.openai_api_key, max_retries=5)

    results = []
    for prompt in settings.geo_prompts:
        response = client.chat.completions.create(
            model=settings.openai_model,
            max_tokens=600,
            messages=[
                {"role": "system", "content": NEUTRAL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        krogsveen_mentioned, competitors_mentioned = detect_mentions(text, settings.competitors)

        sentiment, begrunnelse = None, None
        if krogsveen_mentioned:
            analysis = _analyze_sentiment(client, settings.openai_model, text, "Krogsveen")
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
