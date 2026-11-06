"""Optional: Änderungswünsche in eigenen Worten umsetzen ("Text größer, Hintergrund rot") mit Claude.

Braucht einen Anthropic-API-Schlüssel in den Einstellungen. Ohne Schlüssel bleibt der Knopf aus.
Jede Änderung kostet Bruchteile eines Cents.
"""
import json
import os
import re
import urllib.request

import planer

MODELL = os.environ.get("KI_MODELL", "claude-sonnet-5-5")


def _emojis():
    ordner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "emoji")
    return sorted(f[:-4] for f in os.listdir(ordner) if f.endswith(".png"))


def aenderung(schluessel, entwurf, wunsch, fotos=(), thema=""):
    anweisung = f"""Du bearbeitest ein YouTube-Thumbnail. Es ist als JSON beschrieben:
{json.dumps(entwurf, ensure_ascii=False)}

Felder:
- vorlage: {planer.VORLAGEN} (strahlen = Strahlen-Hintergrund, split = dunkel links/farbig rechts, spot = dunkel mit Lichtfleck und Textband, vergleich = links grau/rechts farbig mit Pfeil, zeilen[0] links, zeilen[1] rechts)
- stil: Farbwelt {planer.STILE} (finanzen = grün, fitness = orange/pink, gaming = lila, tech = blau, allgemein = rot)
- zeilen: 1 bis 3 kurze Textzeilen in GROSSBUCHSTABEN (je höchstens 20 Zeichen)
- farbe1, farbe2: Textfarben als #rrggbb (Zeile 1, ab Zeile 2)
- schrift: {planer.SCHRIFTEN}
- emoji: 1 bis 2 Namen aus dieser Liste: {", ".join(_emojis())}
- foto: Dateiname eines Kundenfotos oder "" (verfügbar: {list(fotos) or "keine"})
- pfeil: true/false
- banner: kurzer Zusatztext auf einem Band oder ""
- gross: Textgröße in Prozent, 60 bis 140
Videothema: {thema}

Änderungswunsch: {wunsch}

Antworte nur mit dem vollständigen, geänderten JSON. Ändere nur, was der Wunsch verlangt."""
    body = json.dumps({"model": MODELL, "max_tokens": 800,
                       "messages": [{"role": "user", "content": anweisung}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": schluessel, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        antwort = json.load(r)
    text = "".join(b.get("text", "") for b in antwort.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("Die KI hat kein gültiges Ergebnis geliefert.")
    neu = planer.entwurf_pruefen(json.loads(m.group(0)))
    if neu["foto"] and neu["foto"] not in fotos:
        neu["foto"] = ""
    return neu
