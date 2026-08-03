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


def classify_tiltak(tiltak: dict, history_rows: list[dict], today: date) -> dict:
    """history_rows: rank_tracker_weekly-rader, forventes forhåndsfiltrert til én enhet
    (mobil — se pipeline.py) slik at posisjonstallene er sammenlignbare uke mot uke."""
    dato = tiltak.get("dato")
    malord = {m.lower() for m in tiltak.get("malord", [])}

    if not malord or dato in (None, "planlagt"):
        return {**tiltak, "status_vurdering": "ikke_vurdert"}

    try:
        start = datetime.strptime(dato, "%Y-%m-%d").date()
    except ValueError:
        return {**tiltak, "status_vurdering": "ikke_vurdert"}

    weeks_active = max((today - start).days // 7, 0)
    malord_posisjoner = _malord_posisjoner(history_rows, malord)

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
    }


def classify_all(tiltak_list: list[dict], history_rows: list[dict], today: date) -> list[dict]:
    return [classify_tiltak(t, history_rows, today) for t in tiltak_list]
