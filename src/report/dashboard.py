"""Genererer en statisk HTML-dashboard fra ukens analyse-data + historikk fra SQLite.

Filen skrives til docs/index.html i prosjektroten — GitHub Pages kan servere direkte
fra en /docs-mappe på main uten egen build-branch. GitHub Actions committer og pusher
filen etter hver ukentlig kjøring (se .github/workflows/weekly-report.yml), så siden
er "levende" uten at noen manuelt må gjøre noe utover initial Pages-oppsett.
"""
from __future__ import annotations

import json
import logging
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
) -> dict:
    return {
        "generated": report_date.isoformat(),
        "uke": analysis["uke"],
        "ar": analysis["ar"],
        "domain_rating": analysis.get("domain_rating"),
        "site_metrics": analysis.get("site_metrics"),
        "gsc_site": analysis.get("gsc_site", []),
        "cluster_summaries": analysis.get("cluster_summaries", []),
        "avvik": analysis.get("avvik", [])[:15],
        "geo": analysis.get("geo", {}),
        "tiltak": analysis.get("tiltak", []),
        "datamangler": analysis.get("datamangler", []),
        "position_trend": position_trend,
        "clicks_trend": clicks_trend,
        "competitor_benchmark": competitor_benchmark,
    }


def build_sheet_payload(dashboard_payload: dict) -> dict:
    """Flat versjon av dashboard-payloaden, tilpasset Google Sheets-skriveren
    (se src/report/sheets_writer.py) — samme kildedata, enklere struktur."""
    geo = dashboard_payload.get("geo", {})
    claude_rows = geo.get("claude_selvsjekk", [])
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
        "claude_mentions": sum(1 for r in claude_rows if r.get("krogsveen_mentioned")),
        "claude_total": len(claude_rows),
        "avg_position": (
            dashboard_payload["position_trend"][-1]["avg_position"] if dashboard_payload.get("position_trend") else None
        ),
        "cluster_summaries": dashboard_payload.get("cluster_summaries", []),
        "claude_selvsjekk": claude_rows,
        "tiltak": dashboard_payload.get("tiltak", []),
        "competitor_benchmark": dashboard_payload.get("competitor_benchmark", []),
    }


def render_dashboard(payload: dict, output_path: Path = OUTPUT_PATH) -> Path:
    html = _TEMPLATE.replace("__DASHBOARD_DATA__", json.dumps(payload, ensure_ascii=False))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("Dashboard skrevet til %s", output_path)
    return output_path


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
    --series-1: #0C8A75; --series-2: #b8791f;
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
      --series-1: #2E9A84; --series-2: #B4823F;
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
    --series-1: #2E9A84; --series-2: #B4823F;
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
    --series-1: #0C8A75; --series-2: #b8791f;
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
  .cluster-row { display: grid; grid-template-columns: 100px 1fr 60px 50px; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--line); font-size: 12.5px; }
  .cluster-row:last-child { border-bottom: none; }
  .cluster-name { font-weight: 600; }
  .cluster-track { height: 7px; border-radius: 4px; background: var(--bg-surface-2); overflow: hidden; display: flex; }
  .cluster-track .seg-up { background: var(--good); }
  .cluster-track .seg-down { background: var(--critical); }
  .cluster-track .seg-flat { background: var(--line-strong); }
  .cluster-count { text-align: right; color: var(--ink-muted); }
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

  <div class="two-col">
    <div class="card">
      <h2>Snittposisjon over tid</h2>
      <div class="card-sub">Alle sporede søkeord, desktop</div>
      <div id="position-chart"></div>
    </div>
    <div class="card">
      <h2>GSC-klikk over tid</h2>
      <div class="card-sub">Site-wide, via Ahrefs</div>
      <div id="clicks-chart"></div>
    </div>
  </div>

  <div class="card">
    <h2>Cluster-bevegelse denne uken</h2>
    <div class="card-sub" id="cluster-sub"></div>
    <div id="cluster-rows"></div>
  </div>

  <div class="two-col">
    <div class="card">
      <h2>GEO / AI-synlighet</h2>
      <div class="card-sub">Claude-selvsjekk (ekte) vs. Brand Radar (venter på oppsett)</div>
      <div id="geo-panel"></div>
    </div>
    <div class="card">
      <h2>Konkurrentbenchmark</h2>
      <div class="card-sub">Domain Rating og org. trafikk, denne uken</div>
      <div class="table-scroll"><table id="competitor-table"><thead><tr><th>Domene</th><th>DR</th><th>Org. trafikk/mnd</th></tr></thead><tbody></tbody></table></div>
    </div>
  </div>

  <div class="card">
    <h2>Tiltaks-status</h2>
    <div class="table-scroll"><table id="tiltak-table"><thead><tr><th>Side</th><th>Målord</th><th>Status</th><th>Uker aktiv</th></tr></thead><tbody></tbody></table></div>
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
  addChip("GSC (via Ahrefs)", true);
  var brandRadarOk = data.geo.brand_radar_omtaler && Object.keys(data.geo.brand_radar_omtaler).some(function(k) {
    return data.geo.brand_radar_omtaler[k].total > 0;
  });
  addChip("Brand Radar", brandRadarOk);
  addChip("Claude-selvsjekk", true);

  // ---- Stat tiles ----
  var statGrid = document.getElementById("stat-grid");
  function addStat(label, value, delta) {
    var tile = document.createElement("div");
    tile.className = "stat-tile";
    tile.innerHTML =
      '<div class="label">' + label + '</div>' +
      '<div class="value num">' + value + '</div>' +
      (delta ? '<div class="delta">' + delta + '</div>' : "");
    statGrid.appendChild(tile);
  }
  addStat("Domain Rating", data.domain_rating ? data.domain_rating.domain_rating || "–" : "–");
  var allDevice = (data.gsc_site || []).find(function (r) { return r.device === "all"; });
  addStat("GSC-klikk (uke)", allDevice ? fmt.format(allDevice.clicks) : "–",
    allDevice ? fmt.format(allDevice.impressions) + " visninger" : "");
  var aiCount = (data.geo.ai_overview_sokeord || []).length;
  addStat("AI Overview-eksponering", aiCount, "søkeord med AI Overview i SERP");
  var claudeMentions = (data.geo.claude_selvsjekk || []).filter(function (r) { return r.krogsveen_mentioned; }).length;
  var claudeTotal = (data.geo.claude_selvsjekk || []).length;
  addStat("Claude nevner Krogsveen", claudeMentions + " / " + claudeTotal, "av kjørte GEO-prompts");

  // ---- Trend charts (single-series, simple) ----
  function renderTrendChart(containerId, points, valueKey, color, label) {
    var container = document.getElementById(containerId);
    if (!points || points.length < 2) {
      container.innerHTML = '<div class="empty-note">Bygger historikk — for få uker med data ennå (' + (points ? points.length : 0) + ' registrert)</div>';
      return;
    }
    var W = 420, H = 160, M = { top: 10, right: 10, bottom: 24, left: 44 };
    var plotW = W - M.left - M.right, plotH = H - M.top - M.bottom;
    var values = points.map(function (p) { return p[valueKey]; });
    var minV = Math.min.apply(null, values), maxV = Math.max.apply(null, values);
    if (minV === maxV) { minV -= 1; maxV += 1; }
    var pad = (maxV - minV) * 0.15;
    minV -= pad; maxV += pad;

    function x(i) { return M.left + (plotW * i) / (points.length - 1); }
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
    var d = points.map(function (p, i) { return (i === 0 ? "M" : "L") + x(i) + "," + y(p[valueKey]); }).join(" ");
    var path = document.createElementNS(svgNS, "path");
    path.setAttribute("d", d); path.setAttribute("class", "series-line"); path.setAttribute("stroke", color);
    svg.appendChild(path);
    points.forEach(function (p, i) {
      var c = document.createElementNS(svgNS, "circle");
      c.setAttribute("cx", x(i)); c.setAttribute("cy", y(p[valueKey])); c.setAttribute("r", 3.5);
      c.setAttribute("fill", color); c.setAttribute("class", "series-dot");
      svg.appendChild(c);
      var lbl = document.createElementNS(svgNS, "text");
      lbl.setAttribute("x", x(i)); lbl.setAttribute("y", H - M.bottom + 14);
      lbl.setAttribute("class", "axis-text"); lbl.setAttribute("text-anchor", "middle");
      lbl.textContent = (p.week_start || "").slice(5);
      svg.appendChild(lbl);
    });
    container.appendChild(svg);
  }
  var series1Color = getComputedStyle(document.body).getPropertyValue("--series-1").trim();
  var series2Color = getComputedStyle(document.body).getPropertyValue("--series-2").trim();
  renderTrendChart("position-chart", data.position_trend, "avg_position", series1Color, "Snittposisjon");
  renderTrendChart("clicks-chart", data.clicks_trend, "clicks", series2Color, "Klikk");

  // ---- Cluster rows ----
  var clusterWrap = document.getElementById("cluster-rows");
  var totalTracked = (data.cluster_summaries || []).reduce(function (s, c) { return s + c.keyword_count; }, 0);
  document.getElementById("cluster-sub").textContent = "Desktop, uke-mot-uke — " + totalTracked + " sporede søkeord på tvers av clustre";
  (data.cluster_summaries || []).forEach(function (c) {
    var total = c.improved + c.declined + c.unchanged || 1;
    var row = document.createElement("div");
    row.className = "cluster-row";
    var deltaClass = c.avg_position_delta > 0 ? "up" : c.avg_position_delta < 0 ? "down" : "flat";
    var sign = c.avg_position_delta > 0 ? "+" : "";
    row.innerHTML =
      '<span class="cluster-name">' + c.name + '</span>' +
      '<span class="cluster-track">' +
        '<span class="seg-up" style="flex:' + c.improved + '"></span>' +
        '<span class="seg-down" style="flex:' + c.declined + '"></span>' +
        '<span class="seg-flat" style="flex:' + c.unchanged + '"></span>' +
      '</span>' +
      '<span class="cluster-count">' + c.keyword_count + '</span>' +
      '<span class="cluster-delta ' + deltaClass + '">' + sign + c.avg_position_delta.toFixed(1) + '</span>';
    clusterWrap.appendChild(row);
  });

  // ---- GEO panel ----
  var geoPanel = document.getElementById("geo-panel");
  var brandItem = document.createElement("div");
  brandItem.className = "geo-item";
  brandItem.innerHTML =
    '<div class="geo-item-head"><span class="title">Brand Radar</span>' +
    '<span class="status-chip ' + (brandRadarOk ? "ok" : "blocked") + '">' + (brandRadarOk ? "Aktiv" : "Ikke konfigurert") + '</span></div>' +
    '<p>' + (brandRadarOk ? "Data flyter fra ChatGPT/Gemini/Perplexity/AI Overviews/AI Mode." : "Prompts mangler i Ahrefs UI — datakildene er satt til ukentlig, men ingen spørsmål er lagt inn ennå.") + '</p>';
  geoPanel.appendChild(brandItem);

  var claudeItem = document.createElement("div");
  claudeItem.className = "geo-item";
  var claudeHtml = '<div class="geo-item-head"><span class="title">Claude-selvsjekk</span><span class="status-chip ok">Live data</span></div>';
  (data.geo.claude_selvsjekk || []).forEach(function (r) {
    var mentioned = r.krogsveen_mentioned;
    var label = mentioned ? "Nevnt" + (r.sentiment ? " · " + r.sentiment : "") : "–";
    claudeHtml += '<div class="prompt-row"><span class="p">' + r.prompt + '</span><span class="mentioned ' + (mentioned ? "yes" : "no") + '">' + label + '</span></div>';
  });
  claudeItem.innerHTML = claudeHtml;
  geoPanel.appendChild(claudeItem);

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
    tr.innerHTML =
      '<td class="mono">' + (t.side || "") + '</td>' +
      '<td>' + (t.malord || []).join(", ") + '</td>' +
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
