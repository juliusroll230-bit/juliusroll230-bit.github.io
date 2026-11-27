"""Akquise: neue Creator finden, ein persönliches Redesign bauen und eine Mail als Gmail-ENTWURF vorbereiten.

Gesendet wird hier nie etwas. Kaltakquise per Mail ist in Deutschland heikel (§ 7 UWG), deshalb entscheidest du
bei jedem Entwurf selbst in Gmail, ob er rausgeht. Antwortet ein Creator, merkt die App das beim Gmail-Abruf.
"""
import csv
import datetime as dt
import io
import os
import re
import shutil
import threading
import traceback

import freisteller
import ki
import mail
import planer
import render
import store
import youtube

STATUS = ["neu", "redesign", "entwurf", "gesendet", "nachgefasst", "antwort", "kunde", "kein_interesse"]
_warteschlange_lock = threading.Lock()
lauf = {"aktiv": False, "fertig": 0, "gesamt": 0, "aktuell": ""}

SPALTEN = {  # Spaltenname in der Excel-/CSV-Liste -> Feld
    "kanal": "kanal", "link": "link", "kanal-link": "link", "nische": "nische", "unterthema": "unterthema",
    "abos (ca.)": "abos", "abos": "abos", "videotitel": "videotitel", "video-link": "video_link", "video": "video_link",
    "e-mail": "email", "email": "email", "mail": "email", "status": "status", "kontaktiert am": "kontaktiert",
    "follow-up am": "followup", "notizen": "notiz", "notiz": "notiz", "priorität": "prioritaet", "prioritaet": "prioritaet",
    "ansprechpartner": "ansprechpartner", "name": "ansprechpartner",
}
STATUS_IMPORT = {"neu": "neu", "kontaktiert": "gesendet", "gesendet": "gesendet", "antwort": "antwort", "kunde": "kunde",
                 "kein interesse": "kein_interesse", "abgelehnt": "kein_interesse"}


def ordner(lead_id):
    p = os.path.join(store.DATA, "leads", lead_id)
    os.makedirs(p, exist_ok=True)
    return p


def lead(s, lead_id):
    return next((x for x in s.get("leads", []) if x["id"] == lead_id), None)


def _datum(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v.strftime("%Y-%m-%d")
    v = str(v or "").strip()
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", v)
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else v[:10]


def _zeilen_aus_datei(name, daten):
    if name.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(daten), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        reihen = list(ws.iter_rows(values_only=True))
        if not reihen:
            return []
        kopf = [str(k or "").strip().lower() for k in reihen[0]]
        return [dict(zip(kopf, r)) for r in reihen[1:]]
    text = daten.decode("utf-8-sig", "replace")
    trenner = ";" if text.count(";") > text.count(",") else ","
    return [{(k or "").strip().lower(): v for k, v in r.items()} for r in csv.DictReader(io.StringIO(text), delimiter=trenner)]


def importieren(name, daten):
    """Liest eine Lead-Liste (Excel oder CSV) ein. Vorhandene Leads (gleiche Mail oder gleicher Kanal) werden ergänzt."""
    neu, aktualisiert = 0, 0
    zeilen = _zeilen_aus_datei(name, daten)
    with store.aendern() as s:
        leads = s.setdefault("leads", [])
        for z in zeilen:
            d = {}
            for k, v in z.items():
                feld = SPALTEN.get(k)
                if feld and v not in (None, ""):
                    d[feld] = _datum(v) if feld in ("kontaktiert", "followup") else str(v).strip()
            if not d.get("kanal") and not d.get("link"):
                continue
            d["email"] = d.get("email", "").lower()
            if "@" not in d["email"]:
                d["email"] = ""
            d["status"] = STATUS_IMPORT.get(d.get("status", "neu").lower(), "neu")
            vorhanden = next((x for x in leads if (d["email"] and x.get("email") == d["email"]) or
                              (d.get("kanal") and x.get("kanal", "").lower() == d["kanal"].lower())), None)
            if vorhanden:
                for k, v in d.items():
                    if k == "status" and vorhanden.get("status") != "neu":
                        continue  # in der App gepflegten Status nicht überschreiben
                    if v and not vorhanden.get(k):
                        vorhanden[k] = v
                aktualisiert += 1
            else:
                leads.append(dict(_leer(), **d))
                neu += 1
        store.ereignis(s, f"Lead-Liste importiert: {neu} neu, {aktualisiert} ergänzt")
    return neu, aktualisiert


def _leer():
    return {"id": store.neue_id(), "kanal": "", "link": "", "nische": "", "unterthema": "", "abos": "", "email": "",
            "ansprechpartner": "", "videotitel": "", "video_link": "", "status": "neu", "prioritaet": "", "notiz": "",
            "kontaktiert": "", "followup": "", "angelegt": store.jetzt(), "redesign": {}, "mail": {}, "verlauf": []}


def anlegen(d):
    """Neuen Lead von Hand anlegen. Reicht ein Kanal-Link, holt die App das neueste Video selbst."""
    l = dict(_leer(), **{k: str(d.get(k, "")).strip() for k in ("kanal", "link", "nische", "email", "ansprechpartner",
                                                                  "videotitel", "video_link", "notiz", "abos")})
    l["email"] = l["email"].lower()
    if l["link"] and not l["video_link"]:
        videos = youtube.neueste_videos(l["link"], 1)
        if videos:
            l["video_link"] = f"https://www.youtube.com/watch?v={videos[0]['id']}"
            l["videotitel"] = l["videotitel"] or videos[0]["titel"]
    if l["video_link"] and not (l["videotitel"] and l["kanal"]):
        infos = youtube.video_infos(youtube.video_id(l["video_link"]))
        l["videotitel"] = l["videotitel"] or infos.get("titel", "")
        l["kanal"] = l["kanal"] or infos.get("kanal", "")
        l["link"] = l["link"] or infos.get("kanal_link", "")
    if not l["kanal"]:
        m = re.search(r"@([\w.\-]+)", l["link"])
        l["kanal"] = m.group(1) if m else "Neuer Kanal"
    with store.aendern() as s:
        s.setdefault("leads", []).insert(0, l)
        store.ereignis(s, f"Lead angelegt: {l['kanal']}")
    return l["id"]


def neuestes_video(lead_id):
    """Aktuelles Video des Kanals holen (damit das Redesign zu einem frischen Video passt)."""
    s = store.lesen()
    l = lead(s, lead_id)
    if not l.get("link"):
        raise ValueError("Für den Lead fehlt der Kanal-Link.")
    videos = youtube.neueste_videos(l["link"], 1)
    if not videos:
        raise ValueError("Kein Video gefunden. Ist der Kanal-Link richtig?")
    with store.aendern() as s:
        x = lead(s, lead_id)
        x["video_link"] = f"https://www.youtube.com/watch?v={videos[0]['id']}"
        x["videotitel"] = videos[0]["titel"]


def redesign(lead_id, original=None):
    """Original-Thumbnail holen, Person freistellen, Redesign planen (KI oder Regeln), rendern, Vorher/Nachher bauen.
    original: optional eigene Bilddaten statt YouTube."""
    s = store.lesen()
    l = lead(s, lead_id)
    e = s["einstellungen"]
    o = ordner(lead_id)
    titel = l.get("videotitel", "")
    if original is None:
        m = youtube.material(video_link=l.get("video_link", ""), kanal_link=l.get("link", ""))
        original = m.get("bild", b"")
        titel = titel or m.get("titel", "")
        if m.get("video_id") and not l.get("video_link"):
            with store.aendern() as s2:
                lead(s2, lead_id)["video_link"] = f"https://www.youtube.com/watch?v={m['video_id']}"
    for alt in os.listdir(o):
        if alt.startswith(("original", "person-frei", "redesign", "pitch")):
            os.remove(os.path.join(o, alt))
    hat_original, person = False, ""
    if original:
        with open(os.path.join(o, "original.jpg"), "wb") as f:
            f.write(original)
        hat_original = True
        try:
            if freisteller.verfuegbar() and freisteller.freistellen(os.path.join(o, "original.jpg"), os.path.join(o, "person-frei.png")):
                person = "person-frei.png"
        except Exception:
            traceback.print_exc()
    b = {"thema": titel, "kanal": l.get("kanal", ""), "wuensche": ""}
    entwurf, quelle = None, "regeln"
    if e.get("ki_schluessel"):
        try:
            k = ki.konzepte(e["ki_schluessel"], b, os.path.join(o, "original.jpg") if hat_original else "", bool(person))
            # für die Akquise zählt ein einziges, starkes Bild: das erste mit Person, sonst das erste
            wahl = next((x for x in k if x.get("mit_bild") and person), k[0])
            wahl = dict(wahl, foto=person if wahl.get("mit_bild") and person else "",
                        hintergrund="original.jpg" if hat_original and wahl.get("vorlage") in ("person", "strahlen") else "")
            entwurf, quelle = planer.entwurf_pruefen(wahl), "ki"
        except Exception as ex:
            traceback.print_exc()
            with store.aendern() as s2:
                store.ereignis(s2, f"KI-Redesign für {l['kanal']} fehlgeschlagen, Regeln übernehmen: {ex}")
    if entwurf is None:
        entwurf = planer.entwuerfe_planen(b, "", person, "original.jpg" if hat_original else "")[0]
    _rendern(lead_id, entwurf, hat_original)
    with store.aendern() as s2:
        x = lead(s2, lead_id)
        x["redesign"] = {"entwurf": entwurf, "stand": int(dt.datetime.now().timestamp()), "quelle": quelle,
                         "original": hat_original, "person": bool(person)}
        if x["status"] == "neu":
            x["status"] = "redesign"
        store.ereignis(s2, f"Redesign gebaut für {x['kanal']}" + (" (mit KI)" if quelle == "ki" else ""))


def _rendern(lead_id, entwurf, hat_original):
    o = ordner(lead_id)
    l = lead(store.lesen(), lead_id)
    render.als_png([(entwurf, o, os.path.join(o, "redesign.png"))])
    html = render.pitch_html(l.get("kanal", ""), l.get("videotitel", ""),
                             "file://" + os.path.join(o, "original.jpg") if hat_original else "",
                             "file://" + os.path.join(o, "redesign.png"), entwurf.get("idee", ""),
                             "file://" + render.ASSETS + "/")
    render.html_png(html, os.path.join(o, "pitch.png"))


def entwurf_aendern(lead_id, entwurf):
    """Redesign im Editor geändert: neu rendern."""
    e = planer.entwurf_pruefen(entwurf)
    l = lead(store.lesen(), lead_id)
    _rendern(lead_id, e, bool((l.get("redesign") or {}).get("original")))
    with store.aendern() as s:
        x = lead(s, lead_id)
        x["redesign"] = dict(x.get("redesign") or {}, entwurf=e, stand=int(dt.datetime.now().timestamp()))


def _vorlage_text(e, l):
    vorlage = e.get("akquise_text") or ""
    werte = {"kanal": l.get("kanal", ""), "videotitel": l.get("videotitel", ""), "dein_name": e.get("dein_name", ""),
             "preis_einzel": _zahl(e.get("preis_einzel")), "preis_abo": _zahl(e.get("preis_abo")),
             "website": e.get("website_url", ""), "anrede": ("Hi " + l["ansprechpartner"].split(" ")[0]) if l.get("ansprechpartner") else "Hi"}
    try:
        return vorlage.format(**werte)
    except (KeyError, IndexError, ValueError):
        return vorlage


def _zahl(x):
    try:
        x = float(x or 0)
        return str(int(x)) if x == int(x) else f"{x:.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return str(x)


def mail_schreiben(lead_id, mit_ki=True):
    s = store.lesen()
    l = lead(s, lead_id)
    e = s["einstellungen"]
    betreff = f"Thumbnail-Idee für dein Video „{l.get('videotitel', '')[:60]}“" if l.get("videotitel") else f"Thumbnail-Idee für {l.get('kanal', '')}"
    text, quelle = "", "vorlage"
    if mit_ki and e.get("ki_schluessel"):
        try:
            r = ki.akquise_mail(e["ki_schluessel"], l, e.get("dein_name", ""), _zahl(e.get("preis_einzel")),
                                _zahl(e.get("preis_abo")), e.get("website_url", ""))
            betreff, text, quelle = r.get("betreff") or betreff, r.get("text", ""), "ki"
        except Exception as ex:
            traceback.print_exc()
            with store.aendern() as s2:
                store.ereignis(s2, f"KI-Mail für {l['kanal']} fehlgeschlagen, Vorlage genommen: {ex}")
    if not text:
        text = _vorlage_text(e, l)
    with store.aendern() as s2:
        lead(s2, lead_id)["mail"] = {"betreff": betreff, "text": text, "quelle": quelle}
    return betreff, text


def gmail_entwurf(lead_id, betreff=None, text=None, nachfassen=False):
    """Legt die Mail mit Vorher/Nachher-Bild und Redesign als Gmail-ENTWURF an. Senden machst du selbst in Gmail."""
    s = store.lesen()
    l = lead(s, lead_id)
    e = s["einstellungen"]
    if not l.get("email"):
        raise ValueError("Für diesen Creator fehlt die E-Mail-Adresse (steht meist im Impressum oder unter „Kanalinfo“).")
    if not (e["gmail"] and e["app_passwort"]):
        raise ValueError("Gmail ist noch nicht verbunden (Einstellungen).")
    o = ordner(lead_id)
    anhaenge = []
    if nachfassen:
        betreff = betreff or "Re: " + ((l.get("mail") or {}).get("betreff") or "Thumbnail-Idee")
        text = text or _nachfass_text(e, l)
    else:
        if not os.path.exists(os.path.join(o, "pitch.png")):
            raise ValueError("Bau zuerst das Redesign.")
        betreff = betreff or (l.get("mail") or {}).get("betreff")
        text = text or (l.get("mail") or {}).get("text")
        if not (betreff and text):
            betreff, text = mail_schreiben(lead_id)
        slug = re.sub(r"[^a-z0-9]+", "-", l.get("kanal", "kanal").lower()).strip("-") or "kanal"
        for datei, name in (("pitch.png", f"vorher-nachher-{slug}.png"), ("redesign.png", f"thumbnail-idee-{slug}.png")):
            with open(os.path.join(o, datei), "rb") as f:
                anhaenge.append((name, f.read()))
    msg = mail.entwurf_bauen(e["gmail"], l["email"], betreff, text, anhaenge=anhaenge,
                             html_text=mail.html_mail(text, e.get("dein_name", "")), absender_name=e.get("dein_name", ""),
                             als_antwort=nachfassen)
    imap = mail.verbinden(e["gmail"], e["app_passwort"])
    try:
        mail.entwurf_anlegen(imap, msg)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    with store.aendern() as s2:
        x = lead(s2, lead_id)
        x["mail"] = dict(x.get("mail") or {}, betreff=betreff if not nachfassen else (x.get("mail") or {}).get("betreff", betreff),
                         text=text if not nachfassen else (x.get("mail") or {}).get("text", text))
        x["verlauf"].append({"zeit": store.jetzt(), "text": ("Nachfass-Entwurf" if nachfassen else "Entwurf") + " in Gmail angelegt"})
        if not nachfassen and x["status"] in ("neu", "redesign"):
            x["status"] = "entwurf"
        store.ereignis(s2, f"Akquise-{'Nachfass-' if nachfassen else ''}Entwurf in Gmail: {x['kanal']}")


def _nachfass_text(e, l):
    vorlage = e.get("nachfass_text") or ""
    try:
        return vorlage.format(kanal=l.get("kanal", ""), videotitel=l.get("videotitel", ""), dein_name=e.get("dein_name", ""),
                              anrede=("Hi " + l["ansprechpartner"].split(" ")[0]) if l.get("ansprechpartner") else "Hi")
    except (KeyError, IndexError, ValueError):
        return vorlage


def status_setzen(lead_id, status, notiz=None):
    with store.aendern() as s:
        x = lead(s, lead_id)
        if status in STATUS and status != x["status"]:
            x["status"] = status
            heute = dt.date.today()
            if status == "gesendet":
                x["kontaktiert"] = heute.isoformat()
                x["followup"] = (heute + dt.timedelta(days=int(s["einstellungen"].get("nachfassen_tage") or 6))).isoformat()
            if status == "nachgefasst":
                x["followup"] = ""
            if status in ("antwort", "kunde", "kein_interesse"):
                x["followup"] = ""
            x["verlauf"].append({"zeit": store.jetzt(), "text": "Status: " + status})
        if notiz is not None:
            x["notiz"] = str(notiz)


def antwort_gekommen(s, von_mail, text, betreff):
    """Beim Gmail-Abruf: Mail von einem Lead. True, wenn es ein Lead war."""
    x = next((l for l in s.get("leads", []) if l.get("email") and l["email"] == von_mail), None)
    if not x:
        return False
    if x["status"] not in ("kunde", "kein_interesse"):
        x["status"] = "antwort"
    x["followup"] = ""
    x["verlauf"].append({"zeit": store.jetzt(), "text": "Antwort: " + (mail.ohne_zitat(text) or betreff)[:300]})
    store.ereignis(s, f"Antwort von {x['kanal']} auf deine Akquise-Mail")
    return True


def faellig(s):
    """Leads, bei denen heute Nachfassen dran ist."""
    heute = dt.date.today().isoformat()
    return [l for l in s.get("leads", []) if l.get("status") == "gesendet" and l.get("followup") and l["followup"] <= heute]


def stapel(anzahl=5, ids=None):
    """Für die nächsten Leads (oder die gewählten) im Hintergrund Redesign + Mail + Gmail-Entwurf vorbereiten."""
    if not _warteschlange_lock.acquire(blocking=False):
        raise ValueError("Es läuft schon eine Vorbereitung.")
    s = store.lesen()
    reihenfolge = {"A+": 0, "A": 1, "B": 2, "C": 3}
    if ids:
        liste = [l for l in s.get("leads", []) if l["id"] in ids]
    else:
        liste = sorted([l for l in s.get("leads", []) if l.get("status") == "neu" and l.get("email")],
                       key=lambda l: (reihenfolge.get(l.get("prioritaet", ""), 9), l.get("angelegt", "")))[:anzahl]
    if not liste:
        _warteschlange_lock.release()
        raise ValueError("Keine neuen Leads mit E-Mail-Adresse da.")
    lauf.update(aktiv=True, fertig=0, gesamt=len(liste), aktuell="")

    def arbeit():
        try:
            gmail_ok = bool(s["einstellungen"].get("gmail") and s["einstellungen"].get("app_passwort"))
            for l in liste:
                lauf["aktuell"] = l["kanal"]
                try:
                    redesign(l["id"])
                    mail_schreiben(l["id"])
                    if gmail_ok and l.get("email"):
                        gmail_entwurf(l["id"])
                except Exception as ex:
                    traceback.print_exc()
                    with store.aendern() as s2:
                        store.ereignis(s2, f"Akquise für {l['kanal']} fehlgeschlagen: {ex}")
                lauf["fertig"] += 1
        finally:
            lauf.update(aktiv=False, aktuell="")
            _warteschlange_lock.release()
    threading.Thread(target=arbeit, daemon=True).start()
    return len(liste)


def loeschen(lead_id):
    with store.aendern() as s:
        s["leads"] = [x for x in s.get("leads", []) if x["id"] != lead_id]
    shutil.rmtree(os.path.join(store.DATA, "leads", lead_id), ignore_errors=True)
