# Krogsveen SEO/GEO-agent

Automatisert ukentlig SEO/GEO-analyse for krogsveen.no (norsk eiendomsmegler).
Dette dokumentet er komplett kontekst for å bygge systemet. All logikk er validert
manuelt i en Cowork-økt uke 29/2026 — dette er port + utvidelse, ikke nybrottsarbeid.

## Mål

Hver mandag 07:00 (Europe/Oslo): hent ferske data, sammenlign mot forrige uke og
historikk, analyser per cluster, skriv rapport til Google Drive-mappen
«SEO-rapporter Krogsveen» og post kort sammendrag (Slack/e-post, TBD).
Rapporten skal være konklusjonsdrevet, maks 2 sider, på norsk.

## Arkitektur (anbefalt)

1. **Collectors** (deterministisk kode, ikke LLM):
   - Ahrefs API v3 direkte (API-nøkkel, `https://api.ahrefs.com/v3/...`).
     Docs: https://docs.ahrefs.com/docs/api/reference/introduction
   - Google Search Console API direkte via service account (løser dagens datahull —
     Ahrefs' gsc-* endepunkter svarer «No GSC data available» tross fungerende UI-integrasjon).
     Property: `sc-domain:krogsveen.no` eller URL-prefix — verifiser i GSC.
   - Lagre rådata som ukesfiler (parquet/SQLite) → historikk/trender over tid,
     ikke bare uke-mot-uke.
2. **Analyse** (kode): cluster-aggregering, avviksdeteksjon (>3 posisjoner, >20 % klikk),
   tiltaks-tracking (se `tiltak.json`).
3. **LLM-lag**: Claude API skriver rapporttekst fra analyse-output (strukturert JSON inn).
4. **Levering**: Google Drive API (Docs) i mappe-ID `1bHjPT1HVyDvL7StnI1DREpIYc96ofzdg`.
5. **Kjøring**: GitHub Actions cron `0 5 * * 1` (UTC = 07:00 Oslo sommertid) eller server-cron.

## Ahrefs: validerte endepunkter og parametre

- Prosjekt: **project_id 8825594** (Krogsveen, *.www.krogsveen.no/*, 338 sporede søkeord, land NO)
- `rank-tracker/overview`: select `keyword,position,position_prev,volume,url,serp_features`,
  date = i går, date_compared = −7 dager, device desktop (kjør også mobile — volum er ~70 % mobil),
  output csv. **Koster 0 API-enheter.** NB: `serp_features` inneholder `ai_overview` /
  `ai_overview_found` → GEO-signal per søkeord. NB: feltet feilet med 500 én gang sammen med
  csv-output — retry uten serp_features som fallback.
- `site-explorer/domain-rating`: target krogsveen.no (50 enheter per kall).
- `site-explorer/metrics|metrics-history`: trafikk-estimat, mode subdomains.
- Brand Radar (GEO) er **fjernet** (21.07.2026) — begrenset til 5 prompts totalt med
  skrivebeskyttet API (ingen automatisk rotasjon mulig), vurdert for tynt til å gi et
  godt grunnlag. Erstattet av en egen GEO-selvsjekk (se `src/collectors/claude_geo.py`,
  `chatgpt_geo.py`, `gemini_geo.py`, `perplexity_geo.py`) som kjører alle 36
  `geo_prompts` fra `config.json` mot fire reelle LLM-er ukentlig — dekker 4 av Brand
  Radar sine 5 datakilder direkte (ChatGPT/Gemini/Perplexity/Google AI Overviews via
  Ahrefs SERP-features), pluss krogsveen_cited-sporing for Perplexity (siterer
  krogsveen.no som kilde, ikke bare nevner merket — sterkere GEO-signal). Google AI Mode
  har ingen offentlig API og er en akseptert dekningsmangel.
- `subscription-info/limits-and-usage` (gratis): sjekk før kjøring; Lite-plan = 100 000 enheter/mnd.
  Budsjettregel: hopp over enhets-kostende kall hvis >80 % brukt, noter i rapport.

## Cluster-definisjoner (regex mot keyword, case-insensitive)

Se `clusters.json`. Kort: boligverdi (boligverdi|verdt|verdivurdering|eiendomsverdi|
boligkalkulator|e.?takst|takst), boligpriser (boligpris|prisstatistikk|kvadratmeterpris|
eiendomspris|boligmarked), finansiering (finansieringsbevis|boliglån|egenkapital|lånebevis),
forsikring (forsikring|eierskifte), solgte (solgt|eiendomsoverdragelse),
lokal_megler (megler + bynavn), merkevare (krogsveen), kjøp (til salgs|kjøpe bolig|enebolig|
leilighet|gi bud|budrunde). Vurder å tagge ordene i Ahrefs Rank Tracker for renere uttrekk.

## Konkurrenter (benchmark og share-of-voice)

hjemla.no, dnbeiendom.no, eiendomsmegler1.no, privatmegleren.no, nordvikbolig.no,
bolig.ai, eie.no, meglersmart.no (innholdskonkurrent på guides/pris-sider).

## Tiltaks-tracking

`tiltak.json` inneholder alle SEO-tiltak med dato og målside/målord (uke 29-tiltakene
er forhåndsutfylt). Rapporten skal kommentere utviklingen for aktive tiltak spesielt,
og markere tiltak som «bekreftet effekt» / «avventer» / «ingen effekt etter 6 uker».

## Rapportformat

1. Hovedbildet (3–5 setninger). 2. Per cluster: snittendring, antall opp/ned, topp 3
bevegelser hver vei. 3. GEO: selvsjekk-resultater (nevnt/sitert) per LLM-kilde
(Claude/ChatGPT/Gemini/Perplexity), søkeord med ai_overview i SERP. 4. Tiltaks-effekt.
5. Avvik (>3 pos / >20 % klikk). 6. Anbefaling for kommende uke (2–3 punkter).
Ærlig om datamangler. Ingen rådata-dumper.

## Kjente forhold / fallgruver

- GSC via Ahrefs API gir tomt svar tross fungerende UI-kobling → bygg GSC direkte
  (løst: OAuth med brukerens egen konto, se `src/collectors/gsc_oauth.py`).
- Rank Tracker-data har mange null-posisjoner på desktop; kjør mobile i tillegg.
- «Basic»-verifisering i Ahrefs-prosjektet; ikke alle 400 ord returneres (fikk 100 rader
  ved limit 400 — undersøk paginering).
- Baseline-analysen (uke 29) med alle funn ligger i rapporten
  «SEO-ukerapport Krogsveen – uke 29 2026» i Drive-mappen, og i Cowork-øktens
  leveranser (crawl-rapport, backlog, metatitler — se `docs/`).
- En Cowork-scheduled task («ukentlig-seo-geo-rapport-krogsveen») kjører samme analyse
  enklere. **Deaktiver den når denne pipelinen er i produksjon** for å unngå dobbeltrapport.

## Roadmap etter v1

1. ~~GSC direkte + klikk/CTR-lag i rapporten.~~ **Ferdig** — OAuth med brukerens egen
   konto (`src/collectors/gsc_oauth.py`), engangsoppsett via `scripts/gsc_auth_setup.py`.
2. ~~Historikk-database → trendgrafer (4/12 ukers glidende).~~ **Ferdig** — SQLite
   (`data/history.db`), posisjon/klikk/organisk fotavtrykk over tid.
3. ~~Live dashboard.~~ **Ferdig** — statisk side (`docs/index.html`) generert per
   kjøring, publisert via GitHub Pages, pluss Google Sheet-versjon.
4. SERP-vakt: varsle når AI Overview dukker opp på cluster-ord, eller konkurrent
   passerer på topp-ord (rank-tracker/competitors-overview). Ikke bygget ennå.
5. ~~Månedlig GEO-stikkprøve mot ChatGPT/Perplexity (supplement til Brand Radar).~~
   **Ferdig, og utvidet langt forbi opprinnelig plan** — ukentlig (ikke månedlig)
   selvsjekk mot fire LLM-er (Claude/ChatGPT/Gemini/Perplexity), 36 prompts hver, med
   sentiment og (for Perplexity) faktisk sitat-sporing. Erstatter Brand Radar helt,
   ikke bare et supplement.
6. Sporbare "aktive forslag" — anbefalinger fra rapporten koblet til `tiltak.json` med
   status som kan markeres utført, ikke bare tekst som forsvinner etter én uke.
7. GA4-integrasjon for ekte konverteringsdata (leads, kontaktskjema, budforespørsler
   per landingsside/cluster).
