"""Kaller Claude API for å skrive selve rapportteksten fra analyse-JSON."""
from __future__ import annotations

import logging

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
