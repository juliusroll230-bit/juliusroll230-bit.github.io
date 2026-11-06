"""Baut aus einem Entwurf (dict aus planer.py) ein Thumbnail: erst HTML, dann mit Chromium ein PNG (1280 x 720)."""
import html as _html
import os
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
CHROMIUM = os.environ.get("CHROMIUM_PATH", "")  # leer = Playwright nimmt seinen eigenen Browser

PALETTEN = {  # hell, mittel, dunkel
    "finanzen": ("#00d26a", "#006b2e", "#002a12"),
    "fitness": ("#ff8a00", "#ff2d55", "#3a0010"),
    "gaming": ("#b026ff", "#5b0bd6", "#12002e"),
    "tech": ("#00b4ff", "#0047ff", "#000d33"),
    "allgemein": ("#ff3b3b", "#b00000", "#2a0000"),
}
SCHRIFT_CSS = {"Anton": "Anton", "Bebas": "Bebas", "Mont": "Mont", "Lucky": "Lucky", "Archivo": "Archivo"}


def _css(base):
    f = base + "fonts/"
    return f"""
@font-face {{ font-family: 'Anton'; src: url({f}anton-latin-400-normal.woff2), url({f}anton-latin-ext-400-normal.woff2); }}
@font-face {{ font-family: 'Bebas'; src: url({f}bebas-neue-latin-400-normal.woff2), url({f}bebas-neue-latin-ext-400-normal.woff2); }}
@font-face {{ font-family: 'Mont'; font-weight: 900; src: url({f}montserrat-latin-900-normal.woff2), url({f}montserrat-latin-ext-900-normal.woff2); }}
@font-face {{ font-family: 'Lucky'; src: url({f}luckiest-guy-latin-400-normal.woff2); }}
@font-face {{ font-family: 'Archivo'; src: url({f}archivo-black-latin-400-normal.woff2), url({f}archivo-black-latin-ext-400-normal.woff2); }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ width: 1280px; height: 720px; overflow: hidden; background: #000; }}
.c {{ position: relative; width: 1280px; height: 720px; overflow: hidden; }}
.abs {{ position: absolute; }}
.t {{ position: absolute; text-transform: uppercase; line-height: .92; white-space: nowrap; font-weight: 900;
     paint-order: stroke fill; -webkit-text-stroke: var(--sw, 16px) #000;
     filter: drop-shadow(0 10px 0 rgba(0,0,0,.4)); }}
.t div {{ white-space: nowrap; }}
.emo {{ position: absolute; filter: drop-shadow(0 18px 22px rgba(0,0,0,.45)); }}
.sticker {{ filter: drop-shadow(6px 0 0 #fff) drop-shadow(-6px 0 0 #fff) drop-shadow(0 6px 0 #fff) drop-shadow(0 -6px 0 #fff) drop-shadow(0 18px 20px rgba(0,0,0,.5)); }}
.foto {{ position: absolute; object-fit: cover; border: 12px solid #fff; border-radius: 6px; box-shadow: 0 24px 40px rgba(0,0,0,.55); }}
.vig {{ position: absolute; inset: 0; background: radial-gradient(ellipse at center, rgba(0,0,0,0) 50%, rgba(0,0,0,.6) 100%); pointer-events: none; }}
.rays {{ position: absolute; inset: -500px; background: repeating-conic-gradient(from 0deg at 50% 50%, rgba(255,255,255,.1) 0deg 8deg, rgba(255,255,255,0) 8deg 16deg); }}
.banner {{ position: absolute; padding: 12px 30px 6px; transform: rotate(-3deg); box-shadow: 0 10px 0 rgba(0,0,0,.35); white-space: nowrap; text-transform: uppercase; line-height: 1; }}
"""


# Passt jede Textzeile in ihre maximale Breite (wird im Browser ausgeführt, bevor das Bild entsteht)
FIT_JS = """
<script>
document.fonts.ready.then(function () {
  document.querySelectorAll('[data-maxw]').forEach(function (el) {
    var maxw = +el.dataset.maxw, maxh = +(el.dataset.maxh || 9999), fs = parseFloat(getComputedStyle(el).fontSize);
    for (var i = 0; i < 80 && (el.scrollWidth > maxw || el.scrollHeight > maxh) && fs > 30; i++) {
      fs -= 3; el.style.fontSize = fs + 'px'; el.style.setProperty('--sw', Math.max(8, Math.round(fs / 7)) + 'px');
    }
  });
  document.body.setAttribute('data-fertig', '1');
});
</script>"""


def _e(t):
    return _html.escape(str(t), quote=True)


def _text(zeilen, farben, schrift, size, links, oben, maxw, maxh=9999, extra=""):
    teile = "".join(f'<div style="color:{farben[min(i, len(farben) - 1)]}">{_e(z)}</div>' for i, z in enumerate(zeilen))
    return (f'<div class="t" data-maxw="{maxw}" data-maxh="{maxh}" style="left:{links}px;top:{oben}px;'
            f'font-family:{SCHRIFT_CSS.get(schrift, "Anton")};font-size:{size}px;--sw:{max(8, round(size / 7))}px;{extra}">'
            f'{teile}</div>')


def _emoji(base, name, style, cls=""):
    return f'<img class="emo {cls}" src="{base}emoji/{_e(name)}.png" style="{style}">'


def _pfeil(style, farbe="#ff2a2a", spiegeln=False):
    flip = "transform: scaleX(-1);" if spiegeln else ""
    return f"""<svg class="abs" style="{style}; overflow: visible; filter: drop-shadow(0 8px 0 rgba(0,0,0,.35)); {flip}" viewBox="0 0 300 200">
  <path d="M20 170 C 70 40, 190 20, 250 70" fill="none" stroke="#fff" stroke-width="44" stroke-linecap="round"/>
  <path d="M215 20 L 290 85 L 200 120 Z" fill="#fff" stroke="#fff" stroke-width="22" stroke-linejoin="round"/>
  <path d="M20 170 C 70 40, 190 20, 250 70" fill="none" stroke="{farbe}" stroke-width="26" stroke-linecap="round"/>
  <path d="M215 20 L 290 85 L 200 120 Z" fill="{farbe}" stroke="{farbe}" stroke-width="6" stroke-linejoin="round"/>
</svg>"""


def _banner(text, links, oben, bg="#fff", farbe="#111", size=72, schrift="Anton", maxw=1100):
    if not text:
        return ""
    return (f'<div class="banner" data-maxw="{maxw}" style="left:{links}px;top:{oben}px;background:{bg};color:{farbe};'
            f'font-family:{SCHRIFT_CSS.get(schrift, "Anton")};font-size:{size}px">{_e(text)}</div>')


def _rechts_bild(e, base, foto_url, links, oben, groesse, drehung=6):
    """Kundenfoto (falls vorhanden) oder das erste Emoji auf der rechten Seite."""
    if e.get("foto") and foto_url:
        w, h = int(groesse * 0.92), int(groesse * 1.08)
        return (f'<img class="foto" src="{foto_url}{_e(e["foto"])}" style="left:{links}px;top:{oben - 20}px;'
                f'width:{w}px;height:{h}px;transform:rotate({drehung * 0.5}deg)">')
    return _emoji(base, e["emoji"][0], f"left:{links}px;top:{oben}px;width:{groesse}px;transform:rotate({drehung}deg)", "sticker")


def thumbnail_html(e, base="", foto_url=""):
    """e: geprüfter Entwurf. base: Adresse des assets-Ordners (mit / am Ende). foto_url: Ordner der Kundenfotos."""
    hell, mittel, dunkel = PALETTEN.get(e["stil"], PALETTEN["allgemein"])
    z = e["zeilen"]
    f1, f2 = e["farbe1"], e["farbe2"]
    s = e.get("schrift", "Anton")
    g = e.get("gross", 100) / 100
    em2 = e["emoji"][1] if len(e["emoji"]) > 1 else e["emoji"][0]
    v = e["vorlage"]
    teile = []
    if v == "strahlen":
        teile += [
            f'<div class="abs" style="inset:0;background:radial-gradient(circle at 72% 50%,{hell} 0%,{mittel} 45%,{dunkel} 100%)"></div>',
            '<div class="abs" style="inset:0;overflow:hidden;-webkit-mask-image:linear-gradient(90deg,transparent 10%,#000 55%)">'
            '<div class="abs" style="left:280px;top:0;width:1280px;height:720px"><div class="rays"></div></div></div>',
            _emoji(base, em2, "left:1090px;top:24px;width:160px;transform:rotate(14deg)"),
            _rechts_bild(e, base, foto_url, 790, 150, 440, 8),
            _text(z, [f1, f2], s, int(170 * g), 56, 130 if len(z) > 1 else 220, 740, 470),
            _banner(e["banner"], 60, 575, schrift=s, maxw=700),
            '<div class="vig"></div>',
        ]
        if e["pfeil"]:
            teile.insert(-1, _pfeil("left:560px;top:420px;width:260px;height:170px", f2))
    elif v == "split":
        teile += [
            '<div class="abs" style="inset:0;background:linear-gradient(160deg,#30343b,#121418)"></div>',
            f'<div class="abs" style="left:720px;top:-40px;width:900px;height:820px;background:linear-gradient(150deg,{hell},{mittel});'
            'transform:skewX(-8deg);overflow:hidden;box-shadow:-24px 0 40px rgba(0,0,0,.5)"><div class="rays"></div></div>',
            _emoji(base, em2, "left:1080px;top:30px;width:170px;transform:rotate(12deg)"),
            _rechts_bild(e, base, foto_url, 800, 190, 420, -6),
            _text(z, [f1, f2], s, int(150 * g), 50, 120 if len(z) > 1 else 220, 640, 470),
            _banner(e["banner"], 60, 575, bg=f2, schrift=s, maxw=620),
            '<div class="vig"></div>',
        ]
        if e["pfeil"]:
            teile.insert(-1, _pfeil("left:560px;top:430px;width:250px;height:165px", f2))
    elif v == "spot":
        oben, unten = z[0], " ".join(z[1:])
        teile += [
            '<div class="abs" style="inset:0;background:#0b0b0f"></div>',
            '<div class="abs" style="inset:0;background-image:linear-gradient(rgba(255,255,255,.05) 2px,transparent 2px),'
            'linear-gradient(90deg,rgba(255,255,255,.05) 2px,transparent 2px);background-size:64px 64px"></div>',
            f'<div class="abs" style="inset:0;background:radial-gradient(circle at 78% 52%,{hell}cc 0%,{mittel}88 30%,rgba(0,0,0,0) 62%)"></div>',
            f'<div class="abs" style="left:0;bottom:0;width:1280px;height:16px;background:{hell}"></div>',
            _rechts_bild(e, base, foto_url, 800, 120, 430, 4),
            _text([oben], [f1], s, int(180 * g), 50, 60, 760, 330),
            _banner(unten or e["banner"], 50, 470, bg=f2, farbe="#111", size=int(120 * g), schrift=s, maxw=760),
            _banner(e["banner"] if unten else "", 60, 620, bg="#fff", size=48, schrift=s, maxw=700),
            '<div class="vig"></div>',
        ]
        if e["pfeil"]:
            teile.insert(-1, _pfeil("left:640px;top:250px;width:200px;height:140px", f2))
    else:  # vergleich: links grau (vorher), rechts farbig (nachher)
        links_t, rechts_t = z[0], " ".join(z[1:]) or z[0]
        teile += [
            '<div class="abs" style="left:0;top:0;width:660px;height:720px;background:linear-gradient(160deg,#3a3f47,#1b1e23)"></div>',
            f'<div class="abs" style="left:600px;top:-40px;width:900px;height:820px;background:linear-gradient(150deg,{hell},{mittel});'
            'transform:skewX(-8deg);overflow:hidden"><div class="rays"></div></div>',
            _emoji(base, e["emoji"][0], "left:120px;top:230px;width:330px;filter:grayscale(.75) drop-shadow(0 18px 22px rgba(0,0,0,.5))"),
            _rechts_bild(e, base, foto_url, 800, 200, 400, -6) if e.get("foto") else
            _emoji(base, em2, "left:800px;top:190px;width:400px;transform:rotate(-6deg)", "sticker"),
            _text([links_t], ["#c9ced6"], s, int(130 * g), 50, 40, 540, 170),
            _text([rechts_t], [f2], s, int(130 * g), 700, 30, 540, 170, "transform:rotate(-3deg)"),
            _pfeil("left:470px;top:300px;width:320px;height:210px", f2),
            _banner(e["banner"], 260, 590, schrift=s, maxw=800),
            '<div class="vig"></div>',
        ]
    return ('<!doctype html><html><head><meta charset="utf-8"><style>' + _css(base) + '</style></head><body>'
            '<div class="c">' + "".join(teile) + "</div>" + FIT_JS + "</body></html>")


_lock = threading.Lock()


def als_png(auftraege):
    """auftraege: Liste von (entwurf, foto_ordner, ziel_pfad). Rendert alle mit einem Browser."""
    from playwright.sync_api import sync_playwright
    base = "file://" + ASSETS + "/"
    with _lock, sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch(executable_path=CHROMIUM or None, args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            for i, (e, foto_ordner, ziel) in enumerate(auftraege):
                foto_url = ("file://" + os.path.abspath(foto_ordner) + "/") if foto_ordner else ""
                datei = os.path.join(tmp, f"t{i}.html")
                with open(datei, "w", encoding="utf-8") as f:
                    f.write(thumbnail_html(e, base, foto_url))
                page.goto("file://" + datei)
                page.wait_for_selector("body[data-fertig]", state="attached", timeout=15000)
                page.wait_for_timeout(50)
                os.makedirs(os.path.dirname(ziel), exist_ok=True)
                page.screenshot(path=ziel, type="png")
        finally:
            browser.close()
