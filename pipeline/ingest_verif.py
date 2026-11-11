# -*- coding: utf-8 -*-
"""
ingest_verif.py — data verifikasi otomatis: prakiraan model vs hujan pengamatan satelit, per jendela 3 jam (sama dengan slot produk) -> verifikasi.js

Pengamatan  : CMORPH V0.x ADJ, per jam, 0,25° (NOAA CPC, publik, tanpa akun, latensi ±1–2 jam)
              https://ftp.cpc.ncep.noaa.gov/precip/CMORPH_RT/ICDR/0.25deg-HLY/   (file jam H = hujan jam H:00–H:59 UTC, mm/jam)
Prakiraan   : Open-Meteo "previous runs" — prakiraan per lead time (hari 0 = run terbaru, hari-1, hari-2, hari-3 sebelumnya) untuk ECMWF, GFS, ICON, AIFS
Jendela     : 3 jam UTC kelipatan 3 (T, T+3j) = slot produk 02,05,08,...,23 WITA.  Obs = jumlah file T,T+1,T+2 ; prakiraan = nilai jam T+1..T+3
              (precipitation Open-Meteo = jumlah jam SEBELUMNYA).
Titik       : 6 titik berpiksel CMORPH berbeda (nearest-pixel) — pengamatan satelit 0,25° (±28 km), BUKAN pos hujan resmi.

Penyimpanan inkremental: verif_obs.json (hujan per jam per titik) dipulihkan dari cabang `site`, hanya jam baru yang diunduh.

    python pipeline/ingest_verif.py            # jendela 45 hari
    VERIF_DAYS=6 python pipeline/ingest_verif.py   # uji cepat
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

import numpy as np

import config as C

BASE = "https://ftp.cpc.ncep.noaa.gov/precip/CMORPH_RT/ICDR/0.25deg-HLY"
FNAME = "CMORPH_V0.x_ADJ_0.25deg-HLY_{ts}.nc"
DAYS = int(os.environ.get("VERIF_DAYS", "45"))
MAX_NEW = int(os.environ.get("VERIF_MAX_NEW", "1300"))
WORKERS = int(os.environ.get("VERIF_WORKERS", "12"))
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "ecmwf_aifs025_single"]
LEADS = [0, 1, 2, 3]
PT_IDS = ["bandara", "sape", "dompu", "lambu", "tambora", "wera"]
UA = {"User-Agent": "mosaic-bima-dompu/1.0 (verifikasi; github.com/laksita0127/mosaic)"}
ROOT = C.PROJECT_DIR
OBS_STORE = os.path.join(ROOT, "verif_obs.json")
OUT = os.path.join(ROOT, "verifikasi.js")
EPOCH = dt.datetime(1970, 1, 1)


def hour_idx(d):               # datetime UTC naif -> jam sejak epoch
    return int((d - EPOCH).total_seconds() // 3600)


def idx_dt(h):
    return EPOCH + dt.timedelta(hours=h)


def log(m):
    print(f"[{dt.datetime.utcnow():%H:%M:%S}Z] {m}", flush=True)


def http(url, timeout=90, tries=4):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:     # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise last


def listing():
    html = http(BASE + "/", 120).decode("utf-8", "ignore")
    return set(re.findall(r"HLY_(\d{10})\.nc", html))


def pixel_index(ds, pts):
    lat = ds["lat"][:]; lon = ds["lon"][:]
    out = {}
    for pid, (la, lo) in pts.items():
        out[pid] = (int(np.argmin(np.abs(lat - la))), int(np.argmin(np.abs(lon - (lo % 360)))))
    return out


def read_hour(ts, pts, pix):
    import netCDF4
    data = http(f"{BASE}/{FNAME.format(ts=ts)}")
    ds = netCDF4.Dataset("mem.nc", memory=data)
    try:
        a = np.ma.filled(ds["cmorph"][0], np.nan)
        res = {}
        for pid, (i, j) in pix.items():
            v = float(a[i, j]); res[pid] = None if (np.isnan(v) or v < 0 or v > 400) else round(v, 2)
        return res
    finally:
        ds.close()


def load_store():
    try:
        return {int(k): v for k, v in json.load(open(OBS_STORE, encoding="utf-8"))["hours"].items()}
    except Exception:
        return {}


def save_store(obs):
    keep = max(obs) - 70 * 24 if obs else 0
    json.dump({"hours": {str(k): v for k, v in sorted(obs.items()) if k >= keep}}, open(OBS_STORE, "w", encoding="utf-8"), separators=(",", ":"))


def get_forecasts(pts, d0, d1):
    """-> {pid: {model: {lead: {time_str: value}}}}"""
    out = {}
    for pid, (la, lo) in pts.items():
        vars_ = ",".join("precipitation" + ("" if L == 0 else f"_previous_day{L}") for L in LEADS)
        q = (f"https://previous-runs-api.open-meteo.com/v1/forecast?latitude={la}&longitude={lo}&hourly={vars_}&models={','.join(MODELS)}"
             f"&start_date={d0}&end_date={d1}&timezone=UTC")
        j = json.loads(http(q, 180).decode())
        h = j["hourly"]; times = h["time"]; res = {}
        for m in MODELS:
            res[m] = {}
            for L in LEADS:
                arr = h.get(f"precipitation{'' if L == 0 else f'_previous_day{L}'}_{m}")
                res[m][L] = dict(zip(times, arr)) if arr else {}
        out[pid] = res
        log(f"  prakiraan {pid} ok")
        time.sleep(3)
    return out


def main():
    stations = {s[0]: (s[2], s[3], s[1]) for s in C.STATION_POINTS}
    pts = {pid: (stations[pid][0], stations[pid][1]) for pid in PT_IDS}
    now = dt.datetime.utcnow()
    first_win = (now - dt.timedelta(days=DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    h_first = hour_idx(first_win)

    # ---------- pengamatan (inkremental) ----------
    obs = load_store()
    log(f"toko pengamatan: {len(obs)} jam tersimpan")
    avail = listing()
    want = [h for h in range(h_first, hour_idx(now) + 1) if h not in obs and idx_dt(h).strftime("%Y%m%d%H") in avail]
    want = want[-MAX_NEW:] if len(want) > MAX_NEW else want
    log(f"perlu diunduh: {len(want)} jam")
    pix = None
    if want:
        import netCDF4
        first = http(f"{BASE}/{FNAME.format(ts=idx_dt(want[0]).strftime('%Y%m%d%H'))}")
        ds0 = netCDF4.Dataset("mem.nc", memory=first)
        pix = pixel_index(ds0, pts); ds0.close()
        log("piksel: " + ", ".join(f"{k}={v}" for k, v in pix.items()))
        if len(set(pix.values())) < len(pix):
            log("PERINGATAN: ada titik berpiksel sama")
        done = 0
        with cf.ThreadPoolExecutor(WORKERS) as ex:
            futs = {ex.submit(read_hour, idx_dt(h).strftime("%Y%m%d%H"), pts, pix): h for h in want}
            for f in cf.as_completed(futs):
                h = futs[f]
                try:
                    obs[h] = f.result()
                except Exception as e:      # noqa
                    log(f"  gagal jam {idx_dt(h):%Y-%m-%d %H}: {str(e)[:60]}")
                done += 1
                if done % 100 == 0:
                    log(f"  {done}/{len(want)}")
        save_store(obs)
    if not obs:
        log("tidak ada data pengamatan"); return 1

    # ---------- jendela 3 jam ----------
    last_obs_h = max(obs)
    wins = [h for h in range(h_first - h_first % 3, last_obs_h - 1) if h % 3 == 0]         # h = awal jendela (UTC, kelipatan 3)
    wins = [h for h in wins if h >= h_first]
    obs3 = {pid: [] for pid in PT_IDS}
    for h in wins:
        for pid in PT_IDS:
            v = [obs.get(h + k, {}).get(pid) for k in range(3)]
            obs3[pid].append(round(sum(v), 2) if all(x is not None for x in v) else None)

    # ---------- prakiraan ----------
    log("mengambil arsip prakiraan Open-Meteo (previous runs)")
    d0 = idx_dt(wins[0]).date().isoformat(); d1 = idx_dt(wins[-1] + 4).date().isoformat()
    fc = get_forecasts(pts, d0, d1)
    out_fc = {}
    for pid in PT_IDS:
        out_fc[pid] = {}
        for m in MODELS:
            out_fc[pid][m] = {}
            for L in LEADS:
                ser = fc[pid][m][L]; arr = []
                for h in wins:
                    v = [ser.get(idx_dt(h + k).strftime("%Y-%m-%dT%H:00")) for k in (1, 2, 3)]
                    arr.append(round(sum(v), 2) if all(x is not None for x in v) else None)
                out_fc[pid][m][str(L)] = arr

    payload = {
        "generated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
        "obs_src": "CMORPH V0.x ADJ per jam 0,25° (NOAA CPC) — estimasi satelit, bukan pos hujan",
        "fc_src": "Open-Meteo previous runs (prakiraan per lead time)",
        "start": idx_dt(wins[0]).strftime("%Y-%m-%dT%H:00Z"), "step_h": 3, "n": len(wins),
        "pts": [{"id": pid, "name": stations[pid][2], "lat": pts[pid][0], "lon": pts[pid][1]} for pid in PT_IDS],
        "models": MODELS, "leads": LEADS, "obs": obs3, "fc": out_fc,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// dibuat otomatis oleh pipeline/ingest_verif.py - JANGAN diedit tangan" + chr(10))
        f.write("window.VERIF = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";" + chr(10))
    n_obs = sum(1 for v in obs3[PT_IDS[0]] if v is not None)
    log(f"tulis {OUT}: {len(wins)} jendela, {n_obs} dengan pengamatan, {os.path.getsize(OUT)/1e3:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
