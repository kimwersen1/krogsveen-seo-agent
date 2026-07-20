"""Bruker Claude til å foreslå konkrete artikkel-/sideideer basert på søkeordsgap
funnet av src/analysis/keyword_gap.py (untracked + competitor gap keywords).

Kjøres kun av scripts/keyword_discovery.py (månedlig), ikke del av den ukentlige
pipelinen — dette er en tolkning av gap-listen, ikke en kostnadsfri deterministisk
transformasjon som resten av discovery-scriptet.
"""
from __future__ import annotations

import anthropic

from src.settings import Settings

SYSTEM_PROMPT = """Du er en SEO-innholdsstrateg for krogsveen.no, en norsk eiendomsmegler.
Du får en liste søkeord Krogsveen enten rangerer på uten å spore det i Rank Tracker, eller
helt mangler synlighet på sammenlignet med navngitte konkurrenter.

Foreslå 5-8 konkrete artikkel-/sideideer basert på dette. For hvert forslag:
- En kort, konkret tittel (ikke generisk "guide om boligsalg")
- Hvilke søkeord fra listen den dekker
- Én setning om vinkling — hvorfor denne siden dekker brukerens behov bedre enn det
  som finnes i dag, eller hvorfor det er et reelt hull

Skriv på norsk, som en markdown-punktliste, ingen innledning eller avslutning.
Prioriter forslag med høyest samlet søkevolum og tydeligst cluster-tilhørighet."""


def suggest_content(settings: Settings, untracked: list[dict], gaps: list[dict]) -> str:
    if not untracked and not gaps:
        return "Ingen søkeordsgap denne runden å basere forslag på."

    lines = ["Søkeord Krogsveen rangerer på, men ikke sporer i Rank Tracker:"]
    for row in untracked[:30]:
        lines.append(
            f"- {row['keyword']} (pos {row.get('best_position')}, vol {row.get('volume') or 'ukjent'}, "
            f"cluster: {', '.join(row.get('clusters', [])) or 'ingen'})"
        )

    lines.append("\nSøkeord konkurrenter rangerer godt på (topp 10), Krogsveen mangler synlighet:")
    for row in gaps[:30]:
        clusters_label = ", ".join(row.get("clusters", [])) or "utenfor definerte clustre"
        lines.append(
            f"- {row['keyword']} (vol {row.get('volume')}, {row.get('_competitor')} pos {row.get('best_position')}, "
            f"Krogsveen: {row.get('krogsveen_position') or 'ingen rangering'}, cluster: {clusters_label})"
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=5)
    with client.messages.stream(
        model=settings.anthropic_model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n".join(lines)}],
    ) as stream:
        final_message = stream.get_final_message()
    return "".join(block.text for block in final_message.content if block.type == "text")
