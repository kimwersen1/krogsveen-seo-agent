"""Kaller Claude API for å skrive selve rapportteksten fra analyse-JSON."""
from __future__ import annotations

import logging
import re

import anthropic

from src.report.prompt_builder import build_prompt
from src.settings import Settings

logger = logging.getLogger(__name__)


def generate_report(settings: Settings, analysis: dict) -> str:
    """Streamer svaret i stedet for ett blokkerende create()-kall.

    Denne rapporten er stor (opptil 8000 output-tokens + extended thinking), og et
    ikke-strømmet kall kan ligge stille lenge nok til at et nettverksledd (ruter/brannmur)
    dropper forbindelsen som "inaktiv" — observert som gjentatte RemoteProtocolError
    ("Server disconnected without sending a response") 17.07.2026. Streaming holder
    forbindelsen aktiv underveis og unngår dette.
    """
    system_prompt, user_prompt = build_prompt(analysis)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=5)
    with client.messages.stream(
        model=settings.anthropic_model,
        max_tokens=12000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        final_message = stream.get_final_message()
    if final_message.stop_reason == "max_tokens":
        logger.warning("Rapporten ble kuttet av max_tokens-grensen — vurder å stramme inn analyse-JSON eller heve grensen ytterligere.")
    return "".join(block.text for block in final_message.content if block.type == "text")


def extract_recommendations(report_markdown: str) -> list[str]:
    """Plukker ut punktlisten under seksjon 6 ("Anbefaling for kommende uke") fra den
    genererte rapportteksten, til bruk i dashboards som ikke viser hele rapportteksten
    (se REPORT_FORMAT i prompt_builder.py — Claude instrueres til å nummerere seksjoner
    som '## 6. ...'). Feiler stille (tom liste) hvis Claude skulle avvike fra formatet."""
    match = re.search(r"^##\s*6\..*?$(.*?)(?=^##\s*\d|\Z)", report_markdown, re.MULTILINE | re.DOTALL)
    if not match:
        return []
    bullets = re.findall(r"^[-*]\s+(.*)$", match.group(1), re.MULTILINE)
    # Dashboards viser disse som ren tekst (ikke Docs rich-text som drive_writer.py
    # håndterer separat) — fjern **bold**-markører i stedet for å vise dem bokstavelig.
    return [re.sub(r"\*\*(.+?)\*\*", r"\1", b).strip() for b in bullets if b.strip()]
