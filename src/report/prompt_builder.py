"""Bygger prompten til Claude fra strukturert analyse-JSON."""
from __future__ import annotations

import json

REPORT_FORMAT = """
1. Hovedbildet (3–5 setninger).
2. Per cluster: snittendring, antall opp/ned, topp 3 bevegelser hver vei.
3. GEO — presenter som TO ATSKILTE deler, ikke slått sammen:
   a) Brand Radar (ChatGPT/Gemini/Perplexity/AI Overviews/AI Mode): omtaler + share-of-voice.
      Hvis alt er 0 — si eksplisitt at prompts ikke er konfigurert ennå i Ahrefs UI, ikke at
      Krogsveen er fraværende fra disse kildene (det er ukjent, ikke bekreftet).
   b) Claude-selvsjekk (geo.claude_selvsjekk): hvor mange av prompt-ene nevnte Krogsveen vs.
      hvilke konkurrenter, med 1-2 konkrete eksempler. Dette ER ekte data, presenter det som det.
      Bruk sentiment/sentiment_begrunnelse-feltene der Krogsveen er nevnt — nevn eksplisitt om
      omtalen er positiv/nøytral/negativ og hvorfor, ikke bare at merket ble nevnt.
   c) Søkeord med ai_overview i SERP (fra Ahrefs rank tracker).
4. Tiltaks-effekt.
5. Avvik (>3 pos / >20 % klikk).
6. Anbefaling for kommende uke (2–3 punkter).
Ærlig om datamangler. Ingen rådata-dumper.
""".strip()

SYSTEM_PROMPT = f"""Du skriver en ukentlig SEO/GEO-rapport for krogsveen.no, en norsk eiendomsmegler.
Rapporten skal være konklusjonsdrevet, maks 2 sider, på norsk, og følge nøyaktig denne strukturen:

{REPORT_FORMAT}

Du får strukturert analysedata som JSON — ikke gjenta rådata, syntetiser og konkluder.
Vær ærlig når data mangler (f.eks. Brand Radar uten konfigurerte prompts, GSC-hull) i stedet for
å late som alt er komplett.
Skriv i seksjoner med tydelige overskrifter ("## Overskrift") og punktlister ("- punkt") i markdown,
klar for direkte konvertering til Google Docs. Ingen innledende hilsen, og ingen egen tittel/H1 øverst
(rapporten settes inn under en tittel som allerede finnes) — start rett på "## 1. Hovedbildet"."""


def build_prompt(analysis: dict) -> tuple[str, str]:
    """Returnerer (system_prompt, user_prompt)."""
    user_prompt = (
        "Her er ukens strukturerte analysedata for krogsveen.no:\n\n"
        f"```json\n{json.dumps(analysis, ensure_ascii=False, indent=2, default=str)}\n```\n\n"
        "Skriv rapporten nå, følg strukturen fra systeminstruksen."
    )
    return SYSTEM_PROMPT, user_prompt
