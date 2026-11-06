"""Rechnungen für Überweisung per IBAN: Nummer vergeben, als PDF bauen, Zahlungshinweis für die Mail.

Als Kleinunternehmer (§ 19 UStG) ohne Umsatzsteuer. Beträge bis 250 € sind Kleinbetragsrechnungen,
dafür reicht die Anschrift des Ausstellers.
"""
import datetime as dt
import html
import os
import re

import store


def euro(x):
    return f"{float(x):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def iban_schoen(iban):
    iban = re.sub(r"\s+", "", iban or "").upper()
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def iban_gueltig(iban):
    iban = re.sub(r"\s+", "", iban or "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return False
    zahl = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return int(zahl) % 97 == 1


def _ab(bezahlt_bis):
    """Beginn des nächsten Abo-Zeitraums: das Datum "bezahlt bis", wenn es noch in der Zukunft liegt, sonst heute."""
    try:
        d = dt.date.fromisoformat(str(bezahlt_bis)[:10])
    except ValueError:
        d = None
    return max(d or dt.date.today(), dt.date.today())


def naechste_nummer(s):
    jahr = dt.date.today().year
    vorhanden = [int(m.group(1)) for r in s["rechnungen"] if (m := re.fullmatch(rf"RE-{jahr}-(\d+)", r["nr"]))]
    start = int(s["einstellungen"].get("rechnung_start") or 1)
    return f"RE-{jahr}-{max(vorhanden + [start - 1]) + 1:03d}"


def anlegen(s, email, name, kanal, posten, betrag, auftrag_id=""):
    """Neue Rechnung im Speicher (ohne PDF). Gibt das Rechnungs-Dict zurück."""
    e = s["einstellungen"]
    heute = dt.date.today()
    r = {"id": store.neue_id(), "nr": naechste_nummer(s), "datum": heute.isoformat(),
         "faellig": (heute + dt.timedelta(days=int(e.get("zahlungsziel_tage") or 7))).isoformat(),
         "email": email, "name": name, "kanal": kanal, "posten": posten, "betrag": round(float(betrag), 2),
         "auftrag": auftrag_id, "bezahlt": "", "datei": ""}
    s["rechnungen"].insert(0, r)
    return r


def zahlungs_hinweis(e, r):
    """Textblock für die Mail: Betrag, Frist, Bankdaten, Verwendungszweck."""
    if not r:
        return ""
    if not e.get("iban"):
        return f"Die Rechnung {r['nr']} über {euro(r['betrag'])} hängt an.\n\n"
    frist = dt.date.fromisoformat(r["faellig"]).strftime("%d.%m.%Y")
    return (f"Die Rechnung hängt an. Bitte überweise {euro(r['betrag'])} bis zum {frist} an:\n"
            f"{e.get('kontoinhaber') or e.get('dein_name', '')}\nIBAN: {iban_schoen(e['iban'])}\n"
            + (f"BIC: {e['bic']}\n" if e.get("bic") else "")
            + f"Verwendungszweck: {r['nr']}\n\n")


def html_rechnung(e, impressum, r):
    def x(t):
        return html.escape(str(t or ""))
    datum = dt.date.fromisoformat(r["datum"]).strftime("%d.%m.%Y")
    frist = dt.date.fromisoformat(r["faellig"]).strftime("%d.%m.%Y")
    absender = impressum.get("name") or e.get("kontoinhaber") or e.get("dein_name", "")
    adresse = ", ".join(t for t in (impressum.get("strasse"), impressum.get("ort")) if t)
    an = r["name"] or r["kanal"] or r["email"]
    bank = (f"<tr><td>Kontoinhaber</td><td>{x(e.get('kontoinhaber') or absender)}</td></tr>"
            f"<tr><td>IBAN</td><td><b>{x(iban_schoen(e.get('iban')))}</b></td></tr>"
            + (f"<tr><td>BIC</td><td>{x(e.get('bic'))}</td></tr>" if e.get("bic") else "")
            + f"<tr><td>Verwendungszweck</td><td><b>{x(r['nr'])}</b></td></tr>") if e.get("iban") else ""
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 0 }}
body {{ margin: 0; font: 11pt/1.5 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #18181b }}
.seite {{ padding: 22mm 20mm }}
.kopf {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18mm }}
.marke {{ font-size: 18pt; font-weight: 700; letter-spacing: -.01em }}
.marke span {{ color: #16a34a }}
.klein {{ color: #71717a; font-size: 9pt }}
h1 {{ font-size: 20pt; margin: 0 0 2mm; letter-spacing: -.01em }}
table {{ border-collapse: collapse; width: 100% }}
.posten th {{ text-align: left; font-size: 9pt; color: #71717a; font-weight: 600; border-bottom: 1px solid #e4e4e7; padding: 3mm 0 }}
.posten td {{ padding: 4mm 0; border-bottom: 1px solid #f4f4f5 }}
.posten .r {{ text-align: right }}
.summe td {{ padding-top: 5mm; font-size: 13pt; font-weight: 700 }}
.bank {{ margin-top: 12mm; background: #f4f4f5; border-radius: 3mm; padding: 6mm 7mm }}
.bank td {{ padding: 1mm 6mm 1mm 0 }}
.bank td:first-child {{ color: #71717a; width: 42mm }}
.fuss {{ position: fixed; bottom: 14mm; left: 20mm; right: 20mm; color: #71717a; font-size: 8.5pt; border-top: 1px solid #e4e4e7; padding-top: 3mm }}
</style></head><body><div class="seite">
<div class="kopf"><div><div class="marke">{x(e.get('dein_name') or absender)}<span>.</span></div><div class="klein">Thumbnail-Design für YouTube</div></div>
<div class="klein" style="text-align:right">{x(absender)}<br>{x(impressum.get('strasse'))}<br>{x(impressum.get('ort'))}<br>{x(e.get('gmail'))}</div></div>
<div class="klein">Rechnung an</div><div style="margin-bottom:10mm"><b>{x(an)}</b>{('<br>' + x(r['email'])) if r['email'] and an != r['email'] else ''}</div>
<h1>Rechnung</h1>
<table style="width:auto;margin-bottom:10mm" class="klein"><tr><td style="padding-right:8mm">Rechnungsnummer</td><td><b style="color:#18181b">{x(r['nr'])}</b></td></tr>
<tr><td>Rechnungsdatum</td><td>{datum}</td></tr><tr><td>Leistungsdatum</td><td>{datum}</td></tr><tr><td>Zahlbar bis</td><td>{frist}</td></tr></table>
<table class="posten"><tr><th>Leistung</th><th class="r">Betrag</th></tr>
<tr><td>{x(r['posten'])}</td><td class="r">{euro(r['betrag'])}</td></tr>
<tr class="summe"><td>Gesamtbetrag</td><td class="r">{euro(r['betrag'])}</td></tr></table>
<p class="klein" style="margin-top:4mm">{'Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.' if impressum.get('kleinunternehmer', True) else ''}</p>
{f'<div class="bank"><div style="font-weight:600;margin-bottom:2mm">Bitte überweise den Betrag bis {frist} auf dieses Konto:</div><table>{bank}</table></div>' if bank else ''}
<p style="margin-top:12mm">Danke für deinen Auftrag!</p>
<div class="fuss">{x(absender)}{(' · ' + x(adresse)) if adresse else ''} · {x(e.get('gmail'))}</div>
</div></body></html>"""


def pdf_bauen(s, r, impressum, ordner):
    import render
    ziel = os.path.join(ordner, f"{r['nr']}.pdf")
    render.als_pdf(html_rechnung(s["einstellungen"], impressum, r), ziel)
    return ziel
