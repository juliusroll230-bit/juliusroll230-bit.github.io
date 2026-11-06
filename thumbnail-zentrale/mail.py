"""Gmail über IMAP: Bestellungen und Kunden-Antworten lesen, Antwort-Entwürfe mit Bildern anlegen.

Es wird nie etwas gesendet. Entwürfe landen im Gmail-Ordner "Entwürfe", du schickst sie selbst ab.
Anmeldung mit einem Google-App-Passwort (Google-Konto > Sicherheit > 2-Faktor > App-Passwörter).
"""
import datetime as dt
import email
import email.utils
import html
import imaplib
import re
import time
from email.message import EmailMessage
from email.policy import default as POLICY

IMAP_HOST = "imap.gmail.com"


def verbinden(adresse, app_passwort):
    imap = imaplib.IMAP4_SSL(IMAP_HOST, timeout=60)
    imap.login(adresse, app_passwort.replace(" ", ""))
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


def entwurf_bauen(ich, an, betreff, text, antwort_auf="", references="", anhaenge=()):
    msg = EmailMessage()
    msg["From"] = ich
    msg["To"] = an
    msg["Subject"] = betreff if re.match(r"^\s*(re|aw)\s*:", betreff, re.I) else "Re: " + betreff
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain="thumbnail-zentrale.local")
    if antwort_auf:  # damit Gmail den Entwurf in denselben Verlauf einsortiert
        msg["In-Reply-To"] = antwort_auf
        msg["References"] = (references + " " + antwort_auf).strip()
    msg.set_content(text)
    for name, daten in anhaenge:
        msg.add_attachment(daten, maintype="image", subtype="png", filename=name)
    return msg


def entwurf_anlegen(imap, msg):
    ordner = entwuerfe_ordner(imap)
    imap.append(_quote(ordner), "(\\Draft)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())


def _quote(ordner):
    return ordner if ordner.startswith('"') else '"' + ordner + '"'
