"""YouTube ohne API-Schlüssel: Videotitel, Original-Thumbnail und das neueste Video eines Kanals.

Alles über öffentliche Adressen (oEmbed, i.ytimg.com, Kanal-RSS). Schlägt etwas fehl, gibt es einfach nichts zurück.
"""
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Thumbnail-Zentrale", "Accept-Language": "de-DE,de;q=0.9"}


def _get(url, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def video_id(text):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([\w-]{11})", text or "")
    return m.group(1) if m else ""


def video_link_in(text):
    """Erster YouTube-Videolink in einem Text (z. B. in der Bestell-Mail)."""
    vid = video_id(text)
    return f"https://www.youtube.com/watch?v={vid}" if vid else ""


def kanal_link_in(text):
    m = re.search(r"(https?://(?:www\.|m\.)?youtube\.com/(?:@[\w.\-%]+|channel/UC[\w-]{22}|c/[\w.\-%]+|user/[\w.\-%]+))", text or "")
    if m:
        return m.group(1)
    m = re.search(r"(?<![\w.])@([\w.\-]{3,30})\b", text or "")
    return f"https://www.youtube.com/@{m.group(1)}" if m and "." not in m.group(1)[-4:] else ""


def video_infos(vid):
    """{'titel', 'kanal'} über oEmbed."""
    try:
        d = json.loads(_get("https://www.youtube.com/oembed?format=json&url=" +
                            urllib.parse.quote(f"https://www.youtube.com/watch?v={vid}")))
        return {"titel": d.get("title", ""), "kanal": d.get("author_name", ""), "kanal_link": d.get("author_url", "")}
    except Exception:
        return {}


def thumbnail(vid):
    """Original-Thumbnail als Bytes (größte verfügbare Auflösung)."""
    for name in ("maxresdefault.jpg", "sddefault.jpg", "hqdefault.jpg"):
        try:
            daten = _get(f"https://i.ytimg.com/vi/{vid}/{name}")
            if len(daten) > 3000:  # YouTube liefert für fehlende Größen ein winziges Platzhalterbild
                return daten
        except Exception:
            continue
    return b""


def kanal_id(link):
    m = re.search(r"channel/(UC[\w-]{22})", link or "")
    if m:
        return m.group(1)
    try:
        html = _get(link).decode("utf-8", "replace")
    except Exception:
        return ""
    m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', html) or re.search(r"channel/(UC[\w-]{22})", html)
    return m.group(1) if m else ""


def neueste_videos(kanal_link, anzahl=5):
    """[{'id', 'titel', 'datum'}] aus dem öffentlichen RSS-Feed des Kanals (ohne Shorts, soweit erkennbar)."""
    cid = kanal_id(kanal_link)
    if not cid:
        return []
    try:
        root = ET.fromstring(_get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"))
    except Exception:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    out = []
    for e in root.findall("a:entry", ns):
        link = (e.find("a:link", ns).get("href") if e.find("a:link", ns) is not None else "")
        if "/shorts/" in link:
            continue
        out.append({"id": e.findtext("yt:videoId", "", ns), "titel": e.findtext("a:title", "", ns),
                    "datum": e.findtext("a:published", "", ns)[:10]})
        if len(out) >= anzahl:
            break
    return out


def material(text="", video_link="", kanal_link=""):
    """Sucht zu einer Bestellung oder einem Lead ein passendes Video und holt Titel + Original-Thumbnail.
    Gibt {'video_id', 'titel', 'kanal', 'bild': bytes} zurück oder {}."""
    vid = video_id(video_link) or video_id(text)
    if not vid:
        kl = kanal_link or kanal_link_in(text)
        videos = neueste_videos(kl, 1) if kl else []
        vid = videos[0]["id"] if videos else ""
    if not vid:
        return {}
    bild = thumbnail(vid)
    infos = video_infos(vid)
    if not bild and not infos:
        return {}
    return {"video_id": vid, "titel": infos.get("titel", ""), "kanal": infos.get("kanal", ""),
            "kanal_link": infos.get("kanal_link", ""), "bild": bild}
