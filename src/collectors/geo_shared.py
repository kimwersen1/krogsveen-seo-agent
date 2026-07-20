"""Delt logikk for LLM-baserte GEO-selvsjekk-moduler (claude_geo.py, chatgpt_geo.py, ...).

Holder prompt-tekst og merkevare-deteksjon på ett sted slik at de ulike leverandørene
(Anthropic, OpenAI, ...) faktisk sjekkes likt og sammenlignbart.
"""
from __future__ import annotations

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


def detect_mentions(text: str, competitors: list[str]) -> tuple[bool, list[str]]:
    lowered = text.lower()
    krogsveen_mentioned = "krogsveen" in lowered
    competitors_mentioned = [
        domain
        for domain, aliases in COMPETITOR_ALIASES.items()
        if domain in competitors and any(alias.lower() in lowered for alias in aliases)
    ]
    return krogsveen_mentioned, competitors_mentioned


def sentiment_prompt(response_text: str, brand: str = "Krogsveen") -> str:
    return f"Hvordan omtales merket «{brand}» i denne teksten?\n\n---\n{response_text}\n---"
