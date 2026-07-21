"""Skriver et levende dashboard til et Google Sheet i samme Drive-mappe som rapporten.

Samme begrensning som drive_writer.py: service accounts har 0 byte egen Drive-kvote og
kan ikke opprette nye filer i en vanlig mappe. Brukeren oppretter regnearket én gang
(tomt, med riktig navn), deler mappen (allerede gjort), og denne modulen skriver kun
til det eksisterende arket — aldri oppretter et nytt.

Ark-struktur (opprettes/verifiseres ved første kjøring):
  - "Dashboard": nøkkeltall, cluster-tabell, GEO, tiltak — overskrives hver uke.
  - "Historikk": én rad lagt til per uke (trend-data), med to linjediagrammer som
    leser fra et sjenerøst forhåndssatt radområde slik at de vokser automatisk.
"""
from __future__ import annotations

import logging

from google.oauth2 import service_account
from googleapiclient.discovery import build

from src.settings import Settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

HISTORY_MAX_ROWS = 300  # ~5,7 år med ukentlige rader — diagrammene leser dette området fast


class DashboardSheetNotFound(RuntimeError):
    pass


def _credentials(settings: Settings):
    return service_account.Credentials.from_service_account_file(
        str(settings.google_service_account_json), scopes=SCOPES
    )


def find_dashboard_sheet(settings: Settings) -> str | None:
    creds = _credentials(settings)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    safe_name = settings.google_dashboard_sheet_name.replace("'", "\\'")
    query = (
        f"name contains '{safe_name}' "
        f"and '{settings.google_drive_folder_id}' in parents "
        "and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
    )
    result = drive.files().list(q=query, fields="files(id, name)").execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None


def _sheet_id_by_title(spreadsheet: dict, title: str) -> int | None:
    for sheet in spreadsheet.get("sheets", []):
        if sheet["properties"]["title"] == title:
            return sheet["properties"]["sheetId"]
    return None


def _ensure_structure(sheets_api, spreadsheet_id: str) -> tuple[int, int, bool]:
    """Sikrer at 'Dashboard' og 'Historikk'-faner finnes. Returnerer (dashboard_sheet_id,
    historikk_sheet_id, charts_already_exist)."""
    spreadsheet = sheets_api.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    dashboard_id = _sheet_id_by_title(spreadsheet, "Dashboard")
    historikk_id = _sheet_id_by_title(spreadsheet, "Historikk")
    charts_exist = any(s.get("charts") for s in spreadsheet.get("sheets", []))

    requests_ = []
    default_sheet_id = spreadsheet["sheets"][0]["properties"]["sheetId"]
    default_sheet_title = spreadsheet["sheets"][0]["properties"]["title"]

    if dashboard_id is None:
        if default_sheet_title not in ("Dashboard", "Historikk") and len(spreadsheet["sheets"]) == 1:
            requests_.append(
                {"updateSheetProperties": {"properties": {"sheetId": default_sheet_id, "title": "Dashboard"}, "fields": "title"}}
            )
            dashboard_id = default_sheet_id
        else:
            requests_.append({"addSheet": {"properties": {"title": "Dashboard"}}})

    if historikk_id is None:
        requests_.append({"addSheet": {"properties": {"title": "Historikk"}}})

    if requests_:
        response = sheets_api.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests_}).execute()
        for reply, req in zip(response.get("replies", []), requests_):
            if "addSheet" in req:
                new_id = reply["addSheet"]["properties"]["sheetId"]
                if req["addSheet"]["properties"]["title"] == "Historikk":
                    historikk_id = new_id
                else:
                    dashboard_id = new_id

    return dashboard_id, historikk_id, charts_exist


def _values(rows: list[list]) -> dict:
    return {"values": rows}


def update_dashboard_sheet(settings: Settings, payload: dict) -> str:
    spreadsheet_id = find_dashboard_sheet(settings)
    if not spreadsheet_id:
        raise DashboardSheetNotFound(
            f"Fant ikke et Google Sheet med navnet «{settings.google_dashboard_sheet_name}» i mappen "
            f"(ID {settings.google_drive_folder_id}). Opprett et tomt Google Sheet med akkurat dette "
            "navnet i mappen selv (ikke service-kontoen — den kan ikke opprette nye filer), og pass på "
            "at mappen fortsatt er delt med service-kontoen som Redaktør."
        )

    creds = _credentials(settings)
    sheets_api = build("sheets", "v4", credentials=creds, cache_discovery=False)

    dashboard_id, historikk_id, charts_exist = _ensure_structure(sheets_api, spreadsheet_id)

    # --- Historikk: legg til én rad for denne uken ---
    history_row = [[
        payload["generated"],
        payload.get("avg_position"),
        payload.get("gsc_clicks"),
        payload.get("ai_overview_count"),
        payload.get("claude_mentions"),
        payload.get("domain_rating"),
        payload.get("org_traffic"),
    ]]
    existing = sheets_api.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range="Historikk!A:A"
    ).execute().get("values", [])
    if not existing:
        header = [["Uke", "Snittposisjon", "GSC-klikk", "AI Overview-søkeord", "Claude-nevnelser", "Domain Rating", "Org. trafikk"]]
        sheets_api.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range="Historikk!A1", valueInputOption="RAW", body=_values(header)
        ).execute()
        next_row = 2
    else:
        next_row = len(existing) + 1
    sheets_api.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"Historikk!A{next_row}", valueInputOption="RAW", body=_values(history_row)
    ).execute()

    if not charts_exist:
        _create_trend_charts(sheets_api, spreadsheet_id, dashboard_id, historikk_id)

    # --- Dashboard: overskriv snapshot-tabellene ---
    rows: list[list] = [
        ["Krogsveen SEO/GEO — Live-status", "", ""],
        [f"Uke {payload['uke']} {payload['ar']} — oppdatert {payload['generated']}", "", ""],
        ["", "", ""],
        ["Nøkkeltall", "", ""],
        ["Domain Rating", payload.get("domain_rating"), ""],
        ["GSC-klikk (uke)", payload.get("gsc_clicks"), ""],
        ["AI Overview-søkeord", payload.get("ai_overview_count"), ""],
        ["Claude nevner Krogsveen", f"{payload.get('claude_mentions')} / {payload.get('claude_total')}", ""],
        ["", "", ""],
        ["Cluster", "Antall", "Snittendring"],
    ]
    for c in payload.get("cluster_summaries", []):
        rows.append([c["name"], c["keyword_count"], round(c["avg_position_delta"], 2)])

    footprint_cluster = payload.get("organisk_fotavtrykk_cluster", [])
    if footprint_cluster:
        total = payload.get("organisk_fotavtrykk_total")
        rows += [["", "", ""], [f"Organisk fotavtrykk ({total} søkeord totalt, topp 50)", "Antall", "Snittposisjon"]]
        for c in footprint_cluster:
            rows.append([c["name"], c["keyword_count"], c.get("avg_position") if c.get("avg_position") is not None else ""])

    anbefaling = payload.get("anbefaling", [])
    if anbefaling:
        rows += [["", "", ""], ["Anbefaling for neste uke", "", ""]]
        for point in anbefaling:
            rows.append([point, "", ""])

    innholdsforslag = payload.get("innholdsforslag", [])
    if innholdsforslag:
        rows += [["", "", ""], ["Innholdsforslag", "", ""]]
        for point in innholdsforslag:
            rows.append([point, "", ""])

    ai_overview_rows = payload.get("ai_overview_sokeord", [])
    rows += [["", "", ""], ["Søkeord med AI Overview i SERP", "Cluster", ""]]
    if not ai_overview_rows:
        rows.append(["Ingen søkeord med AI Overview denne uken", "", ""])
    for r in ai_overview_rows:
        rows.append([r.get("keyword", ""), ", ".join(r.get("clusters", [])), ""])

    rows += [["", "", ""], ["GEO-prompt (Claude)", "Nevnt?", "Sentiment"]]
    for r in payload.get("claude_selvsjekk", []):
        sentiment = r.get("sentiment") or ""
        rows.append([r["prompt"], "Ja" if r["krogsveen_mentioned"] else "–", sentiment])

    chatgpt_rows = payload.get("chatgpt_selvsjekk", [])
    if chatgpt_rows:
        rows += [["", "", ""], ["GEO-prompt (ChatGPT)", "Nevnt?", "Sentiment"]]
        for r in chatgpt_rows:
            sentiment = r.get("sentiment") or ""
            rows.append([r["prompt"], "Ja" if r["krogsveen_mentioned"] else "–", sentiment])

    rows += [["", "", ""], ["Tiltak", "Status", "Uker aktiv"]]
    for t in payload.get("tiltak", []):
        rows.append([t.get("side", ""), t.get("status_vurdering", ""), t.get("uker_aktiv", "")])

    rows += [["", "", ""], ["Konkurrent", "Domain Rating", "Org. trafikk"]]
    for c in payload.get("competitor_benchmark", []):
        rows.append([c["domain"], c.get("domain_rating"), c.get("org_traffic")])

    # Tøm gammelt innhold først (mer rader forrige uke enn denne ville ellers bli liggende igjen)
    sheets_api.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range="Dashboard!A1:C500").execute()
    sheets_api.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range="Dashboard!A1", valueInputOption="RAW", body=_values(rows)
    ).execute()

    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    logger.info("Dashboard-ark oppdatert: %s", url)
    return url


def _create_trend_charts(sheets_api, spreadsheet_id: str, dashboard_sheet_id: int, historikk_sheet_id: int) -> None:
    def line_chart(title: str, value_col_index: int, position: dict) -> dict:
        return {
            "addChart": {
                "chart": {
                    "spec": {
                        "title": title,
                        "basicChart": {
                            "chartType": "LINE",
                            "legendPosition": "NO_LEGEND",
                            "axis": [{"position": "BOTTOM_AXIS"}, {"position": "LEFT_AXIS"}],
                            "domains": [
                                {
                                    "domain": {
                                        "sourceRange": {
                                            "sources": [
                                                {
                                                    "sheetId": historikk_sheet_id,
                                                    "startRowIndex": 1,
                                                    "endRowIndex": HISTORY_MAX_ROWS,
                                                    "startColumnIndex": 0,
                                                    "endColumnIndex": 1,
                                                }
                                            ]
                                        }
                                    }
                                }
                            ],
                            "series": [
                                {
                                    "series": {
                                        "sourceRange": {
                                            "sources": [
                                                {
                                                    "sheetId": historikk_sheet_id,
                                                    "startRowIndex": 1,
                                                    "endRowIndex": HISTORY_MAX_ROWS,
                                                    "startColumnIndex": value_col_index,
                                                    "endColumnIndex": value_col_index + 1,
                                                }
                                            ]
                                        }
                                    },
                                    "targetAxis": "LEFT_AXIS",
                                }
                            ],
                        },
                    },
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {"sheetId": dashboard_sheet_id, "rowIndex": 0, "columnIndex": 4},
                            "offsetXPixels": 0,
                            "offsetYPixels": position["offsetY"],
                            "widthPixels": 480,
                            "heightPixels": 260,
                        }
                    },
                }
            }
        }

    requests_ = [
        line_chart("Snittposisjon over tid", 1, {"offsetY": 0}),
        line_chart("GSC-klikk over tid", 2, {"offsetY": 280}),
    ]
    sheets_api.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests_}).execute()
