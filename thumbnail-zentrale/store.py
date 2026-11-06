"""Speichert alles als JSON im Datenordner (im Container /data, auf ZimaOS /DATA/AppData/thumbnail-zentrale)."""
import copy
import datetime as dt
import json
import os
import secrets
import threading

DATA = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DATEI = os.path.join(DATA, "zentrale.json")
AUFTRAEGE = os.path.join(DATA, "auftraege")

STANDARD = {
    "einstellungen": {
        "gmail": "",                  # deine Gmail-Adresse
        "app_passwort": "",           # Google-App-Passwort (16 Zeichen), NICHT dein normales Passwort
        "pruefen_minuten": 5,
        "entwurf_automatisch": True,  # Antwort-Entwurf mit Bildern sofort in Gmail anlegen
        "dein_name": "Julius",
        "preis_einzel": 5,
        "preis_abo": 35,
        "ki_schluessel": "",          # optional: Anthropic-API-Schlüssel für Änderungen in eigenen Worten
        "antwort_text": (
            "Hallo {vorname},\n\n"
            "danke für deine Bestellung{thema_satz}! Im Anhang findest du drei erste Entwürfe (A, B und C).\n\n"
            "Sag mir einfach, welcher dir am besten gefällt und was ich noch ändern soll, zum Beispiel Text, Farben oder Bild. "
            "Fotos von dir oder Screenshots aus dem Video kannst du direkt an deine Antwort hängen.\n\n"
            "Viele Grüße\n{dein_name}"
        ),
    },
    "auftraege": [],
    "kunden": [],
    "verlauf": [],
    "zahlungen": [],
    "mail": {"letzte_pruefung": "", "fehler": "", "gesehen": []},
}

_lock = threading.RLock()
_state = None


def jetzt():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _laden():
    global _state
    if _state is None:
        os.makedirs(AUFTRAEGE, exist_ok=True)
        try:
            with open(DATEI, encoding="utf-8") as f:
                _state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _state = {}
        for k, v in STANDARD.items():
            if k not in _state:
                _state[k] = copy.deepcopy(v)
            elif isinstance(v, dict):
                for k2, v2 in v.items():
                    _state[k].setdefault(k2, copy.deepcopy(v2))
    return _state


def _speichern():
    tmp = DATEI + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATEI)


class aendern:
    """with store.aendern() as s: ...  -> speichert danach automatisch."""
    def __enter__(self):
        _lock.acquire()
        return _laden()

    def __exit__(self, typ, wert, tb):
        try:
            if typ is None:
                _speichern()
        finally:
            _lock.release()


def lesen():
    with _lock:
        return copy.deepcopy(_laden())


def neue_id():
    return dt.datetime.now().strftime("%y%m%d-%H%M%S-") + secrets.token_hex(2)


def ordner(auftrag_id):
    p = os.path.join(AUFTRAEGE, auftrag_id)
    os.makedirs(p, exist_ok=True)
    return p


def ereignis(s, text, auftrag_id=""):
    s["verlauf"].insert(0, {"zeit": jetzt(), "text": text, "auftrag": auftrag_id})
    del s["verlauf"][300:]


def auftrag(s, auftrag_id):
    return next((a for a in s["auftraege"] if a["id"] == auftrag_id), None)


def kunde_fuer(s, email, anlegen=None):
    email = (email or "").lower()
    k = next((k for k in s["kunden"] if k["email"] == email), None)
    if k is None and anlegen:
        k = dict({"email": email, "name": "", "kanal": "", "paket": "Einzel", "abo_status": "", "abo_seit": "",
                  "bezahlt_bis": "", "notiz": "", "angelegt": jetzt()}, **anlegen)
        s["kunden"].append(k)
    return k
