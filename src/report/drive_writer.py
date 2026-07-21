"""Konverterer rapport-markdown til et Google Doc i Drive-mappen «SEO-rapporter Krogsveen»."""
from __future__ import annotations

import logging
import re
from datetime import date

from google.oauth2 import service_account
from googleapiclient.discovery import build

from src.settings import Settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive"]

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _credentials(settings: Settings):
    return service_account.Credentials.from_service_account_file(
        str(settings.google_service_account_json), scopes=SCOPES
    )


def _strip_bold_markers(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Fjerner **markers** fra en linje og returnerer (ren tekst, [(lokal_start, lokal_slutt), ...])."""
    clean_parts: list[str] = []
    bold_ranges: list[tuple[int, int]] = []
    pos = 0
    for m in _BOLD_RE.finditer(text):
        clean_parts.append(text[pos : m.start()])
        bold_start = sum(len(p) for p in clean_parts)
        clean_parts.append(m.group(1))
        bold_ranges.append((bold_start, bold_start + len(m.group(1))))
        pos = m.end()
    clean_parts.append(text[pos:])
    return "".join(clean_parts), bold_ranges


def _markdown_to_requests(markdown: str) -> list[dict]:
    """Enkel v1-konverter: '## ' -> Heading 2, '- ' -> punktliste, '**fet**' -> fet skrift,
    alt annet -> vanlig avsnitt.

    Tekst settes inn i ett insertText-kall, så alle offsets under er beregnet mot samme
    full_text og trenger ikke justeres for etterfølgende innsettinger.
    """
    lines = markdown.strip("\n").split("\n")
    full_text = ""
    style_ranges: list[tuple[int, int, str]] = []
    bullet_ranges: list[tuple[int, int]] = []
    bold_ranges: list[tuple[int, int]] = []

    for line in lines:
        if line.startswith("## "):
            raw_content = line[3:]
            paragraph_style = "HEADING_2"
        elif line.startswith("# "):
            raw_content = line[2:]
            paragraph_style = "HEADING_1"
        elif line.startswith("- "):
            raw_content = line[2:]
            paragraph_style = "NORMAL_TEXT"
        else:
            raw_content = line
            paragraph_style = "NORMAL_TEXT"

        clean_content, local_bold_ranges = _strip_bold_markers(raw_content)
        start = len(full_text) + 1  # Docs body starter på index 1
        content = clean_content + "\n"

        # Alltid en eksplisitt namedStyleType per avsnitt — ikke bare på overskrifter.
        # Uten dette arver nytt innsatt tekst formateringen til det som allerede sto
        # på innsettingspunktet (indeks 1), som ved gjentatt bruk av denne funksjonen
        # ofte er en HEADING fra forrige ukes rapport. Verifisert som reell bug 17.07.2026.
        style_ranges.append((start, start + len(content) - 1, paragraph_style))
        if line.startswith("- "):
            bullet_ranges.append((start, start + len(content) - 1))
        for local_start, local_end in local_bold_ranges:
            bold_ranges.append((start + local_start, start + local_end))

        full_text += content

    requests_ = [{"insertText": {"location": {"index": 1}, "text": full_text}}]
    for start, end, style in style_ranges:
        requests_.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": {"namedStyleType": style},
                    "fields": "namedStyleType",
                }
            }
        )
    for start, end in bullet_ranges:
        requests_.append(
            {
                "createParagraphBullets": {
                    "range": {"startIndex": start, "endIndex": end},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            }
        )
    for start, end in bold_ranges:
        requests_.append(
            {
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            }
        )
    return requests_


def report_title(report_date: date) -> str:
    iso_week = report_date.isocalendar()[1]
    return f"SEO-ukerapport Krogsveen – uke {iso_week} {report_date.year}"


class ReportDocNotFound(RuntimeError):
    pass


def find_report_doc(settings: Settings) -> str | None:
    """Finner den løpende rapport-dokumentet i mappen ved navn. Returnerer doc-ID eller None."""
    creds = _credentials(settings)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    # 'contains' i stedet for eksakt match — mer tolerant for små avvik i hva
    # brukeren faktisk skrev inn som dokumentnavn i Drive.
    safe_name = settings.google_report_doc_name.replace("'", "\\'")
    query = (
        f"name contains '{safe_name}' "
        f"and '{settings.google_drive_folder_id}' in parents "
        "and mimeType = 'application/vnd.google-apps.document' and trashed = false"
    )
    result = drive.files().list(q=query, fields="files(id, name)").execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None


class ContentBriefsDocNotFound(RuntimeError):
    pass


def find_content_briefs_doc(settings: Settings) -> str | None:
    """Finner det dedikerte innholdsforslag-dokumentet ved navn. Returnerer doc-ID eller None."""
    creds = _credentials(settings)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    safe_name = settings.google_content_briefs_doc_name.replace("'", "\\'")
    query = (
        f"name contains '{safe_name}' "
        f"and '{settings.google_drive_folder_id}' in parents "
        "and mimeType = 'application/vnd.google-apps.document' and trashed = false"
    )
    result = drive.files().list(q=query, fields="files(id, name)").execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None


def _clear_document(docs, doc_id: str) -> None:
    doc = docs.documents().get(documentId=doc_id).execute()
    end_index = doc["body"]["content"][-1]["endIndex"]
    if end_index > 2:
        docs.documents().batchUpdate(
            documentId=doc_id, body={"requests": [{"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}}]}
        ).execute()


def replace_content_briefs_doc(settings: Settings, markdown: str) -> str:
    """Overskriver hele innholdet i det dedikerte innholdsforslag-dokumentet med denne
    kjøringens 2-3 forslag — i motsetning til prepend_report_section (som bygger en
    løpende historikk), er dette alltid KUN de nyeste forslagene, ikke en logg.

    Samme opprettelsesbegrensning som prepend_report_section — dokumentet må finnes fra
    før (opprettet manuelt av et menneske, delt med service-kontoen som Redaktør)."""
    doc_id = find_content_briefs_doc(settings)
    if not doc_id:
        raise ContentBriefsDocNotFound(
            f"Fant ikke et Google Doc med navnet «{settings.google_content_briefs_doc_name}» i "
            f"mappen (ID {settings.google_drive_folder_id}). Opprett et tomt Google Doc med "
            "akkurat dette navnet i mappen (som deg selv, ikke service-kontoen), og pass på "
            "at mappen fortsatt er delt med service-kontoen som Redaktør."
        )

    creds = _credentials(settings)
    docs = build("docs", "v1", credentials=creds, cache_discovery=False)

    _clear_document(docs, doc_id)
    requests_ = _markdown_to_requests(markdown.strip())
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests_}).execute()

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    logger.info("Innholdsforslag-dokument oppdatert: %s", url)
    return url


def prepend_report_section(settings: Settings, title: str, markdown: str) -> str:
    """Setter inn ukens rapport øverst i det løpende dokumentet (nyeste først).

    Service accounts har 0 byte egen Drive-lagringskvote og kan derfor ALDRI opprette
    nye filer i en vanlig (ikke-Shared Drive) mappe — kun personlige Google Workspace-
    kontoer med domain-wide delegation eller Shared Drives (begge Workspace-only,
    ikke tilgjengelig på vanlig @gmail.com) kan gi en service account skrivekvote for
    nye filer. Løsningen er å ALDRI opprette nye filer — kun redigere ett dokument som
    et menneske allerede eier og har delt med service-kontoen (verifisert 17.07.2026:
    docs.documents().create() og drive.files().create() feiler begge med
    403/storageQuotaExceeded på en vanlig @gmail.com-konto).

    Dokumentet må finnes fra før (se find_report_doc) — hvis ikke, reiser vi
    ReportDocNotFound med en forklarende feilmelding.
    """
    doc_id = find_report_doc(settings)
    if not doc_id:
        raise ReportDocNotFound(
            f"Fant ikke et Google Doc med navnet «{settings.google_report_doc_name}» i "
            f"mappen (ID {settings.google_drive_folder_id}). Opprett et tomt Google Doc med "
            "akkurat dette navnet i mappen (som deg selv, ikke service-kontoen), og pass på "
            "at mappen fortsatt er delt med service-kontoen som Redaktør. Service-kontoer kan "
            "ikke opprette nye filer i en vanlig Drive-mappe (0 byte egen lagringskvote), "
            "kun redigere filer et menneske allerede har opprettet."
        )

    creds = _credentials(settings)
    docs = build("docs", "v1", credentials=creds, cache_discovery=False)

    section = f"# {title}\n\n{markdown.strip()}\n\n{'_' * 60}\n\n"
    requests_ = _markdown_to_requests(section)
    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests_}).execute()

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    logger.info("Rapport satt inn øverst i løpende dokument: %s", url)
    return url
