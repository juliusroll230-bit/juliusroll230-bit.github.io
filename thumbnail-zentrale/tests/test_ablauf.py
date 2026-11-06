"""Kompletter Ablauf mit einem nachgebauten Gmail: Bestellung rein -> 3 PNGs -> Entwurf mit Anhängen -> Kunden-Antwort.

  python3 tests/test_ablauf.py
"""
import email
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from email.message import EmailMessage
from email.policy import default as POLICY

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="tz-test-")
os.environ.setdefault("PORT", "18091")

import mail  # noqa: E402
import planer  # noqa: E402
import server  # noqa: E402
import store  # noqa: E402

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


def main():
    mail.verbinden = lambda adresse, pw: FakeImap()
    threading.Thread(target=lambda: server.ThreadingHTTPServer(("127.0.0.1", server.PORT), server.Handler).serve_forever(),
                     daemon=True).start()
    time.sleep(0.3)

    # 1. Gmail einrichten und eine Bestellung ins Postfach legen
    post("/api/einstellungen", {"gmail": ICH, "app_passwort": "abcd efgh ijkl mnop", "dein_name": "Julius"})
    FakeImap.postfach = {"1": bestellung_mail()}
    d = post("/api/mail/pruefen", {})
    assert d["ergebnis"] == "1 neue Mail(s)", d["ergebnis"]
    assert len(d["auftraege"]) == 1, d["auftraege"]
    a = d["auftraege"][0]
    print("Auftrag:", a["kanal"], "|", a["thema"], "|", a["status"], "| Fotos:", a["fotos"])
    assert a["kanal"] == "Max Money" and a["email"] == "max@example.com" and a["fotos"] == ["ich.png"]
    assert a["status"] == "in_gmail", a["status"]
    for n in "abc":
        png = get(f"/dateien/{a['id']}/{n}.png")
        assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 50_000, n
    print("3 PNGs gebaut")

    # 2. Entwurf in Gmail: Antwort im selben Verlauf, 3 Bilder dran, nichts gesendet
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

    # 5. Im Editor ändern -> PNG neu
    alt = a["entwuerfe"][1]["stand"]
    entwurf = dict(a["entwuerfe"][1]["entwurf"], farbe2="#ff2a2a", zeilen=["NEUER", "TEXT"])
    time.sleep(1.1)
    d = post(f"/api/auftrag/{a['id']}/entwurf/1", {"entwurf": entwurf})
    a = d["auftraege"][0]
    assert a["entwuerfe"][1]["entwurf"]["zeilen"] == ["NEUER", "TEXT"] and a["entwuerfe"][1]["stand"] > alt

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
    d = post("/api/abo-zahlung", {"email": "lisa@example.com"})
    k = next(k for k in d["kunden"] if k["email"] == "lisa@example.com")
    assert k["abo_status"] == "aktiv" and k["bezahlt_bis"], k
    assert d["kennzahlen"]["abos_aktiv"] == 1 and d["kennzahlen"]["einnahmen_gesamt"] == 40, d["kennzahlen"]
    lisa = next(x for x in d["auftraege"] if x["id"] == r["id"])
    assert lisa["entwuerfe"][2]["entwurf"]["vorlage"] == "vergleich", lisa["entwuerfe"][2]
    print("Kennzahlen:", d["kennzahlen"])

    # 8. Vorschau-HTML und Website
    html = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{server.PORT}/api/vorschau",
                                  data=json.dumps({"entwurf": entwurf, "auftrag": a["id"]}).encode())).read().decode()
    assert "NEUER" in html and "/assets/fonts/" in html
    assert b"Thumbnail-Zentrale" in get("/")
    print("ALLES OK, Daten in", store.DATA)


if __name__ == "__main__":
    main()
