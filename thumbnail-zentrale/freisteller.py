"""Stellt Personen auf Fotos frei (Hintergrund weg), damit sie groß und mit weißem Rand aufs Thumbnail kommen.

Nutzt das KI-Modell "u2net_human_seg" (läuft lokal auf dem Server, kostenlos). Beim ersten Mal lädt die App
das Modell einmalig herunter (ca. 170 MB) und speichert es im Datenordner. Klappt etwas nicht, gibt es
einfach kein freigestelltes Bild und die Thumbnails nehmen das normale Foto.
"""
import os
import threading
import urllib.request

MODELL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx"
_lock = threading.Lock()
_sitzung = None


def _modell_pfad():
    import store
    ordner = os.path.join(store.DATA, "modelle")
    os.makedirs(ordner, exist_ok=True)
    return os.path.join(ordner, "u2net_human_seg.onnx")


def _sitzung_holen():
    global _sitzung
    if _sitzung is None:
        import onnxruntime as ort
        pfad = _modell_pfad()
        if not os.path.exists(pfad) or os.path.getsize(pfad) < 100_000_000:
            tmp = pfad + ".laden"
            urllib.request.urlretrieve(MODELL_URL, tmp)
            os.replace(tmp, pfad)
        opt = ort.SessionOptions()
        opt.intra_op_num_threads = 2
        _sitzung = ort.InferenceSession(pfad, opt, providers=["CPUExecutionProvider"])
    return _sitzung


def maske(bild):
    """Graustufen-Maske (Person weiß) in Bildgröße."""
    import numpy as np
    from PIL import Image
    s = _sitzung_holen()
    im = np.array(bild.convert("RGB").resize((320, 320), Image.Resampling.LANCZOS), dtype=np.float32)
    im = im / max(float(im.max()), 1e-6)
    mittel, abw = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)
    for k in range(3):
        im[:, :, k] = (im[:, :, k] - mittel[k]) / abw[k]
    eingabe = {s.get_inputs()[0].name: im.transpose((2, 0, 1))[None].astype(np.float32)}
    pred = s.run(None, eingabe)[0][:, 0, :, :]
    pred = (pred - pred.min()) / max(float(pred.max() - pred.min()), 1e-6)
    m = Image.fromarray((np.squeeze(pred) * 255).astype("uint8"), mode="L")
    return m.resize(bild.size, Image.Resampling.LANCZOS)


def _groesste_flaeche(m):
    """Nur die größte zusammenhängende Fläche behalten (Krümel und Logos im Hintergrund fliegen raus)."""
    import numpy as np
    from PIL import Image
    klein = m.resize((max(1, m.width // 4), max(1, m.height // 4)))
    a = np.array(klein) > 128
    h, w = a.shape
    besucht = np.zeros_like(a)
    beste, beste_n = None, 0
    for y in range(h):
        for x in range(w):
            if a[y, x] and not besucht[y, x]:
                stapel, punkte = [(y, x)], []
                besucht[y, x] = True
                while stapel:
                    cy, cx = stapel.pop()
                    punkte.append((cy, cx))
                    for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                        if 0 <= ny < h and 0 <= nx < w and a[ny, nx] and not besucht[ny, nx]:
                            besucht[ny, nx] = True
                            stapel.append((ny, nx))
                if len(punkte) > beste_n:
                    beste, beste_n = punkte, len(punkte)
    if not beste:
        return m
    behalten = np.zeros_like(a, dtype=np.uint8)
    ys, xs = zip(*beste)
    behalten[list(ys), list(xs)] = 255
    gross = Image.fromarray(behalten, mode="L").resize(m.size).point(lambda v: 255 if v > 0 else 0)
    from PIL import ImageChops, ImageFilter
    return ImageChops.multiply(m, gross.filter(ImageFilter.MaxFilter(9)))


def freistellen(quelle, ziel):
    """Speichert die freigestellte Person als PNG (zugeschnitten). True, wenn eine Person gefunden wurde."""
    from PIL import Image, ImageOps
    with _lock:
        bild = ImageOps.exif_transpose(Image.open(quelle)).convert("RGB")
        if max(bild.size) > 1600:
            bild.thumbnail((1600, 1600))
        roh = maske(bild)
        import numpy as np
        a = np.asarray(roh, dtype=np.float32)
        sicher = a[a > 60]
        unsicher = ((a > 40) & (a < 215)).sum() / max(1, (a > 40).sum())
        if sicher.size == 0 or sicher.mean() < 180 or unsicher > 0.4:  # das Modell ist sich nicht sicher: keine Person
            return False
        m = _groesste_flaeche(roh)
        box = m.point(lambda v: 255 if v > 60 else 0).getbbox()
        if not box:
            return False
        flaeche = (box[2] - box[0]) * (box[3] - box[1]) / (bild.width * bild.height)
        if flaeche < 0.03:  # nur ein Fleck gefunden: lieber kein Freisteller
            return False
        rgba = bild.copy()
        rgba.putalpha(m)
        rgba.crop(box).save(ziel, "PNG")
        return True


def verfuegbar():
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        return True
    except Exception:
        return False
