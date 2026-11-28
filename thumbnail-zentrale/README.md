# Thumbnail-Zentrale

Deine Thumbnail-App für den Zima-Server, gebaut wie die Shorts-Zentrale.

- Schaut alle paar Minuten in dein Gmail. Jede Bestellung von deiner Website (Betreff „Anfrage: Einzel-Thumbnail …“ oder „Anfrage: Monats-Abo …“) wird zum Auftrag.
- Baut sofort **3 Thumbnail-Entwürfe** (PNG, 1280 × 720). Mit KI-Schlüssel liest die KI die Bestellung, schaut sich Foto oder Original-Thumbnail an und plant drei klar unterschiedliche Ideen. Ohne Schlüssel planen feste Regeln, kostenlos.
- **Echtes Material statt KI-Look:** Steht ein YouTube-Link in der Bestellung, holt die App das Original-Thumbnail. Personen auf Fotos werden automatisch freigestellt und kommen groß mit weißem Rand aufs Bild.
- **Freigabe:** Die fertigen Entwürfe warten in der Übersicht auf dein OK. Erst wenn du freigibst, geht die Mail raus (oder als Gmail-Entwurf).
- Antwortet der Kunde („B gefällt mir, Text bitte rot“), setzt die KI den Wunsch um und legt dir das Ergebnis wieder zur Freigabe vor.
- Im **Editor** änderst du Text, Farben, Schrift, Emoji, Foto, Pfeil und Vorlage mit Live-Vorschau. Optional mit KI: einfach hinschreiben, was anders sein soll.
- **Per Mail senden:** Fertiges Thumbnail mit HTML-Mail, eigenen Anhängen und Rechnung (PDF) an den Kunden, entweder sofort oder als Gmail-Entwurf.
- **Finanzen:** Einnahmen und Ausgaben selbst eintragen, Gewinn pro Monat und Jahr, Diagramm der letzten 12 Monate, Export als CSV für Excel. Rechnungen mit fortlaufender Nummer, IBAN und Verwendungszweck. Kunden zahlen per Überweisung, du klickst „Bezahlt“. Gesamtumsatz, Monatsumsatz, offene Beträge, Abos mit Verlängerung und Kündigung, monatliche Abo-Rechnung.
- **Akquise:** Lead-Liste (Excel/CSV) importieren. Für jeden Creator holt die App das neueste Video, baut ein besseres Thumbnail und ein Vorher/Nachher-Bild und schreibt eine kurze, persönliche Mail. Die Mail landet **nur als Gmail-Entwurf**, du sendest selbst. Mit Status, Nachfass-Erinnerung und Antwort-Erkennung.
- **Website:** Preise, Texte und Vorher-Nachher-Bilder der öffentlichen Seite ändern, ohne Code. Die App speichert die Änderung über GitHub, nach etwa einer Minute ist sie live.
- Dunkles Design, läuft auf Handy, Tablet und Computer.

Alles bleibt auf deinem Server unter `/DATA/AppData/thumbnail-zentrale`.

## Installation auf ZimaOS

1. ZimaOS öffnen > **App Store** > oben rechts **+** > **Benutzerdefinierte App installieren** > **Importieren**.
2. Den Inhalt von [`docker-compose.yml`](docker-compose.yml) einfügen und installieren.
3. Die App öffnen: `http://<IP-deines-Servers>:8091`

## Gmail verbinden (5 Minuten)

1. Google-Konto: Die **Bestätigung in zwei Schritten** muss an sein (myaccount.google.com > Sicherheit).
2. **App-Passwort** erstellen: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) > Name „Thumbnail-Zentrale“ > Erstellen. Google zeigt 16 Buchstaben.
3. In der App unter **Einstellungen** deine Gmail-Adresse und die 16 Buchstaben eintragen > **Verbindung testen** > **Speichern**.

Ab jetzt prüft die App das Postfach alle 5 Minuten (einstellbar). Über „Übersicht > Jetzt prüfen“ geht es sofort.

Das App-Passwort kannst du jederzeit auf derselben Google-Seite löschen. Dann kommt die App nicht mehr an dein Postfach.

## Bankdaten und Rechnungen

Unter **Einstellungen > Bankverbindung & Rechnung** Kontoinhaber, IBAN und deine Anschrift (wie im Impressum) eintragen. Die IBAN steht nur auf Rechnungen und in Mails an Kunden, nie auf der Website.

Beim Senden eines fertigen Thumbnails „Rechnung anhängen“ anhaken. In der Mail steht dann automatisch Betrag, Frist, IBAN und Verwendungszweck (die Rechnungsnummer). Sobald das Geld auf deinem Konto ist, unter **Finanzen** bei der Rechnung auf **Bezahlt** klicken.

## Website bearbeiten

Die App braucht dafür einen GitHub-Token, der nur dein Website-Repository ändern darf:

1. [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new) öffnen.
2. Name „Thumbnail-Zentrale“, Ablaufdatum nach Wunsch.
3. *Repository access* > **Only select repositories** > `juliusroll230-bit.github.io`.
4. *Permissions* > *Repository permissions* > **Contents** > **Read and write**.
5. **Generate token**, den Token kopieren und in der App unter **Einstellungen > Website-Editor** einfügen.

## Automatisch aktuell halten

Wenn du den Shorts-Updater schon installiert hast: In ZimaOS beim **shorts-updater** die Einstellungen öffnen und beim Befehl `shorts-zentrale` ein Leerzeichen und `thumbnail-zentrale` anhängen. Dann holt er jede Nacht um 4 Uhr auch für diese App die neueste Version.

## Optional

- **Passwort:** In der docker-compose-Datei die Zeile `PASSWORD:` aktivieren. Benutzername ist `admin`.
- **KI:** Unter Einstellungen einen Anthropic-API-Schlüssel eintragen (console.anthropic.com). Kostet ein paar Cent pro Bestellung. Ohne Schlüssel läuft alles mit festen Regeln.
- **Freistellen:** Beim ersten Mal lädt die App einmalig ein Modell herunter (ca. 170 MB). Das läuft lokal auf deinem Server und kostet nichts.

## Für Entwickler

| Datei | Zweck |
|---|---|
| `server.py` | Website, API, Gmail-Abruf im Hintergrund |
| `planer.py` | Liest die Bestell-Mail und plant 3 Entwürfe (Text, Farbwelt, Emojis) |
| `render.py` | Vorlagen als HTML, Chromium macht daraus PNGs |
| `mail.py` | Gmail: lesen und Entwürfe (IMAP), Senden nur auf Knopfdruck (SMTP), HTML-Mail |
| `rechnung.py` | Rechnungsnummern, Rechnung als PDF, Zahlungshinweis mit IBAN |
| `website.py` | Website-Editor: CONFIG, Texte und Bilder in index.html über die GitHub-API ändern |
| `ki.py` | Optional (Claude): plant 3 Konzepte aus Bestellung und Bild, setzt Änderungswünsche um, schreibt Akquise-Mails |
| `freisteller.py` | Stellt Personen frei (u2net_human_seg über onnxruntime, lokal) |
| `youtube.py` | Videotitel, Original-Thumbnail und neuestes Video eines Kanals, ohne API-Schlüssel |
| `akquise.py` | Leads importieren, Redesign + Vorher/Nachher bauen, Mail-Entwurf (nie senden), Nachfassen |
| `store.py` | Speichert alles in `/data/zentrale.json` |
| `web/index.html` | Die Oberfläche |
| `tests/test_ablauf.py` | Ganzer Ablauf mit nachgebautem Gmail und GitHub |

Lokal starten: `pip install playwright && playwright install chromium && python3 server.py` (Port 8080, Daten in `./data`).
