"""Genererer 2-3 grundige innholdsforslag (SEO + GEO) som et eget Google-dokument, basert
på søkeordsgap funnet av src/analysis/keyword_gap.py (untracked + competitor gap keywords).

Kjøres kun av scripts/keyword_discovery.py --to-drive (to ganger i måneden) — dette er en
tolkning av gap-listen (kostbar Claude-samtale), ikke en kostnadsfri deterministisk
transformasjon. Dashboardet viser kun en lenke til dette dokumentet (se
src/collectors/storage.py sin content_briefs_meta-tabell), ikke selve forslagene inline —
brukeren fant den forrige punktlisten i dashboardet uoversiktlig (21.07.2026).

Bruker et eget Google Doc (via src.report.drive_writer.replace_content_briefs_doc), ikke en
faktisk .docx-fil — forsøk på å generere og laste opp en ekte Word-fil via den tilkoblede
Drive-connectoren i denne økten viste seg upraktisk (base64-innhold av selv en liten .docx
sprenger kontekstvinduet pga. dårlig tokenisering av base64), og uansett kan den
connectoren kun brukes interaktivt — den automatiserte kjøringen har bare service-kontoen,
som ikke kan opprette nye filer i det hele tatt. Et Google Doc er nedlastbart som ekte
Word-fil når som helst (Fil → Last ned → Microsoft Word) hvis det trengs."""
from __future__ import annotations

import json
import re

import anthropic

from src.settings import Settings

# Grunnet i to kilder (21.07.2026):
# 1. Faktisk gjennomgang av krogsveen.no — magasinartikler (narrativ prosa, ekte navngitte
#    meglere/kontorsjefer sitert med tittel, "vi/du"-tone) vs. transaksjonssider som
#    /e-takst (sterk "Hva er X? / Hvor lenge er X gyldig?"-struktur — mer GEO/AI
#    Overview-vennlig fordi LLM-er lettere trekker ut rene spørsmål-svar-par).
# 2. Krogsveens offisielle kommunikasjonsstrategi (PDF delt av bruker, "Ring 2"/2025) —
#    formål, verdier og en eksplisitt "vi er / vi er ikke"-tonematrise.
TONE_OF_VOICE = """Formål: "Vi skaper trygghet og gir retning til verdifulle livsvalg."
Løfte: "Vi tilfører verdier – i alle betydninger av ordet" — en dobbel bunn av økonomi
(markedsverdi) og følelser (trygghet, historie, livsvalg, relasjoner). Kjerneordet er
"verdi", og den offisielle meldingsformelen er "Verdien av [noe]" (samme mønster som
forsidens tittel "Verdien av en god megler") — bruk denne formelen i titler der det
passer naturlig, ikke tvunget inn overalt.

Fire verdier: Trygg, Ambisiøs, Dedikert, Lagspiller.

Tone-of-voice-matrise (offisiell, "vi er / vi er ikke") — bruk denne som en sjekkliste:
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
brødteksten. Tillit bygges gjennom konkrete, ærlige råd, ofte med et sitat fra en
navngitt megler eller kontorsjef med tittel og kontor. Overskrifter er innsikt, ikke
etiketter ("Lokalkunnskap gir et bedre utgangspunkt", ikke "Om lokalkunnskap").

Strukturell svakhet å rette opp i nye forslag: dagens magasinartikler er ren narrativ
prosa uten eksplisitte spørsmål-overskrifter, mens sider som /e-takst allerede viser at
Krogsveen kan skrive god Q&A-struktur. Nye forslag bør derfor inkludere eksplisitte
spørsmålsoverskrifter som matcher reelle søkefraser, i tillegg til den varme narrative
tonen — ikke bytte den ut.

VIKTIG MERKEVAREREGEL (fra bruker, 21.07.2026): Krogsveen er en av landets største
eiendomsmeglere og skriver nøkternt — ALDRI sammenlign eller nevn navngitte
meglerkonkurrenter (hjemla.no, DNB Eiendom, Eiendomsmegler1, osv.) i et forslag, selv om
konkurrent-gap-dataen under viser hvilket firma som rangerer på et ord. Bruk gap-dataen
kun til å identifisere SELVE SØKEORDET/BEHOVET som mangler dekning. Skryt ikke av
størrelse eller overdriv — dette matcher "selvsikre, men ikke arrogante" fra
tonematrisen over."""

SYSTEM_PROMPT = f"""Du er en SEO/GEO-innholdsstrateg for krogsveen.no, en norsk eiendomsmegler.
Du får en liste søkeord Krogsveen enten rangerer på uten å spore det i Rank Tracker, eller
helt mangler synlighet på sammenlignet med navngitte konkurrenter.

{TONE_OF_VOICE}

Foreslå NØYAKTIG 3 grundige artikkelforslag, hver med BÅDE en SEO-vinkel og en GEO-vinkel
(de kan overlappe, men nevn begge eksplisitt). Prioriter forslag med høyest samlet
søkevolum og tydeligst cluster-tilhørighet — konsolidering av mange beslektede long-tail-
søk til én sterk side er ofte bedre enn ett forslag per enkeltord.

Returner KUN gyldig JSON, ingen annen tekst, i dette skjemaet:
[{{"tittel": "...", "malgruppe_sokeord": ["...", "..."], "seo_fokus": "1-2 setninger",
"geo_fokus": "1-2 setninger", "foreslatt_struktur": ["Spørsmål-overskrift 1", "..."],
"begrunnelse": "hvorfor dette er et reelt hull, 1-2 setninger"}}]"""


def generate_content_briefs(settings: Settings, untracked: list[dict], gaps: list[dict]) -> list[dict]:
    """Returnerer 2-3 strukturerte innholdsforslag (title/keywords/seo/geo/struktur/
    begrunnelse) som Python-dicts, klare til å bygges om til et Word-dokument via
    build_briefs_docx(). Tom liste hvis det ikke er noe gap-data å basere forslag på."""
    if not untracked and not gaps:
        return []

    lines = ["Søkeord Krogsveen rangerer på, men ikke sporer i Rank Tracker:"]
    for row in untracked[:60]:
        lines.append(
            f"- {row['keyword']} (pos {row.get('best_position')}, vol {row.get('volume') or 'ukjent'}, "
            f"cluster: {', '.join(row.get('clusters', [])) or 'ingen'})"
        )

    lines.append("\nSøkeord konkurrenter rangerer godt på (topp 10), Krogsveen mangler synlighet:")
    for row in gaps[:60]:
        clusters_label = ", ".join(row.get("clusters", [])) or "utenfor definerte clustre"
        lines.append(
            f"- {row['keyword']} (vol {row.get('volume')}, {row.get('_competitor')} pos {row.get('best_position')}, "
            f"Krogsveen: {row.get('krogsveen_position') or 'ingen rangering'}, cluster: {clusters_label})"
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=5)
    # max_tokens romslig satt — komplekse strukturerte forslag over mange søkeord trigger
    # ofte extended thinking, som deler samme budsjett som selve svaret (opplevd 21.07.2026:
    # 2500/4000 var ikke nok, kappet svaret midt i JSON-en).
    with client.messages.stream(
        model=settings.anthropic_model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n".join(lines)}],
    ) as stream:
        final_message = stream.get_final_message()
    text = "".join(block.text for block in final_message.content if block.type == "text")

    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    raw = match.group(1) if match else text
    return json.loads(raw)


def format_content_briefs_markdown(briefs: list[dict], generated_label: str) -> str:
    """Formaterer strukturerte forslag (se generate_content_briefs()) som markdown, klar
    for src.report.drive_writer.replace_content_briefs_doc() (samme markdown->Docs-API-
    konverter som den ukentlige rapporten allerede bruker)."""
    lines = [
        "# Innholdsforslag – Krogsveen SEO/GEO",
        f"Generert {generated_label} — basert på søkeord Krogsveen allerede rangerer på "
        "uten å spore, og konkurrent-gap-analyse.",
        "",
    ]
    for i, brief in enumerate(briefs, start=1):
        lines.append(f"## {i}. {brief['tittel']}")
        lines.append(f"**Målgruppe-søkeord:** {', '.join(brief.get('malgruppe_sokeord', []))}")
        lines.append(f"**SEO-fokus:** {brief.get('seo_fokus', '')}")
        lines.append(f"**GEO-fokus:** {brief.get('geo_fokus', '')}")
        lines.append("**Foreslått struktur (spørsmålsoverskrifter):**")
        for spm in brief.get("foreslatt_struktur", []):
            lines.append(f"- {spm}")
        lines.append(f"**Begrunnelse:** {brief.get('begrunnelse', '')}")
        lines.append("")
    return "\n".join(lines)
