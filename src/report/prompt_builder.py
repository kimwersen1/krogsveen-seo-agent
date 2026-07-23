"""Bygger prompten til Claude fra strukturert analyse-JSON."""
from __future__ import annotations

import json

REPORT_FORMAT = """
1. Hovedbildet (3–5 setninger).
2. Per cluster: snittendring, antall opp/ned, topp 3 bevegelser hver vei. Bruk
   organisk_fotavtrykk (bredere enn de sporede Rank Tracker-ordene — hele domenets
   synlige søkeord per cluster) som context der det er relevant, f.eks. hvis et cluster
   har mange usporede søkeord med god posisjon, eller påfallende få totalt — ikke behandle
   det som samme datakilde som cluster_summaries (ingen uke-mot-uke-delta her ennå).
   Hvert cluster har også ga4_sessions/ga4_key_events (GA4-konverteringer — reelle
   handlinger som verdivurdering_innsendt, nettvurdering_innsendt eller avtalt møte med
   megler, landingsside tagget mot samme cluster-regex). null/manglende felt betyr at
   clusteret ikke hadde noen GA4-økter denne uken, ikke at data mangler.
   IKKE nøy deg med å rapportere GA4-tallene — bruk dem til å avgjøre HVA slags problem
   (eller mulighet) clusteret faktisk har, og si det rett ut:
   - Mange økter, lav/null konverteringsrate → dette er IKKE et rangerings-/synlighets-
     problem, det er et sidenivå-problem (svak CTA, uklart neste steg, dårlig UX/hastighet).
     Foreslå en konkret endring på den spesifikke landingssiden, ikke en generisk "forbedre
     innhold"-anbefaling.
   - Få økter, men god konverteringsrate på de øktene som finnes → siden konverterer godt
     når noen først lander der; problemet er synlighet/volum. Her ER en posisjonsforbedring
     eller bredere søkeordsdekning den riktige anbefalingen.
   - Cluster taper posisjon OG har historisk god konvertering → dette er økonomisk
     viktigere å prioritere enn et cluster som taper posisjon men aldri konverterte uansett.
     Ranger tiltak i seksjon 6 deretter, ikke bare etter størrelsen på posisjonsfallet.
   - Tynt datagrunnlag (under ~50-100 økter) → ikke trekk konklusjoner, si det er for
     tidlig å si noe sikkert i stedet for å tvinge fram et mønster.
3. GEO — egen selvsjekk mot fire LLM-er (geo.claude_selvsjekk / chatgpt_selvsjekk /
   gemini_selvsjekk / perplexity_selvsjekk), samme 36 prompts kjørt mot alle. Dette ER
   ekte data, presenter det som det:
   a) For hver kilde: hvor mange av prompt-ene nevnte Krogsveen vs. hvilke konkurrenter,
      med 1-2 konkrete eksempler. Bruk sentiment/sentiment_begrunnelse der Krogsveen er
      nevnt — nevn eksplisitt om omtalen er positiv/nøytral/negativ og hvorfor.
      Perplexity har i tillegg krogsveen_cited (om krogsveen.no faktisk ble sitert som
      kilde, ikke bare nevnt i teksten) — dette er det sterkeste GEO-signalet av de fire,
      fremhev det spesielt.
      En tom liste for en kilde betyr at API-nøkkelen ikke er konfigurert (valgfritt for
      ChatGPT/Gemini/Perplexity), ikke at kilden ble sjekket og ikke fant noe — vær presis
      på denne forskjellen.
   b) Trekk fram tydelig uenighet mellom kildene der det finnes (f.eks. hvis Krogsveen
      nevnes hos Claude/Gemini men ikke ChatGPT/Perplexity) — det er ofte mer informativt
      enn gjennomsnittet.
   c) Søkeord med ai_overview i SERP (fra Ahrefs rank tracker).
4. Tiltaks-effekt.
5. Avvik (>3 pos / >20 % klikk).
6. Anbefaling for kommende uke (2–3 punkter). Minst ett punkt SKAL være direkte
   utledet av et GA4-funn fra seksjon 2, der datagrunnlaget tillater det (høy trafikk/lav
   konvertering på en spesifikk side = konkret CTA/UX-tiltak; god konvertering på lite
   trafikk = konkret synlighetstiltak). Formuler det som en handling på en navngitt side,
   ikke som "undersøk konverteringen nærmere". Hvis GA4-dataen denne uken er for tynt til
   å gi noe konkret (f.eks. GA4 ikke konfigurert, eller alle clustre under terskelen i
   punkt 2), si det eksplisitt i stedet for å late som om et punkt er GA4-drevet når det
   ikke er det.
Ærlig om datamangler. Ingen rådata-dumper.
""".strip()

SYSTEM_PROMPT = f"""Du skriver en ukentlig SEO/GEO-rapport for krogsveen.no, en norsk eiendomsmegler.
Rapporten skal være konklusjonsdrevet, maks 2 sider, på norsk, og følge nøyaktig denne strukturen:

{REPORT_FORMAT}

Du får strukturert analysedata som JSON — ikke gjenta rådata, syntetiser og konkluder.
Vær ærlig når data mangler (f.eks. en GEO-kilde uten konfigurert API-nøkkel, GSC-hull) i
stedet for å late som alt er komplett.
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
