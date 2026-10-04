# -*- coding: utf-8 -*-
"""
ingest_climate.py — ambil indeks iklim skala besar terbaru (gratis, tanpa kunci) -> dinamika.js

  Niño 3.4  : NOAA CPC, anomali SST mingguan (OISST)       wksst9120.for
  SOI       : NOAA CPC, SOI terstandar BULANAN               soi
  DMI (IOD) : NOAA PSL, DMI BULANAN (HadISST/OISST)          dmi.had.long.data

Catatan: ini BUKAN buletin BMKG. SOI CPC berskala terstandar (±0,7 ~ setara ±7 pada skala BoM), DMI bulanan terlambat
±1-2 bulan. MJO, Kelvin/Rossby, indeks surge tidak punya sumber terbuka yang andal -> tetap lewat buletin yang ditempel.

    python pipeline/ingest_climate.py
"""
import datetime
import json
import os
import re
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 mosaic-bima-dompu/1.0"}
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dinamika.js")
NUM = re.compile(r"-?\d+\.\d+")
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def nino34():
    last = None
    for ln in get("https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for").splitlines():
        m = re.match(r"\s*(\d{2})([A-Z]{3})(\d{4})\s+(.*)", ln)
        if not m:
            continue
        v = NUM.findall(m.group(4))
        if len(v) >= 8:
            last = (m.group(3), MON.index(m.group(2)) + 1, int(m.group(1)), float(v[5]), float(v[4]))
    if not last:
        raise RuntimeError("Niño 3.4 tidak terbaca")
    y, mo, d, ssta, sst = last
    return {"value": ssta, "sst": sst, "date": f"{y}-{mo:02d}-{d:02d}", "src": "NOAA CPC, anomali SST mingguan"}


def soi():
    txt = get("https://www.cpc.ncep.noaa.gov/data/indices/soi")
    part = txt.split("STANDARDIZED", 1)[-1]          # tabel kedua = terstandar
    last = None
    for ln in part.splitlines():
        m = re.match(r"\s*(\d{4})(.*)", ln)
        if not m:
            continue
        vals = NUM.findall(m.group(2))
        for i, s in enumerate(vals[:12]):
            if float(s) > -900:
                last = (int(m.group(1)), i + 1, float(s))
    if not last:
        raise RuntimeError("SOI tidak terbaca")
    y, mo, v = last
    return {"value": v, "month": f"{y}-{mo:02d}", "src": "NOAA CPC, SOI terstandar bulanan"}


def dmi():
    last = None
    for ln in get("https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data").splitlines():
        p = ln.split()
        if len(p) == 13 and p[0].isdigit():
            for i, s in enumerate(p[1:]):
                if float(s) > -900:
                    last = (int(p[0]), i + 1, float(s))
    if not last:
        raise RuntimeError("DMI tidak terbaca")
    y, mo, v = last
    return {"value": v, "month": f"{y}-{mo:02d}", "src": "NOAA PSL, DMI bulanan"}


def main():
    out, err = {}, []
    for k, fn in (("nino34", nino34), ("soi", soi), ("dmi", dmi)):
        try:
            out[k] = fn()
            print(k, out[k])
        except Exception as e:  # satu sumber gagal tidak menggagalkan yang lain
            err.append(f"{k}: {e}")
            print("GAGAL", k, e, file=sys.stderr)
    if not out:
        return 1
    out["generated"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// dibuat otomatis oleh pipeline/ingest_climate.py - JANGAN diedit tangan\n")
        f.write("window.DINAMIKA = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print("tulis", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
