# -*- coding: utf-8 -*-
"""
verify_atmos.py — apakah penyesuaian "+ kondisi atmosfer" memperbaiki prakiraan hujan? (rekonstruksi SEDERHANA, uji awal)

Memakai verifikasi.js (hujan CMORPH per jendela 3 jam + prakiraan model lead 0) dan merekonstruksi skor atmosfer harian dari arsip Open-Meteo:
  RH 850/700/500 hPa, uap air total, CAPE, angin 850 hPa, geser 850-200 hPa  (aturan & ambang SAMA dengan analisis.js)
TIDAK direkonstruksi (arsipnya tidak ada): konvergensi/konfluensi, gelombang MJO/Kelvin/ER/Low, indeks skala besar, peluang ensemble per model.
=> skor di sini lebih "kasar" daripada di aplikasi; hasilnya petunjuk apakah arah penyesuaiannya benar, bukan nilai pasti.

Aturan satu model:  tanpa atmosfer: hujan bila model >= 0,5 mm/3 jam (ambang kategori "Hujan Ringan")
                    atmosfer menghambat : hujan bila >= 2 mm (>=5 mm lolos otomatis) ; netral/mendukung: >= 0,5 mm
Aturan kesepakatan: tanpa atmosfer: >=2 dari 4 model >= 1 mm ;  menghambat: >=2 model >= 1 mm DAN rata² >= 2 mm
    python pipeline/verify_atmos.py
"""
import datetime as dt
import json
import math
import os
import sys
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "verifikasi.js")
TH = {"rh850": (60, 80), "rh700": (50, 70), "rh500": (40, 60), "pw": (35, 50)}
LEVEL_PT = {"bandara": "bima", "sape": "bima", "lambu": "bima", "tambora": "bima", "wera": "bima", "dompu": "dompu"}
LPTS = {"bima": (-8.5418, 118.6922), "dompu": (-8.5401, 118.4647)}
LMODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]
VARS = ["relative_humidity_850hPa", "relative_humidity_700hPa", "relative_humidity_500hPa", "total_column_integrated_water_vapour", "cape",
        "wind_speed_850hPa", "wind_direction_850hPa", "wind_speed_200hPa", "wind_direction_200hPa"]


def load():
    t = open(SRC, encoding="utf-8").read()
    return json.loads(t[t.index("= ") + 2:].rstrip().rstrip(";"))


def levels(d0, d1):
    out = {}
    for k, (la, lo) in LPTS.items():
        q = (f"https://historical-forecast-api.open-meteo.com/v1/forecast?latitude={la}&longitude={lo}&start_date={d0}&end_date={d1}"
             f"&hourly={','.join(VARS)}&models={','.join(LMODELS)}&timezone=Asia%2FMakassar&wind_speed_unit=kmh")
        with urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "mosaic-verify/1.0"}), timeout=180) as r:
            out[k] = json.loads(r.read().decode())["hourly"]
    return out


def env_for_day(h, day):
    idx = [i for i, t in enumerate(h["time"]) if t.startswith(day)]
    if len(idx) < 24:
        return None

    def mean_models(var):
        vals = []
        for m in LMODELS:
            a = h.get(f"{var}_{m}")
            if a:
                v = [a[i] for i in idx if a[i] is not None]
                if v:
                    vals.append(np.mean(v))
        return float(np.mean(vals)) if vals else None
    rh850, rh700, rh500, pw = (mean_models(v) for v in VARS[:4])
    cape = []
    for m in LMODELS:
        a = h.get(f"cape_{m}")
        if a:
            v = [a[i] for i in idx if a[i] is not None]
            if v:
                cape.append(max(v))
    cape = float(np.mean(cape)) if cape else None
    sx = sy = n = 0.0
    shear = []
    for m in LMODELS:
        s8, d8, s2, d2 = (h.get(f"{v}_{m}") for v in ("wind_speed_850hPa", "wind_direction_850hPa", "wind_speed_200hPa", "wind_direction_200hPa"))
        if not (s8 and d8 and s2 and d2):
            continue
        for i in idx:
            if None in (s8[i], d8[i], s2[i], d2[i]):
                continue
            r8, r2 = math.radians(d8[i]), math.radians(d2[i])
            sx += s8[i] * math.sin(r8); sy += s8[i] * math.cos(r8); n += 1
            shear.append(math.hypot(s2[i] * math.sin(r2) - s8[i] * math.sin(r8), s2[i] * math.cos(r2) - s8[i] * math.cos(r8)))
    wdir = (math.degrees(math.atan2(sx / n, sy / n)) + 360) % 360 if n else None
    mon = int(day[5:7]); dry_mon = 4 <= mon <= 10
    pro = con = 0
    for key, v in (("rh850", rh850), ("rh700", rh700), ("rh500", rh500), ("pw", pw)):
        if v is None:
            continue
        lo, hi = TH[key]
        if v >= hi: pro += 1
        elif v < lo: con += 1
    if cape is not None:
        if cape >= 1000: pro += 1
        elif cape < 250: con += 1
    if wdir is not None:
        if 225 <= wdir <= 315: pro += 1
        elif dry_mon and 45 <= wdir <= 180: con += 1
    if shear and float(np.mean(shear)) > 50:
        con += 1
    score = pro - con
    return {"score": score, "mode": "dry" if score <= -3 else ("wet" if score >= 2 else "neutral"), "pro": pro, "con": con}


def stats(o, f):
    o = np.array(o, bool); f = np.array(f, bool)
    h = int((o & f).sum()); mi = int((o & ~f).sum()); fa = int((~o & f).sum())
    return dict(h=h, mi=mi, fa=fa, pod=h / (h + mi) if h + mi else float("nan"), far=fa / (h + fa) if h + fa else float("nan"),
                csi=h / (h + mi + fa) if h + mi + fa else float("nan"), bias=(h + fa) / (h + mi) if h + mi else float("nan"))


def main():
    V = load(); n = V["n"]; start = dt.datetime.strptime(V["start"], "%Y-%m-%dT%H:00Z")
    models = V["models"]
    d0 = (start + dt.timedelta(hours=8)).date().isoformat(); d1 = (start + dt.timedelta(hours=3 * n + 8)).date().isoformat()
    print(f"jendela {n} ({d0} .. {d1}); mengambil arsip atmosfer Open-Meteo", flush=True)
    lv = levels(d0, d1)
    cache = {}
    rows = []
    for pid in [p["id"] for p in V["pts"]]:
        lp = LEVEL_PT[pid]
        for i in range(n):
            o = V["obs"][pid][i]
            if o is None:
                continue
            m = {k: V["fc"][pid][k]["0"][i] for k in models}
            if any(v is None for v in m.values()):
                continue
            day = (start + dt.timedelta(hours=3 * i + 8)).strftime("%Y-%m-%d")
            key = (lp, day)
            if key not in cache:
                cache[key] = env_for_day(lv[lp], day)
            e = cache[key]
            if e is None:
                continue
            rows.append((o, m, e["mode"], e["score"]))
    print(f"sampel {len(rows)}; mode atmosfer: " + ", ".join(f"{k}={sum(1 for r in rows if r[2] == k)}" for k in ("dry", "neutral", "wet")))
    for thr in (1, 5):
        print(f"\n=== peristiwa pengamatan >= {thr} mm/3 jam ===")
        for mode in ("dry", "neutral", "wet"):
            rr = [r for r in rows if r[2] == mode]
            if rr:
                ev = sum(1 for r in rr if r[0] >= thr)
                print(f"mode {mode:8s}: {len(rr):5d} jendela, hujan teramati {ev:4d} ({100 * ev / len(rr):.1f}%), rata² {np.mean([r[0] for r in rr]):.2f} mm/3j")
    obs = [r[0] for r in rows]
    thr = 1
    print(f"\n=== PERBANDINGAN (peristiwa >= {thr} mm/3 jam; hujan = >=0,5 mm model; lihat aturan di atas) ===")
    print(f"{'sumber':22s} {'CSI':>5s} {'POD':>5s} {'FAR':>5s} {'bias':>5s} {'alarm palsu':>11s} {'terlewat':>8s}")

    def rule_single(k, with_atm):
        out = []
        for o, m, mode, _ in rows:
            v = m[k]
            if with_atm and mode == "dry":
                out.append(v >= 5 or v >= 2)
            else:
                out.append(v >= 0.5)
        return out

    def rule_cons(with_atm):
        out = []
        for o, m, mode, _ in rows:
            vals = list(m.values()); votes = sum(v >= 1 for v in vals); mean = float(np.mean(vals))
            ok = votes >= 2
            if with_atm and mode == "dry":
                ok = ok and mean >= 2
            out.append(ok)
        return out
    for k in models:
        for atm in (False, True):
            s = stats([o >= thr for o in obs], rule_single(k, atm))
            print(f"{ {'ecmwf_ifs025':'ECMWF','gfs_seamless':'GFS','icon_seamless':'ICON','ecmwf_aifs025_single':'AIFS'}[k] + (' + atmosfer' if atm else ''):22s} {s['csi']:5.2f} {s['pod']:5.2f} {s['far']:5.2f} {s['bias']:5.2f} {s['fa']:11d} {s['mi']:8d}")
    for atm in (False, True):
        s = stats([o >= thr for o in obs], rule_cons(atm))
        print(f"{'Kesepakatan' + (' + atmosfer' if atm else ''):22s} {s['csi']:5.2f} {s['pod']:5.2f} {s['far']:5.2f} {s['bias']:5.2f} {s['fa']:11d} {s['mi']:8d}")


if __name__ == "__main__":
    sys.exit(main())
