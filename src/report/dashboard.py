"""Genererer en statisk HTML-dashboard fra ukens analyse-data + historikk fra SQLite.

Filen skrives til docs/index.html i prosjektroten — GitHub Pages kan servere direkte
fra en /docs-mappe på main uten egen build-branch. GitHub Actions committer og pusher
filen etter hver ukentlig kjøring (se .github/workflows/weekly-report.yml), så siden
er "levende" uten at noen manuelt må gjøre noe utover initial Pages-oppsett.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "index.html"


def build_dashboard_payload(
    analysis: dict,
    position_trend: list[dict],
    clicks_trend: list[dict],
    competitor_benchmark: list[dict],
    report_date: date,
    footprint_trend: list[dict] | None = None,
    position_trend_desktop: list[dict] | None = None,
) -> dict:
    return {
        "generated": report_date.isoformat(),
        "uke": analysis["uke"],
        "ar": analysis["ar"],
        "domain_rating": analysis.get("domain_rating"),
        "site_metrics": analysis.get("site_metrics"),
        "gsc_site": analysis.get("gsc_site", []),
        "gsc_kilde": analysis.get("gsc_kilde", "ingen"),
        # cluster_summaries og organisk_fotavtrykk brukes ikke lenger av HTML-dashboardet
        # (fjernet 03.08.2026 — leste som generisk søkeordsstøy uten kobling til faktisk
        # utført arbeid), men holdes i payloaden fordi build_sheet_payload under fortsatt
        # bruker dem til Google Sheets-versjonen av dashboardet.
        "cluster_summaries": analysis.get("cluster_summaries", []),
        "geo": analysis.get("geo", {}),
        "tiltak": analysis.get("tiltak", []),
        "anbefaling": analysis.get("anbefaling", []),
        "innholdsforslag_dokument": analysis.get("innholdsforslag_dokument"),
        "organisk_fotavtrykk": analysis.get("organisk_fotavtrykk", {}),
        "datamangler": analysis.get("datamangler", []),
        "position_trend": position_trend,
        "position_trend_desktop": position_trend_desktop or [],
        "clicks_trend": clicks_trend,
        "footprint_trend": footprint_trend or [],
        "competitor_benchmark": competitor_benchmark,
    }


def build_sheet_payload(dashboard_payload: dict) -> dict:
    """Flat versjon av dashboard-payloaden, tilpasset Google Sheets-skriveren
    (se src/report/sheets_writer.py) — samme kildedata, enklere struktur."""
    geo = dashboard_payload.get("geo", {})
    claude_rows = geo.get("claude_selvsjekk", [])
    chatgpt_rows = geo.get("chatgpt_selvsjekk", [])
    gemini_rows = geo.get("gemini_selvsjekk", [])
    perplexity_rows = geo.get("perplexity_selvsjekk", [])
    site_metrics = dashboard_payload.get("site_metrics") or {}
    domain_rating = dashboard_payload.get("domain_rating") or {}
    all_device = next((r for r in dashboard_payload.get("gsc_site", []) if r.get("device") == "all"), {})

    return {
        "generated": dashboard_payload["generated"],
        "uke": dashboard_payload["uke"],
        "ar": dashboard_payload["ar"],
        "domain_rating": domain_rating.get("domain_rating"),
        "org_traffic": site_metrics.get("org_traffic"),
        "gsc_clicks": all_device.get("clicks"),
        "ai_overview_count": len(geo.get("ai_overview_sokeord", [])),
        "ai_overview_sokeord": geo.get("ai_overview_sokeord", [])[:30],
        "anbefaling": dashboard_payload.get("anbefaling", []),
        "innholdsforslag_dokument": dashboard_payload.get("innholdsforslag_dokument"),
        "organisk_fotavtrykk_total": dashboard_payload.get("organisk_fotavtrykk", {}).get("total_sokeord"),
        "organisk_fotavtrykk_cluster": dashboard_payload.get("organisk_fotavtrykk", {}).get("cluster_summary", []),
        "claude_mentions": sum(1 for r in claude_rows if r.get("krogsveen_mentioned")),
        "claude_total": len(claude_rows),
        "chatgpt_mentions": sum(1 for r in chatgpt_rows if r.get("krogsveen_mentioned")),
        "chatgpt_total": len(chatgpt_rows),
        "gemini_mentions": sum(1 for r in gemini_rows if r.get("krogsveen_mentioned")),
        "gemini_total": len(gemini_rows),
        "perplexity_mentions": sum(1 for r in perplexity_rows if r.get("krogsveen_mentioned")),
        "perplexity_cited": sum(1 for r in perplexity_rows if r.get("krogsveen_cited")),
        "perplexity_total": len(perplexity_rows),
        "avg_position": (
            dashboard_payload["position_trend"][-1]["avg_position"] if dashboard_payload.get("position_trend") else None
        ),
        "cluster_summaries": dashboard_payload.get("cluster_summaries", []),
        "claude_selvsjekk": claude_rows,
        "chatgpt_selvsjekk": chatgpt_rows,
        "gemini_selvsjekk": gemini_rows,
        "perplexity_selvsjekk": perplexity_rows,
        "tiltak": dashboard_payload.get("tiltak", []),
        "competitor_benchmark": dashboard_payload.get("competitor_benchmark", []),
    }


def render_dashboard(payload: dict, output_path: Path = OUTPUT_PATH) -> Path:
    html = _TEMPLATE.replace("__DASHBOARD_DATA__", json.dumps(payload, ensure_ascii=False))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("Dashboard skrevet til %s", output_path)
    return output_path


def update_content_briefs_section(meta: dict | None, output_path: Path = OUTPUT_PATH) -> Path | None:
    """Patcher KUN innholdsforslag-kortet i den allerede publiserte dashboard-HTML-en, uten
    å røre resten av siden (payload['generated'] og alt annet er fra forrige ukentlige
    kjøring, ikke denne). Brukt av scripts/keyword_discovery.py --to-drive, som ikke har
    (og ikke bør hente på nytt for) resten av ukesrapportens analysedata — kun den
    bi-ukentlige jobbens egen del av siden.

    Oppdaget 18.08.2026: uten dette lå dashboardets 'sist oppdatert'-dato på innholdsforslag
    fast til neste mandags fulle pipeline-kjøring, selv om selve Drive-dokumentet og
    historikken i data/history.db var korrekt oppdatert med det samme av
    scripts/keyword_discovery.py. Samme mønster som d8565d8/011fddb-fiksene, men for det
    normale, løpende tilfellet fremover i stedet for en engangsretting."""
    if not output_path.exists():
        logger.warning("Fant ikke %s — kan ikke oppdatere innholdsforslag-kortet uten en eksisterende dashboard.", output_path)
        return None
    html = output_path.read_text(encoding="utf-8")
    match = re.search(r'<script id="dashboard-data" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not match:
        logger.warning("Fant ikke dashboard-data-payloaden i %s — hopper over oppdatering.", output_path)
        return None
    payload = json.loads(match.group(1))
    payload["innholdsforslag_dokument"] = meta
    return render_dashboard(payload, output_path)


_TEMPLATE = r"""<!doctype html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Krogsveen SEO/GEO — Live-status</title>
<style>
  :root {
    color-scheme: light;
    --bg-page: #EAEDE5; --bg-surface: #F6F7F1; --bg-surface-2: #EEF1E7;
    --ink: #14170F; --ink-2: #4B5147; --ink-muted: #83887C;
    --line: #D9DCD0; --line-strong: #C3C7B7;
    --accent: #0C8A75; --accent-soft: #DCEAE5;
    --brass: #8A5E17;
    --series-1: #0C8A75; --series-2: #b8791f; --series-3: #8B93A6;
    --good: #0ca30c; --good-soft: #DCF0DA;
    --warning: #9a6a00; --warning-soft: #FBE9C4;
    --critical: #b23327; --critical-soft: #F8DFDA;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      color-scheme: dark;
      --bg-page: #0F120B; --bg-surface: #181B12; --bg-surface-2: #1E2217;
      --ink: #ECEADF; --ink-2: #C3C7B4; --ink-muted: #8B9080;
      --line: #2B2F24; --line-strong: #3A3F30;
      --accent: #4CB59D; --accent-soft: #1C2B24;
      --brass: #D9A857;
      --series-1: #2E9A84; --series-2: #B4823F; --series-3: #7C859C;
      --good: #4CAE55; --good-soft: #16281A;
      --warning: #D9A857; --warning-soft: #322A15;
      --critical: #E08277; --critical-soft: #301917;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --bg-page: #0F120B; --bg-surface: #181B12; --bg-surface-2: #1E2217;
    --ink: #ECEADF; --ink-2: #C3C7B4; --ink-muted: #8B9080;
    --line: #2B2F24; --line-strong: #3A3F30;
    --accent: #4CB59D; --accent-soft: #1C2B24; --brass: #D9A857;
    --series-1: #2E9A84; --series-2: #B4823F; --series-3: #7C859C;
    --good: #4CAE55; --good-soft: #16281A;
    --warning: #D9A857; --warning-soft: #322A15;
    --critical: #E08277; --critical-soft: #301917;
  }
  :root[data-theme="light"] {
    color-scheme: light;
    --bg-page: #EAEDE5; --bg-surface: #F6F7F1; --bg-surface-2: #EEF1E7;
    --ink: #14170F; --ink-2: #4B5147; --ink-muted: #83887C;
    --line: #D9DCD0; --line-strong: #C3C7B7;
    --accent: #0C8A75; --accent-soft: #DCEAE5; --brass: #8A5E17;
    --series-1: #0C8A75; --series-2: #b8791f; --series-3: #8B93A6;
    --good: #0ca30c; --good-soft: #DCF0DA;
    --warning: #9a6a00; --warning-soft: #FBE9C4;
    --critical: #b23327; --critical-soft: #F8DFDA;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg-page); color: var(--ink);
    font-family: -apple-system, "Segoe UI", ui-sans-serif, system-ui, sans-serif;
    font-size: 15px; line-height: 1.5; padding: 40px 24px 80px;
  }
  .wrap { max-width: 1100px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }
  h1, h2 { font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif; font-weight: 600; text-wrap: balance; margin: 0; }
  .num { font-variant-numeric: tabular-nums; }
  .masthead { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--line-strong); padding-bottom: 18px; }
  .eyebrow { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); font-weight: 600; margin-bottom: 6px; }
  .masthead h1 { font-size: 26px; }
  .masthead .sub { color: var(--ink-2); font-size: 13.5px; margin-top: 6px; }
  .chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
  .chip { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--line-strong); background: var(--bg-surface); color: var(--ink-2); }
  .chip .dot { width: 6px; height: 6px; border-radius: 50%; }
  .chip.ok { color: var(--good); background: var(--good-soft); border-color: color-mix(in srgb, var(--good) 40%, var(--line-strong)); }
  .chip.ok .dot { background: var(--good); }
  .chip.blocked { color: var(--critical); background: var(--critical-soft); border-color: color-mix(in srgb, var(--critical) 40%, var(--line-strong)); }
  .chip.blocked .dot { background: var(--critical); }
  .stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--line); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
  .stat-tile { background: var(--bg-surface); padding: 16px 16px 14px; display: flex; flex-direction: column; gap: 5px; }
  .stat-tile .label { font-size: 11.5px; color: var(--ink-muted); }
  .stat-tile .value { font-size: 24px; font-weight: 600; }
  .stat-tile .delta { font-size: 12px; color: var(--ink-2); }
  .card { background: var(--bg-surface); border: 1px solid var(--line); border-radius: 12px; padding: 20px 22px; }
  .card h2 { font-size: 16px; margin-bottom: 3px; }
  .card .card-sub { font-size: 12.5px; color: var(--ink-muted); margin-bottom: 14px; }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
  @media (max-width: 800px) { .two-col { grid-template-columns: 1fr; } .stat-grid { grid-template-columns: repeat(2, 1fr); } }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { text-align: right; padding: 7px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  th { color: var(--ink-muted); font-weight: 500; font-size: 11px; text-transform: uppercase; border-bottom: 1px solid var(--line-strong); }
  td { font-variant-numeric: tabular-nums; }
  tr.self td { background: var(--accent-soft); font-weight: 600; }
  .table-scroll { overflow-x: auto; }
  .cluster-delta { text-align: right; font-weight: 600; }
  .cluster-delta.up { color: var(--good); }
  .cluster-delta.down { color: var(--critical); }
  .cluster-delta.flat { color: var(--ink-muted); }
  .geo-item { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; }
  .geo-item:last-child { margin-bottom: 0; }
  .geo-item-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 5px; }
  .geo-item-head .title { font-weight: 600; font-size: 13.5px; }
  .status-chip { font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.02em; padding: 2px 8px; border-radius: 999px; }
  .status-chip.ok { color: var(--good); background: var(--good-soft); }
  .status-chip.blocked { color: var(--critical); background: var(--critical-soft); }
  .geo-item p { margin: 0; font-size: 12.5px; color: var(--ink-2); }
  .prompt-row { display: flex; justify-content: space-between; gap: 10px; padding: 4px 0; font-size: 12.5px; border-bottom: 1px dashed var(--line); }
  .prompt-row:last-child { border-bottom: none; }
  .prompt-row .p { color: var(--ink-2); }
  .prompt-row .mentioned { font-weight: 600; }
  .prompt-row .mentioned.yes { color: var(--good); }
  .prompt-row .mentioned.no { color: var(--ink-muted); }
  .chart-frame { position: relative; }
  svg.chart { width: 100%; height: auto; overflow: visible; }
  .gridline { stroke: var(--line); stroke-width: 1; }
  .axis-text { fill: var(--ink-muted); font-size: 10px; font-family: ui-monospace, "SF Mono", monospace; }
  .series-line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
  .series-dot { stroke: var(--bg-surface); stroke-width: 2; }
  .empty-note { font-size: 12.5px; color: var(--ink-muted); padding: 30px 0; text-align: center; }
  .tiltak-status { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; text-transform: uppercase; }
  .tiltak-status.bekreftet { color: var(--good); background: var(--good-soft); }
  .tiltak-status.avventer { color: var(--warning); background: var(--warning-soft); }
  .tiltak-status.ingen { color: var(--critical); background: var(--critical-soft); }
  .tiltak-status.ikke_vurdert { color: var(--ink-muted); background: var(--bg-surface-2); }
  footer { border-top: 1px solid var(--line-strong); padding-top: 14px; font-size: 11.5px; color: var(--ink-muted); display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; }
  footer .gap-note { color: var(--warning); }
  .mono { font-family: ui-monospace, "SF Mono", monospace; }
</style>
</head>
<body>
<div class="wrap">
  <div class="masthead">
    <div>
      <div class="eyebrow">Live SEO / GEO-status</div>
      <h1>Krogsveen.no</h1>
      <div class="sub" id="sub-date"></div>
      <div class="chip-row" id="chip-row"></div>
    </div>
  </div>

  <div class="stat-grid" id="stat-grid"></div>

  <div class="card" id="anbefaling-card" style="display:none">
    <h2>Anbefaling for neste uke</h2>
    <div class="card-sub">Hentet fra ukens rapporttekst</div>
    <ul id="anbefaling-list" style="margin:0;padding-left:18px;font-size:13px;color:var(--ink-2);display:flex;flex-direction:column;gap:6px;"></ul>
  </div>

  <div class="card" id="innholdsforslag-card" style="display:none">
    <h2>Innholdsforslag</h2>
    <div class="card-sub">2-3 grundige forslag (SEO + GEO), oppdatert to ganger i måneden med søkeordsgap mot konkurrenter</div>
    <a id="innholdsforslag-link" href="#" target="_blank" rel="noopener" style="font-size:13.5px; font-weight: 600; color: var(--accent);"></a>
    <div id="innholdsforslag-updated" style="font-size:12px; color: var(--ink-muted); margin-top: 4px;"></div>
  </div>

  <div class="two-col">
    <div class="card">
      <h2>Snittposisjon over tid</h2>
      <div class="card-sub" id="position-chart-sub">Alle sporede søkeord — mobil (~70 % av søkevolumet, primærkilde ellers på siden) og desktop</div>
      <div id="position-chart"></div>
    </div>
    <div class="card">
      <h2>GSC-klikk over tid</h2>
      <div class="card-sub">Site-wide, via Ahrefs</div>
      <div id="clicks-chart"></div>
    </div>
  </div>

  <div class="card" id="ga4-card" style="display:none">
    <h2>AI-referral-trafikk <span id="ga4-period-badge" class="card-sub" style="font-weight:normal"></span></h2>
    <div class="card-sub">Faktiske økter fra AI-chatter (GA4) — selvsjekken lenger ned viser om Krogsveen nevnes, dette viser om noen faktisk klikker seg inn. Lavvolum-tall, derfor et lengre vindu enn resten av siden (som viser denne uken).</div>
    <div class="table-scroll"><table id="ga4-table"><thead><tr><th>Kilde</th><th>Økter</th><th>Engasjement</th><th>Konverteringer</th></tr></thead><tbody></tbody></table></div>
  </div>

  <div class="card">
    <h2>Effekt av arbeidet ditt</h2>
    <div class="card-sub">Hvert tiltak i tiltak.json, med faktisk posisjon (mobil og desktop) første → siste kjente uke per målord — ikke bare en statusetikett. Status beregnes fra mobil, primærkilden ellers på siden.</div>
    <div class="table-scroll"><table id="tiltak-table"><thead><tr><th>Side</th><th>Målord</th><th>Posisjon</th><th>Status</th><th>Uker aktiv</th></tr></thead><tbody></tbody></table></div>
  </div>

  <div class="card">
    <h2>Konkurrentbenchmark</h2>
    <div class="card-sub">Domain Rating og org. trafikk, denne uken</div>
    <div class="table-scroll"><table id="competitor-table"><thead><tr><th>Domene</th><th>DR</th><th>Org. trafikk/mnd</th></tr></thead><tbody></tbody></table></div>
  </div>

  <div class="card">
    <h2>Søkeord med AI Overview i SERP</h2>
    <div class="card-sub" id="ai-overview-sub"></div>
    <div id="ai-overview-list"></div>
  </div>

  <div class="card" id="ai-responses-card" style="display:none">
    <h2>AI-siteringer (domenevidt)</h2>
    <div class="card-sub">Antall siteringer av krogsveen.no i AI-plattformers svar, HELE domenet — ikke begrenset til de 338 sporede ordene over. Ahrefs' egen siterings-telling, separat fra selvsjekken under.</div>
    <div class="table-scroll"><table id="ai-responses-table"><thead><tr><th>Platform</th><th>Siteringer</th><th>Sider</th></tr></thead><tbody></tbody></table></div>
  </div>

  <div class="card">
    <h2>GEO / AI-synlighet</h2>
    <div class="card-sub">Egen selvsjekk mot Claude, ChatGPT, Gemini og Perplexity — ekte data, 36 prompts hver</div>
    <div id="geo-panel"></div>
  </div>

  <footer>
    <span id="footer-source"></span>
    <span class="gap-note" id="footer-gaps"></span>
  </footer>
</div>

<script id="dashboard-data" type="application/json">__DASHBOARD_DATA__</script>
<script>
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("dashboard-data").textContent);
  var fmt = new Intl.NumberFormat("nb-NO");
  var svgNS = "http://www.w3.org/2000/svg";

  document.getElementById("sub-date").textContent =
    "Uke " + data.uke + " " + data.ar + " — generert " + data.generated;

  // ---- Chips ----
  var chipRow = document.getElementById("chip-row");
  function addChip(label, ok) {
    var span = document.createElement("span");
    span.className = "chip " + (ok ? "ok" : "blocked");
    span.innerHTML = '<span class="dot"></span>' + label;
    chipRow.appendChild(span);
  }
  addChip("Ahrefs Rank Tracker", true);
  var gscLabels = {
    oauth: ["GSC (direkte, OAuth)", true],
    csv: ["GSC (manuell CSV)", true],
    ingen: ["GSC (ikke konfigurert)", false]
  };
  var gscChip = gscLabels[data.gsc_kilde] || gscLabels.ingen;
  addChip(gscChip[0], gscChip[1]);
  addChip("Claude-selvsjekk", true);
  if ((data.geo.chatgpt_selvsjekk || []).length) {
    addChip("ChatGPT-selvsjekk", true);
  }
  if ((data.geo.gemini_selvsjekk || []).length) {
    addChip("Gemini-selvsjekk", true);
  }
  if ((data.geo.perplexity_selvsjekk || []).length) {
    addChip("Perplexity-selvsjekk", true);
  }

  // ---- Stat tiles ----
  var statGrid = document.getElementById("stat-grid");
  function addStat(label, value, delta, deltaClass) {
    var tile = document.createElement("div");
    tile.className = "stat-tile";
    tile.innerHTML =
      '<div class="label">' + label + '</div>' +
      '<div class="value num">' + value + '</div>' +
      (delta ? '<div class="delta' + (deltaClass ? " cluster-delta " + deltaClass : "") + '">' + delta + '</div>' : "");
    statGrid.appendChild(tile);
  }

  // ---- Snittposisjon-trend (mobil) — svarer på "har siden generelt blitt sterkere?" ved
  // å sammenligne eldste og nyeste uke i vinduet. Vises som tekst under selve grafen den
  // beskriver, ikke som egen firkant i stat-gridet (bruker ba om dette 03.08.2026). ----
  var posTrend = data.position_trend || [];
  var posSubEl = document.getElementById("position-chart-sub");
  if (posTrend.length >= 2) {
    var oldestPos = posTrend[0].avg_position;
    var newestPos = posTrend[posTrend.length - 1].avg_position;
    var posDiff = oldestPos - newestPos; // positivt = forbedring (lavere posisjon er bedre)
    var posLabel = posDiff > 0.05 ? "bedre" : (posDiff < -0.05 ? "svakere" : "uendret");
    posSubEl.textContent =
      "Alle sporede søkeord — mobil (~70 % av søkevolumet, primærkilde ellers på siden) og desktop — mobil " +
      Math.abs(posDiff).toFixed(1) + " plasser " + posLabel + " siste " + (posTrend.length - 1) + " uker.";
  }

  // Rad 1: generelle SEO-nøkkeltall. Rad 2: GEO-selvsjekk per kilde — 8 ruter totalt
  // for en jevn 4x2-rutenett (bruker ba om dette 22.07.2026).
  addStat("Domain Rating", data.domain_rating ? data.domain_rating.domain_rating || "–" : "–");
  addStat("Org. trafikk/mnd", data.site_metrics ? fmt.format(data.site_metrics.org_traffic || 0) : "–");
  var allDevice = (data.gsc_site || []).find(function (r) { return r.device === "all"; });
  addStat("GSC-klikk (uke)", allDevice ? fmt.format(allDevice.clicks) : "–",
    allDevice ? fmt.format(allDevice.impressions) + " visninger" : "");
  var aiCount = (data.geo.ai_overview_sokeord || []).length;
  addStat("AI Overview-eksponering", aiCount, "av 338 sporede søkeord — se domenevid siteringstelling lenger ned for full bredde");

  function addSelfcheckStat(label, rows) {
    var mentions = (rows || []).filter(function (r) { return r.krogsveen_mentioned; }).length;
    addStat(label, mentions + " / " + (rows || []).length, "av kjørte GEO-prompts");
  }
  addSelfcheckStat("Claude nevner Krogsveen", data.geo.claude_selvsjekk);
  addSelfcheckStat("ChatGPT nevner Krogsveen", data.geo.chatgpt_selvsjekk);
  addSelfcheckStat("Gemini nevner Krogsveen", data.geo.gemini_selvsjekk);
  var perplexityRows = data.geo.perplexity_selvsjekk || [];
  var perplexityCited = perplexityRows.filter(function (r) { return r.krogsveen_cited; }).length;
  addStat("Perplexity siterer Krogsveen", perplexityCited + " / " + perplexityRows.length, "av kjørte GEO-prompts");

  // ---- Anbefaling for neste uke ----
  var anbefaling = data.anbefaling || [];
  if (anbefaling.length) {
    document.getElementById("anbefaling-card").style.display = "";
    var anbefalingList = document.getElementById("anbefaling-list");
    anbefaling.forEach(function (point) {
      var li = document.createElement("li");
      li.textContent = point;
      anbefalingList.appendChild(li);
    });
  }

  // ---- Innholdsforslag (lenke til eget dokument, ikke inline punktliste) ----
  var briefsDoc = data.innholdsforslag_dokument;
  if (briefsDoc && briefsDoc.url) {
    document.getElementById("innholdsforslag-card").style.display = "";
    var link = document.getElementById("innholdsforslag-link");
    link.href = briefsDoc.url;
    link.textContent = "Åpne innholdsforslag (" + (briefsDoc.antall_forslag || "?") + " forslag) →";
    document.getElementById("innholdsforslag-updated").textContent = "Sist oppdatert " + briefsDoc.updated_at;
  }

  // ---- AI Overview-søkeord ----
  var aiRows = data.geo.ai_overview_sokeord || [];
  document.getElementById("ai-overview-sub").textContent = aiRows.length + " søkeord denne uken (mobil)";
  var aiList = document.getElementById("ai-overview-list");
  aiRows.forEach(function (r) {
    var row = document.createElement("div");
    row.className = "prompt-row";
    row.innerHTML = '<span class="p">' + r.keyword + '</span><span class="mentioned">' + (r.clusters || []).join(", ") + '</span>';
    aiList.appendChild(row);
  });
  if (!aiRows.length) {
    aiList.innerHTML = '<div class="empty-note">Ingen søkeord med AI Overview denne uken</div>';
  }

  // ---- AI-siteringer (domenevidt) — Ahrefs' ai-responses-count, se ahrefs.py ----
  var aiResponses = data.geo.ai_responses_count;
  if (aiResponses) {
    document.getElementById("ai-responses-card").style.display = "";
    var AI_RESPONSES_LABELS = {
      google_ai_overviews_keywords: "Google AI Overviews",
      google_ai_mode: "Google AI Mode",
      chatgpt: "ChatGPT",
      gemini: "Gemini",
      perplexity: "Perplexity",
      copilot: "Copilot",
      grok: "Grok",
    };
    var arBody = document.querySelector("#ai-responses-table tbody");
    Object.keys(AI_RESPONSES_LABELS).forEach(function (key) {
      var v = aiResponses[key];
      if (!v) return;
      var tr = document.createElement("tr");
      tr.innerHTML =
        '<td>' + AI_RESPONSES_LABELS[key] + '</td>' +
        '<td class="num">' + fmt.format(v.citations || 0) + '</td>' +
        '<td class="num">' + fmt.format(v.pages || 0) + '</td>';
      arBody.appendChild(tr);
    });
  }

  // ---- Trend charts. Tar en liste av serier (points/color/label) i stedet for én, slik
  // at Snittposisjon-grafen kan vise mobil OG desktop side ved side — bruker ba om dette
  // 03.08.2026 fordi mobil-only skjuler akkurat den typen avvik (desktop ↔ mobil motsatt
  // retning) som var grunnen til at vi byttet primærkilde til mobil i utgangspunktet. ----
  function renderTrendChart(containerId, seriesList, valueKey) {
    var container = document.getElementById(containerId);
    seriesList = (seriesList || []).filter(function (s) { return s.points && s.points.length; });
    if (!seriesList.length || seriesList[0].points.length < 2) {
      var n = seriesList.length ? seriesList[0].points.length : 0;
      container.innerHTML = '<div class="empty-note">Bygger historikk — for få uker med data ennå (' + n + ' registrert)</div>';
      return;
    }
    var weeks = seriesList[0].points.map(function (p) { return p.week_start; });
    var W = 420, H = 160, M = { top: 10, right: 10, bottom: 24, left: 44 };
    var plotW = W - M.left - M.right, plotH = H - M.top - M.bottom;
    var allValues = [];
    seriesList.forEach(function (s) { s.points.forEach(function (p) { allValues.push(p[valueKey]); }); });
    var minV = Math.min.apply(null, allValues), maxV = Math.max.apply(null, allValues);
    if (minV === maxV) { minV -= 1; maxV += 1; }
    var pad = (maxV - minV) * 0.15;
    minV -= pad; maxV += pad;

    function x(i) { return M.left + (plotW * i) / (weeks.length - 1); }
    function y(v) { return M.top + plotH - (plotH * (v - minV)) / (maxV - minV); }

    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("class", "chart");
    [0, 0.5, 1].forEach(function (t) {
      var v = minV + (maxV - minV) * t;
      var yy = y(v);
      var line = document.createElementNS(svgNS, "line");
      line.setAttribute("x1", M.left); line.setAttribute("x2", W - M.right);
      line.setAttribute("y1", yy); line.setAttribute("y2", yy);
      line.setAttribute("class", "gridline");
      svg.appendChild(line);
      var text = document.createElementNS(svgNS, "text");
      text.setAttribute("x", M.left - 8); text.setAttribute("y", yy + 3);
      text.setAttribute("class", "axis-text"); text.setAttribute("text-anchor", "end");
      text.textContent = valueKey === "avg_position" ? v.toFixed(1) : fmt.format(Math.round(v));
      svg.appendChild(text);
    });
    seriesList.forEach(function (s) {
      var byWeek = {};
      s.points.forEach(function (p) { byWeek[p.week_start] = p; });
      var d = "", started = false;
      weeks.forEach(function (w, i) {
        var p = byWeek[w];
        if (!p || p[valueKey] == null) { started = false; return; }
        d += (started ? "L" : "M") + x(i) + "," + y(p[valueKey]) + " ";
        started = true;
      });
      var path = document.createElementNS(svgNS, "path");
      path.setAttribute("d", d.trim()); path.setAttribute("class", "series-line"); path.setAttribute("stroke", s.color);
      svg.appendChild(path);
      weeks.forEach(function (w, i) {
        var p = byWeek[w];
        if (!p || p[valueKey] == null) return;
        var c = document.createElementNS(svgNS, "circle");
        c.setAttribute("cx", x(i)); c.setAttribute("cy", y(p[valueKey])); c.setAttribute("r", 3.5);
        c.setAttribute("fill", s.color); c.setAttribute("class", "series-dot");
        svg.appendChild(c);
      });
    });
    weeks.forEach(function (w, i) {
      var lbl = document.createElementNS(svgNS, "text");
      lbl.setAttribute("x", x(i)); lbl.setAttribute("y", H - M.bottom + 14);
      lbl.setAttribute("class", "axis-text"); lbl.setAttribute("text-anchor", "middle");
      lbl.textContent = (w || "").slice(5);
      svg.appendChild(lbl);
    });
    container.appendChild(svg);
    if (seriesList.length > 1) {
      var legend = document.createElement("div");
      legend.style.cssText = "display:flex;gap:14px;font-size:11.5px;color:var(--ink-muted);margin-top:4px;";
      seriesList.forEach(function (s) {
        var item = document.createElement("span");
        item.innerHTML = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + s.color + ';margin-right:5px;"></span>' + s.label;
        legend.appendChild(item);
      });
      container.appendChild(legend);
    }
  }
  var series1Color = getComputedStyle(document.body).getPropertyValue("--series-1").trim();
  var series2Color = getComputedStyle(document.body).getPropertyValue("--series-2").trim();
  var series3Color = getComputedStyle(document.body).getPropertyValue("--series-3").trim();
  renderTrendChart("position-chart", [
    { points: data.position_trend, color: series1Color, label: "Mobil" },
    { points: data.position_trend_desktop, color: series3Color, label: "Desktop" }
  ], "avg_position");
  renderTrendChart("clicks-chart", [{ points: data.clicks_trend, color: series2Color, label: "Klikk" }], "clicks");

  // ---- GEO panel ----
  var geoPanel = document.getElementById("geo-panel");

  function renderSelfcheckPanel(title, rows) {
    var item = document.createElement("div");
    item.className = "geo-item";
    var html = '<div class="geo-item-head"><span class="title">' + title + '</span><span class="status-chip ok">Live data</span></div>';
    rows.forEach(function (r) {
      var mentioned = r.krogsveen_mentioned;
      var label = "–";
      if (mentioned) {
        label = "Nevnt";
        if (typeof r.krogsveen_cited !== "undefined") {
          label += r.krogsveen_cited ? " · sitert" : " · ikke sitert";
        }
        if (r.sentiment) { label += " · " + r.sentiment; }
      }
      html += '<div class="prompt-row"><span class="p">' + r.prompt + '</span><span class="mentioned ' + (mentioned ? "yes" : "no") + '">' + label + '</span></div>';
    });
    item.innerHTML = html;
    geoPanel.appendChild(item);
  }
  renderSelfcheckPanel("Claude-selvsjekk", data.geo.claude_selvsjekk || []);
  if ((data.geo.chatgpt_selvsjekk || []).length) {
    renderSelfcheckPanel("ChatGPT-selvsjekk", data.geo.chatgpt_selvsjekk);
  }
  if ((data.geo.gemini_selvsjekk || []).length) {
    renderSelfcheckPanel("Gemini-selvsjekk", data.geo.gemini_selvsjekk);
  }
  if ((data.geo.perplexity_selvsjekk || []).length) {
    renderSelfcheckPanel("Perplexity-selvsjekk", data.geo.perplexity_selvsjekk);
  }

  // ---- GA4 AI-referral-tabell ----
  var ga4Rows = data.geo.ga4_ai_referral || [];
  if (ga4Rows.length) {
    document.getElementById("ga4-card").style.display = "";
    var ga4Days = data.geo.ga4_ai_referral_periode_dager;
    document.getElementById("ga4-period-badge").textContent = ga4Days ? "(siste " + ga4Days + " dager)" : "";
    var ga4Body = document.querySelector("#ga4-table tbody");
    ga4Rows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        '<td class="mono">' + r.source + '</td>' +
        '<td>' + fmt.format(r.sessions || 0) + '</td>' +
        '<td>' + (r.engagement_rate != null ? r.engagement_rate + "%" : "–") + '</td>' +
        '<td>' + (r.conversions || 0) + '</td>';
      ga4Body.appendChild(tr);
    });
  }

  // ---- Competitor table ----
  var compBody = document.querySelector("#competitor-table tbody");
  (data.competitor_benchmark || []).forEach(function (row) {
    var tr = document.createElement("tr");
    tr.innerHTML =
      '<td class="mono">' + row.domain + '</td>' +
      '<td>' + (row.domain_rating != null ? row.domain_rating : "–") + '</td>' +
      '<td>' + (row.org_traffic != null ? fmt.format(row.org_traffic) : "–") + '</td>';
    compBody.appendChild(tr);
  });
  if (!data.competitor_benchmark || !data.competitor_benchmark.length) {
    compBody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--ink-muted)">Ingen data denne uken (budsjett-hopp over eller første kjøring)</td></tr>';
  }

  // ---- Tiltak table ----
  var STATUS_CLASS = {
    "bekreftet effekt": "bekreftet",
    "avventer": "avventer",
    "ingen effekt etter 6 uker": "ingen",
    "ikke_vurdert": "ikke_vurdert"
  };
  var tiltakBody = document.querySelector("#tiltak-table tbody");
  (data.tiltak || []).forEach(function (t) {
    var statusKey = STATUS_CLASS[t.status_vurdering] || "ikke_vurdert";
    var tr = document.createElement("tr");
    var desktopByMalord = {};
    (t.malord_posisjoner_desktop || []).forEach(function (mp) { desktopByMalord[mp.malord] = mp; });
    function fmtDevicePos(mp) {
      if (!mp || mp.posisjon_forst == null || mp.posisjon_sist == null) return "–";
      var cls = mp.posisjon_sist < mp.posisjon_forst ? "up" : (mp.posisjon_sist > mp.posisjon_forst ? "down" : "flat");
      return '<span class="cluster-delta ' + cls + '">' + mp.posisjon_forst + " → " + mp.posisjon_sist + '</span>';
    }
    var posisjonHtml = (t.malord_posisjoner || []).map(function (mp) {
      return mp.malord + ": mobil " + fmtDevicePos(mp) + " · desktop " + fmtDevicePos(desktopByMalord[mp.malord]);
    }).join("<br>") || "–";
    tr.innerHTML =
      '<td class="mono">' + (t.side || "") + '</td>' +
      '<td>' + (t.malord || []).join(", ") + '</td>' +
      '<td>' + posisjonHtml + '</td>' +
      '<td><span class="tiltak-status ' + statusKey + '">' + (t.status_vurdering || "ikke vurdert") + '</span></td>' +
      '<td>' + (t.uker_aktiv != null ? t.uker_aktiv : "–") + '</td>';
    tiltakBody.appendChild(tr);
  });

  // ---- Footer ----
  document.getElementById("footer-source").textContent = "Kilde: Ahrefs API v3 + Claude-selvsjekk, generert " + data.generated;
  document.getElementById("footer-gaps").textContent = (data.datamangler || []).length ? "Datamangler: " + data.datamangler.join(" · ") : "";
})();
</script>
</body>
</html>
"""
