"""Gmail: Bestellungen und Kunden-Antworten lesen (IMAP), Antworten als Entwurf anlegen oder auf Knopfdruck senden (SMTP).

Automatisch wird nie etwas gesendet. Gesendet wird nur, wenn du beim Auftrag auf "Jetzt senden" klickst.
Anmeldung mit einem Google-App-Passwort (Google-Konto > Sicherheit > 2-Faktor > App-Passwörter).
"""
import datetime as dt
import email
import email.utils
import html
import imaplib
import mimetypes
import re
import smtplib
import time
from email.message import EmailMessage
from email.policy import default as POLICY

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"


def passwort_pruefen(app_passwort):
    """Google-App-Passwörter sind 16 Buchstaben, oft mit Leerzeichen angezeigt. Alles andere gleich klar melden."""
    pw = re.sub(r"\s+", "", app_passwort or "")
    if not pw:
        raise ValueError("Es ist noch kein App-Passwort gespeichert.")
    if not pw.isascii() or not re.fullmatch(r"[A-Za-z]{16}", pw):
        raise ValueError("Das App-Passwort stimmt nicht. Es sind genau 16 Buchstaben von Google. "
                         "Bitte das Feld ganz leeren, das Passwort neu einfügen und speichern.")
    return pw


def verbinden(adresse, app_passwort):
    pw = passwort_pruefen(app_passwort)
    imap = imaplib.IMAP4_SSL(IMAP_HOST, timeout=60)
    imap.login(adresse.strip(), pw)
    return imap


def entwuerfe_ordner(imap):
    """Gmail heißt den Ordner je nach Sprache "[Gmail]/Drafts" oder "[Gmail]/Entw&APw-rfe". Wir suchen das Kennzeichen."""
    typ, zeilen = imap.list()
    for z in zeilen or []:
        z = z.decode("utf-8", "replace") if isinstance(z, bytes) else str(z)
        if "\\Drafts" in z:
            m = re.search(r'"([^"]+)"\s*$', z) or re.search(r"\s(\S+)\s*$", z)
            if m:
                return m.group(1)
    return "[Gmail]/Drafts"


def _text_aus(msg):
    plain, htm = "", ""
    for teil in msg.walk():
        if teil.get_content_maintype() == "multipart" or teil.get_filename():
            continue
        typ = teil.get_content_type()
        try:
            inhalt = teil.get_content()
        except Exception:
            continue
        if typ == "text/plain" and not plain:
            plain = inhalt
        elif typ == "text/html" and not htm:
            htm = inhalt
    if plain:
        return plain
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", htm)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", t)
    return html.unescape(re.sub(r"<[^>]+>", "", t))


def ohne_zitat(text):
    """Schneidet den zitierten Teil einer Antwort ab ("Am ... schrieb ...", "> ...")."""
    zeilen = []
    for z in (text or "").splitlines():
        if re.match(r"^\s*>", z) or re.match(r"^\s*(Am|On)\s.+(schrieb|wrote)", z) or z.strip() in ("-----Original Message-----",):
            break
        zeilen.append(z)
    return "\n".join(zeilen).strip()


def _bilder_aus(msg):
    out = []
    for teil in msg.walk():
        if teil.get_content_maintype() == "image" and (teil.get_filename() or teil.get("Content-ID")):
            daten = teil.get_payload(decode=True) or b""
            if 0 < len(daten) < 20_000_000:
                name = teil.get_filename() or f"bild.{teil.get_content_subtype()}"
                out.append((name, daten))
    return out


def lies_mail(roh):
    msg = email.message_from_bytes(roh, policy=POLICY)
    von_name, von_mail = email.utils.parseaddr(str(msg.get("From", "")))
    try:
        datum = email.utils.parsedate_to_datetime(str(msg.get("Date"))).astimezone().isoformat(timespec="seconds")
    except Exception:
        datum = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "message_id": str(msg.get("Message-ID", "")).strip(),
        "references": str(msg.get("References", "")).strip(),
        "betreff": str(msg.get("Subject", "")),
        "von_name": von_name,
        "von_mail": von_mail.lower(),
        "datum": datum,
        "text": _text_aus(msg),
        "bilder": _bilder_aus(msg),
    }


def neue_mails(imap, ich, ist_relevant, gesehen, tage=14):
    """Liefert neue Mails aus dem Posteingang, für die ist_relevant(betreff, absender) True ist."""
    imap.select("INBOX", readonly=True)
    seit = (dt.date.today() - dt.timedelta(days=tage)).strftime("%d-%b-%Y")
    typ, daten = imap.uid("search", None, "SINCE", seit)
    uids = (daten[0] or b"").split() if daten else []
    out = []
    for uid in uids[-200:]:
        typ, kopf = imap.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT)])")
        if not kopf or not isinstance(kopf[0], tuple):
            continue
        h = email.message_from_bytes(kopf[0][1], policy=POLICY)
        mid = str(h.get("Message-ID", "")).strip()
        _, von = email.utils.parseaddr(str(h.get("From", "")))
        von = von.lower()
        if not mid or mid in gesehen or von == ich.lower():
            continue
        if not ist_relevant(str(h.get("Subject", "")), von):
            continue
        typ, voll = imap.uid("fetch", uid, "(BODY.PEEK[])")
        if voll and isinstance(voll[0], tuple):
            out.append(lies_mail(voll[0][1]))
    return out


def html_mail(text, absender_name=""):
    """Schlichte, gut lesbare HTML-Version des Textes (funktioniert in Gmail, Outlook und auf dem Handy)."""
    absaetze = "".join(
        f'<p style="margin:0 0 16px">{html.escape(a).replace(chr(10), "<br>")}</p>'
        for a in re.split(r"\n\s*\n", text.strip()) if a.strip())
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#f4f4f5">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:24px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:14px;border:1px solid #e4e4e7">
<tr><td style="background:#0b0b0c;border-radius:14px 14px 0 0;padding:18px 28px;color:#ffffff;font:600 15px/1.4 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;letter-spacing:.02em">
{html.escape(absender_name or "Thumbnails")} <span style="color:#22c55e">&#9679;</span></td></tr>
<tr><td style="padding:28px;color:#18181b;font:15px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">{absaetze}</td></tr>
<tr><td style="padding:0 28px 24px;color:#71717a;font:12px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">Die Bilder hängen als PNG-Dateien an dieser Mail (1280 &times; 720 px).</td></tr>
</table></td></tr></table></body></html>"""


def entwurf_bauen(ich, an, betreff, text, antwort_auf="", references="", anhaenge=(), html_text=None, absender_name=""):
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((absender_name, ich)) if absender_name else ich
    msg["To"] = an
    msg["Subject"] = betreff if re.match(r"^\s*(re|aw)\s*:", betreff, re.I) else "Re: " + betreff
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain="thumbnail-zentrale.local")
    if antwort_auf:  # damit Gmail den Entwurf in denselben Verlauf einsortiert
        msg["In-Reply-To"] = antwort_auf
        msg["References"] = (references + " " + antwort_auf).strip()
    msg.set_content(text)
    if html_text:
        msg.add_alternative(html_text, subtype="html")
    for name, daten in anhaenge:
        typ = (mimetypes.guess_type(name)[0] or "application/octet-stream").split("/", 1)
        msg.add_attachment(daten, maintype=typ[0], subtype=typ[1], filename=name)
    return msg


def senden(adresse, app_passwort, msg):
    """Schickt die Mail über Gmail ab. Gmail legt sie automatisch unter "Gesendet" ab."""
    with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=60) as smtp:
        smtp.login(adresse.strip(), passwort_pruefen(app_passwort))
        smtp.send_message(msg)


def entwurf_anlegen(imap, msg):
    ordner = entwuerfe_ordner(imap)
    imap.append(_quote(ordner), "(\\Draft)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())


def _quote(ordner):
    return ordner if ordner.startswith('"') else '"' + ordner + '"'
