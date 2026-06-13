"""delivery/smtp/send.py — server-less SMTP delivery adapter.

Sends the full HTML inline (no doGet link) for users without GAS.
Inline CSS only — no <style> block reliance; safe for all email clients.
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_inline(
    html: str,
    plaintext: str,
    to_email: str,
    date: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
) -> None:
    """Send the full letter HTML inline via SMTP (server-less, no doGet link).

    Parameters
    ----------
    html        : Full letter HTML (inline CSS only).
    plaintext   : Plaintext version (fallback body).
    to_email    : Recipient address.
    date        : "YYYY-MM-DD" — used in the subject line.
    smtp_host   : SMTP server hostname.
    smtp_port   : SMTP port (typically 587 for STARTTLS).
    smtp_user   : SMTP login username (usually sender address).
    smtp_pass   : SMTP password or app password.
    """
    subject = f"Dear Oracle, {date}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_user
    msg["To"]      = to_email

    msg.attach(MIMEText(plaintext, "plain", "utf-8"))
    msg.attach(MIMEText(html,      "html",  "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())
