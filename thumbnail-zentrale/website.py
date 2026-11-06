"""Website-Editor: liest index.html der öffentlichen Seite von GitHub und schreibt Änderungen als Commit zurück.

Bearbeitet werden nur drei Dinge, ohne den Rest der Datei anzufassen:
  - Werte im CONFIG-Block oben (Preise, Lieferzeit, Kontakt, Links ...)
  - einfache Texte (Überschriften, Absätze, Listenpunkte ohne weitere Formatierung)
  - Bilder in window.IMAGES (Vorher/Nachher, Galerie)
"""
import base64
import html
import json
import os
import re
import urllib.error
import urllib.request

GITHUB_API = os.environ.get("GITHUB_API", "https://api.github.com")

CONFIG_RE = re.compile(r"const CONFIG = \{\n(.*?)\n\};", re.S)
ZEILE_RE = re.compile(r'^(\s*)([A-Za-z_]\w*):\s*(".*?(?<!\\)"|-?\d+(?:\.\d+)?|true|false)(\s*,?)(\s*//\s*(.*))?$')
BLOCK_AUF_RE = re.compile(r"^\s*([A-Za-z_]\w*):\s*\{\s*(//\s*(.*))?$")
TEXT_RE = re.compile(r"<(h1|h2|h3|p|li|figcaption|summary)((?:\s[^<>]*)?)>([^<>]{2,600})</\1>")
IMAGES_RE = re.compile(r'^(\s*)"([\w\-]+)":\s*"(data:image/[^"]+|[^"]+)"(,?)\s*$', re.M)


class WebsiteFehler(Exception):
    pass


# ======================= GitHub =======================
def _gh(token, pfad, daten=None, methode=None, roh=False):
    h = {"Authorization": f"Bearer {token.strip()}", "Accept": "application/vnd.github.raw" if roh else "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "thumbnail-zentrale"}
    body = None
    if daten is not None:
        body = json.dumps(daten).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{GITHUB_API}{pfad}", data=body, headers=h, method=methode)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            inhalt = r.read()
            return inhalt.decode("utf-8") if roh else json.loads(inhalt or b"{}")
    except urllib.error.HTTPError as e:
        try:
            text = json.loads(e.read() or b"{}").get("message", "")
        except Exception:
            text = ""
        if e.code == 401:
            raise WebsiteFehler("GitHub lehnt den Token ab. Bitte in den Einstellungen neu eintragen.")
        if e.code in (403, 404):
            raise WebsiteFehler(f"Kein Zugriff auf das Repository ({e.code}). Hat der Token Lese- und Schreibrechte für „Contents“?")
        raise WebsiteFehler(f"GitHub {e.code}: {text}")
    except urllib.error.URLError as e:
        raise WebsiteFehler(f"GitHub nicht erreichbar ({e.reason})")


def laden(token, repo, branch, datei):
    """Gibt (inhalt, commit_sha) des aktuellen Stands zurück."""
    ref = _gh(token, f"/repos/{repo}/git/ref/heads/{branch}")
    sha = ref["object"]["sha"]
    inhalt = _gh(token, f"/repos/{repo}/contents/{datei}?ref={sha}", roh=True)
    return inhalt, sha


def speichern(token, repo, branch, datei, inhalt, basis_sha, nachricht):
    """Commit mit der neuen Datei auf den Branch. Schlägt fehl, wenn sich der Branch inzwischen bewegt hat."""
    commit = _gh(token, f"/repos/{repo}/git/commits/{basis_sha}")
    blob = _gh(token, f"/repos/{repo}/git/blobs", {"content": base64.b64encode(inhalt.encode()).decode(), "encoding": "base64"})
    baum = _gh(token, f"/repos/{repo}/git/trees", {"base_tree": commit["tree"]["sha"],
                                                    "tree": [{"path": datei, "mode": "100644", "type": "blob", "sha": blob["sha"]}]})
    neu = _gh(token, f"/repos/{repo}/git/commits", {"message": nachricht, "tree": baum["sha"], "parents": [basis_sha]})
    _gh(token, f"/repos/{repo}/git/refs/heads/{branch}", {"sha": neu["sha"], "force": False}, methode="PATCH")
    return neu["sha"]


# ======================= Lesen =======================
def _js_wert(roh):
    if roh in ("true", "false"):
        return roh == "true"
    if roh.startswith('"'):
        return json.loads(roh)
    return float(roh) if "." in roh else int(roh)


def config_felder(inhalt):
    m = CONFIG_RE.search(inhalt)
    if not m:
        return []
    felder, block = [], []
    for zeile in m.group(1).split("\n"):
        auf = BLOCK_AUF_RE.match(zeile)
        if auf:
            block.append(auf.group(1))
            continue
        if re.match(r"^\s*\},?\s*(//.*)?$", zeile):
            if block:
                block.pop()
            continue
        z = ZEILE_RE.match(zeile)
        if z:
            felder.append({"schluessel": ".".join(block + [z.group(2)]), "wert": _js_wert(z.group(3)),
                           "hinweis": (z.group(6) or "").strip()})
    return felder


def _ohne_code(inhalt):
    """Positionen von <script> und <style>, damit dort nichts als Text erkannt wird."""
    return [(m.start(), m.end()) for m in re.finditer(r"<(script|style)\b.*?</\1>", inhalt, re.S)]


def texte(inhalt):
    sperre = _ohne_code(inhalt)
    out = []
    for i, m in enumerate(TEXT_RE.finditer(inhalt)):
        if any(a <= m.start() < b for a, b in sperre):
            continue
        roh = m.group(3)
        if not roh.strip() or 'data-cfg' in m.group(2):
            continue
        # Abschnitt suchen, damit Julius weiß, wo der Text steht
        vor = inhalt.rfind("<section", 0, m.start())
        sid = re.search(r'id="([^"]+)"', inhalt[vor:inhalt.find(">", vor)]) if vor >= 0 else None
        out.append({"nr": i, "tag": m.group(1), "text": html.unescape(" ".join(roh.split())),
                    "bereich": sid.group(1) if sid else ""})
    return out


def bilder(inhalt):
    start = inhalt.find("window.IMAGES = {")
    if start < 0:
        return []
    return [{"name": m.group(2), "src": m.group(3)} for m in IMAGES_RE.finditer(inhalt, start)]


def lesen(inhalt):
    return {"config": config_felder(inhalt), "texte": texte(inhalt), "bilder": [b["name"] for b in bilder(inhalt)]}


# ======================= Ändern =======================
def config_setzen(inhalt, aenderungen):
    m = CONFIG_RE.search(inhalt)
    if not m:
        raise WebsiteFehler("CONFIG-Block nicht gefunden.")
    zeilen, block, gesetzt = m.group(1).split("\n"), [], set()
    for i, zeile in enumerate(zeilen):
        auf = BLOCK_AUF_RE.match(zeile)
        if auf:
            block.append(auf.group(1))
            continue
        if re.match(r"^\s*\},?\s*(//.*)?$", zeile):
            if block:
                block.pop()
            continue
        z = ZEILE_RE.match(zeile)
        if not z:
            continue
        key = ".".join(block + [z.group(2)])
        if key not in aenderungen:
            continue
        alt, neu = _js_wert(z.group(3)), aenderungen[key]
        if isinstance(alt, bool):
            neu_roh = "true" if neu in (True, "true", "1", 1) else "false"
        elif isinstance(alt, (int, float)):
            try:
                zahl = float(str(neu).replace(",", "."))
            except ValueError:
                raise WebsiteFehler(f"„{key}“ muss eine Zahl sein.")
            neu_roh = str(int(zahl)) if zahl == int(zahl) else str(zahl)
        else:
            neu_roh = json.dumps(str(neu), ensure_ascii=False)
        zeilen[i] = zeile[:z.start(3)] + neu_roh + zeile[z.end(3):]
        gesetzt.add(key)
    fehlt = set(aenderungen) - gesetzt
    if fehlt:
        raise WebsiteFehler("Unbekannte Felder: " + ", ".join(sorted(fehlt)))
    return inhalt[:m.start(1)] + "\n".join(zeilen) + inhalt[m.end(1):]


def texte_setzen(inhalt, aenderungen):
    """aenderungen: {nr: {"alt": alter Text, "neu": neuer Text}}. alt schützt davor, den falschen Text zu treffen."""
    aenderungen = {int(k): v for k, v in aenderungen.items()}
    teile, pos = [], 0
    for i, m in enumerate(TEXT_RE.finditer(inhalt)):
        if i not in aenderungen:
            continue
        a = aenderungen.pop(i)
        if html.unescape(" ".join(m.group(3).split())) != a["alt"]:
            raise WebsiteFehler("Die Seite wurde inzwischen geändert. Bitte neu laden und nochmal versuchen.")
        neu = html.escape(" ".join(str(a["neu"]).split()), quote=False)
        if not neu:
            raise WebsiteFehler("Ein Text darf nicht leer sein.")
        teile += [inhalt[pos:m.start(3)], neu]
        pos = m.end(3)
    if aenderungen:
        raise WebsiteFehler("Text nicht gefunden. Bitte neu laden.")
    return "".join(teile) + inhalt[pos:]


def bild_setzen(inhalt, name, data_url):
    if not re.fullmatch(r"data:image/(webp|jpeg|png);base64,[A-Za-z0-9+/=]+", data_url):
        raise WebsiteFehler("Bild muss WebP, JPEG oder PNG sein.")
    if len(data_url) > 1_500_000:
        raise WebsiteFehler("Bild ist zu groß (höchstens etwa 1 MB).")
    start = inhalt.find("window.IMAGES = {")
    for m in IMAGES_RE.finditer(inhalt, start):
        if m.group(2) == name:
            return inhalt[:m.start(3)] + data_url + inhalt[m.end(3):]
    raise WebsiteFehler(f"Bild „{name}“ nicht gefunden.")


def bild_daten(inhalt, name):
    for b in bilder(inhalt):
        if b["name"] == name:
            return b["src"]
    return ""
