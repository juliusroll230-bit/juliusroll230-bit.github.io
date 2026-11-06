# Thumbnail-Zentrale

Deine Thumbnail-App für den Zima-Server, gebaut wie die Shorts-Zentrale.

- Schaut alle paar Minuten in dein Gmail. Jede Bestellung von deiner Website (Betreff „Anfrage: Einzel-Thumbnail …“ oder „Anfrage: Monats-Abo …“) wird zum Auftrag.
- Baut sofort **3 Thumbnail-Entwürfe** (PNG, 1280 × 720) aus Videothema und Wünschen. Hängt der Kunde ein Foto an, kommt es mit aufs Bild.
- Legt einen **Antwort-Entwurf in Gmail** an, die Bilder hängen schon dran. Gesendet wird nichts, du klickst in Gmail selbst auf Senden.
- Antwortet der Kunde („B gefällt mir, Text bitte rot“), steht das als Änderungswunsch beim Auftrag.
- Im **Editor** änderst du Text, Farben, Schrift, Emoji, Foto, Pfeil und Vorlage mit Live-Vorschau. Optional mit KI: einfach hinschreiben, was anders sein soll.
- **Übersicht** mit Gesamteinnahmen, Monatsumsatz, aktiven Abos und offenen Aufträgen. Unter „Abos & Geld“ verbuchst du Zahlungen.

Alles bleibt auf deinem Server unter `/DATA/AppData/thumbnail-zentrale`.

## Installation auf ZimaOS

1. **Einmalig das Paket freigeben:** Auf GitHub oben rechts auf dein Profilbild > *Your packages* > **thumbnail-zentrale** > *Package settings* > ganz unten *Change visibility* > **Public**. Sonst kann der Server das Programm nicht herunterladen. (Das Paket enthält nur das Programm, keine Daten.)
2. ZimaOS öffnen > **App Store** > oben rechts **+** > **Benutzerdefinierte App installieren** > **Importieren**.
3. Den Inhalt von [`docker-compose.yml`](docker-compose.yml) einfügen und installieren.
4. Die App öffnen: `http://<IP-deines-Servers>:8091`

## Gmail verbinden (5 Minuten)

1. Google-Konto: Die **Bestätigung in zwei Schritten** muss an sein (myaccount.google.com > Sicherheit).
2. **App-Passwort** erstellen: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) > Name „Thumbnail-Zentrale“ > Erstellen. Google zeigt 16 Buchstaben.
3. In der App unter **Einstellungen** deine Gmail-Adresse und die 16 Buchstaben eintragen > **Verbindung testen** > **Speichern**.

Ab jetzt prüft die App das Postfach alle 5 Minuten (einstellbar). Über „Übersicht > Jetzt prüfen“ geht es sofort.

Das App-Passwort kannst du jederzeit auf derselben Google-Seite löschen. Dann kommt die App nicht mehr an dein Postfach.

## Automatisch aktuell halten

Wenn du den Shorts-Updater schon installiert hast: In ZimaOS beim **shorts-updater** die Einstellungen öffnen und beim Befehl `shorts-zentrale` ein Leerzeichen und `thumbnail-zentrale` anhängen. Dann holt er jede Nacht um 4 Uhr auch für diese App die neueste Version.

## Optional

- **Passwort:** In der docker-compose-Datei die Zeile `PASSWORD:` aktivieren. Benutzername ist `admin`.
- **Änderungen in eigenen Worten (KI):** Unter Einstellungen einen Anthropic-API-Schlüssel eintragen (console.anthropic.com). Eine Änderung kostet weniger als einen Cent.

## Für Entwickler

| Datei | Zweck |
|---|---|
| `server.py` | Website, API, Gmail-Abruf im Hintergrund |
| `planer.py` | Liest die Bestell-Mail und plant 3 Entwürfe (Text, Farbwelt, Emojis) |
| `render.py` | Vorlagen als HTML, Chromium macht daraus PNGs |
| `mail.py` | Gmail per IMAP: lesen, Entwürfe anlegen (nie senden) |
| `ki.py` | Optional: Änderungswunsch in Worten -> geänderter Entwurf |
| `store.py` | Speichert alles in `/data/zentrale.json` |
| `web/index.html` | Die Oberfläche |
| `tests/test_ablauf.py` | Ganzer Ablauf mit nachgebautem Gmail |

Lokal starten: `pip install playwright && playwright install chromium && python3 server.py` (Port 8080, Daten in `./data`).
