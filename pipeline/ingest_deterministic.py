# -*- coding: utf-8 -*-
"""
ingest_deterministic.py — model deterministik (ECMWF IFS, GFS, ICON, AIFS) untuk 77 titik, 8 hari, per jam -> det_data.js

Tujuan: halaman TIDAK lagi memanggil Open-Meteo dari browser tiap pengguna (batas laju gratis per IP kantor!).
Pipeline memanggil Open-Meteo SEKALI per run dari GitHub, halaman cukup membaca berkas statis.
Bentuk data meniru respons Open-Meteo (hourly['temperature_2m_<model>']) sehingga HTML memakai parser yang sama.

Juga menyimpan profil lapisan atas (RH 850/700/500/200, angin, CAPE, uap air) untuk titik Bima & Dompu (kartu Analisis).

    python pipeline/ingest_deterministic.py
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

import config as C

MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "ecmwf_aifs025_single"]
VARS = ["temperature_2m", "relative_humidity_2m", "precipitation", "weather_code", "wind_speed_10m", "wind_direction_10m"]
LEVEL_VARS = ["relative_humidity_850hPa", "relative_humidity_700hPa", "relative_humidity_500hPa", "relative_humidity_200hPa",
              "temperature_200hPa", "wind_speed_850hPa", "wind_direction_850hPa", "wind_speed_200hPa", "wind_direction_200hPa",
              "cape", "total_column_integrated_water_vapour"]
LEVEL_PTS = [("bima", -8.5418, 118.6922), ("dompu", -8.5401, 118.4647)]
DAYS = 8
BATCH = 20
API_KEY = os.environ.get("OPENMETEO_API_KEY", "").strip()
API = "https://customer-api.open-meteo.com/v1/forecast" if API_KEY else "https://api.open-meteo.com/v1/forecast"
PACE = float(os.environ.get("OM_PACE", "8"))
UA = "mosaic-bima-dompu/1.0 (BMKG Stamet Bima; github.com/laksita0127/mosaic)"
OUT = os.path.join(C.PROJECT_DIR, "det_data.js")


def log(m):
    print(f"[{dt.datetime.utcnow():%H:%M:%S}Z] {m}", flush=True)


def http_json(url, tries=6, base=15):
    last = None
    for i in range(tries):
        wait = base * (2 ** i)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=240) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:200]
            last = f"HTTP {e.code} {body}"
            if e.code == 400:
                raise RuntimeError(last)
            if e.code == 429:
                low = body.lower()
                if "daily" in low:
                    raise RuntimeError("batas harian Open-Meteo habis (" + last + ")")
                wait = 600 if "hourly" in low else max(wait, 65)
        except Exception as e:  # noqa
            last = str(e)[:150]
        log(f"    ulang {i + 1}/{tries} dalam {min(wait, 300)} dtk ({last})")
        time.sleep(min(wait, 300))
    raise RuntimeError(last)


def fetch(points, variables):
    q = (f"{API}?latitude={','.join(str(p[1]) for p in points)}&longitude={','.join(str(p[2]) for p in points)}"
         f"&hourly={','.join(variables)}&models={','.join(MODELS)}&forecast_days={DAYS}&timezone=Asia%2FMakassar&wind_speed_unit=kmh")
    if API_KEY:
        q += f"&apikey={API_KEY}"
    j = http_json(q)
    return j if isinstance(j, list) else [j]


def main():
    pts = [(p[0], p[2], p[3]) for p in C.ALL_POINTS]
    out_pts, times = {}, None
    for i in range(0, len(pts), BATCH):
        b = pts[i:i + BATCH]
        log(f"batch {i // BATCH + 1}/{(len(pts) + BATCH - 1) // BATCH}: {len(b)} titik")
        for p, entry in zip(b, fetch(b, VARS)):
            h = entry["hourly"]
            times = times or h["time"]
            out_pts[p[0]] = {k: v for k, v in h.items() if k != "time"}
        time.sleep(PACE)
    log("profil lapisan atas Bima & Dompu")
    lv = {}
    for p, entry in zip(LEVEL_PTS, fetch(LEVEL_PTS, LEVEL_VARS)):
        lv[p[0]] = {k: v for k, v in entry["hourly"].items() if k != "time"}
        lv_times = entry["hourly"]["time"]
    out = {"schema": "mosaic-det/1", "generated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "models": MODELS,
           "time": times, "points": out_pts, "levels": {"time": lv_times, "points": lv}}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// dibuat otomatis oleh pipeline/ingest_deterministic.py - JANGAN diedit tangan" + chr(10))
        f.write("window.DET_DATA = " + json.dumps(out, separators=(",", ":")) + ";" + chr(10))
    log(f"tulis {OUT}: {len(out_pts)} titik, {len(times)} jam, {os.path.getsize(OUT) / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
