# -*- coding: utf-8 -*-
"""
ingest_openmeteo_ens.py
=======================

Ensemble MULTI-MODEL untuk MOSAIC lewat Open-Meteo Ensemble API:

    ECMWF IFS ENS  (51 skenario)     ECMWF AIFS ENS (51)
    NOAA GEFS      (31)              DWD ICON-EPS   (40)

untuk 77 titik (32 kecamatan/bandara + 45 grid) -> ../ens_multi.js
(window.ENS_MULTI), dibaca langsung oleh halaman MOSAIC.

Kenapa selain pipeline GRIB ECMWF (ingest_ecmwf_ens.py)?
  * Satu API JSON untuk 4 ensemble — tanpa decode GRIB, tanpa rate-limit portal
    ECMWF (503 "Slow Down" yang menghantam IP GitHub).
  * Jumlah skenario penuh (51), bukan 15-20.
  * GEFS 12 UTC masuk ~01:40 WITA dan ICON-EPS 12 UTC ~23:50 WITA, jadi ada
    ensemble siklus 12 UTC SEBELUM tenggat kirim 04:00 (ECMWF 12 UTC belum).
  Kekurangan: IFS ENS di Open-Meteo masuk ~12 jam setelah run (pipeline GRIB
  langsung dari ECMWF ~8-9 jam) — halaman otomatis memakai yang lebih baru.

Catatan waktu: precipitation Open-Meteo = jumlah JAM SEBELUMNYA. Jadi hujan
jendela [T, T+3 jam) = nilai pada T+1, T+2, T+3.

Pemakaian:
    python ingest_openmeteo_ens.py                  # semua model, 77 titik
    python ingest_openmeteo_ens.py --models gefs    # satu model saja
    python ingest_openmeteo_ens.py --limit-points 8 # uji cepat
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request

import numpy as np

import config as C

UTC = dt.timezone.utc
WITA = dt.timezone(dt.timedelta(hours=C.TZ_OFFSET_HOURS))

ALL_VARS = ["precipitation", "temperature_2m", "wind_speed_10m", "wind_direction_10m"]
# key, label, singkat, nama model di Ensemble API, nama di endpoint meta (info run), variabel, semua 77 titik?
# Open-Meteo membatasi "bobot" panggilan (600/menit, 5.000/jam, 10.000/hari) dan tiap kolom skenario
# dihitung berat (bobot per lokasi ≈ variabel x skenario / 5 — terukur: 2 batch ECMWF 4-variabel x 8 titik
# sudah menghabiskan jatah semenit). Maka SEMUA model hanya diminta CURAH HUJAN (yang dipakai peluang &
# gabungan); suhu/angin ensemble ECMWF diambil dari pipeline GRIB (ingest_ecmwf_ens.py). ECMWF di 77 titik,
# AIFS/GEFS/ICON di 32 titik kecamatan → ±1.600 bobot per run, 3 run/hari ≈ 4.800 (batas 10.000/hari).
RAIN = ["precipitation"]
MODELS = [
    ("ecmwf", "ECMWF IFS ENS", "ECMWF", "ecmwf_ifs025", "ecmwf_ifs025_ensemble", RAIN, False),
    ("aifs", "ECMWF AIFS ENS", "AIFS", "ecmwf_aifs025", "ecmwf_aifs025_ensemble", RAIN, False),
    ("gefs", "NOAA GEFS", "GEFS", "ncep_gefs025", "ncep_gefs025", RAIN, False),
    ("icon", "DWD ICON-EPS", "ICON", "icon_seamless", "dwd_icon_eps", RAIN, False),
]
HOURLY = ALL_VARS
SLOTS = [2, 5, 8, 11, 14, 17, 20, 23]          # sama dengan tabel produk BMKG & HTML
SHOW_DAYS = 8                                   # hari yang ditampilkan
FORECAST_DAYS = SHOW_DAYS + 1                   # +1 hari penyangga (jendela hujan butuh T+3)
BATCH = 8
API_KEY = os.environ.get("OPENMETEO_API_KEY", "").strip()      # opsional (langganan berbayar)
API = ("https://customer-ensemble-api.open-meteo.com/v1/ensemble" if API_KEY
       else "https://ensemble-api.open-meteo.com/v1/ensemble")
PACE = float(os.environ.get("OM_PACE", "10"))                   # detik jeda antar batch (jaga < 600 bobot/menit)
META = "https://api.open-meteo.com/data/{name}/static/meta.json"
UA = "mosaic-bima-dompu/1.0 (BMKG Stamet Bima; github.com/laksita0127/mosaic)"
POE = [1, 5, 10, 20]            # ambang peluang hujan 3-jam (mm) — cukup untuk UI, hemat ukuran file
OUT_DEFAULT = os.path.join(C.PROJECT_DIR, "ens_multi.js")


def log(msg):
    print(f"[{dt.datetime.now(WITA):%H:%M:%S}] {msg}", flush=True)


def iso(ts):
    if ts is None:
        return None
    return dt.datetime.fromtimestamp(int(ts), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def http_json(url, tries=6, base=15):
    last = None
    for i in range(tries):
        wait = base * (2 ** i)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=240) as r:
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


def get_run(meta_name):
    try:
        m = http_json(META.format(name=meta_name), tries=3, base=5)
        return {"run": iso(m.get("last_run_initialisation_time")),
                "avail": iso(m.get("last_run_availability_time"))}
    except Exception:  # noqa
        return {"run": None, "avail": None}


# ---------------------------------------------------------------------------
# parsing & produk
# ---------------------------------------------------------------------------
def member_cols(hourly, var):
    cols = [k for k in hourly if k == var or re.fullmatch(re.escape(var) + r"_member\d+", k)]
    cols.sort(key=lambda k: (0 if k == var else int(k.rsplit("member", 1)[1])))
    return cols


def to_matrix(hourly, var):
    cols = member_cols(hourly, var)
    if not cols:
        return None
    return np.array([hourly[c] for c in cols], dtype=float)   # (M, H), None -> nan


def r1(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 1)


def r2(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 2)


def circ_mean(deg):
    deg = deg[~np.isnan(deg)]
    if deg.size == 0:
        return None
    rad = np.radians(deg)
    return float(np.degrees(np.arctan2(np.sin(rad).sum(), np.cos(rad).sum())) % 360.0)


def build_steps(first_date):
    d0 = dt.date.fromisoformat(first_date)
    steps = []
    for d in range(SHOW_DAYS):
        day = d0 + dt.timedelta(days=d)
        for h in SLOTS:
            steps.append(f"{day.isoformat()}T{h:02d}:00")
    return steps


def hour_key(step):
    """'2026-10-04T14:00' -> dt untuk menggeser jam."""
    return dt.datetime.strptime(step, "%Y-%m-%dT%H:%M")


def fmt(t):
    return t.strftime("%Y-%m-%dT%H:%M")


def slot_matrices(h, times, steps):
    """Per langkah (jendela [T, T+3h)): precip3, temp, ws, wd -> array (M, nstep)."""
    idx = {t: i for i, t in enumerate(times)}
    P = h["precipitation"]
    M = P.shape[0]
    n = len(steps)
    p3 = np.full((M, n), np.nan)
    tmp = np.full((M, n), np.nan)
    ws = np.full((M, n), np.nan)
    wd = np.full((M, n), np.nan)
    for si, s in enumerate(steps):
        t0 = hour_key(s)
        i1 = idx.get(fmt(t0 + dt.timedelta(hours=1)))
        i2 = idx.get(fmt(t0 + dt.timedelta(hours=2)))
        i3 = idx.get(fmt(t0 + dt.timedelta(hours=3)))
        if i1 is not None and i2 is not None and i3 is not None:
            p3[:, si] = P[:, [i1, i2, i3]].sum(axis=1)       # jam sebelumnya: T+1..T+3
        if i1 is not None:
            if h.get("temperature_2m") is not None:
                tmp[:, si] = h["temperature_2m"][:, i1]
            if h.get("wind_speed_10m") is not None:
                ws[:, si] = h["wind_speed_10m"][:, i1]
            if h.get("wind_direction_10m") is not None:
                wd[:, si] = h["wind_direction_10m"][:, i1]
    return p3, tmp, ws, wd


def col_stats(mat, with_minmax=True):
    """mat (M, n) -> dict list per langkah."""
    n = mat.shape[1]
    out = {k: [] for k in ("mean", "min", "max", "p10", "p90")}
    for si in range(n):
        v = mat[:, si]
        v = v[~np.isnan(v)]
        if v.size == 0:
            for k in out:
                out[k].append(None)
            continue
        p10, p90 = np.percentile(v, [10, 90])
        out["mean"].append(r1(v.mean()))
        out["min"].append(r1(v.min()))
        out["max"].append(r1(v.max()))
        out["p10"].append(r1(p10))
        out["p90"].append(r1(p90))
    return out


def poe_stats(mat):
    n = mat.shape[1]
    out = {str(t): [] for t in POE}
    for si in range(n):
        v = mat[:, si]
        v = v[~np.isnan(v)]
        for t in POE:
            out[str(t)].append(None if v.size == 0 else r2((v >= t).mean()))
    return out


def point_products(h, times, steps):
    p3, tmp, ws, wd = slot_matrices(h, times, steps)
    prec = col_stats(p3)
    prec["poe"] = poe_stats(p3)
    entry = {
        "precip3": prec,
        "temp": col_stats(tmp) if h.get("temperature_2m") is not None else None,
        "wind_speed": col_stats(ws) if h.get("wind_speed_10m") is not None else None,
        "wind_dir": {"mean": [r1(circ_mean(wd[:, si])) for si in range(wd.shape[1])]}
                    if h.get("wind_direction_10m") is not None else None,
    }
    entry = {k: v for k, v in entry.items() if v is not None}
    return entry, p3


def wperc(vals, w, qs):
    o = np.argsort(vals)
    v, ww = vals[o], w[o]
    cw = (np.cumsum(ww) - 0.5 * ww) / ww.sum()
    return np.interp(qs, cw, v)


def pooled_products(mats, thr):
    """mats: list matriks precip3 (M_i, n). Bobot sama per MODEL (bukan per member)."""
    n = mats[0].shape[1]
    out = {"mean": [], "p10": [], "p50": [], "p90": [], "nm": [],
           "poe": {str(t): [] for t in thr}}
    for si in range(n):
        vals, wts, nm = [], [], 0
        for m in mats:
            v = m[:, si]
            v = v[~np.isnan(v)]
            if v.size:
                vals.append(v)
                wts.append(np.full(v.size, 1.0 / v.size))
                nm += 1
        if not vals:
            for k in ("mean", "p10", "p50", "p90"):
                out[k].append(None)
            out["nm"].append(0)
            for t in thr:
                out["poe"][str(t)].append(None)
            continue
        v = np.concatenate(vals)
        w = np.concatenate(wts)
        p10, p50, p90 = wperc(v, w, [0.10, 0.50, 0.90])
        out["mean"].append(r1(np.average(v, weights=w)))
        out["p10"].append(r1(p10))
        out["p50"].append(r1(p50))
        out["p90"].append(r1(p90))
        out["nm"].append(nm)
        for t in thr:
            out["poe"][str(t)].append(r2(w[v >= t].sum() / w.sum()))
    return out


# ---------------------------------------------------------------------------
# ambil satu model untuk semua titik
# ---------------------------------------------------------------------------
def fetch_model(key, om_model, points, steps_holder, vars_):
    results = {}      # id -> (entry, p3 matrix)
    n_members = None
    for b in range(0, len(points), BATCH):
        batch = points[b:b + BATCH]
        q = (f"{API}?latitude={','.join(str(p[2]) for p in batch)}"
             f"&longitude={','.join(str(p[3]) for p in batch)}"
             f"&hourly={','.join(vars_)}&models={om_model}&forecast_days={FORECAST_DAYS}"
             f"&timezone=Asia%2FMakassar&wind_speed_unit=kmh" + (f"&apikey={API_KEY}" if API_KEY else ""))
        t0 = time.time()
        data = http_json(q)
        if isinstance(data, dict):
            data = [data]
        if len(data) != len(batch):
            raise RuntimeError(f"jumlah lokasi tidak cocok ({len(data)} vs {len(batch)})")
        for p, d in zip(batch, data):
            hourly = d["hourly"]
            times = hourly["time"]
            if not steps_holder:
                steps_holder.extend(build_steps(times[0][:10]))
            h = {v: to_matrix(hourly, v) for v in vars_}
            if h["precipitation"] is None:
                raise RuntimeError("kolom precipitation tidak ada")
            n_members = h["precipitation"].shape[0]
            entry, p3 = point_products(h, times, steps_holder)
            results[p[0]] = (entry, p3)
        log(f"  {key}: titik {min(b + BATCH, len(points))}/{len(points)} ({time.time() - t0:.0f} dtk)")
        time.sleep(PACE)
    return results, n_members


def load_old(path):
    try:
        s = open(path, encoding="utf-8").read()
        j = s[s.index("{"):s.rindex("}") + 1]
        return json.loads(j)
    except Exception:  # noqa
        return None


def main():
    ap = argparse.ArgumentParser(description="Ensemble multi-model (Open-Meteo) -> ens_multi.js")
    ap.add_argument("--models", default=",".join(m[0] for m in MODELS))
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--limit-points", type=int, default=0, help="uji cepat: hanya N titik pertama")
    args = ap.parse_args()

    want = [m for m in MODELS if m[0] in args.models.split(",")]
    points = list(C.ALL_POINTS)
    if args.limit_points:
        points = points[:args.limit_points]
    old = load_old(args.out)
    steps = []
    models_out, pool_mats = {}, {}
    t_start = time.time()
    log(f"{len(points)} titik, model: {', '.join(m[0] for m in want)}")

    for key, label, short, om_model, meta_name, vars_, all_pts in want:
        pts = points if all_pts else [p for p in points if p[0] in C.STATION_IDS]
        log(f"model {key} ({om_model}), {len(pts)} titik")
        meta_before = get_run(meta_name)
        try:
            results, n_members = fetch_model(key, om_model, pts, steps, vars_)
            meta_after = get_run(meta_name)
            if meta_before["run"] and meta_after["run"] and meta_before["run"] != meta_after["run"]:
                log("  run berganti di tengah unduhan — ulang model ini sekali")
                steps.clear()
                results, n_members = fetch_model(key, om_model, pts, steps, vars_)
                meta_before = get_run(meta_name)
            else:
                meta_before = meta_after
            models_out[key] = {
                "label": label, "short": short, "n_members": n_members,
                "run": meta_before["run"], "avail": meta_before["avail"],
                "source": "Open-Meteo Ensemble API",
                "points": {pid: e for pid, (e, _p3) in results.items()},
            }
            pool_mats[key] = {pid: p3 for pid, (_e, p3) in results.items()}
            log(f"  {key}: {n_members} skenario, run {meta_before['run']}")
        except Exception as e:  # noqa
            log(f"  !! {key} GAGAL: {str(e)[:200]}")
            if old and old.get("models", {}).get(key):
                keep = old["models"][key]
                keep["stale"] = True
                models_out[key] = keep
                log(f"  {key}: pakai data lama (ditandai stale)")

    if not models_out:
        log("tidak ada data sama sekali — batal menulis")
        return 1
    if not steps:
        steps = (old or {}).get("steps") or []

    # gabungan (bobot sama per model) dari model yang BARU diambil
    pooled_pts = {}
    fresh = [k for k in pool_mats]
    if len(fresh) >= 2 and steps:
        for p in points:
            mats = [pool_mats[k][p[0]] for k in fresh if p[0] in pool_mats[k]]
            if len(mats) >= 2:
                pooled_pts[p[0]] = {"precip3": pooled_products(mats, POE)}
    elif old and old.get("pooled"):
        pooled_pts = old["pooled"].get("points", {})

    payload = {
        "schema": "mosaic-ens-multi/1",
        "generated": dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": "Asia/Makassar (UTC+8)",
        "steps": steps,
        "thresholds_mm": POE,
        "models": models_out,
        "pooled": {"n_models": len(fresh), "models": fresh, "points": pooled_pts},
    }
    js = ("// dibuat otomatis oleh pipeline/ingest_openmeteo_ens.py - JANGAN diedit tangan\n"
          f"// generated {payload['generated']}\n"
          "window.ENS_MULTI = " + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(js)
    log(f"tulis {args.out} ({len(js) / 1024:.0f} KB, {len(models_out)} model, "
        f"{len(steps)} langkah) dalam {time.time() - t_start:.0f} dtk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
