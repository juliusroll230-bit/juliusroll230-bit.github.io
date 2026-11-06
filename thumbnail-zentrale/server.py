"""Thumbnail-Zentrale: Website, Gmail-Abruf und Thumbnail-Baukasten in einem Prozess.

  python3 server.py        startet auf Port 8080 (änderbar mit PORT)

Umgebungsvariablen:
  DATA_DIR       Speicherort (Standard ./data, im Container /data)
  PASSWORD       optional: schützt die Website mit Benutzer "admin" und diesem Passwort
  CHROMIUM_PATH  optional: eigener Chromium (sonst der von Playwright)
"""
import base64
import datetime as dt
import json
import mimetypes
import os
import re
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ki
import rechnung
import mail
import planer
import render
import store
import website

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
PORT = int(os.environ.get("PORT", "8080"))
PASSWORD = os.environ.get("PASSWORD", "")
VERSION = {"sha": os.environ.get("APP_VERSION", "dev")[:7], "built": os.environ.get("APP_BUILT", "")}
VARIANTEN = "abc"
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
OFFEN = ("neu", "bereit", "in_gmail", "aenderung")

mail_lock = threading.Lock()
status = {"mail_laeuft": False}
GEHEIM = ("app_passwort", "ki_schluessel", "github_token")


# ======================= Aufträge =======================
def fotos_von(a):
    return [f for f in a.get("fotos", [])]


def png_pfad(a_id, n):
    return os.path.join(store.ordner(a_id), f"{VARIANTEN[n]}.png")


def rendern(a_id, nummern=None):
    """Baut die PNGs eines Auftrags neu (alle oder nur die genannten Varianten)."""
    s = store.lesen()
    a = store.auftrag(s, a_id)
    if not a:
        return
    ordner = store.ordner(a_id)
    nummern = range(len(a["entwuerfe"])) if nummern is None else nummern
    render.als_png([(a["entwuerfe"][n]["entwurf"], ordner, png_pfad(a_id, n)) for n in nummern])
    with store.aendern() as s:
        a = store.auftrag(s, a_id)
        for n in nummern:
            a["entwuerfe"][n]["stand"] = int(time.time())
        if a["status"] == "neu":
            a["status"] = "bereit"


def foto_speichern(a_id, name, daten):
    name = re.sub(r"[^\w.\-]", "_", os.path.basename(name or "foto.jpg"))[-60:]
    if not re.search(r"\.(png|jpe?g|webp|gif)$", name, re.I):
        name += ".jpg"
    ordner = store.ordner(a_id)
    basis, endung = os.path.splitext(name)
    i = 1
    while os.path.exists(os.path.join(ordner, name)):
        name = f"{basis}-{i}{endung}"
        i += 1
    with open(os.path.join(ordner, name), "wb") as f:
        f.write(daten)
    return name


def auftrag_anlegen(b, quelle="manuell", mail_info=None, bilder=()):
    a_id = store.neue_id()
    fotos = [foto_speichern(a_id, n, d) for n, d in bilder]
    entwuerfe = planer.entwuerfe_planen(b, fotos[0] if fotos else "")
    with store.aendern() as s:
        a = {
            "id": a_id, "eingang": (mail_info or {}).get("datum") or store.jetzt(), "quelle": quelle,
            "name": b.get("name", ""), "kanal": b.get("kanal", ""), "email": b.get("email", ""),
            "paket": b.get("paket", "Einzel-Thumbnail"), "thema": b.get("thema", ""), "wuensche": b.get("wuensche", ""),
            "mail": {k: (mail_info or {}).get(k, "") for k in ("message_id", "references", "betreff", "text")},
            "fotos": fotos, "entwuerfe": [{"entwurf": e, "stand": 0} for e in entwuerfe],
            "status": "neu", "bezahlt": False, "aenderungen": [], "gmail_entwurf": "", "geliefert": "",
        }
        s["auftraege"].insert(0, a)
        if a["email"]:
            k = store.kunde_fuer(s, a["email"], anlegen={"name": a["name"], "kanal": a["kanal"]})
            k["name"] = k["name"] or a["name"]
            k["kanal"] = k["kanal"] or a["kanal"]
            if a["paket"] == "Monats-Abo" and k.get("abo_status") not in ("aktiv",):
                k["paket"], k["abo_status"] = "Abo", "angefragt"
        store.ereignis(s, f"Neue Bestellung: {a['kanal'] or a['name'] or a['email']} ({a['paket']})", a_id)
    try:
        rendern(a_id)
    except Exception as e:
        traceback.print_exc()
        with store.aendern() as s:
            store.ereignis(s, f"Thumbnails konnten nicht gebaut werden: {e}", a_id)
    return a_id


def antwort_text(s, a, vorlage=None):
    e = s["einstellungen"]
    vorlage = vorlage or e["antwort_text"]
    vorname = (a.get("name") or "").split(" ")[0] or "du"
    try:
        return vorlage.format(vorname=vorname, name=a.get("name", ""), kanal=a.get("kanal", ""),
                                        thema_satz=f" zu „{a['thema']}“" if a.get("thema") else "",
                                        dein_name=e.get("dein_name", ""), zahlung="{zahlung}",
                                        monat=MONATE[dt.date.today().month - 1] + " " + str(dt.date.today().year))
    except (KeyError, IndexError, ValueError):
        return vorlage


def liefer_text(s, a):
    return antwort_text(s, a, s["einstellungen"].get("liefer_text") or s["einstellungen"]["antwort_text"])


def mail_raus(e, an, betreff, text, anhaenge, senden, antwort_auf="", references=""):
    """Baut die Mail (Text + HTML) und legt sie als Gmail-Entwurf an oder sendet sie. Gibt die Message-ID zurück."""
    if not (e["gmail"] and e["app_passwort"]):
        raise ValueError("Gmail ist noch nicht verbunden (Einstellungen).")
    if senden and not e.get("direkt_senden"):
        raise ValueError("Direktes Senden ist in den Einstellungen ausgeschaltet.")
    msg = mail.entwurf_bauen(e["gmail"], an, betreff, text, antwort_auf, references, anhaenge,
                             html_text=mail.html_mail(text, e.get("dein_name", "")), absender_name=e.get("dein_name", ""))
    if senden:
        mail.senden(e["gmail"], e["app_passwort"], msg)
    else:
        imap = mail.verbinden(e["gmail"], e["app_passwort"])
        try:
            mail.entwurf_anlegen(imap, msg)
        finally:
            try:
                imap.logout()
            except Exception:
                pass
    return msg["Message-ID"]


def impressum(e):
    return {"name": e.get("absender_name") or e.get("kontoinhaber") or e.get("dein_name", ""),
            "strasse": e.get("absender_strasse", ""), "ort": e.get("absender_ort", ""),
            "kleinunternehmer": e.get("kleinunternehmer", True)}


def rechnung_pdf(r_id):
    s = store.lesen()
    r = next(x for x in s["rechnungen"] if x["id"] == r_id)
    pfad = rechnung.pdf_bauen(s, r, impressum(s["einstellungen"]), store.RECHNUNGEN)
    with store.aendern() as s:
        next(x for x in s["rechnungen"] if x["id"] == r_id)["datei"] = os.path.basename(pfad)
    return pfad


def rechnung_fuer_auftrag(a_id):
    """Offene Rechnung zum Auftrag holen oder neu anlegen (Einzel-Thumbnail)."""
    with store.aendern() as s:
        a = store.auftrag(s, a_id)
        r = next((x for x in s["rechnungen"] if x["auftrag"] == a_id and not x.get("storniert")), None)
        if not r:
            posten = "Einzel-Thumbnail" + (f" „{a['thema']}“" if a.get("thema") else "") + (f" für {a['kanal']}" if a.get("kanal") else "")
            r = rechnung.anlegen(s, a["email"], a.get("name", ""), a.get("kanal", ""), posten,
                                 s["einstellungen"].get("preis_einzel") or 0, a_id)
            store.ereignis(s, f"Rechnung {r['nr']} erstellt: {rechnung.euro(r['betrag'])} an {a['kanal'] or a['email']}", a_id)
        r = dict(r)
    rechnung_pdf(r["id"])
    return r


def gmail_entwurf(a_id, nummern=None, text=None, betreff=None, extra=(), senden=False, mit_rechnung=False):
    """Antwort an den Kunden mit den angehakten PNGs (und optional Rechnung und weiteren Dateien).
    senden=False legt einen Gmail-Entwurf an, senden=True schickt die Mail sofort ab."""
    s = store.lesen()
    a = store.auftrag(s, a_id)
    e = s["einstellungen"]
    if not a.get("email"):
        raise ValueError("Bei diesem Auftrag fehlt die E-Mail-Adresse des Kunden.")
    if not (e["gmail"] and e["app_passwort"]):
        raise ValueError("Gmail ist noch nicht verbunden (Einstellungen).")
    nummern = list(range(len(a["entwuerfe"]))) if nummern is None else nummern
    slug = re.sub(r"[^a-z0-9]+", "-", (a.get("kanal") or a.get("name") or "thumbnail").lower()).strip("-") or "thumbnail"
    anhaenge = []
    for n in nummern:
        with open(png_pfad(a_id, n), "rb") as f:
            anhaenge.append((f"thumbnail-{slug}-{VARIANTEN[n]}.png", f.read()))
    r = None
    if mit_rechnung and a["paket"] != "Monats-Abo":
        r = rechnung_fuer_auftrag(a_id)
        with open(os.path.join(store.RECHNUNGEN, f"{r['nr']}.pdf"), "rb") as f:
            anhaenge.append((f"Rechnung-{r['nr']}.pdf", f.read()))
    anhaenge += list(extra)
    if not anhaenge:
        raise ValueError("Die Mail hat keinen Anhang.")
    betreff = betreff or a["mail"].get("betreff") or f"Dein Thumbnail{(' für ' + a['kanal']) if a.get('kanal') else ''}"
    text = (text or antwort_text(s, a)).replace("{zahlung}", rechnung.zahlungs_hinweis(e, r))
    mid = mail_raus(e, a["email"], betreff, text, anhaenge, senden, a["mail"].get("message_id", ""), a["mail"].get("references", ""))
    with store.aendern() as s:
        a = store.auftrag(s, a_id)
        if r:
            next(x for x in s["rechnungen"] if x["id"] == r["id"])["verschickt"] = store.jetzt() if senden else ""
        if senden:
            a["gesendet"] = store.jetzt()
            a["mail"]["message_id"] = mid  # damit die Antwort des Kunden im selben Verlauf landet
            a["aenderungen"].append({"zeit": store.jetzt(), "von": "du", "fotos": [],
                                     "text": f"Mail gesendet mit {len(anhaenge)} Anhang/Anhängen: {betreff}"})
            if a["status"] != "archiv":
                a["status"] = "geliefert"
                a["geliefert"] = a.get("geliefert") or store.jetzt()
            store.ereignis(s, f"Mail mit {len(anhaenge)} Anhang/Anhängen gesendet an {a['kanal'] or a['email']}", a_id)
        else:
            a["gmail_entwurf"] = store.jetzt()
            if a["status"] in ("neu", "bereit", "aenderung"):
                a["status"] = "in_gmail"
            store.ereignis(s, f"Antwort-Entwurf mit {len(anhaenge)} Anhang/Anhängen in Gmail angelegt: {a['kanal'] or a['email']}", a_id)


def abo_rechnung(email, senden=False, text=None):
    """Monatsrechnung für ein Abo erstellen und per Mail schicken (oder als Entwurf)."""
    with store.aendern() as s:
        k = store.kunde_fuer(s, email)
        if not k:
            raise ValueError("Kunde nicht gefunden")
        e = s["einstellungen"]
        von = rechnung._ab(k.get("bezahlt_bis"))
        bis = _monat_weiter(von) - dt.timedelta(days=1)
        posten = f"Monats-Abo Thumbnails (unbegrenzt), {von.strftime('%d.%m.%Y')} bis {bis.strftime('%d.%m.%Y')}"
        r = rechnung.anlegen(s, k["email"], k.get("name", ""), k.get("kanal", ""), posten,
                             k.get("abo_betrag") or e.get("preis_abo") or 0)
        r["abo"] = True
        store.ereignis(s, f"Abo-Rechnung {r['nr']} erstellt: {rechnung.euro(r['betrag'])} an {k['kanal'] or k['email']}")
        r, k = dict(r), dict(k)
    pfad = rechnung_pdf(r["id"])
    s = store.lesen()
    e = s["einstellungen"]
    if not (e["gmail"] and e["app_passwort"]):
        return r  # Rechnung liegt als PDF bereit, Mail geht ohne Gmail nicht
    a = {"name": k.get("name", ""), "kanal": k.get("kanal", ""), "thema": ""}
    text = (text or antwort_text(s, a, e.get("abo_rechnung_text"))).replace("{zahlung}", rechnung.zahlungs_hinweis(e, r))
    with open(pfad, "rb") as f:
        mail_raus(e, k["email"], f"Rechnung {r['nr']} – Thumbnail-Abo", text, [(f"Rechnung-{r['nr']}.pdf", f.read())], senden)
    with store.aendern() as s:
        x = next(x for x in s["rechnungen"] if x["id"] == r["id"])
        x["verschickt"] = store.jetzt() if senden else ""
        store.ereignis(s, f"Abo-Rechnung {r['nr']} " + ("gesendet" if senden else "als Gmail-Entwurf angelegt"))
    return r


def rechnung_bezahlt(s, r, bezahlt=True):
    """Rechnung als bezahlt markieren: Zahlung buchen, Auftrag bzw. Abo mitziehen."""
    if bezahlt and not r.get("bezahlt"):
        r["bezahlt"] = dt.date.today().isoformat()
        zahlung_buchen(s, r["betrag"], r["email"], f"{r['nr']} · {r['posten']}", r.get("auftrag", ""))
        s["zahlungen"][0]["rechnung"] = r["id"]
        a = store.auftrag(s, r.get("auftrag", ""))
        if a:
            a["bezahlt"] = True
        if r.get("abo"):
            k = store.kunde_fuer(s, r["email"])
            if k:
                k["bezahlt_bis"] = _monat_weiter(rechnung._ab(k.get("bezahlt_bis"))).isoformat()
                k["abo_status"], k["paket"] = "aktiv", "Abo"
                k["abo_seit"] = k.get("abo_seit") or dt.date.today().isoformat()
    elif not bezahlt and r.get("bezahlt"):
        r["bezahlt"] = ""
        s["zahlungen"] = [z for z in s["zahlungen"] if z.get("rechnung") != r["id"]]
        a = store.auftrag(s, r.get("auftrag", ""))
        if a:
            a["bezahlt"] = False


# ======================= Gmail abrufen =======================
def mail_pruefen():
    if not mail_lock.acquire(blocking=False):
        return "läuft schon"
    status["mail_laeuft"] = True
    try:
        s = store.lesen()
        e = s["einstellungen"]
        if not (e["gmail"] and e["app_passwort"]):
            return "nicht eingerichtet"
        bekannte = {a["email"] for a in s["auftraege"] if a["email"] and a["status"] != "archiv"}
        bekannte |= {k["email"] for k in s["kunden"] if k.get("abo_status") in ("aktiv", "angefragt")}
        gesehen = set(s["mail"]["gesehen"])
        imap = mail.verbinden(e["gmail"], e["app_passwort"])
        try:
            mails = mail.neue_mails(imap, e["gmail"], lambda betreff, von: planer.ist_bestellung(betreff) or von in bekannte, gesehen)
        finally:
            try:
                imap.logout()
            except Exception:
                pass
        neue_auftraege = []
        for m in sorted(mails, key=lambda m: m["datum"]):
            try:
                if planer.ist_bestellung(m["betreff"]) and not re.match(r"^\s*(re|aw)\s*:", m["betreff"], re.I):
                    b = planer.bestellung_lesen(m["betreff"], m["text"], m["von_name"], m["von_mail"])
                    neue_auftraege.append(auftrag_anlegen(b, "gmail", m, m["bilder"]))
                else:
                    kunden_antwort(m)
            except Exception as ex:
                traceback.print_exc()
                with store.aendern() as s2:
                    store.ereignis(s2, f"Mail „{m['betreff']}“ konnte nicht verarbeitet werden: {ex}")
            with store.aendern() as s2:
                s2["mail"]["gesehen"] = (s2["mail"]["gesehen"] + [m["message_id"]])[-3000:]
        if e.get("entwurf_automatisch"):
            for a_id in neue_auftraege:
                try:
                    gmail_entwurf(a_id)
                except Exception as ex:
                    with store.aendern() as s2:
                        store.ereignis(s2, f"Gmail-Entwurf fehlgeschlagen: {ex}", a_id)
        with store.aendern() as s2:
            s2["mail"]["letzte_pruefung"] = store.jetzt()
            s2["mail"]["fehler"] = ""
        return f"{len(mails)} neue Mail(s)"
    except Exception as ex:
        traceback.print_exc()
        text = str(ex)
        if "AUTHENTICATIONFAILED" in text or "Invalid credentials" in text:
            text = "Anmeldung bei Gmail fehlgeschlagen. Prüfe Adresse und App-Passwort."
        with store.aendern() as s2:
            s2["mail"]["fehler"] = text
            s2["mail"]["letzte_pruefung"] = store.jetzt()
        return text
    finally:
        status["mail_laeuft"] = False
        mail_lock.release()


def kunden_antwort(m):
    """Antwort eines Kunden: als Änderungswunsch an seinen neuesten offenen Auftrag hängen."""
    with store.aendern() as s:
        kandidaten = [a for a in s["auftraege"] if a["email"] == m["von_mail"] and a["status"] != "archiv"]
        if not kandidaten:
            return
        a = kandidaten[0]
        text = mail.ohne_zitat(m["text"]) or "(ohne Text)"
        neue_fotos = [foto_speichern(a["id"], n, d) for n, d in m["bilder"]]
        a["fotos"] += neue_fotos
        a["aenderungen"].append({"zeit": m["datum"], "von": "kunde", "text": text, "fotos": neue_fotos})
        a["mail"]["message_id"] = m["message_id"] or a["mail"].get("message_id", "")
        a["mail"]["references"] = m.get("references", "")
        a["status"] = "aenderung"
        store.ereignis(s, f"Antwort von {a['kanal'] or a['email']}: „{text[:80]}“", a["id"])


def abos_aufraeumen():
    """Abos, deren Kündigungsdatum erreicht ist, auf "gekündigt" setzen."""
    heute = dt.date.today().isoformat()
    with store.aendern() as s:
        for k in s["kunden"]:
            if k.get("abo_status") == "aktiv" and k.get("kuendigt_zum") and k["kuendigt_zum"] <= heute:
                k["abo_status"] = "gekündigt"
                store.ereignis(s, f"Abo beendet: {k['kanal'] or k['email']}")


def zeitplan():
    while True:
        try:
            abos_aufraeumen()
            mail_pruefen()
        except Exception:
            traceback.print_exc()
        minuten = max(2, int(store.lesen()["einstellungen"].get("pruefen_minuten") or 5))
        time.sleep(minuten * 60)


# ======================= Zahlungen =======================
def zahlung_buchen(s, betrag, email, text, auftrag_id=""):
    s.setdefault("zahlungen", []).insert(0, {"id": store.neue_id(), "zeit": store.jetzt(), "betrag": round(betrag, 2),
                                             "email": email, "text": text, "auftrag": auftrag_id})
    store.ereignis(s, f"Zahlung {betrag:.2f} €".replace(".", ",") + f": {text}", auftrag_id)


def _datum(t):
    try:
        return dt.date.fromisoformat(str(t)[:10])
    except ValueError:
        return None


def _monat_weiter(d):
    j, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    for tag in (d.day, 30, 29, 28):
        try:
            return dt.date(j, m, tag)
        except ValueError:
            continue


# ======================= Übersicht =======================
def kennzahlen(s):
    e = s["einstellungen"]
    monat = dt.date.today().strftime("%Y-%m")
    auftraege = s["auftraege"]
    geliefert_monat = [a for a in auftraege if (a.get("geliefert") or "").startswith(monat)]
    abos_aktiv = [k for k in s["kunden"] if k.get("abo_status") == "aktiv"]
    einzel_monat = [a for a in geliefert_monat if a["paket"] != "Monats-Abo"]
    zahlungen = s.get("zahlungen", [])
    return {
        "einnahmen_gesamt": round(sum(z["betrag"] for z in zahlungen), 2),
        "einnahmen_monat": round(sum(z["betrag"] for z in zahlungen if z["zeit"].startswith(monat)), 2),
        "offen": sum(1 for a in auftraege if a["status"] in OFFEN),
        "aenderungen": sum(1 for a in auftraege if a["status"] == "aenderung"),
        "abos_aktiv": len(abos_aktiv),
        "abos_angefragt": sum(1 for k in s["kunden"] if k.get("abo_status") == "angefragt"),
        "abos_kuendigen": sum(1 for k in s["kunden"] if k.get("abo_status") == "aktiv" and k.get("kuendigt_zum")),
        "abo_umsatz": round(sum(float(k.get("abo_betrag") or e.get("preis_abo") or 0) for k in abos_aktiv if not k.get("kuendigt_zum")), 2),
        "abo_umsatz_hinweis": "pro Monat",
        "geliefert_monat": len(geliefert_monat),
        "umsatz_monat": len(abos_aktiv) * float(e.get("preis_abo") or 0) + len(einzel_monat) * float(e.get("preis_einzel") or 0),
        "offen_betrag": round(sum(r["betrag"] for r in s["rechnungen"] if not r.get("bezahlt") and not r.get("storniert")), 2),
        "offen_rechnungen": sum(1 for r in s["rechnungen"] if not r.get("bezahlt") and not r.get("storniert")),
        "ueberfaellig": sum(1 for r in s["rechnungen"] if not r.get("bezahlt") and not r.get("storniert") and r["faellig"] < dt.date.today().isoformat()),
        "abos_faellig": sum(1 for k in abos_aktiv if k.get("bezahlt_bis") and k["bezahlt_bis"] <= (dt.date.today() + dt.timedelta(days=3)).isoformat()),
        "unbezahlt": sum(1 for a in auftraege if a["status"] == "geliefert" and not a.get("bezahlt") and a["paket"] != "Monats-Abo"),
    }


def stand():
    s = store.lesen()
    e = dict(s["einstellungen"])
    for g in GEHEIM:
        e[g] = "••••" if e.get(g) else ""
    return {
        "einstellungen": e, "auftraege": s["auftraege"], "kunden": s["kunden"], "verlauf": s["verlauf"][:60],
        "zahlungen": s.get("zahlungen", [])[:200],
        "rechnungen": s.get("rechnungen", [])[:300],
        "mail": {"letzte_pruefung": s["mail"]["letzte_pruefung"], "fehler": s["mail"]["fehler"],
                 "laeuft": status["mail_laeuft"]},
        "kennzahlen": kennzahlen(s), "version": VERSION,
        "optionen": {"vorlagen": planer.VORLAGEN, "stile": planer.STILE, "schriften": planer.SCHRIFTEN,
                     "emojis": sorted(f[:-4] for f in os.listdir(os.path.join(render.ASSETS, "emoji")) if f.endswith(".png"))},
    }


# ======================= Website-Editor =======================
website_cache = {}


def _gh_einstellungen():
    e = store.lesen()["einstellungen"]
    if not e.get("github_token"):
        raise ValueError("Für den Website-Editor fehlt der GitHub-Token (Einstellungen).")
    return e["github_token"], e["github_repo"], e["github_branch"], e["github_datei"]


def website_laden():
    inhalt, sha = website.laden(*_gh_einstellungen())
    website_cache.update(inhalt=inhalt, sha=sha)
    return inhalt, sha


def website_speichern(d):
    """Änderungen immer auf den frischesten Stand anwenden und committen. Bei einem Wettlauf einmal neu versuchen."""
    token, repo, branch, datei = _gh_einstellungen()
    config, texte, bilder = d.get("config") or {}, d.get("texte") or {}, d.get("bilder") or {}
    if not (config or texte or bilder):
        raise ValueError("Keine Änderungen.")
    teile = ([f"{len(config)} Einstellung(en)"] if config else []) + ([f"{len(texte)} Text(e)"] if texte else []) + \
            ([f"{len(bilder)} Bild(er)"] if bilder else [])
    for versuch in range(2):
        inhalt, sha = website.laden(token, repo, branch, datei)
        neu = website.config_setzen(inhalt, config) if config else inhalt
        neu = website.texte_setzen(neu, texte) if texte else neu
        for name, data_url in bilder.items():
            neu = website.bild_setzen(neu, name, data_url)
        try:
            commit = website.speichern(token, repo, branch, datei, neu, sha, "Website-Editor: " + ", ".join(teile) + " geändert")
            break
        except website.WebsiteFehler as ex:
            if versuch or "422" not in str(ex) and "409" not in str(ex):
                raise
    website_cache.update(inhalt=neu, sha=commit)
    with store.aendern() as s:  # Preise der App mitziehen, damit Zahlungen und Kennzahlen stimmen
        for web_key, app_key in (("preisEinzel", "preis_einzel"), ("preisAbo", "preis_abo")):
            if web_key in config:
                s["einstellungen"][app_key] = float(str(config[web_key]).replace(",", "."))
        store.ereignis(s, "Website geändert: " + ", ".join(teile))
    return dict(website.lesen(neu), sha=commit, url=store.lesen()["einstellungen"]["website_url"], stand=stand())


# ======================= Website =======================
class Handler(BaseHTTPRequestHandler):
    server_version = "ThumbnailZentrale"

    def log_message(self, *a):
        pass

    def _auth(self):
        if not PASSWORD:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                if base64.b64decode(h[6:]).decode().split(":", 1)[1] == PASSWORD:
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Thumbnail-Zentrale"')
        self.end_headers()
        return False

    def _senden(self, code, body, typ="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _datei(self, pfad, download=False):
        if not os.path.isfile(pfad):
            return self._senden(404, {"fehler": "nicht gefunden"})
        typ = mimetypes.guess_type(pfad)[0] or "application/octet-stream"
        with open(pfad, "rb") as f:
            daten = f.read()
        extra = {"Content-Disposition": f'attachment; filename="{os.path.basename(pfad)}"'} if download else {}
        self._senden(200, daten, typ, extra)

    def _json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        if not self._auth():
            return
        url = urllib.parse.urlparse(self.path)
        p = urllib.parse.unquote(url.path)
        q = urllib.parse.parse_qs(url.query)
        if p in ("/", "/index.html"):
            return self._datei(os.path.join(WEB, "index.html"))
        if p.startswith("/web/") and ".." not in p:
            return self._datei(os.path.join(WEB, p[5:]))
        if p.startswith("/assets/") and ".." not in p:
            return self._datei(os.path.join(render.ASSETS, p[8:]))
        m = re.match(r"^/rechnungen/(RE-[\d\-]+\.pdf)$", p)
        if m:
            return self._datei(os.path.join(store.RECHNUNGEN, m.group(1)), download="download" in q)
        m = re.match(r"^/dateien/([\w\-]+)/([\w.\-]+)$", p)
        if m:
            return self._datei(os.path.join(store.AUFTRAEGE, m.group(1), m.group(2)), download="download" in q)
        if p == "/api/stand":
            return self._senden(200, stand())
        m = re.match(r"^/api/website/bild/([\w\-]+)$", p)
        if m:
            src = website.bild_daten(website_cache.get("inhalt", ""), m.group(1))
            if not src.startswith("data:"):
                return self._senden(404, {"fehler": "nicht gefunden"})
            kopf, daten = src.split(",", 1)
            return self._senden(200, base64.b64decode(daten), kopf[5:].split(";")[0], {"Cache-Control": "max-age=60"})
        self._senden(404, {"fehler": "nicht gefunden"})

    def do_POST(self):
        if not self._auth():
            return
        p = urllib.parse.urlparse(self.path).path
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            return self._post(p, q)
        except Exception as ex:
            traceback.print_exc()
            self._senden(400, {"fehler": str(ex)})

    def _post(self, p, q):
        if p == "/api/vorschau":
            d = self._json()
            e = planer.entwurf_pruefen(d.get("entwurf") or {})
            foto_url = f"/dateien/{d['auftrag']}/" if re.fullmatch(r"[\w\-]+", d.get("auftrag", "")) else ""
            return self._senden(200, render.thumbnail_html(e, "/assets/", foto_url), "text/html; charset=utf-8")

        if p == "/api/auftrag":  # Auftrag von Hand anlegen
            d = self._json()
            b = {k: str(d.get(k, "")).strip() for k in ("name", "kanal", "email", "thema", "wuensche")}
            b["email"] = b["email"].lower()
            b["paket"] = "Monats-Abo" if d.get("paket") == "Monats-Abo" else "Einzel-Thumbnail"
            return self._senden(200, {"id": auftrag_anlegen(b)})

        m = re.match(r"^/api/auftrag/([\w\-]+)/(\w+)(?:/(\d))?$", p)
        if m:
            return self._auftrag_aktion(m.group(1), m.group(2), int(m.group(3)) if m.group(3) else None, q)

        if p == "/api/kunde":
            d = self._json()
            with store.aendern() as s:
                k = store.kunde_fuer(s, d.get("email"), anlegen={})
                for feld in ("name", "kanal", "paket", "abo_status", "abo_seit", "bezahlt_bis", "notiz", "kuendigt_zum", "abo_betrag"):
                    if feld in d:
                        k[feld] = str(d[feld])
                if d.get("loeschen"):
                    s["kunden"].remove(k)
            return self._senden(200, stand())

        if p == "/api/abo-zahlung":  # ein Abo-Monat ist bezahlt: Zahlung buchen, "bezahlt bis" einen Monat weiter
            d = self._json()
            with store.aendern() as s:
                k = store.kunde_fuer(s, d.get("email"))
                if not k:
                    raise ValueError("Kunde nicht gefunden")
                r = next((r for r in reversed(s["rechnungen"]) if r["email"] == k["email"] and r.get("abo")
                          and not r.get("bezahlt") and not r.get("storniert")), None)
                if r:  # offene Abo-Rechnung vorhanden: die gilt als bezahlt
                    rechnung_bezahlt(s, r)
                    return self._senden(200, stand())
                betrag = float(d.get("betrag") or s["einstellungen"].get("preis_abo") or 0)
                zahlung_buchen(s, betrag, k["email"], f"Abo {k['kanal'] or k['name'] or k['email']}")
                start = max(dt.date.today(), _datum(k.get("bezahlt_bis")) or dt.date.today())
                k["bezahlt_bis"] = _monat_weiter(start).isoformat()
                k["abo_status"] = "aktiv"
                k["paket"] = "Abo"
                k["abo_seit"] = k.get("abo_seit") or dt.date.today().isoformat()
            return self._senden(200, stand())

        if p == "/api/zahlung":  # sonstige Zahlung von Hand, oder löschen
            d = self._json()
            with store.aendern() as s:
                if d.get("loeschen"):
                    s["zahlungen"] = [z for z in s["zahlungen"] if z["id"] != d["loeschen"]]
                else:
                    zahlung_buchen(s, float(d.get("betrag") or 0), d.get("email", ""), str(d.get("text", "Zahlung")))
            return self._senden(200, stand())

        if p == "/api/einstellungen":
            d = self._json()
            with store.aendern() as s:
                e = s["einstellungen"]
                for k, v in d.items():
                    if k not in e or (k in GEHEIM and v in ("", "••••")):  # leer = unverändert
                        continue
                    if isinstance(e[k], bool):
                        v = bool(v)
                    elif isinstance(e[k], (int, float)) and not isinstance(e[k], bool):
                        v = float(v) if "." in str(v) else int(v or 0)
                    else:
                        v = str(v).strip() if k not in ("antwort_text", "liefer_text", "abo_rechnung_text") else str(v)
                    if k == "app_passwort":
                        v = mail.passwort_pruefen(v)
                    if k == "iban" and v:
                        if not rechnung.iban_gueltig(v):
                            raise ValueError("Die IBAN stimmt nicht. Bitte nochmal prüfen.")
                        v = rechnung.iban_schoen(v)
                    e[k] = v
            return self._senden(200, stand())

        if p == "/api/mail/pruefen":
            ergebnis = mail_pruefen()
            return self._senden(200, dict(stand(), ergebnis=ergebnis))

        if p == "/api/rechnung":
            d = self._json()
            if d.get("abo_email"):  # Monatsrechnung fürs Abo
                abo_rechnung(d["abo_email"], senden=d.get("modus") == "senden")
                return self._senden(200, stand())
            if d.get("auftrag"):  # nur Rechnung erstellen, ohne Mail
                rechnung_fuer_auftrag(d["auftrag"])
                return self._senden(200, stand())
            with store.aendern() as s:
                r = next((r for r in s["rechnungen"] if r["id"] == d.get("id")), None)
                if not r:
                    raise ValueError("Rechnung nicht gefunden")
                if "bezahlt" in d:
                    rechnung_bezahlt(s, r, bool(d["bezahlt"]))
                if d.get("storniert") and not r.get("bezahlt"):
                    r["storniert"] = dt.date.today().isoformat()
                    store.ereignis(s, f"Rechnung {r['nr']} storniert", r.get("auftrag", ""))
            if d.get("neu_bauen"):
                rechnung_pdf(d["id"])
            return self._senden(200, stand())

        if p == "/api/website":  # Website frisch von GitHub laden
            inhalt, sha = website_laden()
            return self._senden(200, dict(website.lesen(inhalt), sha=sha, url=store.lesen()["einstellungen"]["website_url"]))

        if p == "/api/website/speichern":
            return self._senden(200, website_speichern(self._json()))

        if p == "/api/mail/test":
            e = store.lesen()["einstellungen"]
            imap = mail.verbinden(e["gmail"], e["app_passwort"])
            ordner = mail.entwuerfe_ordner(imap)
            imap.logout()
            return self._senden(200, {"ok": True, "entwuerfe": ordner})

        self._senden(404, {"fehler": "unbekannt"})

    def _auftrag_aktion(self, a_id, aktion, n, q):
        s = store.lesen()
        a = store.auftrag(s, a_id)
        if not a:
            return self._senden(404, {"fehler": "Auftrag nicht gefunden"})

        if aktion == "entwurf":  # Entwurf aus dem Editor speichern und neu rendern
            e = planer.entwurf_pruefen(self._json().get("entwurf") or {})
            with store.aendern() as s:
                x = store.auftrag(s, a_id)
                x["entwuerfe"][n]["entwurf"] = e
                x["geoeffnet"] = True
                if x["status"] == "in_gmail":  # der Gmail-Entwurf ist jetzt veraltet
                    x["status"] = "bereit"
            rendern(a_id, [n])
        elif aktion == "ki":
            d = self._json()
            schluessel = s["einstellungen"].get("ki_schluessel")
            if not schluessel:
                raise ValueError("Für Änderungen in eigenen Worten fehlt der KI-Schlüssel (Einstellungen).")
            neu = ki.aenderung(schluessel, a["entwuerfe"][n]["entwurf"], d.get("wunsch", ""), fotos_von(a), a.get("thema", ""))
            with store.aendern() as s:
                store.auftrag(s, a_id)["entwuerfe"][n]["entwurf"] = neu
            rendern(a_id, [n])
        elif aktion == "neuplanen":
            d = self._json()
            b = {k: d.get(k, a.get(k, "")) for k in ("name", "kanal", "email", "thema", "wuensche", "paket")}
            neu = planer.entwuerfe_planen(b, (a["fotos"] or [""])[0])
            with store.aendern() as s:
                x = store.auftrag(s, a_id)
                x.update({k: b[k] for k in ("name", "kanal", "thema", "wuensche")})
                x["entwuerfe"] = [{"entwurf": e, "stand": 0} for e in neu]
            rendern(a_id)
        elif aktion == "gmail":
            d = self._json()
            nummern = [int(x) for x in d.get("varianten", [])] or None
            gmail_entwurf(a_id, nummern, d.get("text") or None)
        elif aktion == "versand":  # Fenster "Per Mail senden": Text, Betreff, Bilder, eigene Anhänge
            d = self._json()
            extra = []
            for x in d.get("extra", [])[:10]:
                daten = base64.b64decode(str(x.get("daten", "")).split(",")[-1])
                if len(daten) > 20_000_000:
                    raise ValueError("Ein Anhang ist größer als 20 MB.")
                extra.append((re.sub(r"[^\w.\- ]", "_", os.path.basename(str(x.get("name") or "anhang")))[-80:], daten))
            gmail_entwurf(a_id, [int(x) for x in d.get("varianten", [])], str(d.get("text") or "") or None,
                          str(d.get("betreff") or "") or None, extra, senden=d.get("modus") == "senden",
                          mit_rechnung=bool(d.get("rechnung")))
        elif aktion == "mailvorschlag":
            e = s["einstellungen"]
            offen = next((r for r in s["rechnungen"] if r["auftrag"] == a_id and not r.get("storniert")), None)
            fertig = a["status"] in ("in_gmail", "geliefert") or bool(a.get("geoeffnet"))
            return self._senden(200, {
                "betreff": a["mail"].get("betreff") or f"Dein Thumbnail{(' für ' + a['kanal']) if a.get('kanal') else ''}",
                "text": antwort_text(s, a, e.get("liefer_text") if fertig else e["antwort_text"]),
                "rechnung": a["paket"] != "Monats-Abo" and not a.get("bezahlt"),
                "rechnung_nr": offen["nr"] if offen else rechnung.naechste_nummer(s),
                "rechnung_betrag": offen["betrag"] if offen else float(e.get("preis_einzel") or 0),
                "rechnung_vorhanden": bool(offen),
                "iban": bool(e.get("iban")), "direkt": bool(e.get("direkt_senden")),
                "vorlagen": {"erste": antwort_text(s, a, e["antwort_text"]), "fertig": antwort_text(s, a, e.get("liefer_text"))},
            })
        elif aktion == "status":
            d = self._json()
            with store.aendern() as s:
                x = store.auftrag(s, a_id)
                if d.get("status") in ("neu", "bereit", "in_gmail", "aenderung", "geliefert", "archiv"):
                    x["status"] = d["status"]
                    if d["status"] == "geliefert" and not x.get("geliefert"):
                        x["geliefert"] = store.jetzt()
                        store.ereignis(s, f"Geliefert: {x['kanal'] or x['email']}", a_id)
                r = next((r for r in s["rechnungen"] if r["auftrag"] == a_id and not r.get("storniert")), None)
                if "bezahlt" in d and r:
                    rechnung_bezahlt(s, r, bool(d["bezahlt"]))
                elif "bezahlt" in d and bool(d["bezahlt"]) != bool(x.get("bezahlt")):
                    x["bezahlt"] = bool(d["bezahlt"])
                    if x["paket"] != "Monats-Abo":  # Einzel-Thumbnail: Zahlung verbuchen bzw. zurücknehmen
                        if x["bezahlt"]:
                            zahlung_buchen(s, float(s["einstellungen"].get("preis_einzel") or 0), x["email"],
                                           f"Einzel-Thumbnail {x['kanal'] or x['name']}", a_id)
                        else:
                            s["zahlungen"] = [z for z in s["zahlungen"] if z.get("auftrag") != a_id]
                if "email" in d:
                    x["email"] = str(d["email"]).strip().lower()
                if "geoeffnet" in d:
                    x["geoeffnet"] = bool(d["geoeffnet"])
        elif aktion == "notiz":
            text = str(self._json().get("text", "")).strip()
            if text:
                with store.aendern() as s:
                    store.auftrag(s, a_id)["aenderungen"].append({"zeit": store.jetzt(), "von": "du", "text": text, "fotos": []})
        elif aktion == "foto":
            n_bytes = int(self.headers.get("Content-Length") or 0)
            if not 0 < n_bytes < 20_000_000:
                raise ValueError("Bild fehlt oder ist größer als 20 MB.")
            name = foto_speichern(a_id, (q.get("name") or ["foto.jpg"])[0], self.rfile.read(n_bytes))
            with store.aendern() as s:
                store.auftrag(s, a_id)["fotos"].append(name)
        elif aktion == "loeschen":
            with store.aendern() as s:
                s["auftraege"] = [x for x in s["auftraege"] if x["id"] != a_id]
        else:
            return self._senden(404, {"fehler": "unbekannte Aktion"})
        self._senden(200, stand())


def main():
    store.lesen()
    threading.Thread(target=zeitplan, daemon=True).start()
    print(f"Thumbnail-Zentrale läuft auf Port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
