"""Anker klynge-definisjoner til klientens REELLE konverteringshandlinger, i stedet for å
anta at et regex-treff for "kommersiell intensjon" automatisk betyr betalt-relevant.

Bakgrunn (funnet i SEO×Ads Synergy-arbeidet, 18.08.2026): Krogsveens 'kjop'-cluster
(til salgs|kjøpe bolig|gi bud|budrunde) ble tidligere presentert som noe betalt "må bære
hardt". Men Krogsveens Ads-konto har ingen kjøper-side konverteringshandling i det hele
tatt — alt kontoen bys mot er selger-/utleier-side (Booket Møte, avtal møte med megler,
Leievurdering). Hele kjop-clusteret ga 91 impresjoner / 0 konverteringer over 90 dager
(bekreftet Ads-data, Notion Customer Context §9, 12.08.2026). Intensjonen var reelt
kommersiell — bare kommersiell for kjøperens fremtidige megler, ikke for selgerens.

En klynge er "kommersiell" (paid-relevant) KUN hvis en søker i den plausibelt kan trigge
en av klientens faktiske konverteringshandlinger — ikke fordi regexen matcher ord som
"til salgs" eller "budrunde" som isolert sett høres kommersielle ut.
"""
from __future__ import annotations

import json
from pathlib import Path

_CONVERSION_ACTIONS_PATH = Path(__file__).resolve().parent.parent.parent / "conversion_actions.json"
_CLUSTER_RELEVANCE_PATH = Path(__file__).resolve().parent.parent.parent / "cluster_paid_relevance.json"


def load_conversion_actions(client: str) -> dict | None:
    """Klientens reelle konverteringshandlinger, sourcet fra Notion Customer Context §6
    (ikke fra en antakelse i denne kodebasen — se conversion_actions.json sitt 'source'-felt
    for hvor tallene faktisk kommer fra og når de sist ble bekreftet)."""
    if not _CONVERSION_ACTIONS_PATH.exists():
        return None
    data = json.loads(_CONVERSION_ACTIONS_PATH.read_text(encoding="utf-8"))
    return data.get(client)


def load_cluster_paid_relevance(client: str) -> dict[str, dict]:
    """Per-klynge vurdering av om klyngen kan regnes som betalt-kommersiell, se
    cluster_paid_relevance.json. Klynger uten oppføring behandles som 'unreviewed', ALDRI
    som implisitt paid-relevant — se paid_relevant_or_none()."""
    if not _CLUSTER_RELEVANCE_PATH.exists():
        return {}
    data = json.loads(_CLUSTER_RELEVANCE_PATH.read_text(encoding="utf-8"))
    return data.get(client, {})


def paid_relevant_or_none(cluster_name: str, relevance: dict[str, dict]) -> bool | None:
    """True/False hvis vurdert, None hvis clusteret enten mangler helt fra
    cluster_paid_relevance.json eller er eksplisitt flagget confidence='flagged_for_review'
    (paid_relevant: null i JSON-en, f.eks. finansiering/forsikring — mistenkt samme
    kjøper/selger-mismatch som kjop, men ikke bekreftet med harde tall ennå). None betyr
    alltid "ikke bekreftet ennå", aldri "ja, anta paid-relevant" — rapport-generering skal
    eksplisitt si "ikke vurdert" for disse, ikke stille utsagn om betalt-relevans."""
    entry = relevance.get(cluster_name)
    if not entry:
        return None
    return entry.get("paid_relevant")


def seo_only_clusters(client: str) -> list[str]:
    """Klynger som er bekreftet SEO-only — skal ALDRI presenteres som betalt-budsjett-case
    i en SEO×Ads Synergy-rapport, uansett hvor stort søkevolumet er."""
    relevance = load_cluster_paid_relevance(client)
    return [name for name, entry in relevance.items() if entry.get("paid_relevant") is False]
