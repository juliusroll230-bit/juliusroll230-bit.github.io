"""Liest eine Bestell-Mail aus und plant daraus drei Thumbnail-Entwürfe.

Reine Logik ohne Netz und ohne Browser, damit sie sich leicht testen lässt.
Ein Entwurf ist ein kleines dict, das render.py in ein Bild verwandelt.
"""
import re

VORLAGEN = ["strahlen", "split", "spot", "vergleich"]
STILE = ["finanzen", "fitness", "gaming", "tech", "allgemein"]
SCHRIFTEN = ["Anton", "Bebas", "Mont", "Lucky", "Archivo"]

NISCHEN = [
    ("finanzen", r"geld|euro|€|\$|etf|aktie|börse|boerse|dividend|invest|sparen|spar|zins|krypto|bitcoin|rente|finanz|"
                 r"vermögen|vermoegen|reich|million|gehalt|einkommen|steuer|kredit|schulden|depot|immobilie|miete|budget|"
                 r"passiv|business|nebenjob|verdien"),
    ("fitness", r"fitness|gym|training|muskel|abnehm|kilo|\bkg\b|diät|diaet|ernährung|ernaehrung|protein|workout|sixpack|"
                r"bauch|liegestütz|liegestuetz|joggen|laufen|marathon|kalorien|fett|bizeps|squat|kraft|\babs\b|rezept|gesund"),
    ("gaming", r"gaming|game|spiel|minecraft|fortnite|zocken|level|boss|twitch|playstation|ps5|xbox|nintendo|gta|"
               r"valorant|roblox|lets ?play|speedrun|ranked|noob"),
    ("tech", r"tech|handy|iphone|smartphone|samsung|laptop|\bpc\b|computer|apple|android|\bapp\b|\bki\b|\bai\b|chatgpt|"
             r"software|gadget|kamera|unboxing|setup|tesla"),
]
FARBWUNSCH = [
    (r"\brot|red\b", "allgemein"), (r"grün|gruen|green", "finanzen"), (r"blau|blue", "tech"),
    (r"lila|violett|pink|purple|neon", "gaming"), (r"orange", "fitness"),
]
AKZENT = {"finanzen": "#ffd400", "fitness": "#fff200", "gaming": "#00f0ff", "tech": "#fff200", "allgemein": "#fff200"}

EMOJI_REGELN = [
    (r"etf|aktie|börse|boerse|depot|chart|kurs|rendite", "chart_increasing"),
    (r"crash|verlust|minus|absturz|pleite", "chart_decreasing"),
    (r"fehler|falsch|\bnie\b|stop|warnung|vorsicht|achtung|gefahr", "warning"),
    (r"dividend|cashflow|passiv|gehalt|einkommen|verdien", "money_with_wings"),
    (r"spar|budget|euro|€", "euro_banknote"),
    (r"million|reich|vermögen|vermoegen|geld", "money_bag"),
    (r"bitcoin|krypto|coin", "coin"),
    (r"immobilie|\bhaus\b|wohnung|miete", "house"),
    (r"\bbank|kredit|schulden", "bank"),
    (r"steuer|rechnung", "receipt"),
    (r"rente|\bzeit\b|jahre|\btage\b|stunden|24h", "hourglass_done"),
    (r"abnehm|\bfett|kalorien|diät|diaet", "fire"),
    (r"muskel|bizeps|kraft|stark|workout|training|gym", "flexed_biceps"),
    (r"protein|essen|ernährung|ernaehrung|rezept", "egg"),
    (r"laufen|joggen|marathon|cardio", "woman_running"),
    (r"minecraft|fortnite|gaming|game|zocken|spiel|playstation|xbox|nintendo", "video_game"),
    (r"handy|iphone|smartphone|samsung|android", "mobile_phone"),
    (r"laptop|\bpc\b|computer|setup", "laptop"),
    (r"\bki\b|\bai\b|chatgpt|roboter|robot", "robot"),
    (r"business|firma|startup|gründ|gruend|selbstständig|selbststaendig", "rocket"),
    (r"tipps|trick|idee|geheim|hack", "light_bulb"),
    (r"gewinn|sieg|challenge|bester|\btop\b|platz", "trophy"),
    (r"schock|krass|unglaublich|wahnsinn|\bwow\b", "exploding_head"),
]
STANDARD_EMOJIS = {
    "finanzen": ["money_bag", "chart_increasing"], "fitness": ["flexed_biceps", "fire"],
    "gaming": ["video_game", "trophy"], "tech": ["mobile_phone", "exploding_head"],
    "allgemein": ["exploding_head", "fire"],
}
STOPPWOERTER = set((
    "der die das den dem des ein eine einen einem einer und oder aber ich du er sie es wir ihr mein meine dein deine "
    "mit für fuer in im ins am an auf aus bei vom von zu zum zur so wie was warum wieso weshalb wann wer ist sind war "
    "hat habe haben wird werden man nicht auch noch nur sich mal schon ganz sehr dann als bis über ueber nach vor unter "
    "um durch ohne gegen video folge teil dich dir mich mir uns euch sein seine kann kannst muss musst soll sollte "
    "diese dieser dieses jeden jede jeder alle einfach wirklich"
).split())


# ---------------- Mail auslesen ----------------
def _feld(body, *namen):
    for name in namen:
        m = re.search(r"^\s*" + name + r"\s*:\s*(.*)$", body, re.I | re.M)
        if m:
            v = m.group(1).strip()
            if v and not re.fullmatch(r"\[.*\]", v):  # Platzhalter wie "[Dein Name]" ignorieren
                return v
    return ""


def bestellung_lesen(betreff, body, absender_name="", absender_mail=""):
    """Holt Name, Kanal, Thema und Wünsche aus der Mail, die das Bestellformular der Website erzeugt."""
    betreff = betreff or ""
    body = body or ""
    ohne_re = re.sub(r"^\s*((re|aw|fwd?|wg)\s*:\s*)+", "", betreff, flags=re.I)
    kanal = _feld(body, "Kanal")
    if not kanal:
        m = re.search(r"\sfür\s+(.+)$", ohne_re, re.I)
        kanal = m.group(1).strip() if m else ""
    thema = _feld(body, r"Video\s*/\s*Thema", "Thema", "Videotitel", "Video")
    if not thema:
        thema = re.sub(r"^Anfrage:\s*(Einzel-Thumbnail|Monats-Abo)(\s+für\s+.*)?$", "", ohne_re, flags=re.I).strip()
    return {
        "name": _feld(body, "Name") or absender_name,
        "kanal": kanal,
        "thema": thema,
        "wuensche": _feld(body, "Wünsche", "Wuensche"),
        "paket": "Monats-Abo" if re.search(r"monats-abo", betreff + " " + body, re.I) else "Einzel-Thumbnail",
        "email": (absender_mail or "").lower(),
    }


def ist_bestellung(betreff):
    return bool(re.search(r"Anfrage:\s*(Einzel-Thumbnail|Monats-Abo)", betreff or "", re.I))


# ---------------- Text fürs Bild ----------------
def wunsch_text(wuensche):
    """Text, den der Kunde ausdrücklich will: Text: ... oder etwas in Anführungszeichen."""
    w = wuensche or ""
    m = re.search(r"text\s*(?:aufs?\s*(?:bild|thumbnail))?\s*[:=]\s*[\"„“']?([^\"“”'\n]{2,40})", w, re.I) \
        or re.search(r"[\"„“]([^\"“”]{2,40})[\"“”]", w)
    return m.group(1).strip().rstrip(".,;") if m else ""


def text_zeilen(roh):
    """Macht aus einem Titel 1-2 kurze, große Zeilen (höchstens 4 Wörter)."""
    t = re.sub(r"[\U0001F000-\U0001FFFF☀-➿️]", "", str(roh or ""))
    t = re.sub(r"[|#*_~^<>{}\[\]]", " ", t)
    t = re.sub(r"\s*[-–:]\s+", " ", t)
    t = re.sub(r"\s+", " ", t).strip() or "Neues Video"
    woerter = t.split(" ")
    if not (len(t) <= 22 and len(woerter) <= 4):
        stark = [w for w in woerter if re.sub(r"[.,!?]", "", w.lower()) not in STOPPWOERTER]
        quelle = stark if len(stark) >= 2 else woerter
        woerter = []
        for w in quelle:  # höchstens 4 Wörter und ca. 22 Zeichen, damit die Schrift groß bleibt
            if len(woerter) >= 4 or (woerter and len(" ".join(woerter + [w])) > 22):
                break
            woerter.append(w)
    gross = [re.sub(r"[.,;]+$", "", w).upper() for w in woerter if w]
    if len(gross) <= 1:
        return gross or ["NEUES VIDEO"]
    best, diff = 1, 10 ** 9
    for i in range(1, len(gross)):
        a, c = len(" ".join(gross[:i])), len(" ".join(gross[i:]))
        if abs(a - c) < diff:
            best, diff = i, abs(a - c)
    return [" ".join(gross[:best]), " ".join(gross[best:])]


def vergleich_seiten(thema):
    """'Tag 1 vs Tag 30 - ...' -> ['TAG 1', 'TAG 30'] (je höchstens 2 Wörter)."""
    m = re.match(r"\s*(.+?)\s+(?:vs\.?|versus|gegen|statt)\s+(.+)$", thema or "", re.I)
    if not m:
        return []
    links = m.group(1).split()[-2:]
    rechts = re.split(r"\s*[-–:,|(?!]\s*", m.group(2))[0].split()[:2]
    if not links or not rechts:
        return []
    return [" ".join(links).upper(), " ".join(rechts).upper()]


# ---------------- Entwürfe planen ----------------
def nische_von(text):
    for name, muster in NISCHEN:
        if re.search(muster, text, re.I):
            return name
    return "allgemein"


def emojis_von(text, nische):
    out = []
    for muster, e in EMOJI_REGELN:
        if re.search(muster, text, re.I) and e not in out:
            out.append(e)
    for e in STANDARD_EMOJIS[nische]:
        if e not in out:
            out.append(e)
    return out


def entwuerfe_planen(b, foto=""):
    """Drei unterschiedliche Entwürfe (A, B, C) für eine Bestellung."""
    alles = f"{b.get('thema', '')} {b.get('wuensche', '')}"
    nische = nische_von(alles)
    stil = nische
    for muster, s in FARBWUNSCH:
        if re.search(muster, b.get("wuensche", ""), re.I):
            stil = s
            break
    emojis = emojis_von(alles, nische)
    seiten = vergleich_seiten(b.get("thema", ""))
    wunsch = wunsch_text(b.get("wuensche"))
    if seiten and not wunsch:
        zeilen = [seiten[0] + " VS", seiten[1]]
    else:
        zeilen = text_zeilen(wunsch or b.get("thema") or b.get("kanal") or "Neues Video")
    akzent = AKZENT[stil]
    basis = {"stil": stil, "zeilen": zeilen, "farbe1": "#ffffff", "farbe2": akzent, "schrift": "Anton",
             "foto": foto, "pfeil": False, "banner": ""}
    vergleich = bool(seiten) or (re.search(r"vorher|nachher", alles, re.I) and len(zeilen) == 2)
    a = dict(basis, vorlage="strahlen", emoji=[emojis[0], emojis[1]], pfeil=False)
    b2 = dict(basis, vorlage="split", emoji=[emojis[1], emojis[0]], pfeil=True, foto="")
    c = dict(basis, vorlage="vergleich" if vergleich else "spot", emoji=[emojis[0], emojis[1]])
    if seiten:
        c["zeilen"] = seiten
    if foto:  # mit Kundenfoto: A und C zeigen das Foto, B bleibt mit Emojis
        a["foto"] = foto
        c["foto"] = foto if not vergleich else ""
    return [entwurf_pruefen(x) for x in (a, b2, c)]


def entwurf_pruefen(e):
    """Bringt ein (z. B. im Editor oder per KI geändertes) Entwurf-dict in eine gültige Form."""
    hexfarbe = re.compile(r"^#[0-9a-fA-F]{6}$")
    zeilen = [str(z)[:40] for z in (e.get("zeilen") or []) if str(z).strip()][:3] or ["NEUES VIDEO"]
    emoji = [str(x) for x in (e.get("emoji") or []) if re.fullmatch(r"[a-z0-9_\-]+", str(x))][:2]
    return {
        "vorlage": e.get("vorlage") if e.get("vorlage") in VORLAGEN else "strahlen",
        "stil": e.get("stil") if e.get("stil") in STILE else "allgemein",
        "zeilen": zeilen,
        "farbe1": e.get("farbe1") if hexfarbe.match(str(e.get("farbe1", ""))) else "#ffffff",
        "farbe2": e.get("farbe2") if hexfarbe.match(str(e.get("farbe2", ""))) else "#fff200",
        "schrift": e.get("schrift") if e.get("schrift") in SCHRIFTEN else "Anton",
        "emoji": emoji or ["fire"],
        "foto": re.sub(r"[^\w.\-]", "", str(e.get("foto") or "")),
        "pfeil": bool(e.get("pfeil")),
        "banner": str(e.get("banner") or "")[:40],
        "gross": max(60, min(140, int(e.get("gross") or 100))),
    }
