# -*- coding: utf-8 -*-
"""
ingest_verif.py — data verifikasi otomatis: prakiraan model vs hujan pengamatan satelit, per jendela 3 jam (sama dengan slot produk) -> verifikasi.js

Pengamatan  : CMORPH V0.x ADJ, per jam, 0,25° (NOAA CPC, publik, tanpa akun, latensi ±1–2 jam)
              https://ftp.cpc.ncep.noaa.gov/precip/CMORPH_RT/ICDR/0.25deg-HLY/   (file jam H = hujan jam H:00–H:59 UTC, mm/jam)
Prakiraan   : Open-Meteo "previous runs" — prakiraan per lead time (hari 0 = run terbaru, hari-1, hari-2, hari-3 sebelumnya) untuk ECMWF, GFS, ICON, AIFS
Ensemble    : ens_archive.json (diisi ingest_openmeteo_ens.py tiap run) — peluang hujan gabungan per titik, dipasangkan per jendela & lead (hari)
Jendela     : 3 jam UTC kelipatan 3 (T, T+3j) = slot produk 02,05,08,...,23 WITA.  Obs = jumlah file T,T+1,T+2 ; prakiraan = nilai jam T+1..T+3
              (precipitation Open-Meteo = jumlah jam SEBELUMNYA).
Titik       : SEMUA kecamatan/bandara yang jatuh di piksel CMORPH berbeda (1 wakil per piksel; 6 titik lama diutamakan) —
              pengamatan satelit 0,25° (±28 km), BUKAN pos hujan resmi.

Penyimpanan inkremental (dipulihkan dari cabang `site` oleh workflow):
  verif_obs.json : hujan CMORPH per jam per titik — hanya jam/titik baru yang diunduh
  verif_fc.json  : prakiraan per jam per titik/model/lead — hanya ±5 hari terakhir yang diminta ulang (hemat kuota Open-Meteo)

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
import urllib.error
import urllib.request

import numpy as np

import config as C

BASE = "https://ftp.cpc.ncep.noaa.gov/precip/CMORPH_RT/ICDR/0.25deg-HLY"
FNAME = "CMORPH_V0.x_ADJ_0.25deg-HLY_{ts}.nc"
DAYS = int(os.environ.get("VERIF_DAYS", "45"))
MAX_NEW = int(os.environ.get("VERIF_MAX_NEW", "1300"))
WORKERS = int(os.environ.get("VERIF_WORKERS", "12"))
API_KEY = os.environ.get("OPENMETEO_API_KEY", "").strip()
PREV_API = ("https://customer-previous-runs-api.open-meteo.com/v1/forecast" if API_KEY
            else "https://previous-runs-api.open-meteo.com/v1/forecast")
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "ecmwf_aifs025_single"]
LEADS = [0, 1, 2, 3]
PREFERRED = ["bandara", "sape", "dompu", "lambu", "tambora", "wera"]    # titik lama — tetap jadi wakil pikselnya
FC_REFETCH_DAYS = 5          # prakiraan lead 0..3 untuk jam yang sudah lewat tidak berubah -> cukup minta ulang beberapa hari terakhir
UA = {"User-Agent": "mosaic-bima-dompu/1.0 (verifikasi; github.com/laksita0127/mosaic)"}
ROOT = C.PROJECT_DIR
OBS_STORE = os.path.join(ROOT, "verif_obs.json")
FC_STORE = os.path.join(ROOT, "verif_fc.json")
ENS_ARCHIVE = os.path.join(ROOT, "ens_archive.json")
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
        wait = 2 * (i + 1)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:      # Open-Meteo: 429 = kuota per menit/jam habis -> tunggu lebih lama
            body = e.read().decode("utf-8", "ignore")[:200]
            last = RuntimeError(f"HTTP {e.code} {body}")
            if e.code == 400:
                raise last
            if e.code == 429:
                if "daily" in body.lower():
                    raise RuntimeError("batas harian Open-Meteo habis: " + body)
                wait = 300 if "hourly" in body.lower() else 65
        except Exception as e:     # noqa
            last = e
        log(f"    ulang {i + 1}/{tries} dalam {wait} dtk ({str(last)[:120]})")
        time.sleep(wait)
    raise last


def listing():
    html = http(BASE + "/", 120).decode("utf-8", "ignore")
    return set(re.findall(r"HLY_(\d{10})\.nc", html))


def grid_of(ds):
    return np.asarray(ds["lat"][:]), np.asarray(ds["lon"][:])


def pix_of(lat, lon, la, lo):
    return int(np.argmin(np.abs(lat - la))), int(np.argmin(np.abs(lon - (lo % 360))))


def choose_points(lat, lon):
    """1 wakil per piksel CMORPH: titik lama diutamakan, lalu urutan STATION_POINTS."""
    st = {s[0]: s for s in C.STATION_POINTS}
    order = PREFERRED + [s[0] for s in C.STATION_POINTS if s[0] not in PREFERRED]
    used, pts = {}, {}
    for pid in order:
        s = st[pid]
        px = pix_of(lat, lon, s[2], s[3])
        if px in used:
            continue
        used[px] = pid
        pts[pid] = (s[2], s[3], s[1], px)
    return pts


def read_hour(ts, pix):
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


def load_json(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def load_store():
    return {int(k): v for k, v in load_json(OBS_STORE, {"hours": {}})["hours"].items()}


def save_store(obs):
    keep = max(obs) - 70 * 24 if obs else 0
    json.dump({"hours": {str(k): v for k, v in sorted(obs.items()) if k >= keep}}, open(OBS_STORE, "w", encoding="utf-8"), separators=(",", ":"))


def get_forecasts(pts, d0, d1, store):
    """store: {pid: {model: {lead: {time: value}}}} — dilengkapi dari Open-Meteo (hanya rentang yang perlu)."""
    vars_ = ",".join("precipitation" + ("" if L == 0 else f"_previous_day{L}") for L in LEADS)
    recent = (dt.date.fromisoformat(d1) - dt.timedelta(days=FC_REFETCH_DAYS)).isoformat()
    for pid, (la, lo, _n, _px) in pts.items():
        have = store.get(pid)
        start = max(d0, recent) if have else d0                # titik baru -> isi penuh; titik lama -> hanya beberapa hari terakhir
        q = (f"{PREV_API}?latitude={la}&longitude={lo}&hourly={vars_}&models={','.join(MODELS)}"
             f"&start_date={start}&end_date={d1}&timezone=UTC" + (f"&apikey={API_KEY}" if API_KEY else ""))
        j = json.loads(http(q, 180, tries=6).decode())
        h = j["hourly"]; times = h["time"]
        rec = store.setdefault(pid, {})
        for m in MODELS:
            for L in LEADS:
                arr = h.get(f"precipitation{'' if L == 0 else f'_previous_day{L}'}_{m}")
                if not arr:
                    continue
                ser = rec.setdefault(m, {}).setdefault(str(L), {})
                for t, v in zip(times, arr):
                    if v is not None:
                        ser[t] = v
        log(f"  prakiraan {pid} ok ({start}..{d1})")
        time.sleep(3)
    # pangkas jam di luar jendela
    cut = f"{d0}T00:00"
    for pid in store:
        for m in store[pid]:
            for L in store[pid][m]:
                store[pid][m][L] = {t: v for t, v in store[pid][m][L].items() if t >= cut}
    return store


def ens_series(wins, pids):
    """peluang gabungan >=1 mm per titik/lead/jendela dari ens_archive.json; run terbaru per (lead, jendela) dipakai."""
    arc = load_json(ENS_ARCHIVE, None)
    if not arc or not arc.get("issues"):
        return None, 0
    widx = {h: i for i, h in enumerate(wins)}
    out = {pid: {str(L): [None] * len(wins) for L in LEADS} for pid in pids}
    used = 0
    for issue, rec in sorted(arc["issues"].items()):                 # urut waktu -> run terbaru menimpa
        iss = dt.datetime.strptime(issue, "%Y-%m-%dT%H:%M:%SZ")
        iss_wita = (iss + dt.timedelta(hours=8)).date()
        s0 = dt.datetime.strptime(rec["step0"], "%Y-%m-%dT%H:%M")    # WITA
        for pid in pids:
            p = rec["pts"].get(pid)
            if not p:
                continue
            for k, v in enumerate(p["p1"]):
                if v is None:
                    continue
                st_wita = s0 + dt.timedelta(hours=3 * k)
                st_utc = st_wita - dt.timedelta(hours=8)
                if st_utc < iss:                                       # jendela sudah lewat saat run terbit -> bukan prakiraan
                    continue
                L = (st_wita.date() - iss_wita).days
                i = widx.get(hour_idx(st_utc))
                if i is None or L not in LEADS:
                    continue
                out[pid][str(L)][i] = v
        used += 1
    return out, used


def main():
    now = dt.datetime.utcnow()
    first_win = (now - dt.timedelta(days=DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    h_first = hour_idx(first_win)

    # ---------- titik: 1 per piksel CMORPH ----------
    import netCDF4
    avail = listing()
    sample_ts = max(avail)
    ds0 = netCDF4.Dataset("mem.nc", memory=http(f"{BASE}/{FNAME.format(ts=sample_ts)}"))
    lat, lon = grid_of(ds0); ds0.close()
    pts = choose_points(lat, lon)
    pix = {pid: v[3] for pid, v in pts.items()}
    PT_IDS = list(pts)
    log(f"{len(PT_IDS)} titik (piksel CMORPH unik): " + ", ".join(PT_IDS))

    # ---------- pengamatan (inkremental) ----------
    obs = load_store()
    log(f"toko pengamatan: {len(obs)} jam tersimpan")
    want = [h for h in range(h_first, hour_idx(now) + 1)
            if idx_dt(h).strftime("%Y%m%d%H") in avail and (h not in obs or any(pid not in obs[h] for pid in PT_IDS))]
    want = want[-MAX_NEW:] if len(want) > MAX_NEW else want
    log(f"perlu diunduh: {len(want)} jam")
    if want:
        done = 0
        with cf.ThreadPoolExecutor(WORKERS) as ex:
            futs = {ex.submit(read_hour, idx_dt(h).strftime("%Y%m%d%H"), pix): h for h in want}
            for f in cf.as_completed(futs):
                h = futs[f]
                try:
                    obs[h] = {**obs.get(h, {}), **f.result()}
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

    # ---------- prakiraan (inkremental) ----------
    log("mengambil arsip prakiraan Open-Meteo (previous runs)")
    d0 = idx_dt(wins[0]).date().isoformat(); d1 = idx_dt(wins[-1] + 4).date().isoformat()
    fc_store = load_json(FC_STORE, {})
    fc_store = {pid: v for pid, v in fc_store.items() if pid in pts}
    fc = get_forecasts(pts, d0, d1, fc_store)
    json.dump(fc, open(FC_STORE, "w", encoding="utf-8"), separators=(",", ":"))
    out_fc = {}
    for pid in PT_IDS:
        out_fc[pid] = {}
        for m in MODELS:
            out_fc[pid][m] = {}
            for L in LEADS:
                ser = fc.get(pid, {}).get(m, {}).get(str(L), {}); arr = []
                for h in wins:
                    v = [ser.get(idx_dt(h + k).strftime("%Y-%m-%dT%H:00")) for k in (1, 2, 3)]
                    arr.append(round(sum(v), 2) if all(x is not None for x in v) else None)
                out_fc[pid][m][str(L)] = arr

    ens, n_issues = ens_series(wins, PT_IDS)
    log(f"arsip ensemble: {n_issues} run" + ("" if ens else " (belum ada)"))

    payload = {
        "generated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
        "obs_src": "CMORPH V0.x ADJ per jam 0,25° (NOAA CPC) — estimasi satelit, bukan pos hujan",
        "fc_src": "Open-Meteo previous runs (prakiraan per lead time)",
        "start": idx_dt(wins[0]).strftime("%Y-%m-%dT%H:00Z"), "step_h": 3, "n": len(wins),
        "pts": [{"id": pid, "name": pts[pid][2], "lat": pts[pid][0], "lon": pts[pid][1]} for pid in PT_IDS],
        "models": MODELS, "leads": LEADS, "obs": obs3, "fc": out_fc,
        "ens": ens, "ens_issues": n_issues,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// dibuat otomatis oleh pipeline/ingest_verif.py - JANGAN diedit tangan" + chr(10))
        f.write("window.VERIF = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";" + chr(10))
    n_obs = sum(1 for v in obs3[PT_IDS[0]] if v is not None)
    log(f"tulis {OUT}: {len(wins)} jendela, {n_obs} dengan pengamatan, {len(PT_IDS)} titik, {os.path.getsize(OUT)/1e3:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
