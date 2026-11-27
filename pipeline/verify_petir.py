# -*- coding: utf-8 -*-
"""
verify_petir.py — uji aturan "Hujan Petir" terhadap laporan petir SYNOP (ww 17/29/91–99) di Bima + stasiun tetangga beriklim serupa
(Denpasar, Sumbawa Besar, Maumere, Waingapu, Kupang) supaya sampel cukup.

Prakiraan : arsip Open-Meteo historical-forecast (jam-jam awal tiap run ≈ lead 0) ECMWF IFS 0.25° & GFS di titik tiap stasiun:
            hujan per jam, CAPE, lifted index (GFS). Aturan dihitung per slot 3 jam waktu setempat (WITA) seperti tabel produk.
Pengamatan: synop_<wmo>.json (pipeline/ingest_synop.py). Slot petir = ada ww petir pada jam T+1..T+3; hari petir = ada ww petir
            atau W1 = 9 pada hari itu.
Skor      : per slot & per hari (T/L/AP = tepat/terlewat/alarm palsu), gabungan semua stasiun + rincian Bima.

    python pipeline/verify_petir.py
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from ingest_synop import ALL  # noqa: E402

MODELS = ["ecmwf_ifs025", "gfs_seamless"]
SLOTS = [2, 5, 8, 11, 14, 17, 20, 23]


def load_station(st):
    try:
        S = json.load(open(os.path.join(ROOT, f"synop_{st}.json"), encoding="utf-8"))["hours"]
    except Exception:
        return None
    if not S: return None
    keys = sorted(S)
    d0 = (dt.datetime.strptime(keys[0], "%Y-%m-%dT%H:%MZ") + dt.timedelta(days=1)).date()
    d1 = (dt.datetime.strptime(keys[-1], "%Y-%m-%dT%H:%MZ") - dt.timedelta(days=1)).date()
    lat, lon = ALL[st][1], ALL[st][2]
    q = (f"https://historical-forecast-api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
         f"&hourly=precipitation,cape,lifted_index&models={','.join(MODELS)}&start_date={d0}&end_date={d1}&timezone=Asia%2FMakassar")
    h = json.loads(urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "mosaic-verify"}), timeout=180).read())["hourly"]
    idx = {t: i for i, t in enumerate(h["time"])}
    obs, day_ts = {}, {}
    for k, v in S.items():
        w = dt.datetime.strptime(k, "%Y-%m-%dT%H:%MZ") + dt.timedelta(hours=8)
        obs[w.strftime("%Y-%m-%dT%H:00")] = bool(v.get("ts"))
        if v.get("ts") or v.get("ts_past"): day_ts[w.date().isoformat()] = True
    rows = []
    d = d0
    while d <= d1:
        for sh in SLOTS:
            per, ok = {}, True
            for m in MODELS:
                s, c, li = 0.0, None, None
                for kk in (1, 2, 3):
                    i = idx.get((dt.datetime(d.year, d.month, d.day, sh) + dt.timedelta(hours=kk)).strftime("%Y-%m-%dT%H:00"))
                    if i is None or h[f"precipitation_{m}"][i] is None: ok = False; break
                    s += h[f"precipitation_{m}"][i]
                    cv = h.get(f"cape_{m}", [None] * len(h["time"]))[i]
                    if cv is not None: c = max(c or 0, cv)
                    lv = (h.get(f"lifted_index_{m}") or [None] * len(h["time"]))[i]
                    if lv is not None: li = lv if li is None else min(li, lv)
                per[m] = (s, c, li)
            hrs = [(dt.datetime(d.year, d.month, d.day, sh) + dt.timedelta(hours=kk)).strftime("%Y-%m-%dT%H:00") for kk in (1, 2, 3)]
            seen = [obs[t] for t in hrs if t in obs]
            if ok and seen:
                rows.append({"st": st, "day": d.isoformat(), "sh": sh, "obs": any(seen), "per": per, "dts": bool(day_ts.get(d.isoformat()))})
        d += dt.timedelta(days=1)
    return rows


def main():
    rows = []
    for st in ALL:
        r = load_station(st)
        if r:
            rows += r
            print(f"{st} {ALL[st][0]:14s}: {len(r)} slot, {sum(x['obs'] for x in r)} slot petir, "
                  f"{len(set(x['day'] for x in r if x['dts']))} hari petir")
        time.sleep(2)

    def rule(r, cape, mm, slots=None, li=None):
        if slots and r["sh"] not in slots: return False
        caps = [c for (_s, c, _l) in r["per"].values() if c is not None]
        if not caps or min(caps) < cape: return False
        if max(s for (s, _c, _l) in r["per"].values()) < mm: return False
        if li is not None:
            lis = [l for (_s, _c, l) in r["per"].values() if l is not None]
            if not lis or min(lis) > li: return False
        return True

    def score(sub, f):
        h = sum(1 for r in sub if r["obs"] and f(r)); mi = sum(1 for r in sub if r["obs"]) - h; fa = sum(1 for r in sub if f(r) and not r["obs"])
        days = {}
        for r in sub:
            k = (r["st"], r["day"]); a = days.setdefault(k, [False, r["dts"]]); a[0] = a[0] or f(r)
        hd = sum(1 for a in days.values() if a[0] and a[1]); md = sum(1 for a in days.values() if a[1]) - hd; fd = sum(1 for a in days.values() if a[0] and not a[1])
        cs = h / (h + mi + fa) if h + mi + fa else 0; cd = hd / (hd + md + fd) if hd + md + fd else 0
        return f"slot {h:3d}/{mi:3d}/{fa:4d} CSI {cs:.2f} | hari {hd:3d}/{md:3d}/{fd:4d} POD {hd/(hd+md) if hd+md else 0:.2f} FAR {fd/(hd+fd) if hd+fd else 0:.2f} CSI {cd:.2f}"

    AFT = [11, 14, 17]
    print(f"\nGABUNGAN {len(set(r['st'] for r in rows))} stasiun — {sum(r['obs'] for r in rows)} slot petir")
    cases = []
    for cape in (500, 1000, 1500):
        for mm in (1, 2, 3, 5):
            for sl in (None, AFT):
                cases.append((f"CAPE>={cape:4d} hujan>={mm} {'siang' if sl else 'semua'}", dict(cape=cape, mm=mm, slots=sl)))
    for li in (-1, -2, -3):
        for mm in (1, 3):
            cases.append((f"CAPE>=500 hujan>={mm} LI<={li} siang", dict(cape=500, mm=mm, slots=AFT, li=li)))
    for name, kw in cases:
        tag = "  <- aplikasi" if kw == dict(cape=1000, mm=2, slots=AFT) else ""
        print(f"{name:34s} {score(rows, lambda r, kw=kw: rule(r, **kw))}{tag}")
    print("\nrincian per stasiun, aturan aplikasi (CAPE>=1000, hujan>=3, siang):")
    for st in ALL:
        sub = [r for r in rows if r["st"] == st]
        if sub: print(f"  {ALL[st][0]:14s} {score(sub, lambda r: rule(r, 1000, 2, AFT))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
