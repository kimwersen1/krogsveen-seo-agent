"""Kaller Claude API for å skrive selve rapportteksten fra analyse-JSON."""
from __future__ import annotations

import logging

import anthropic

from src.report.prompt_builder import build_prompt
from src.settings import Settings

logger = logging.getLogger(__name__)


def generate_report(settings: Settings, analysis: dict) -> str:
    system_prompt, user_prompt = build_prompt(analysis)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=5)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=8000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    if response.stop_reason == "max_tokens":
        logger.warning("Rapporten ble kuttet av max_tokens-grensen — vurder å stramme inn analyse-JSON eller heve grensen ytterligere.")
    return "".join(block.text for block in response.content if block.type == "text")
