# -*- coding: utf-8 -*-
"""
ingest_climate.py — indeks iklim skala besar terbaru (gratis, tanpa kunci) -> dinamika.js

Sumber UTAMA = yang dipakai buletin BMKG (BoM, Biro Meteorologi Australia), dibaca dari halaman https://www.bom.gov.au/climate/enso/ :
  Niño 3.4 relatif mingguan | SOI 30-hari (skala BoM, ambang ±7) | IOD/DMI mingguan
Cadangan bila BoM tidak dapat diakses (mis. memblokir IP cloud) = NOAA:
  CPC Niño 3.4 mingguan (wksst9120.for) | CPC SOI terstandar BULANAN | PSL DMI BULANAN
MJO: NOAA PSL ROMI (berbasis OLR; BERBEDA dari RMM BoM yang sedang gangguan data — lihat catatan di halaman).

Catatan: ini BUKAN buletin BMKG. Surge, Kelvin/Rossby, belokan/konvergensi dari buletin yang ditempel (atau deteksi model di peta sinoptik).

    python pipeline/ingest_climate.py
"""
import datetime
import html
import json
import math
import os
import re
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dinamika.js")
NUM = re.compile(r"-?\d+\.\d+")
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
MINUS = "-−–‒—"          # BoM memakai tanda minus tipografis / en dash


def get(url, raw=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    return b if raw else b.decode("utf-8", "replace")


def iso(dtxt):
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", dtxt.strip())
    return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}" if m else None


def sgn(s):
    s = s.strip()
    neg = bool(s) and s[0] in MINUS.replace("-", "") + "-"
    v = float(re.sub(r"[^\d.]", "", s))
    return -v if neg else v


# ------------------------------------------------------------------ BoM (utama)
_bom_text = None


def bom_text():
    global _bom_text
    if _bom_text is None:
        raw = get("https://www.bom.gov.au/climate/enso/", raw=True)
        try:
            t = raw.decode("utf-8")
        except UnicodeDecodeError:
            t = raw.decode("cp1252", "replace")
        t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
        t = html.unescape(re.sub(r"<[^>]+>", " ", t))
        _bom_text = re.sub(r"\s+", " ", t)
    return _bom_text


def bom_nino34():
    m = re.search(r"relative\s+Ni.{1,3}o\s?3\.4 index value for the week ending (\d{1,2} \w+ \d{4}) is\s*([%s+]?\s*[\d.]+)" % re.escape(MINUS), bom_text(), re.I)
    if not m:
        raise RuntimeError("Niño 3.4 BoM tidak terbaca")
    return {"value": sgn(m.group(2)), "date": iso(m.group(1)), "src": "BoM, Niño3.4 relatif mingguan", "scale": "bom"}


def bom_soi():
    m = re.search(r"30-day SOI to (\d{1,2} \w+ \d{4}) (?:at|of|is)\s*([%s+]?\s*[\d.]+)" % re.escape(MINUS), bom_text(), re.I)
    if not m:
        raise RuntimeError("SOI BoM tidak terbaca")
    return {"value": sgn(m.group(2)), "date": iso(m.group(1)), "src": "BoM, SOI 30-hari", "scale": "bom"}


def bom_dmi():
    m = re.search(r"IOD index value for the week ending (\d{1,2} \w+ \d{4}) is\s*([%s+]?\s*[\d.]+)" % re.escape(MINUS), bom_text(), re.I)
    if not m:
        raise RuntimeError("IOD BoM tidak terbaca")
    return {"value": sgn(m.group(2)), "date": iso(m.group(1)), "src": "BoM, IOD (DMI) mingguan", "scale": "bom"}


# ------------------------------------------------------------------ NOAA (cadangan)
def noaa_nino34():
    last = None
    for ln in get("https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for").splitlines():
        m = re.match(r"\s*(\d{2})([A-Z]{3})(\d{4})\s+(.*)", ln)
        if not m:
            continue
        v = NUM.findall(m.group(4))
        if len(v) >= 8:
            last = (m.group(3), MON.index(m.group(2)) + 1, int(m.group(1)), float(v[5]))
    if not last:
        raise RuntimeError("Niño 3.4 NOAA tidak terbaca")
    y, mo, d, ssta = last
    return {"value": ssta, "date": f"{y}-{mo:02d}-{d:02d}", "src": "NOAA CPC, anomali SST mingguan (cadangan)", "scale": "noaa"}


def noaa_soi():
    part = get("https://www.cpc.ncep.noaa.gov/data/indices/soi").split("STANDARDIZED", 1)[-1]
    last = None
    for ln in part.splitlines():
        m = re.match(r"\s*(\d{4})(.*)", ln)
        if not m:
            continue
        for i, s in enumerate(NUM.findall(m.group(2))[:12]):
            if float(s) > -900:
                last = (int(m.group(1)), i + 1, float(s))
    if not last:
        raise RuntimeError("SOI NOAA tidak terbaca")
    y, mo, v = last
    return {"value": v, "month": f"{y}-{mo:02d}", "src": "NOAA CPC, SOI terstandar bulanan (cadangan, skala berbeda dari BoM)", "scale": "noaa"}


def noaa_dmi():
    last = None
    for ln in get("https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data").splitlines():
        p = ln.split()
        if len(p) == 13 and p[0].isdigit():
            for i, s in enumerate(p[1:]):
                if float(s) > -900:
                    last = (int(p[0]), i + 1, float(s))
    if not last:
        raise RuntimeError("DMI NOAA tidak terbaca")
    y, mo, v = last
    return {"value": v, "month": f"{y}-{mo:02d}", "src": "NOAA PSL, DMI bulanan (cadangan, terlambat 1-2 bulan)", "scale": "noaa"}


def mjo():
    """ROMI (OLR-based MJO Index, NOAA PSL): RC1, RC2, amplitudo harian. Fase 1-8 mengikuti konvensi RMM."""
    last = None
    for ln in get("https://psl.noaa.gov/mjo/mjoindex/romi.cpcolr.1x.txt").splitlines():
        p = ln.split()
        if len(p) >= 7 and p[0].isdigit():
            try:
                last = (int(p[0]), int(p[1]), int(p[2]), float(p[4]), float(p[5]), float(p[6]))
            except ValueError:
                continue
    if not last:
        raise RuntimeError("MJO tidak terbaca")
    y, mo, d, rc1, rc2, amp = last
    ang = math.degrees(math.atan2(rc2, rc1)) % 360
    phase = [5, 6, 7, 8, 1, 2, 3, 4][int(ang // 45)]
    return {"phase": phase, "amp": round(amp, 2), "date": f"{y}-{mo:02d}-{d:02d}", "src": "NOAA PSL, ROMI (OLR)"}


def main():
    out = {}
    for k, fns in (("nino34", (bom_nino34, noaa_nino34)), ("soi", (bom_soi, noaa_soi)), ("dmi", (bom_dmi, noaa_dmi)), ("mjo", (mjo,))):
        for fn in fns:
            try:
                out[k] = fn()
                print(k, "<-", fn.__name__, out[k])
                break
            except Exception as e:                       # satu sumber gagal -> coba cadangan
                print("GAGAL", fn.__name__, e, file=sys.stderr)
    if not out:
        return 1
    out["generated"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// dibuat otomatis oleh pipeline/ingest_climate.py - JANGAN diedit tangan" + chr(10))
        f.write("window.DINAMIKA = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";" + chr(10))
    print("tulis", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
