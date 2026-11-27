# -*- coding: utf-8 -*-
"""
verify_petir.py — uji aturan "Hujan Petir" (CAPE + hujan deras) terhadap laporan petir SYNOP Bima (WMO 97270).

Prakiraan : arsip Open-Meteo historical-forecast (jam-jam awal tiap run ≈ lead 0) ECMWF IFS 0.25° & GFS, titik Bandara WADB:
            hujan per jam & CAPE. Aturan dihitung per slot 3 jam WITA (02,05,…,23) sama dengan tabel produk.
Pengamatan: synop_97270.json (pipeline/ingest_synop.py): ww 17/29/91–99 pada jam T+1..T+3 (slot) ; hari petir = ada ww petir
            ATAU W1 = 9 pada hari itu (WITA).
Catatan   : satu titik, kejadian sedikit -> hasil = petunjuk arah, bukan angka pasti.

    python pipeline/verify_petir.py
"""
import datetime as dt
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SYN = os.path.join(os.path.dirname(HERE), "synop_97270.json")
PT = (-8.5418, 118.6922)
MODELS = ["ecmwf_ifs025", "gfs_seamless"]
SLOTS = [2, 5, 8, 11, 14, 17, 20, 23]


def main():
    S = json.load(open(SYN, encoding="utf-8"))["hours"]
    keys = sorted(S)
    d0 = (dt.datetime.strptime(keys[0], "%Y-%m-%dT%H:%MZ") + dt.timedelta(days=1)).date()
    d1 = (dt.datetime.strptime(keys[-1], "%Y-%m-%dT%H:%MZ") - dt.timedelta(days=1)).date()
    q = (f"https://historical-forecast-api.open-meteo.com/v1/forecast?latitude={PT[0]}&longitude={PT[1]}&hourly=precipitation,cape"
         f"&models={','.join(MODELS)}&start_date={d0}&end_date={d1}&timezone=Asia%2FMakassar")
    h = json.loads(urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "mosaic-verify"}), timeout=180).read())["hourly"]
    idx = {t: i for i, t in enumerate(h["time"])}
    obs_hour = {}                                     # jam WITA -> petir (ww)
    day_ts = {}
    for k, v in S.items():
        w = dt.datetime.strptime(k, "%Y-%m-%dT%H:%MZ") + dt.timedelta(hours=8)
        obs_hour[w.strftime("%Y-%m-%dT%H:00")] = v.get("ts")
        if v.get("ts") or v.get("ts_past"):
            day_ts[w.date().isoformat()] = True
    rows = []                                         # (tanggal, slot, petir teramati, {model: (mm3j, capeMax)})
    d = d0
    while d <= d1:
        for sh in SLOTS:
            per, ok, obs, nobs = {}, True, False, 0
            for m in MODELS:
                s, c = 0.0, None
                for kk in (1, 2, 3):
                    t = dt.datetime(d.year, d.month, d.day, sh) + dt.timedelta(hours=kk)
                    i = idx.get(t.strftime("%Y-%m-%dT%H:00"))
                    if i is None or h[f"precipitation_{m}"][i] is None: ok = False; break
                    s += h[f"precipitation_{m}"][i]
                    cv = h[f"cape_{m}"][i]
                    if cv is not None: c = max(c or 0, cv)
                per[m] = (s, c)
            for kk in (1, 2, 3):
                t = (dt.datetime(d.year, d.month, d.day, sh) + dt.timedelta(hours=kk)).strftime("%Y-%m-%dT%H:00")
                if t in obs_hour:
                    nobs += 1; obs = obs or bool(obs_hour[t])
            if ok and nobs:
                rows.append((d.isoformat(), sh, obs, per))
        d += dt.timedelta(days=1)
    ev = sum(r[2] for r in rows)
    days = sorted(set(r[0] for r in rows)); evd = sum(1 for x in days if day_ts.get(x))
    print(f"periode {d0}..{d1}: {len(rows)} slot ({ev} slot petir), {len(days)} hari ({evd} hari petir)")

    def rule(per, cape_thr, mm_thr, how):
        caps = [c for (_s, c) in per.values() if c is not None]
        if not caps: return False
        cap = min(caps) if how == "min" else (max(caps) if how == "any" else per["gfs_seamless"][1] or 0)
        return cap >= cape_thr and max(s for (s, _c) in per.values()) >= mm_thr

    def score(fc_slot):
        h_ = sum(1 for r, f in zip(rows, fc_slot) if r[2] and f); mi = ev - h_; fa = sum(1 for r, f in zip(rows, fc_slot) if f and not r[2])
        byday = {}
        for r, f in zip(rows, fc_slot): byday[r[0]] = byday.get(r[0], False) or f
        hd = sum(1 for x in days if byday[x] and day_ts.get(x)); fd = sum(1 for x in days if byday[x] and not day_ts.get(x))
        md = evd - hd
        return (h_, mi, fa, hd, md, fd, sum(fc_slot))

    print(f"\n{'aturan':38s} {'slot T/L/AP':>12s} {'POD':>5s} {'CSI':>5s} | {'hari T/L/AP':>12s} {'POD':>5s} {'FAR':>5s} {'CSI':>5s} | slot ditandai")
    for how in ("min", "any", "gfs"):
        for cape in (1000, 1500, 2000):
            for mm in (1, 3, 5):
                h_, mi, fa, hd, md, fd, n = score([rule(r[3], cape, mm, how) for r in rows])
                csi = h_ / (h_ + mi + fa) if h_ + mi + fa else 0
                csid = hd / (hd + md + fd) if hd + md + fd else 0
                tag = " <- aplikasi" if (how, cape, mm) == ("min", 1500, 3) else ""
                print(f"CAPE {how:3s}>={cape:4d}, hujan>={mm} mm/3j{'':10s} {h_:3d}/{mi:3d}/{fa:4d} {h_/ev if ev else 0:5.2f} {csi:5.2f} | "
                      f"{hd:3d}/{md:3d}/{fd:4d} {hd/evd if evd else 0:5.2f} {fd/(hd+fd) if hd+fd else 0:5.2f} {csid:5.2f} | {n}{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
