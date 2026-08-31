"""Matcher tiltak.json sine målord mot historikk og klassifiserer effekt.

Status: "bekreftet effekt" / "avventer" / "ingen effekt etter 6 uker" / "ikke_vurdert"
(sistnevnte for tiltak med dato "planlagt", som ennå ikke er iverksatt).
"""
from __future__ import annotations

from datetime import date, datetime


def _malord_posisjoner(history_rows: list[dict], malord: set[str]) -> list[dict]:
    """Første og siste kjente posisjon PER målord (ikke blandet på tvers av ulike søkeord —
    en tidligere versjon sorterte alle målords rader sammen på uke alene, som kunne vise
    "bekreftet effekt" selv om det faktiske hovedordet ble svakere, fordi et annet målord
    med flere/senere datapunkter dominerte first/last-utvalget. Oppdaget 03.08.2026 da
    boligverdi gikk 4→9 men tiltaket likevel viste "bekreftet effekt" pga. "hva er boligen
    verdt" sine rader."""
    result = []
    for m in sorted(malord):
        rows = sorted(
            (r for r in history_rows if (r.get("keyword") or "").strip().lower() == m),
            key=lambda r: r["week_start"],
        )
        if rows:
            result.append(
                {
                    "malord": m,
                    "posisjon_forst": rows[0].get("position"),
                    "posisjon_sist": rows[-1].get("position"),
                    "uker_med_data": len(rows),
                }
            )
    return result


def _sidetrafikk_sammendrag(trend: list[dict]) -> dict | None:
    """Første og siste kjente ukes klikk/impresjoner for en sidegruppe (tiltak.json sitt
    'sider'-felt) — samme første/siste-mønster som _malord_posisjoner, men for samlet
    sidetrafikk i stedet for enkeltord-posisjon. Bygget 24.08.2026 fordi et tiltak som
    endrer HELE sider (ikke bare targeter ett søkeord) kan øke trafikk fra et bredt sett
    long-tail-søk som malord-listen aldri fanger — se tiltak.json-notatet for de 12
    eiendomsmegler-fylkessidene."""
    if not trend:
        return None
    return {
        "uker_med_data": len(trend),
        "klikk_forst": trend[0]["clicks"],
        "klikk_sist": trend[-1]["clicks"],
        "impresjoner_forst": trend[0]["impressions"],
        "impresjoner_sist": trend[-1]["impressions"],
    }


def classify_tiltak(
    tiltak: dict,
    history_rows_mobil: list[dict],
    history_rows_desktop: list[dict],
    today: date,
    page_traffic_trend: list[dict] | None = None,
) -> dict:
    """history_rows_mobil/history_rows_desktop: rank_tracker_weekly-rader, hver forhånds-
    filtrert til én enhet, slik at posisjonstallene er sammenlignbare uke mot uke. Status-
    vurderingen (bekreftet effekt / avventer / osv.) beregnes fra mobil alene — samme
    primærkilde som resten av analysen — men begge enheters posisjoner vises, siden mobil
    og desktop kan bevege seg i hver sin retning for samme søkeord (se CLAUDE.md/diffs.py).

    page_traffic_trend: fra storage.get_page_group_traffic_trend() for tiltak.get('sider'),
    KUN gitt for tiltak som faktisk har et 'sider'-felt — se _sidetrafikk_sammendrag()."""
    sidetrafikk = _sidetrafikk_sammendrag(page_traffic_trend) if tiltak.get("sider") else None
    dato = tiltak.get("dato")
    malord = {m.lower() for m in tiltak.get("malord", [])}

    if not malord or dato in (None, "planlagt"):
        return {**tiltak, "status_vurdering": "ikke_vurdert", "sidetrafikk": sidetrafikk}

    try:
        start = datetime.strptime(dato, "%Y-%m-%d").date()
    except ValueError:
        return {**tiltak, "status_vurdering": "ikke_vurdert", "sidetrafikk": sidetrafikk}

    weeks_active = max((today - start).days // 7, 0)
    malord_posisjoner = _malord_posisjoner(history_rows_mobil, malord)
    malord_posisjoner_desktop = _malord_posisjoner(history_rows_desktop, malord)

    # Snitt av per-målord-delta (positivt = forbedring), ikke rå rader blandet på tvers
    # av søkeord — se docstring i _malord_posisjoner for hvorfor.
    deltas = [
        mp["posisjon_forst"] - mp["posisjon_sist"]
        for mp in malord_posisjoner
        if mp["uker_med_data"] >= 2 and mp["posisjon_forst"] is not None and mp["posisjon_sist"] is not None
    ]

    if not deltas:
        vurdering = "avventer"
    else:
        avg_delta = sum(deltas) / len(deltas)
        if avg_delta > 0:
            vurdering = "bekreftet effekt"
        elif weeks_active >= 6:
            vurdering = "ingen effekt etter 6 uker"
        else:
            vurdering = "avventer"

    return {
        **tiltak,
        "uker_aktiv": weeks_active,
        "status_vurdering": vurdering,
        "malord_posisjoner": malord_posisjoner,
        "malord_posisjoner_desktop": malord_posisjoner_desktop,
        "sidetrafikk": sidetrafikk,
    }


def classify_all(
    tiltak_list: list[dict],
    history_rows_mobil: list[dict],
    history_rows_desktop: list[dict],
    today: date,
    page_traffic_trends: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """page_traffic_trends: {tiltak['side']: trend} for tiltak med et 'sider'-felt, se
    src.pipeline for hvor dette bygges (storage.get_page_group_traffic_trend per tiltak)."""
    page_traffic_trends = page_traffic_trends or {}
    return [
        classify_tiltak(t, history_rows_mobil, history_rows_desktop, today, page_traffic_trends.get(t.get("side")))
        for t in tiltak_list
    ]
