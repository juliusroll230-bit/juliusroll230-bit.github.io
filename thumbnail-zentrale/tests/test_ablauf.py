"""Kompletter Ablauf mit nachgebautem Gmail und GitHub: Bestellung rein -> 3 PNGs -> Entwurf mit Anhängen -> Kunden-Antwort
-> Lieferung mit Rechnung (IBAN) -> bezahlt -> Abo-Rechnung -> Website-Editor.

  python3 tests/test_ablauf.py
"""
import email
import json
import os
import sys
import tempfile
import threading
import time
import base64
import urllib.request
from email.message import EmailMessage
from email.policy import default as POLICY

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="tz-test-")
os.environ.setdefault("PORT", "18091")
os.environ["GITHUB_API"] = "http://127.0.0.1:18092"

import akquise  # noqa: E402
import ki  # noqa: E402
import mail  # noqa: E402
import youtube  # noqa: E402
import planer  # noqa: E402
import server  # noqa: E402
import store  # noqa: E402
import website  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

WEBSEITE = """<!doctype html><html><head><script>
const CONFIG = {
  marke: "Julius",                    // großer Name im Logo
  preisEinzel: 5,                     // Euro pro Thumbnail
  kleinunternehmer: true,
  impressum: {
    name: "Julius Roll",
    telefon: ""                       // optional
  },
};
</script></head><body><section id="preise"><h2>Faire Preise.</h2><p>Text &amp; mehr</p></section>
<script>
window.IMAGES = {
  "finance_after": "data:image/webp;base64,AAAA",
  "g_tech": "data:image/webp;base64,BBBB"
};
</script></body></html>"""


class FakeGitHub(BaseHTTPRequestHandler):
    """Gerade genug GitHub-API für den Website-Editor: Datei lesen, Blob/Baum/Commit anlegen, Branch verschieben."""
    datei = WEBSEITE
    commits = []

    def log_message(self, *a):
        pass

    def _antwort(self, daten, roh=False):
        body = daten.encode() if roh else json.dumps(daten).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        assert self.headers["Authorization"] == "Bearer ghp_test"
        if "/git/ref/heads/main" in self.path:
            return self._antwort({"object": {"sha": "c%d" % len(FakeGitHub.commits)}})
        if "/contents/index.html" in self.path:
            return self._antwort(FakeGitHub.datei, roh=True)
        if "/git/commits/" in self.path:
            return self._antwort({"tree": {"sha": "t0"}})
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/git/blobs"):
            FakeGitHub.neu = base64.b64decode(d["content"]).decode()
            return self._antwort({"sha": "b1"})
        if self.path.endswith("/git/trees"):
            assert d["tree"][0]["path"] == "index.html"
            return self._antwort({"sha": "t1"})
        if self.path.endswith("/git/commits"):
            FakeGitHub.commits.append(d["message"])
            return self._antwort({"sha": "c%d" % len(FakeGitHub.commits)})

    def do_PATCH(self):
        FakeGitHub.datei = FakeGitHub.neu
        self._antwort({})

ICH = "julius@example.com"


def test_png(w, h, farbe=(200, 160, 120)):
    """Kleines einfarbiges PNG ohne Zusatz-Bibliotheken."""
    import struct
    import zlib
    roh = b"".join(b"\x00" + bytes(farbe) * w for _ in range(h))

    def block(typ, daten):
        return struct.pack(">I", len(daten)) + typ + daten + struct.pack(">I", zlib.crc32(typ + daten) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + block(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + block(b"IDAT", zlib.compress(roh)) + block(b"IEND", b""))


def bestellung_mail():
    m = EmailMessage()
    m["From"] = "Max Mustermann <max@example.com>"
    m["To"] = ICH
    m["Subject"] = "Anfrage: Einzel-Thumbnail für Max Money"
    m["Message-ID"] = "<bestellung-1@example.com>"
    m["Date"] = email.utils.formatdate(localtime=True)
    m.set_content("Hallo Julius,\n\nich möchte gerne ein Einzel-Thumbnail (5 €) bestellen.\n\nName: Max Mustermann\n"
                  "Kanal: Max Money\nVideo / Thema: Die 3 größten ETF-Fehler, die dich Tausende Euro kosten\n"
                  "Wünsche: grün, seriös\n\nMeine Fotos hänge ich an.\n\nViele Grüße\nMax")
    m.add_attachment(test_png(400, 500), maintype="image", subtype="png", filename="ich.png")
    return m.as_bytes()


def antwort_mail():
    m = EmailMessage()
    m["From"] = "Max Mustermann <max@example.com>"
    m["To"] = ICH
    m["Subject"] = "Re: Anfrage: Einzel-Thumbnail für Max Money"
    m["Message-ID"] = "<antwort-1@example.com>"
    m["In-Reply-To"] = "<bestellung-1@example.com>"
    m["Date"] = email.utils.formatdate(localtime=True)
    m.set_content("Super! B gefällt mir, aber bitte den Text in Rot.\n\nAm 06.11.2026 schrieb Julius:\n> Hallo Max ...")
    return m.as_bytes()


class FakeImap:
    postfach = {}
    entwuerfe = []

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Entw&APw-rfe"']

    def select(self, ordner, readonly=False):
        return "OK", [str(len(self.postfach)).encode()]

    def uid(self, befehl, *args):
        if befehl == "search":
            return "OK", [b" ".join(k.encode() for k in self.postfach)]
        uid, teil = args
        roh = self.postfach[uid.decode() if isinstance(uid, bytes) else uid]
        if "HEADER.FIELDS" in teil:
            h = email.message_from_bytes(roh, policy=POLICY)
            kopf = "".join(f"{k}: {h[k]}\r\n" for k in ("Message-ID", "From", "Subject")).encode()
            return "OK", [(b"1 (BODY[HEADER] {%d}" % len(kopf), kopf), b")"]
        return "OK", [(b"1 (BODY[] {%d}" % len(roh), roh), b")"]

    def append(self, ordner, flags, zeit, daten):
        assert ordner == '"[Gmail]/Entw&APw-rfe"', ordner
        assert "Draft" in flags
        FakeImap.entwuerfe.append(daten)
        return "OK", [b""]

    def logout(self):
        pass


def get(pfad):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.PORT}{pfad}") as r:
        return r.read()


def post(pfad, daten):
    req = urllib.request.Request(f"http://127.0.0.1:{server.PORT}{pfad}", data=json.dumps(daten).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def warten(a_id, sekunden=90):
    """Manuell angelegte Aufträge werden im Hintergrund gebaut."""
    for _ in range(sekunden * 4):
        a = store.auftrag(store.lesen(), a_id)
        if a and a["status"] != "neu":
            return a
        time.sleep(0.25)
    raise AssertionError("Auftrag wurde nicht fertig gebaut")


def lead_antwort_mail():
    m = EmailMessage()
    m["From"] = "Finanz Fritz <fritz@example.com>"
    m["To"] = ICH
    m["Subject"] = "Re: Thumbnail-Idee"
    m["Message-ID"] = "<lead-antwort@example.com>"
    m["Date"] = email.utils.formatdate(localtime=True)
    m.set_content("Hey, sieht gut aus! Was kostet das Abo genau?")
    return m.as_bytes()


def main():
    mail.verbinden = lambda adresse, pw: FakeImap()
    threading.Thread(target=lambda: server.ThreadingHTTPServer(("127.0.0.1", server.PORT), server.Handler).serve_forever(),
                     daemon=True).start()
    time.sleep(0.3)

    # 1. Gmail einrichten und eine Bestellung ins Postfach legen
    post("/api/einstellungen", {"gmail": ICH, "app_passwort": "abcd efgh ijkl mnop", "dein_name": "Julius", "freisteller": False})
    post("/api/einstellungen", {"app_passwort": "••••"})  # Platzhalter überschreibt nichts
    for falsch in ("x••••", "abc"):
        try:
            post("/api/einstellungen", {"app_passwort": falsch})
            raise AssertionError("falsches App-Passwort angenommen: " + falsch)
        except urllib.error.HTTPError as ex:
            assert ex.code == 400 and "16 Buchstaben" in json.loads(ex.read())["fehler"]
    assert store.lesen()["einstellungen"]["app_passwort"] == "abcdefghijklmnop"
    FakeImap.postfach = {"1": bestellung_mail()}
    d = post("/api/mail/pruefen", {})
    assert d["ergebnis"] == "1 neue Mail(s)", d["ergebnis"]
    assert len(d["auftraege"]) == 1, d["auftraege"]
    a = d["auftraege"][0]
    print("Auftrag:", a["kanal"], "|", a["thema"], "|", a["status"], "| Fotos:", a["fotos"])
    assert a["kanal"] == "Max Money" and a["email"] == "max@example.com" and a["fotos"] == ["ich.png"]
    assert a["status"] == "freigabe", a["status"]
    for n in "abc":
        png = get(f"/dateien/{a['id']}/{n}.png")
        assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 50_000, n
    assert len(FakeImap.entwuerfe) == 0, "ohne Freigabe darf nichts nach Gmail"
    assert d["kennzahlen"]["freigabe"] == 1
    print("3 PNGs gebaut, warten auf Freigabe")

    # 2. Freigabe im Dashboard -> Entwurf in Gmail: Antwort im selben Verlauf, 3 Bilder dran, nichts gesendet
    v = post(f"/api/auftrag/{a['id']}/mailvorschlag", {})
    assert v["vorschlag_art"] == "erste", v["vorschlag_art"]
    d = post(f"/api/auftrag/{a['id']}/versand", {"modus": "entwurf", "varianten": [0, 1, 2], "art": "erste",
                                                 "text": v["vorlagen"]["erste"], "betreff": "Re: Anfrage: Einzel-Thumbnail für Max Money"})
    assert d["auftraege"][0]["status"] == "in_gmail" and d["auftraege"][0]["freigegeben"]
    assert len(FakeImap.entwuerfe) == 1
    e = email.message_from_bytes(FakeImap.entwuerfe[0], policy=POLICY)
    assert e["To"] == "max@example.com" and e["In-Reply-To"] == "<bestellung-1@example.com>", (e["To"], e["In-Reply-To"])
    assert e["Subject"] == "Re: Anfrage: Einzel-Thumbnail für Max Money"
    anh = [t.get_filename() for t in e.iter_attachments()]
    assert anh == ["thumbnail-max-money-a.png", "thumbnail-max-money-b.png", "thumbnail-max-money-c.png"], anh
    assert "Hallo Max," in e.get_body(("plain",)).get_content()
    print("Gmail-Entwurf ok:", anh)

    # 3. Dieselbe Mail nicht doppelt verarbeiten
    d = post("/api/mail/pruefen", {})
    assert len(d["auftraege"]) == 1 and len(FakeImap.entwuerfe) == 1

    # 4. Kunde antwortet -> Änderungswunsch am Auftrag, ohne Zitat
    FakeImap.postfach["2"] = antwort_mail()
    d = post("/api/mail/pruefen", {})
    a = d["auftraege"][0]
    assert a["status"] == "aenderung", a["status"]
    assert a["aenderungen"][-1]["text"] == "Super! B gefällt mir, aber bitte den Text in Rot.", a["aenderungen"]
    print("Änderungswunsch:", a["aenderungen"][-1]["text"])

    # 4b. Mit KI-Schlüssel setzt die KI den Wunsch selbst um (nur bei B), danach wieder Freigabe
    post("/api/einstellungen", {"ki_schluessel": "sk-test"})
    ki.aenderung = lambda schluessel, e, wunsch, fotos=(), thema="": planer.entwurf_pruefen(dict(e, farbe2="#ff2a2a"))

    def keine_ki(*a, **k):
        raise RuntimeError("keine KI im Test")
    ki.konzepte = keine_ki
    server.aenderung_umsetzen(a["id"], a["aenderungen"][-1]["text"])
    a = store.auftrag(store.lesen(), a["id"])
    assert a["status"] == "freigabe" and a["entwuerfe"][1]["entwurf"]["farbe2"] == "#ff2a2a", a["status"]
    assert a["entwuerfe"][0]["entwurf"]["farbe2"] != "#ff2a2a", "nur B ändern"
    assert post(f"/api/auftrag/{a['id']}/mailvorschlag", {})["vorschlag_art"] == "korrektur"
    print("KI-Änderung umgesetzt, wartet wieder auf Freigabe")

    # 5. Im Editor ändern -> PNG neu
    alt = a["entwuerfe"][1]["stand"]
    entwurf = dict(a["entwuerfe"][1]["entwurf"], farbe2="#ff2a2a", zeilen=["NEUER", "TEXT"])
    time.sleep(1.1)
    d = post(f"/api/auftrag/{a['id']}/entwurf/1", {"entwurf": entwurf})
    a = d["auftraege"][0]
    assert a["entwuerfe"][1]["entwurf"]["zeilen"] == ["NEUER", "TEXT"] and a["entwuerfe"][1]["stand"] >= alt

    # 6. Nur Variante B schicken, liefern, bezahlen -> Zahlen stimmen
    post(f"/api/auftrag/{a['id']}/gmail", {"varianten": [1]})
    e = email.message_from_bytes(FakeImap.entwuerfe[-1], policy=POLICY)
    assert [t.get_filename() for t in e.iter_attachments()] == ["thumbnail-max-money-b.png"]
    assert e["In-Reply-To"] == "<antwort-1@example.com>"
    post(f"/api/auftrag/{a['id']}/status", {"status": "geliefert"})
    d = post(f"/api/auftrag/{a['id']}/status", {"bezahlt": True})
    assert d["kennzahlen"]["einnahmen_gesamt"] == 5 and d["kennzahlen"]["offen"] == 0, d["kennzahlen"]

    # 7. Abo: Bestellung von Hand, Monat bezahlt
    r = post("/api/auftrag", {"name": "Lisa", "kanal": "FitMitLisa", "email": "lisa@example.com", "paket": "Monats-Abo",
                              "thema": "Tag 1 vs Tag 30 - 100 Liegestütze", "wuensche": ""})
    warten(r["id"])
    d = post("/api/abo-zahlung", {"email": "lisa@example.com"})
    k = next(k for k in d["kunden"] if k["email"] == "lisa@example.com")
    assert k["abo_status"] == "aktiv" and k["bezahlt_bis"], k
    assert d["kennzahlen"]["abos_aktiv"] == 1 and d["kennzahlen"]["einnahmen_gesamt"] == 40, d["kennzahlen"]
    lisa = next(x for x in d["auftraege"] if x["id"] == r["id"])
    assert lisa["entwuerfe"][2]["entwurf"]["vorlage"] == "vergleich", lisa["entwuerfe"][2]
    print("Kennzahlen:", d["kennzahlen"])

    # 8. Bankdaten eintragen (falsche IBAN wird abgelehnt), Lieferung mit Rechnung direkt senden
    try:
        post("/api/einstellungen", {"iban": "DE00 1234"})
        raise AssertionError("falsche IBAN angenommen")
    except urllib.error.HTTPError as ex:
        assert ex.code == 400
    post("/api/einstellungen", {"iban": "de89370400440532013000", "kontoinhaber": "Julius Roll", "absender_name": "Julius Roll",
                                "absender_strasse": "Musterweg 1", "absender_ort": "12345 Musterstadt"})
    gesendet = []
    mail.senden = lambda adresse, pw, msg: gesendet.append(msg)
    r = post("/api/auftrag", {"name": "Tom Test", "kanal": "TomTech", "email": "tom@example.com", "paket": "Einzel-Thumbnail",
                              "thema": "iPhone 17 vs Pixel 10", "wuensche": ""})
    warten(r["id"])
    v = post(f"/api/auftrag/{r['id']}/mailvorschlag", {})
    assert v["rechnung"] and v["iban"] and "{zahlung}" in v["vorlagen"]["fertig"], v
    d = post(f"/api/auftrag/{r['id']}/versand", {"modus": "senden", "varianten": [0], "betreff": "Dein Thumbnail", "rechnung": True,
                                                 "text": v["vorlagen"]["fertig"],
                                                 "extra": [{"name": "notiz.txt", "daten": "data:text/plain;base64," + base64.b64encode(b"hi").decode()}]})
    m = email.message_from_bytes(gesendet[-1].as_bytes(), policy=POLICY)
    namen = [t.get_filename() for t in m.iter_attachments()]
    jahr = time.strftime("%Y")
    assert namen == ["thumbnail-tomtech-a.png", f"Rechnung-RE-{jahr}-001.pdf", "notiz.txt"], namen
    text = m.get_body(("plain",)).get_content()
    assert "IBAN: DE89 3704 0044 0532 0130 00" in text and f"Verwendungszweck: RE-{jahr}-001" in text and "5,00 €" in text, text
    assert m.get_body(("html",)) is not None
    pdf = get(f"/rechnungen/RE-{jahr}-001.pdf")
    assert pdf[:4] == b"%PDF", pdf[:10]
    tom = next(x for x in d["auftraege"] if x["id"] == r["id"])
    assert tom["status"] == "geliefert" and d["kennzahlen"]["offen_betrag"] == 5, (tom["status"], d["kennzahlen"])
    print("Lieferung gesendet:", namen)

    # 9. Rechnung bezahlt -> Umsatz, Auftrag bezahlt
    rid = d["rechnungen"][0]["id"]
    d = post("/api/rechnung", {"id": rid, "bezahlt": True})
    assert d["kennzahlen"]["offen_betrag"] == 0 and d["kennzahlen"]["einnahmen_gesamt"] == 45, d["kennzahlen"]
    assert next(x for x in d["auftraege"] if x["id"] == r["id"])["bezahlt"]

    # 10. Abo-Rechnung senden, dann "Monat bezahlt" -> Rechnung bezahlt, Abo verlängert
    vorher = next(k for k in d["kunden"] if k["email"] == "lisa@example.com")["bezahlt_bis"]
    d = post("/api/rechnung", {"abo_email": "lisa@example.com", "modus": "senden"})
    abo_r = d["rechnungen"][0]
    assert abo_r["nr"] == f"RE-{jahr}-002" and abo_r["abo"] and abo_r["betrag"] == 35, abo_r
    assert gesendet[-1]["To"] == "lisa@example.com" and "Rechnung" in gesendet[-1]["Subject"]
    d = post("/api/abo-zahlung", {"email": "lisa@example.com"})
    lisa_k = next(k for k in d["kunden"] if k["email"] == "lisa@example.com")
    assert d["rechnungen"][0]["bezahlt"] and lisa_k["bezahlt_bis"] > vorher, (lisa_k, vorher)
    assert d["kennzahlen"]["einnahmen_gesamt"] == 80, d["kennzahlen"]
    d = post("/api/kunde", {"email": "lisa@example.com", "kuendigt_zum": "2000-01-01"})
    server.abos_aufraeumen()
    assert next(k for k in server.stand()["kunden"] if k["email"] == "lisa@example.com")["abo_status"] == "gekündigt"
    print("Rechnungen und Abo ok")

    # 10b. Finanzen: Ausgabe eintragen, Einnahme mit Datum, Gewinn und CSV
    d = post("/api/ausgabe", {"betrag": "9,99", "text": "Canva Pro", "kategorie": "Software & KI", "datum": time.strftime("%Y-%m-%d")})
    k = d["kennzahlen"]
    assert k["ausgaben_gesamt"] == 9.99 and k["gewinn_gesamt"] == round(80 - 9.99, 2), k
    assert k["monate"][-1]["ausgaben"] == 9.99 and len(k["monate"]) == 12
    d = post("/api/zahlung", {"betrag": "12", "text": "Extra-Wunsch", "kategorie": "Extra-Wunsch", "datum": "2020-01-15"})
    assert d["kennzahlen"]["einnahmen_gesamt"] == 92 and d["zahlungen"][-1]["zeit"].startswith("2020-01-15")
    csv_text = get("/api/finanzen.csv").decode("utf-8-sig")
    assert "Canva Pro" in csv_text and "-9,99" in csv_text and "Extra-Wunsch" in csv_text
    try:
        post("/api/ausgabe", {"betrag": "0"})
        raise AssertionError("Ausgabe 0 angenommen")
    except urllib.error.HTTPError as ex:
        assert ex.code == 400
    print("Finanzen ok: Gewinn", d["kennzahlen"]["gewinn_gesamt"])

    # 10c. Akquise: Liste importieren, Redesign bauen, Gmail-ENTWURF (ohne Re:), gesendet markieren, Antwort erkennen
    liste = "Priorität;Kanal;Link;Nische;Videotitel;Video-Link;E-Mail;Status\n" \
            "A;Finanz Fritz;https://www.youtube.com/@fritz;Finanzen;Ich habe 10.000 € in ETFs gesteckt;https://youtu.be/abcdefghijk;Fritz@Example.com;neu\n" \
            "B;Ohne Mail;https://www.youtube.com/@ohne;Fitness;;;;neu\n"
    req = urllib.request.Request(f"http://127.0.0.1:{server.PORT}/api/leads/import?name=liste.csv", data=liste.encode())
    d = json.loads(urllib.request.urlopen(req).read())
    assert d["ergebnis"] == "2 neue Creator, 0 ergänzt" and len(d["leads"]) == 2, d["ergebnis"]
    req = urllib.request.Request(f"http://127.0.0.1:{server.PORT}/api/leads/import?name=liste.csv", data=liste.encode())
    assert len(json.loads(urllib.request.urlopen(req).read())["leads"]) == 2, "doppelt importiert"
    fritz = next(l for l in d["leads"] if l["kanal"] == "Finanz Fritz")
    assert fritz["email"] == "fritz@example.com" and fritz["prioritaet"] == "A"
    youtube.material = lambda text="", video_link="", kanal_link="": {"video_id": "abcdefghijk", "titel": "x", "bild": test_png(1280, 720, (40, 60, 90))}
    ki.akquise_mail = keine_ki
    d = post(f"/api/lead/{fritz['id']}/redesign", {})
    fritz = next(l for l in d["leads"] if l["id"] == fritz["id"])
    assert fritz["status"] == "redesign" and fritz["redesign"]["original"], fritz
    assert get(f"/leads/{fritz['id']}/pitch.png")[:8] == b"\x89PNG\r\n\x1a\n"
    vorher, gesendet_vorher = len(FakeImap.entwuerfe), len(gesendet)
    d = post(f"/api/lead/{fritz['id']}/entwurf", {})
    fritz = next(l for l in d["leads"] if l["id"] == fritz["id"])
    assert fritz["status"] == "entwurf" and len(FakeImap.entwuerfe) == vorher + 1
    e = email.message_from_bytes(FakeImap.entwuerfe[-1], policy=POLICY)
    assert e["To"] == "fritz@example.com" and not e["Subject"].startswith("Re:"), e["Subject"]
    assert [t.get_filename() for t in e.iter_attachments()] == ["vorher-nachher-finanz-fritz.png", "thumbnail-idee-finanz-fritz.png"]
    text = e.get_body(("plain",)).get_content()
    assert "Ich habe 10.000 € in ETFs gesteckt" in text and "nein danke" in text and "{" not in text, text
    assert len(gesendet) == gesendet_vorher, "Akquise darf nie senden"
    d = post(f"/api/lead/{fritz['id']}/speichern", {"status": "gesendet"})
    fritz = next(l for l in d["leads"] if l["id"] == fritz["id"])
    assert fritz["kontaktiert"] and fritz["followup"] > fritz["kontaktiert"]
    FakeImap.postfach["9"] = lead_antwort_mail()
    d = post("/api/mail/pruefen", {})
    fritz = next(l for l in d["leads"] if l["id"] == fritz["id"])
    assert fritz["status"] == "antwort" and d["kennzahlen"]["leads_antwort"] == 1, fritz["status"]
    assert len(d["auftraege"]) == 3, "Lead-Antwort ist kein Auftrag"
    try:
        post(f"/api/lead/{next(l for l in d['leads'] if l['kanal'] == 'Ohne Mail')['id']}/entwurf", {})
        raise AssertionError("Entwurf ohne Mail angenommen")
    except urllib.error.HTTPError as ex:
        assert ex.code == 400
    print("Akquise ok: Entwurf mit Vorher/Nachher, Antwort erkannt")

    # 11. Website-Editor: Preis, Text und Bild ändern -> ein Commit, Preis in der App übernommen
    threading.Thread(target=lambda: ThreadingHTTPServer(("127.0.0.1", 18092), FakeGitHub).serve_forever(), daemon=True).start()
    time.sleep(0.2)
    post("/api/einstellungen", {"github_token": "ghp_test"})
    w = post("/api/website", {})
    assert [f["schluessel"] for f in w["config"]] == ["marke", "preisEinzel", "kleinunternehmer", "impressum.name", "impressum.telefon"], w["config"]
    t = next(t for t in w["texte"] if t["text"] == "Text & mehr")
    assert w["bilder"] == ["finance_after", "g_tech"]
    w = post("/api/website/speichern", {"config": {"preisEinzel": "7", "impressum.telefon": "0151 1"},
                                        "texte": {str(t["nr"]): {"alt": t["text"], "neu": "Neu <b>& gut</b>"}},
                                        "bilder": {"g_tech": "data:image/webp;base64,CCCC"}})
    neu = FakeGitHub.datei
    assert 'preisEinzel: 7,' in neu and 'telefon: "0151 1"' in neu and "<p>Neu &lt;b&gt;&amp; gut&lt;/b&gt;</p>" in neu, neu
    assert '"g_tech": "data:image/webp;base64,CCCC"' in neu and '"finance_after": "data:image/webp;base64,AAAA",' in neu
    assert len(FakeGitHub.commits) == 1 and w["stand"]["einstellungen"]["preis_einzel"] == 7
    assert get("/api/website/bild/g_tech") == base64.b64decode("CCCC")
    print("Website-Editor ok:", FakeGitHub.commits[0])

    # 12. Vorschau-HTML und Website
    html = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{server.PORT}/api/vorschau",
                                  data=json.dumps({"entwurf": entwurf, "auftrag": a["id"]}).encode())).read().decode()
    assert "NEUER" in html and "/assets/fonts/" in html
    assert b"Thumbnail-Zentrale" in get("/")
    print("ALLES OK, Daten in", store.DATA)


if __name__ == "__main__":
    main()
