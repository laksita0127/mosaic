# -*- coding: utf-8 -*-
"""
ingest_synoptic.py — medan sinoptik ECMWF IFS HRES (open data) untuk peta isobar & streamline -> sinoptik.js

Ambil run 00/12 UTC terbaru: tekanan muka laut (msl), angin (10 m, 850, 700, 500, 200 hPa) dan kelembapan relatif
(2 m dari 2t/2d, lalu 850/700/500/200 hPa), langkah 6 jam sampai 120 jam, dipotong ke kotak Indonesia & sekitarnya dan
dijarangkan ke 1 derajat. RH dinyatakan terhadap AIR (konversi dari basis campuran es/air IFS) agar konsisten dengan
analisis lapisan di halaman. Keluaran dipadatkan (int8/int16 base64) supaya riwayat git tidak bengkak.

    python pipeline/ingest_synoptic.py --source ecmwf
"""
import argparse
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "sinoptik.js")
CACHE = os.path.join(HERE, "grib_cache")
LAT_N, LAT_S, LON_W, LON_E = 15.0, -20.0, 90.0, 145.0
DEG = 1.0
STEPS = list(range(0, 121, 6))
LEVELS = [850, 700, 500, 200]


def retrieve(client, date, time, target, **req):
    client.retrieve(date=date, time=time, type="fc", stream="oper", step=STEPS, target=target, **req)


def fetch_latest(client):
    os.makedirs(CACHE, exist_ok=True)
    now = dt.datetime.utcnow()
    for back in range(0, 4):
        d = (now - dt.timedelta(days=back)).strftime("%Y%m%d")
        for t in (12, 0):
            if back == 0 and dt.datetime(now.year, now.month, now.day, t) > now - dt.timedelta(hours=7):
                continue                                  # run belum mendarat
            f_sfc = os.path.join(CACHE, f"syn2_sfc_{d}{t:02d}.grib2")
            f_pl = os.path.join(CACHE, f"syn2_pl_{d}{t:02d}.grib2")
            try:
                if not os.path.exists(f_sfc):
                    retrieve(client, d, t, f_sfc, levtype="sfc", param=["msl", "10u", "10v", "2t", "2d"])
                if not os.path.exists(f_pl):
                    retrieve(client, d, t, f_pl, levtype="pl", param=["u", "v", "r", "t"], levelist=LEVELS)
                return d, t, [f_sfc, f_pl]
            except Exception as e:                        # run itu belum ada -> coba yang lebih lama
                print(f"  {d} {t:02d}Z belum tersedia ({str(e)[:80]})")
                for f in (f_sfc, f_pl):
                    if os.path.exists(f):
                        os.remove(f)
    raise RuntimeError("tidak ada run HRES yang bisa diunduh")


def read_fields(files):
    from eccodes import (codes_grib_new_from_file, codes_get, codes_get_array, codes_release)
    fields = {}                                           # (nama, level, step) -> 2D array (lat N->S, lon W->E)
    for path in files:
        with open(path, "rb") as f:
            while True:
                gid = codes_grib_new_from_file(f)
                if gid is None:
                    break
                try:
                    name = codes_get(gid, "shortName")
                    lev = int(codes_get(gid, "level"))
                    step = int(codes_get(gid, "step"))
                    ni, nj = int(codes_get(gid, "Ni")), int(codes_get(gid, "Nj"))
                    la1 = codes_get(gid, "latitudeOfFirstGridPointInDegrees")
                    lo1 = codes_get(gid, "longitudeOfFirstGridPointInDegrees")
                    dj = codes_get(gid, "jDirectionIncrementInDegrees")
                    di = codes_get(gid, "iDirectionIncrementInDegrees")
                    v = codes_get_array(gid, "values").reshape(nj, ni)
                    lats = la1 - dj * np.arange(nj)
                    lons = (lo1 + di * np.arange(ni)) % 360
                    ii = [int(np.argmin(np.abs(lons - x))) for x in np.arange(LON_W, LON_E + 1e-6, DEG)]
                    jj = [int(np.argmin(np.abs(lats - x))) for x in np.arange(LAT_N, LAT_S - 1e-6, -DEG)]
                    fields[(name, lev, step)] = v[np.ix_(jj, ii)]
                finally:
                    codes_release(gid)
    return fields


def esw(tc):
    return 6.112 * np.exp(17.62 * tc / (243.12 + tc))


def esi(tc):
    return 6.112 * np.exp(22.46 * tc / (272.62 + tc))


def rh_to_water(rh, tk):
    """RH IFS (campuran air/es antara 0 dan -23 C) -> RH terhadap air."""
    tc = tk - 273.15
    alpha = np.clip(((tk - 250.16) / (273.16 - 250.16)) ** 2, 0, 1)
    alpha = np.where(tk >= 273.16, 1.0, np.where(tk <= 250.16, 0.0, alpha))
    return np.clip(rh * (alpha * esw(tc) + (1 - alpha) * esi(tc)) / esw(tc), 0, 100)


def b64(arr, dtype):
    import base64
    return base64.b64encode(np.ascontiguousarray(arr.astype(dtype)).tobytes()).decode("ascii")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="ecmwf")
    a = ap.parse_args()
    from ecmwf.opendata import Client
    d, t, files = fetch_latest(Client(source=a.source))
    F = read_fields(files)
    need = [("msl", 0), ("10u", 0), ("10v", 0), ("2t", 0), ("2d", 0)] + [(n, L) for L in LEVELS for n in ("u", "v", "r", "t")]
    steps = [s for s in STEPS if all((n, L, s) in F for n, L in need)]
    if not steps:
        print("tidak ada langkah lengkap", file=sys.stderr)
        return 1
    st = lambda n, L: np.stack([F[(n, L, s)] for s in steps])
    q_wind = lambda x: np.clip(np.round(x / 0.5), -127, 127)               # langkah 0,5 m/s
    fields = {"msl": b64(np.round((st("msl", 0) / 100.0 - 900) * 10), "<i2")}   # (hPa-900)*10
    for nm, L in (("10", 0), ("850", 850), ("700", 700), ("500", 500), ("200", 200)):
        un, vn = ("10u", "10v") if L == 0 else ("u", "v")
        fields["u" + nm] = b64(q_wind(st(un, L)), "i1")
        fields["v" + nm] = b64(q_wind(st(vn, L)), "i1")
    rh2 = np.clip(100 * esw(st("2d", 0) - 273.15) / esw(st("2t", 0) - 273.15), 0, 100)
    fields["rh10"] = b64(np.round(rh2), "i1")
    for L in LEVELS:
        fields[f"rh{L}"] = b64(np.round(rh_to_water(st("r", L), st("t", L))), "i1")
    out = {
        "run": f"{d[:4]}-{d[4:6]}-{d[6:]}T{t:02d}:00Z", "generated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
        "model": "ECMWF IFS HRES (open data)", "lat0": LAT_N, "lat1": LAT_S, "lon0": LON_W, "lon1": LON_E, "d": DEG,
        "nj": int(round((LAT_N - LAT_S) / DEG)) + 1, "ni": int(round((LON_E - LON_W) / DEG)) + 1,
        "steps": steps, "fmt": "packed1",
        "scale": {"wind": 0.5, "msl_off": 900, "msl_mul": 0.1}, "fields": fields,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// dibuat otomatis oleh pipeline/ingest_synoptic.py - JANGAN diedit tangan" + chr(10))
        f.write("window.SINOPTIK = " + json.dumps(out, separators=(",", ":")) + ";" + chr(10))
    print(f"tulis {OUT}: run {out['run']}, {len(steps)} langkah, {out['ni']}x{out['nj']}, {os.path.getsize(OUT)/1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
