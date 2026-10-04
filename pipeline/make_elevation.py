# -*- coding: utf-8 -*-
"""
make_elevation.py — jalankan SEKALI (atau saat titik berubah) untuk membuat elevation.json.

Untuk tiap titik (32 kecamatan + 45 grid) menyimpan:
  dem   = ketinggian titik (DEM 90 m, dari Open-Meteo)
  model = ketinggian orografi model ECMWF (0.25 derajat) hasil interpolasi bilinear
          4 sel sekitar titik — cara yang SAMA dengan ekstraksi suhu di ingest_ecmwf_ens.py
dipakai untuk koreksi suhu ENS: T_titik = T_model - 0.0065 * (dem - model)  [K/m = 6.5 K/km,
sama dengan downscaling Open-Meteo pada tabel deterministik].

    python make_elevation.py
"""
import json
import math
import os
import sys
import urllib.request

import config as C

UA = {"User-Agent": "mosaic-bima-dompu/1.0"}
API = "https://api.open-meteo.com/v1/forecast"
STEP = 0.25
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "elevation.json")


def get(q):
    with urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=90) as r:
        d = json.loads(r.read().decode())
    return d if isinstance(d, list) else [d]


def elevations(coords, model_cell):
    """coords: [(lat, lon)]. model_cell=True -> elevasi sel model (elevation=nan)."""
    out = []
    for i in range(0, len(coords), 20):
        b = coords[i:i + 20]
        q = (f"{API}?latitude={','.join(str(c[0]) for c in b)}&longitude={','.join(str(c[1]) for c in b)}"
             f"&hourly=temperature_2m&forecast_days=1&models=ecmwf_ifs025")
        if model_cell:
            q += "&elevation=" + ",".join(["nan"] * len(b))
        out += [x.get("elevation") for x in get(q)]
    return out


def main():
    pts = C.ALL_POINTS
    dem = elevations([(p[2], p[3]) for p in pts], False)

    # sel model: pusat sel 0.25 deg di sekitar tiap titik
    cells = set()
    for p in pts:
        la0 = math.floor(p[2] / STEP) * STEP
        lo0 = math.floor(p[3] / STEP) * STEP
        for da in (0, STEP):
            for do in (0, STEP):
                cells.add((round(la0 + da, 2), round(lo0 + do, 2)))
    cells = sorted(cells)
    cz = dict(zip(cells, elevations(cells, True)))

    out = {}
    for p, d in zip(pts, dem):
        la0 = math.floor(p[2] / STEP) * STEP
        lo0 = math.floor(p[3] / STEP) * STEP
        wy = (p[2] - la0) / STEP
        wx = (p[3] - lo0) / STEP
        z = lambda a, o: cz[(round(la0 + a, 2), round(lo0 + o, 2))]
        model = (z(0, 0) * (1 - wy) * (1 - wx) + z(0, STEP) * (1 - wy) * wx
                 + z(STEP, 0) * wy * (1 - wx) + z(STEP, STEP) * wy * wx)
        out[p[0]] = {"dem": round(d), "model": round(model), "dz": round(d - model)}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    dz = sorted(abs(v["dz"]) for v in out.values())
    print(f"tulis {OUT}: {len(out)} titik, {len(cells)} sel model, median |dz| {dz[len(dz)//2]} m, maks {dz[-1]} m")
    for k in ("tambora", "donggo", "lambitu", "sape", "bandara", "woja"):
        if k in out:
            print(f"  {k:9s} dem {out[k]['dem']:5d} m  model {out[k]['model']:5d} m  dz {out[k]['dz']:+5d} m  -> {-0.0065 * out[k]['dz']:+.1f} C")
    return 0


if __name__ == "__main__":
    sys.exit(main())
