"""KI-Teil (optional, mit Anthropic-API-Schlüssel in den Einstellungen):

- konzepte():     liest die Bestellung (und schaut sich das Foto/Original-Thumbnail an) und plant 3 starke Thumbnail-Ideen
- aenderung():    setzt einen Änderungswunsch in eigenen Worten um ("Text größer, Hintergrund rot")
- akquise_mail(): schreibt eine kurze, persönliche Mail an einen Creator, dem du ein Redesign zeigen willst

Ohne Schlüssel läuft alles mit den festen Regeln aus planer.py weiter. Kosten: wenige Cent pro Bestellung.
"""
import base64
import io
import json
import os

import planer

MODELL = os.environ.get("KI_MODELL", "claude-opus-5-5")


def _emojis():
    ordner = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "emoji")
    return sorted(f[:-4] for f in os.listdir(ordner) if f.endswith(".png"))


def _client(schluessel):
    import anthropic
    return anthropic.Anthropic(api_key=schluessel, max_retries=2, timeout=120)


def _bild_block(pfad):
    """Bild verkleinert als JPEG für die KI (spart Kosten)."""
    from PIL import Image
    bild = Image.open(pfad).convert("RGB")
    bild.thumbnail((800, 800))
    puffer = io.BytesIO()
    bild.save(puffer, "JPEG", quality=80)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(puffer.getvalue()).decode()}}


def _json_anfrage(schluessel, inhalt, schema, max_tokens=8000, effort="medium"):
    """Eine Anfrage mit festem JSON-Format. Lehnt das Modell ab, springt ein anderes ein (fallbacks)."""
    antwort = _client(schluessel).beta.messages.create(
        model=MODELL,
        max_tokens=max_tokens,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": inhalt}],
    )
    if antwort.stop_reason == "refusal":
        raise ValueError("Die KI hat die Anfrage abgelehnt.")
    if antwort.stop_reason == "max_tokens":
        raise ValueError("Die KI-Antwort war zu lang.")
    text = next((b.text for b in antwort.content if b.type == "text"), "")
    return json.loads(text)


def _entwurf_schema():
    return {
        "type": "object",
        "properties": {
            "idee": {"type": "string"},
            "vorlage": {"type": "string", "enum": planer.VORLAGEN},
            "stil": {"type": "string", "enum": planer.STILE},
            "zeilen": {"type": "array", "items": {"type": "string"}},
            "farbe1": {"type": "string"},
            "farbe2": {"type": "string"},
            "schrift": {"type": "string", "enum": planer.SCHRIFTEN},
            "emoji": {"type": "array", "items": {"type": "string"}},
            "mit_bild": {"type": "boolean"},
            "pfeil": {"type": "boolean"},
            "banner": {"type": "string"},
        },
        "required": ["idee", "vorlage", "stil", "zeilen", "farbe1", "farbe2", "schrift", "emoji", "mit_bild", "pfeil", "banner"],
        "additionalProperties": False,
    }


FELDER = f"""So ist ein Thumbnail aufgebaut (1280 x 720):
- vorlage: person = Person groß freigestellt rechts, riesiger Text links (stärkster Look, wenn es ein Gesicht gibt);
  strahlen = Strahlen-Hintergrund, Bild rechts; split = dunkel links, farbig rechts, Bild rechts;
  spot = dunkel mit Lichtfleck, erste Zeile groß, Rest auf farbigem Band; vergleich = links grau (vorher), rechts farbig (nachher), zeilen[0] links, zeilen[1] rechts
- stil: Farbwelt {planer.STILE} (finanzen = grün, fitness = orange/pink, gaming = lila, tech = blau, allgemein = rot)
- zeilen: 1 bis 2 Zeilen, GROSSBUCHSTABEN, zusammen höchstens 4 Wörter und je höchstens 14 Zeichen. Nie den Videotitel abschreiben,
  sondern den Haken: eine Zahl, ein Ergebnis, ein Gefühl oder eine Frage, die neugierig macht.
- farbe1, farbe2: Textfarben #rrggbb für Zeile 1 und Zeile 2 (stark: #ffffff mit #fff200, #ffd400, #00f0ff oder #ff2a2a)
- schrift: {planer.SCHRIFTEN} (Anton ist der YouTube-Standard)
- emoji: 1 bis 2 Namen aus: {", ".join(_emojis())}
- mit_bild: true = das Foto bzw. die freigestellte Person des Creators kommt aufs Bild
- pfeil: true/false, banner: kurzer Zusatztext auf einem Band (höchstens 3 Wörter) oder ""
- idee: ein kurzer deutscher Satz, was das Thumbnail erzählt (für den Designer)"""


def konzepte(schluessel, bestellung, bild_pfad="", hat_person=False):
    """Drei unterschiedliche, starke Thumbnail-Konzepte als Entwurf-dicts (ohne Fotodateien, die setzt server.py)."""
    teile = []
    if bild_pfad:
        teile.append(_bild_block(bild_pfad))
    teile.append({"type": "text", "text": f"""Du bist ein Top-YouTube-Thumbnail-Designer für deutsche Creator. Plane drei klar unterschiedliche
Thumbnails für diese Bestellung. Ziel: im Handy-Feed in einer halben Sekunde verstanden werden und neugierig machen.
Regeln: eine einzige klare Idee pro Bild, wenig und sehr großer Text, starker Kontrast, ein Gesicht mit Emotion schlägt jedes Emoji.
Der Text ergänzt den Videotitel, er wiederholt ihn nicht.

Kanal: {bestellung.get('kanal', '')}
Videotitel/Thema: {bestellung.get('thema', '')}
Wünsche des Kunden: {bestellung.get('wuensche', '') or 'keine'}
{"Das Bild oben ist Material des Creators (Foto oder sein bisheriges Thumbnail). " if bild_pfad else "Es gibt kein Foto. "}
{"Darauf wurde eine Person gefunden und freigestellt, nutze sie in mindestens zwei Entwürfen (mit_bild = true, gern vorlage person)." if hat_person else "Es gibt keine freigestellte Person, setze mit_bild nur, wenn ein Foto da ist, sonst arbeite mit Emojis."}
Halte dich an Wünsche des Kunden (Farben, Text), wenn er welche nennt.

{FELDER}

Antworte mit genau drei Entwürfen in "entwuerfe"."""})
    schema = {"type": "object", "properties": {"entwuerfe": {"type": "array", "items": _entwurf_schema()}},
              "required": ["entwuerfe"], "additionalProperties": False}
    daten = _json_anfrage(schluessel, teile, schema)
    out = []
    for e in (daten.get("entwuerfe") or [])[:3]:
        e = dict(e)
        e["emoji"] = [x for x in e.get("emoji", []) if x in _emojis()] or ["fire"]
        out.append(e)
    if len(out) < 3:
        raise ValueError("Die KI hat zu wenige Entwürfe geliefert.")
    return out


def aenderung(schluessel, entwurf, wunsch, fotos=(), thema=""):
    """Änderungswunsch in eigenen Worten auf einen Entwurf anwenden."""
    schema = _entwurf_schema()
    schema = dict(schema, properties=dict(schema["properties"], foto={"type": "string"}),
                  required=schema["required"] + ["foto"])
    text = f"""Du bearbeitest ein YouTube-Thumbnail. Es ist als JSON beschrieben:
{json.dumps(entwurf, ensure_ascii=False)}

{FELDER}
- foto: Dateiname eines Fotos oder "" (verfügbar: {list(fotos) or "keine"}; Dateien auf -frei.png sind freigestellte Personen)
Videothema: {thema}

Änderungswunsch: {wunsch}

Gib das vollständige, geänderte Thumbnail zurück. Ändere nur, was der Wunsch verlangt."""
    neu = _json_anfrage(schluessel, text, schema, max_tokens=4000, effort="low")
    neu.pop("mit_bild", None)
    neu["hintergrund"] = entwurf.get("hintergrund", "")
    neu = planer.entwurf_pruefen(dict(entwurf, **neu))
    if neu["foto"] and neu["foto"] not in fotos:
        neu["foto"] = ""
    return neu


def akquise_mail(schluessel, lead, dein_name, preis_einzel, preis_abo, website):
    """Kurze, persönliche Erstkontakt-Mail an einen Creator (nur als Entwurf, Julius sendet selbst)."""
    schema = {"type": "object", "properties": {"betreff": {"type": "string"}, "text": {"type": "string"}},
              "required": ["betreff", "text"], "additionalProperties": False}
    text = f"""Schreib eine kurze Erstkontakt-Mail auf Deutsch an einen YouTube-Creator. Absender: {dein_name}, macht Thumbnails.
Ton: locker, per Du, ehrlich, kein Marketing-Sprech, keine Übertreibungen, keine Emojis. Höchstens 90 Wörter.
Inhalt: ein konkreter Satz zu seinem Video (zeigt, dass du es gesehen hast), dann: du hast als Idee ein neues Thumbnail
für genau dieses Video gebaut, es hängt an (vorher/nachher). Kostenlos und unverbindlich, er darf es nutzen.
Danach kurz das Angebot: Einzel-Thumbnail {preis_einzel} €, Monats-Abo {preis_abo} € unbegrenzt, Infos auf {website}.
Zum Schluss: Wenn kein Interesse, reicht ein kurzes "nein danke", dann meldest du dich nicht mehr.
Grußformel mit {dein_name}. Keine Platzhalter in eckigen Klammern.

Kanal: {lead.get('kanal', '')}
Videotitel: {lead.get('videotitel', '')}
Nische: {lead.get('nische', '')}
Ansprechperson (falls bekannt): {lead.get('ansprechpartner', '') or 'unbekannt, dann einfach "Hi" oder "Hey Kanalname-Team"'}"""
    return _json_anfrage(schluessel, text, schema, max_tokens=3000, effort="low")
