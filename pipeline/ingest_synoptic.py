# -*- coding: utf-8 -*-
"""
ingest_synoptic.py — medan sinoptik ECMWF IFS HRES (open data) untuk peta isobar & streamline -> sinoptik.js

Ambil run 00/12 UTC terbaru: tekanan muka laut (msl) + angin u/v 850 & 200 hPa, langkah 6 jam sampai 144 jam,
dipotong ke kotak Indonesia & sekitarnya dan dijarangkan ke 1 derajat. Ringan (±1-2 MB keluaran).

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
STEPS = list(range(0, 145, 6))


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
            f_sfc = os.path.join(CACHE, f"syn_sfc_{d}{t:02d}.grib2")
            f_pl = os.path.join(CACHE, f"syn_pl_{d}{t:02d}.grib2")
            try:
                if not os.path.exists(f_sfc):
                    retrieve(client, d, t, f_sfc, levtype="sfc", param=["msl"])
                if not os.path.exists(f_pl):
                    retrieve(client, d, t, f_pl, levtype="pl", param=["u", "v"], levelist=[850, 200])
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="ecmwf")
    a = ap.parse_args()
    from ecmwf.opendata import Client
    d, t, files = fetch_latest(Client(source=a.source))
    F = read_fields(files)
    steps = [s for s in STEPS if ("msl", 0, s) in F and ("u", 850, s) in F and ("u", 200, s) in F]
    if not steps:
        print("tidak ada langkah lengkap", file=sys.stderr)
        return 1
    r1 = lambda x: np.round(x, 1).tolist()
    out = {
        "run": f"{d[:4]}-{d[4:6]}-{d[6:]}T{t:02d}:00Z", "generated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
        "model": "ECMWF IFS HRES (open data)", "lat0": LAT_N, "lat1": LAT_S, "lon0": LON_W, "lon1": LON_E, "d": DEG,
        "nj": int(round((LAT_N - LAT_S) / DEG)) + 1, "ni": int(round((LON_E - LON_W) / DEG)) + 1,
        "steps": steps,
        "msl": [r1(F[("msl", 0, s)] / 100.0) for s in steps],                      # hPa
        "u850": [r1(F[("u", 850, s)]) for s in steps], "v850": [r1(F[("v", 850, s)]) for s in steps],   # m/s
        "u200": [r1(F[("u", 200, s)]) for s in steps], "v200": [r1(F[("v", 200, s)]) for s in steps],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// dibuat otomatis oleh pipeline/ingest_synoptic.py - JANGAN diedit tangan\n")
        f.write("window.SINOPTIK = " + json.dumps(out, separators=(",", ":")) + ";\n")
    print(f"tulis {OUT}: run {out['run']}, {len(steps)} langkah, {out['ni']}x{out['nj']}, {os.path.getsize(OUT)/1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
