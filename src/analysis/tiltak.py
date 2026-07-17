"""Matcher tiltak.json sine målord mot historikk og klassifiserer effekt.

Status: "bekreftet effekt" / "avventer" / "ingen effekt etter 6 uker" / "ikke_vurdert"
(sistnevnte for tiltak med dato "planlagt", som ennå ikke er iverksatt).
"""
from __future__ import annotations

from datetime import date, datetime


def classify_tiltak(tiltak: dict, history_rows: list[dict], today: date) -> dict:
    """history_rows: rank_tracker_weekly-rader (alle enheter), uansett søkeord."""
    dato = tiltak.get("dato")
    malord = {m.lower() for m in tiltak.get("malord", [])}

    if not malord or dato in (None, "planlagt"):
        return {**tiltak, "status_vurdering": "ikke_vurdert"}

    try:
        start = datetime.strptime(dato, "%Y-%m-%d").date()
    except ValueError:
        return {**tiltak, "status_vurdering": "ikke_vurdert"}

    weeks_active = max((today - start).days // 7, 0)

    relevant = sorted(
        (r for r in history_rows if (r.get("keyword") or "").strip().lower() in malord),
        key=lambda r: r["week_start"],
    )

    if len(relevant) < 2:
        vurdering = "avventer"
    else:
        first_pos = relevant[0].get("position")
        last_pos = relevant[-1].get("position")
        if first_pos is not None and last_pos is not None and first_pos - last_pos > 0:
            vurdering = "bekreftet effekt"
        elif weeks_active >= 6:
            vurdering = "ingen effekt etter 6 uker"
        else:
            vurdering = "avventer"

    return {**tiltak, "uker_aktiv": weeks_active, "status_vurdering": vurdering}


def classify_all(tiltak_list: list[dict], history_rows: list[dict], today: date) -> list[dict]:
    return [classify_tiltak(t, history_rows, today) for t in tiltak_list]
