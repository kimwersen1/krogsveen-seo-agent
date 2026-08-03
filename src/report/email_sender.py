"""Sender ukesrapporten som e-post via Gmail SMTP + app-passord.

Hvorfor SMTP + app-passord og ikke Gmail API/OAuth: pipelinen har allerede vært gjennom
nok OAuth-trøbbel (se src/collectors/gsc_oauth.py / ga4_oauth.py sin historie 21.07 —
03.08.2026: invalid_client, 7-dagers testmodus-tokenutløp). SMTP med et app-passord er
en langt enklere og mer robust vei for en ren send-jobb — ingen tokens å fornye, ingen
scope å utvide, ingen "Publishing status"-fallgruve. Krever kun at 2-trinns verifisering
er PÅ for avsenderkontoen (nødvendig for å generere et app-passord på
myaccount.google.com/apppasswords — engangsoppsett, se README/chat-instruks).

Feiler denne (manglende oppsett, feil passord, midlertidig Gmail-utilgjengelighet), skal
det aldri velte hele ukesrapporten — se try/except-mønsteret i pipeline.py, samme
robusthetsprinsipp som GSC/GA4/GEO-selvsjekkene.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.settings import Settings

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_weekly_report_email(
    settings: Settings,
    title: str,
    report_url: str,
    sheet_url: str | None,
    hovedbildet: str,
) -> None:
    recipient = settings.weekly_report_email_recipient or settings.google_gmail_address

    lines = [
        "Ukens rapport og dashboard for krogsveen.no.",
        "",
        f"Rapport (Google Doc): {report_url}",
        "",
        f"Live dashboard: {settings.weekly_report_dashboard_url}",
    ]
    if sheet_url:
        lines.append(f"Dashboard (Google Sheet): {sheet_url}")
    lines += ["", "—", "", "Hovedbildet denne uken:", "", hovedbildet or "(ikke tilgjengelig)"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = title
    msg["From"] = settings.google_gmail_address
    msg["To"] = recipient
    msg.attach(MIMEText("\n".join(lines), "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(settings.google_gmail_address, settings.google_gmail_app_password)
        server.send_message(msg)

    logger.info("Ukesrapport sendt på e-post til %s", recipient)
