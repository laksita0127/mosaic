# -*- coding: utf-8 -*-
"""
verify_models.py — perkiraan awal: model mana yang paling cocok dengan hujan harian di sekitar Bima & Dompu?

Pembanding ("kebenaran" pendekatan): CHIRPS v3 (hujan harian satelit+stasiun, 0,05°, per hari UTC; tersedia terlambat ±40 hari).
Model: arsip prakiraan Open-Meteo (historical-forecast-api) — ECMWF IFS, GFS, ICON, AIFS. Catatan: arsip ini menyambung jam-jam awal tiap run
(lead ≈ 0–24 jam), jadi ukur kemampuan jangka pendek.
Hujan model = jumlah per-jam sepanjang hari UTC; CHIRPS = rata-rata kotak 0,25° (5x5 piksel) di sekitar titik (sebanding dengan sel model).

    python pipeline/verify_models.py 2026-01-01 2026-03-15
Hasil: pipeline/verify_cache.json (cache CHIRPS) dan ringkasan di layar.  BUKAN pembanding dengan pos hujan resmi BMKG.
"""
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import sys
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "verify_cache.json")
PTS = {"bima": (-8.5418, 118.6922), "dompu": (-8.5401, 118.4647)}
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "ecmwf_aifs025_single"]
LABEL = {"ecmwf_ifs025": "ECMWF", "gfs_seamless": "GFS", "icon_seamless": "ICON", "ecmwf_aifs025_single": "AIFS"}
HALF = 0.125
URL = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/sat/{y}/chirps-v3.0.sat.{y}.{m:02d}.{d:02d}.tif"


def chirps_day(day):
    import rasterio
    from rasterio.windows import from_bounds
    url = URL.format(y=day.year, m=day.month, d=day.day)
    out = {}
    with rasterio.Env(GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="3", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        with rasterio.open(url) as ds:
            for k, (la, lo) in PTS.items():
                a = ds.read(1, window=from_bounds(lo - HALF, la - HALF, lo + HALF, la + HALF, ds.transform)).astype(float)
                a[a < 0] = np.nan
                out[k] = None if np.isnan(a).all() else float(np.nanmean(a))
    return day.isoformat(), out


def load_cache():
    try:
        return json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        return {}


def get_chirps(d0, d1, workers=8):
    cache = load_cache()
    days = [d0 + dt.timedelta(days=i) for i in range((d1 - d0).days + 1)]
    todo = [d for d in days if d.isoformat() not in cache]
    print(f"CHIRPS: {len(days)} hari, {len(todo)} perlu diunduh", flush=True)
    done = 0
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(chirps_day, d): d for d in todo}
        for f in cf.as_completed(futs):
            try:
                k, v = f.result(); cache[k] = v
            except Exception as e:
                print("gagal", futs[f], str(e)[:80], flush=True)
            done += 1
            if done % 5 == 0:
                json.dump(cache, open(CACHE, "w", encoding="utf-8")); print(f"  {done}/{len(todo)}", flush=True)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"))
    return cache


def get_models(d0, d1):
    out = {}
    for k, (la, lo) in PTS.items():
        q = (f"https://historical-forecast-api.open-meteo.com/v1/forecast?latitude={la}&longitude={lo}&start_date={d0}&end_date={d1}"
             f"&hourly=precipitation&models={','.join(MODELS)}&timezone=UTC")
        with urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "mosaic-verify/1.0"}), timeout=120) as r:
            h = json.loads(r.read().decode())["hourly"]
        days = {}
        for i, t in enumerate(h["time"]):
            for m in MODELS:
                v = h.get(f"precipitation_{m}", [None] * len(h["time"]))[i]
                if v is not None:
                    days.setdefault(t[:10], {}).setdefault(m, []).append(v)
        out[k] = {d: {m: (sum(v) if len(v) >= 20 else None) for m, v in dm.items()} for d, dm in days.items()}
    return out


def scores(obs, fc, thr):
    o = np.array(obs) >= thr; f = np.array(fc) >= thr
    h = int((o & f).sum()); mi = int((o & ~f).sum()); fa = int((~o & f).sum()); cn = int((~o & ~f).sum())
    pod = h / (h + mi) if h + mi else float("nan"); far = fa / (h + fa) if h + fa else float("nan")
    csi = h / (h + mi + fa) if h + mi + fa else float("nan"); bias = (h + fa) / (h + mi) if h + mi else float("nan")
    return dict(h=h, m=mi, fa=fa, cn=cn, pod=pod, far=far, csi=csi, bias=bias)


def main():
    d0 = dt.date.fromisoformat(sys.argv[1]); d1 = dt.date.fromisoformat(sys.argv[2])
    chirps = get_chirps(d0, d1)
    mod = get_models(d0, d1)
    rows = []   # (obs, {model: val})
    for k in PTS:
        for d, v in chirps.items():
            if v is None or v.get(k) is None or d not in mod[k]:
                continue
            dm = mod[k][d]
            if any(dm.get(m) is None for m in MODELS):
                continue
            rows.append((v[k], dm))
    n = len(rows); obs = [r[0] for r in rows]
    print(f"\nsampel: {n} (hari × 2 titik); hari hujan CHIRPS ≥1 mm: {sum(o>=1 for o in obs)}, ≥5 mm: {sum(o>=5 for o in obs)}; rata² {np.mean(obs):.2f} mm/hari")
    series = {LABEL[m]: [r[1][m] for r in rows] for m in MODELS}
    series["Rata² 4 model"] = [float(np.mean([r[1][m] for m in MODELS])) for r in rows]
    series["Kesepakatan (≥2 model ≥1 mm)"] = [(1.0 if sum(r[1][m] >= 1 for m in MODELS) >= 2 else 0.0) * max(1.0, float(np.mean([r[1][m] for m in MODELS]))) for r in rows]
    res = {}
    for name, fc in series.items():
        a = scores(obs, fc, 1); b = scores(obs, fc, 5)
        cc = float(np.corrcoef(obs, fc)[0, 1]) if np.std(fc) > 0 else float("nan")
        res[name] = dict(csi1=a["csi"], pod1=a["pod"], far1=a["far"], bias1=a["bias"], csi5=b["csi"], pod5=b["pod"], far5=b["far"], corr=cc,
                         mean=float(np.mean(fc)), mae=float(np.mean(np.abs(np.array(fc) - np.array(obs)))))
    print(f"\n{'sumber':30s} {'CSI≥1':>6s} {'POD':>5s} {'FAR':>5s} {'bias':>5s} | {'CSI≥5':>6s} {'POD':>5s} {'FAR':>5s} | {'korel':>5s} {'rata²mm':>7s} {'MAE':>5s}")
    for name, r in res.items():
        print(f"{name:30s} {r['csi1']:6.2f} {r['pod1']:5.2f} {r['far1']:5.2f} {r['bias1']:5.2f} | {r['csi5']:6.2f} {r['pod5']:5.2f} {r['far5']:5.2f} | {r['corr']:5.2f} {r['mean']:7.2f} {r['mae']:5.2f}")
    json.dump({"n": n, "obs_mean": float(np.mean(obs)), "scores": res, "range": [str(d0), str(d1)]}, open(os.path.join(HERE, "verify_result.json"), "w"), indent=1)


if __name__ == "__main__":
    sys.exit(main())
