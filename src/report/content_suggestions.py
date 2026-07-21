"""Bruker Claude til å foreslå konkrete artikkel-/sideideer basert på søkeordsgap
funnet av src/analysis/keyword_gap.py (untracked + competitor gap keywords).

To bruksmønstre:
  1. Ukentlig, i pipeline.py: kun untracked-listen (gratis — gjenbruker allerede
     hentet organisk-fotavtrykk-data), lette forslag vist i dashboard.
  2. To ganger i måneden, i scripts/keyword_discovery.py --to-drive: untracked + dyrere
     konkurrent-gap-data, fyldigere forslag skrevet til det løpende Drive-dokumentet.
"""
from __future__ import annotations

import re

import anthropic

from src.settings import Settings

# Grunnet i to kilder (21.07.2026):
# 1. Faktisk gjennomgang av krogsveen.no — to reelle, men ulike mønstre på sitet i dag:
#    magasinartikler (narrativ prosa, ekte navngitte meglere/kontorsjefer sitert med
#    tittel, "vi/du"-tone, ingen eksplisitt spørsmål-struktur) vs. transaksjonssider som
#    /e-takst (sterk "Hva er X? / Hvor lenge er X gyldig?"-struktur, punktlister, klar
#    prising — mye mer GEO/AI Overview-vennlig fordi LLM-er og Googles AI-sammendrag
#    lettere trekker ut rene spørsmål-svar-par).
# 2. Krogsveens offisielle kommunikasjonsstrategi (PDF delt av bruker, "Ring 2"/2025) —
#    formål, verdier og en eksplisitt "vi er / vi er ikke"-tonematrise. Denne dekker ikke
#    alt (ingen målgruppe-/persona-seksjon, ingen eksplisitte skriveregler for
#    nettinnhold) — brukes i kombinasjon med observasjonene fra sitet, ikke i stedet for.
TONE_OF_VOICE = """Formål: "Vi skaper trygghet og gir retning til verdifulle livsvalg."
Løfte: "Vi tilfører verdier – i alle betydninger av ordet" — en dobbel bunn av økonomi
(markedsverdi) og følelser (trygghet, historie, livsvalg, relasjoner). Kjerneordet er
"verdi", og den offisielle meldingsformelen er "Verdien av [noe]" (samme mønster som
forsidens tittel "Verdien av en god megler") — bruk denne formelen i titler der det
passer naturlig, ikke tvunget inn overalt.

Fire verdier: Trygg, Ambisiøs, Dedikert, Lagspiller.

Tone-of-voice-matrise (offisiell, "vi er / vi er ikke") — bruk denne som en sjekkliste,
ikke bare et vibe-notat:
- Solide, MEN IKKE trauste
- Rå (dvs. ærlige/direkte), MEN IKKE kyniske
- Empatiske, MEN IKKE veike
- Kompetente, MEN IKKE rigide
- Effektive, MEN TAR IKKE snarveier
- Selvsikre, MEN IKKE arrogante

Offisiell prinsipp for budskap: "Budskapene må være enkle, men også pedagogiske — de må
gi mening i korte og begrensede formater." Dette støtter direkte GEO-målet: korte,
selvstendige, siterbare avsnitt fungerer både for lesere og for LLM-er som trekker ut
enkeltsetninger.

Konkret i praksis (fra selve nettsiden): snakker til leseren som et menneske med en reell
beslutning foran seg, ikke som et salgsobjekt. Selger ikke Krogsveen direkte i
brødteksten (ingen "bestill hos oss nå"-CTA-er midt i teksten) — tillit bygges gjennom
konkrete, ærlige råd, ofte med et sitat fra en navngitt megler eller kontorsjef med tittel
og kontor (f.eks. "Therese Thon Andreassen, daglig leder i Krogsveen Tønsberg").
Overskrifter er innsikt, ikke etiketter ("Lokalkunnskap gir et bedre utgangspunkt", ikke
"Om lokalkunnskap").

Strukturell svakhet å rette opp i nye forslag: dagens magasinartikler er ren narrativ
prosa uten eksplisitte spørsmål-overskrifter, mens sider som /e-takst allerede viser at
Krogsveen kan skrive god Q&A-struktur når de vil. Nye artikkelforslag bør derfor inkludere
minst 2-3 eksplisitte spørsmålsoverskrifter som matcher reelle søkefraser (f.eks. "Hvor mye
koster e-takst?", "Hvor lenge er en e-takst gyldig?") i tillegg til den varme narrative
tonen — ikke bytte den ut.

VIKTIG MERKEVAREREGEL (fra bruker, 21.07.2026): Krogsveen er en av landets største
eiendomsmeglere og skriver nøkternt — ALDRI sammenlign eller nevn navngitte
meglerkonkurrenter (hjemla.no, DNB Eiendom, Eiendomsmegler1, osv.) i et forslag, selv om
konkurrent-gap-dataen under viser hvilket firma som rangerer på et ord. Bruk gap-dataen
kun til å identifisere SELVE SØKEORDET/BEHOVET som mangler dekning, ikke til å foreslå
sammenligningsinnhold ("Krogsveen vs [konkurrent]" e.l.). Skryt ikke av størrelse eller
overdriv — dette matcher "selvsikre, men ikke arrogante" fra tonematrisen over."""

SYSTEM_PROMPT = f"""Du er en SEO/GEO-innholdsstrateg for krogsveen.no, en norsk eiendomsmegler.
Du får en liste søkeord Krogsveen enten rangerer på uten å spore det i Rank Tracker, eller
helt mangler synlighet på sammenlignet med navngitte konkurrenter.

{TONE_OF_VOICE}

Foreslå 5-8 konkrete artikkel-/sideideer basert på søkeordslisten. For hvert forslag:
- En kort, konkret tittel (ikke generisk "guide om boligsalg")
- Hvilke søkeord fra listen den dekker
- Én setning om vinkling — hvorfor denne siden dekker brukerens behov bedre enn det
  som finnes i dag, eller hvorfor det er et reelt hull
- Én setning om struktur — nevn spesifikt hvilke spørsmålsoverskrifter forslaget bør ha,
  matchet mot tone-of-voice-notatet over

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


def parse_bullets(markdown_text: str) -> list[str]:
    """Plukker ut punktlisten fra suggest_content sin markdown-respons, med
    **bold**-markører fjernet — til bruk i dashboards som viser ren tekst i stedet for
    Docs rich-text (samme mønster som generate.extract_recommendations)."""
    bullets = re.findall(r"^[-*]\s+(.*)$", markdown_text, re.MULTILINE)
    return [re.sub(r"\*\*(.+?)\*\*", r"\1", b).strip() for b in bullets if b.strip()]
