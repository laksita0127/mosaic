# -*- coding: utf-8 -*-
"""
ingest_ecmwf_ens.py
===================

Ambil ECMWF IFS ENS (51 anggota, GRATIS, lisensi CC-BY-4.0) dari ECMWF Open Data,
ekstrak ke 32 titik kecamatan/bandara Bima-Dompu, hitung produk probabilistik per
3 jam (H+0..H+7), lalu tulis ke ../ecmwf_ens.js supaya dibaca oleh
prakiraan-wilayah-bima-dompu-peta.html.

Kenapa perlu pipeline (bukan langsung dari browser):
  - Open-Meteo hanya mengembalikan 1 control run ECMWF, bukan 51 anggota asli.
  - ECMWF Open Data menyajikan ENS penuh gratis, tapi dalam bentuk file GRIB2
    yang harus di-decode di sisi server (cfgrib/eccodes), tidak bisa di browser.
  - Jadi: satu job terjadwal per siklus run -> decode -> ekstrak titik ->
    tulis file JS kecil -> browser tinggal baca.

Pemakaian:
    python ingest_ecmwf_ens.py                 # run terbaru, semua default
    python ingest_ecmwf_ens.py --max-members 20
    python ingest_ecmwf_ens.py --source ecmwf
    python ingest_ecmwf_ens.py --run 20260902/00
    python ingest_ecmwf_ens.py --mock          # data sintetis, tanpa unduh
    python ingest_ecmwf_ens.py --selftest      # unduh mini, cek rantai jalan

Keluaran: ../ecmwf_ens.js  ->  window.ECMWF_ENS_DATA = {...}
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import time

import numpy as np

import config as C

WITA = dt.timezone(dt.timedelta(hours=C.TZ_OFFSET_HOURS))
UTC = dt.timezone.utc

# batas waktu per unduhan parameter (detik); 0 = tanpa batas. Diisi dari --dl-timeout.
DL_TIMEOUT = 0


class DownloadTimeout(Exception):
    pass


def _run_with_timeout(seconds, fn, *args, **kwargs):
    """Jalankan fn dengan batas waktu (POSIX/SIGALRM). Di Windows: tanpa batas."""
    import signal
    if not seconds or not hasattr(signal, "SIGALRM"):
        return fn(*args, **kwargs)

    def _handler(signum, frame):
        raise DownloadTimeout(f"unduhan lewat {seconds} detik")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(int(seconds))
    try:
        return fn(*args, **kwargs)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


# ---------------------------------------------------------------------------
# util
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[{dt.datetime.now(WITA):%H:%M:%S}] {msg}", flush=True)


def kmh(ms: float) -> float:
    return ms * 3.6


def wind_speed_dir(u: float, v: float):
    """u,v (m/s) -> (speed km/h, direction FROM in deg, met convention)."""
    spd = math.hypot(u, v)
    d = (270.0 - math.degrees(math.atan2(v, u))) % 360.0
    return kmh(spd), d


def circular_mean_deg(degs) -> float:
    degs = [d for d in degs if d is not None and not math.isnan(d)]
    if not degs:
        return float("nan")
    s = sum(math.sin(math.radians(d)) for d in degs)
    c = sum(math.cos(math.radians(d)) for d in degs)
    return math.degrees(math.atan2(s, c)) % 360.0


def pct(values, p):
    arr = np.asarray([x for x in values if x is not None and not np.isnan(x)], dtype=float)
    if arr.size == 0:
        return None
    return float(np.percentile(arr, p))


def r1(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 1)


# ---------------------------------------------------------------------------
# langkah waktu lokal (harus cocok dengan grid HTML & tabel produk BMKG:
# jam 2,5,8,11,14,17,20,23 WITA)
# ---------------------------------------------------------------------------
def build_local_steps(run_utc: dt.datetime, horizon_h: int):
    """
    Daftar datetime WITA pada jam 2,5,8,...,23 (kelipatan 3, offset 2),
    yang jendela 3-jamnya ([T, T+3h)) berada dalam [run, run+horizon].
    """
    start_local = (run_utc.astimezone(WITA)).replace(minute=0, second=0, microsecond=0)
    # maju ke slot berikutnya yang jam-nya 2,5,8,...,23
    while start_local.hour % 3 != 2:
        start_local += dt.timedelta(hours=1)
    steps = []
    t = start_local
    end_utc = run_utc + dt.timedelta(hours=horizon_h)
    while t.astimezone(UTC) + dt.timedelta(hours=3) <= end_utc + dt.timedelta(seconds=1):
        steps.append(t)
        t += dt.timedelta(hours=3)
    return steps


def fmt_step(t_local: dt.datetime) -> str:
    # samakan dengan HTML: "YYYY-MM-DDTHH:00"
    return t_local.strftime("%Y-%m-%dT%H:00")


# ---------------------------------------------------------------------------
# interpolasi deret waktu
# ---------------------------------------------------------------------------
def interp_instant(valid_utc_list, series, t_utc):
    """Interpolasi linier nilai sesaat (suhu, komponen angin) pada t_utc."""
    if t_utc <= valid_utc_list[0] or t_utc >= valid_utc_list[-1]:
        if t_utc == valid_utc_list[0]:
            return series[0]
        if t_utc == valid_utc_list[-1]:
            return series[-1]
        return None
    for i in range(1, len(valid_utc_list)):
        if valid_utc_list[i] >= t_utc:
            t0, t1 = valid_utc_list[i - 1], valid_utc_list[i]
            y0, y1 = series[i - 1], series[i]
            if y0 is None or y1 is None:
                return None
            f = (t_utc - t0) / (t1 - t0)
            return y0 + (y1 - y0) * f
    return None


def precip_window_mm(valid_utc_list, tp_accum_m, t_start_utc, t_end_utc):
    """
    Curah hujan (mm) pada jendela [t_start, t_end) dari tp akumulatif (meter).
    Tiap interval native (3 atau 6 jam) dianggap laju hujan seragam, lalu
    diintegralkan pada jendela lokal -> bucket 3-jam yang selaras grid HTML.
    """
    total = 0.0
    covered = 0.0
    win = (t_end_utc - t_start_utc).total_seconds()
    for i in range(1, len(valid_utc_list)):
        a, b = valid_utc_list[i - 1], valid_utc_list[i]
        if tp_accum_m[i] is None or tp_accum_m[i - 1] is None:
            continue
        dur = (b - a).total_seconds()
        if dur <= 0:
            continue
        incr_mm = max(0.0, (tp_accum_m[i] - tp_accum_m[i - 1])) * 1000.0
        rate = incr_mm / dur  # mm per detik
        ov = (min(b, t_end_utc) - max(a, t_start_utc)).total_seconds()
        if ov > 0:
            total += rate * ov
            covered += ov
    # butuh jendela tertutup penuh oleh data model
    if covered < win - 1.0:
        return None
    return total


# ---------------------------------------------------------------------------
# unduh + decode GRIB
# ---------------------------------------------------------------------------
def download_param(client, run_kwargs, param, members, add_control, cache_dir):
    """Unduh 1 param (semua member+step) -> path file GRIB perturbed & control."""
    from ecmwf.opendata import Client  # noqa

    os.makedirs(cache_dir, exist_ok=True)
    pf_path = os.path.join(cache_dir, f"{param}_pf.grib2")
    cf_path = os.path.join(cache_dir, f"{param}_cf.grib2")

    common = dict(stream="enfo", param=param, step=C.STEP_HOURS, **run_kwargs)

    for attempt in range(1, 4):
        try:
            if not (os.path.exists(pf_path) and os.path.getsize(pf_path) > 0):
                log(f"  unduh {param} pf ({len(members)} member) [coba {attempt}]"
                    + (f", batas {DL_TIMEOUT}s" if DL_TIMEOUT else ""))
                _run_with_timeout(DL_TIMEOUT, client.retrieve,
                                  type="pf", number=members, target=pf_path, **common)
            break
        except DownloadTimeout as e:
            log(f"  !! {param} pf timeout ({e}) - server ECMWF membatasi laju")
            if os.path.exists(pf_path):
                os.remove(pf_path)
            raise
        except Exception as e:  # noqa
            log(f"  gagal {param} pf: {str(e)[:160]}")
            if os.path.exists(pf_path):
                os.remove(pf_path)
            if attempt == 3:
                raise
            time.sleep(5 * attempt)

    cf_ok = False
    if add_control:
        for attempt in range(1, 3):
            try:
                if not (os.path.exists(cf_path) and os.path.getsize(cf_path) > 0):
                    log(f"  unduh {param} cf (control) [coba {attempt}]")
                    client.retrieve(type="cf", target=cf_path, **common)
                cf_ok = True
                break
            except Exception as e:  # noqa
                log(f"  info: control {param} tidak tersedia ({str(e)[:100]}) - lanjut tanpa cf")
                if os.path.exists(cf_path):
                    os.remove(cf_path)
                break
    return pf_path, (cf_path if cf_ok else None)


def _bbox_slice(lat_grid, lon_grid, lats, lons, pad=0.4):
    """Index slice grid global yang menutupi semua titik + margin (jamin bracket)."""
    la_lo, la_hi = min(lats) - pad, max(lats) + pad
    lo_lo, lo_hi = min(lons) - pad, max(lons) + pad
    li = np.where((lat_grid >= la_lo) & (lat_grid <= la_hi))[0]
    lj = np.where((lon_grid >= lo_lo) & (lon_grid <= lo_hi))[0]
    if li.size < 2 or lj.size < 2:
        raise RuntimeError("titik di luar cakupan grid model")
    return slice(int(li.min()), int(li.max()) + 1), slice(int(lj.min()), int(lj.max()) + 1)


def _bilinear(block, sub_lat, sub_lon, lat, lon):
    """
    block: array (..., nlat, nlon), sub_lat MENURUN (90..-90), sub_lon MENAIK.
    return: array (...,) hasil interpolasi bilinear di (lat, lon).
    """
    a = int(np.clip(np.searchsorted(-sub_lat, -lat) - 1, 0, len(sub_lat) - 2))
    b = int(np.clip(np.searchsorted(sub_lon, lon) - 1, 0, len(sub_lon) - 2))
    la0, la1 = sub_lat[a], sub_lat[a + 1]
    lo0, lo1 = sub_lon[b], sub_lon[b + 1]
    wy = 0.0 if la1 == la0 else (lat - la0) / (la1 - la0)
    wx = 0.0 if lo1 == lo0 else (lon - lo0) / (lo1 - lo0)
    v00 = block[..., a, b]
    v01 = block[..., a, b + 1]
    v10 = block[..., a + 1, b]
    v11 = block[..., a + 1, b + 1]
    return (v00 * (1 - wy) * (1 - wx) + v01 * (1 - wy) * wx
            + v10 * wy * (1 - wx) + v11 * wy * wx)


def load_param_grid(path, lats, lons):
    """
    Buka 1 file GRIB param (semua member+step), potong ke kotak Bima-Dompu,
    interpolasi bilinear ke tiap titik.
    return: (valid_utc_list, dict member_id -> array(nstep, npoint))
    """
    import xarray as xr

    ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    name = list(ds.data_vars)[0]
    da = ds[name]
    lat_grid = np.asarray(da["latitude"].values)
    lon_grid = np.asarray(da["longitude"].values)
    sl_lat, sl_lon = _bbox_slice(lat_grid, lon_grid, lats, lons)
    da = da.isel(latitude=sl_lat, longitude=sl_lon).load()
    sub_lat = np.asarray(da["latitude"].values)
    sub_lon = np.asarray(da["longitude"].values)

    if "valid_time" in da.coords:
        vt = np.atleast_1d(da["valid_time"].values)
    else:
        vt = np.atleast_1d(np.asarray(da["time"].values) + np.asarray(da["step"].values))
    vt_utc = [dt.datetime.utcfromtimestamp(int(np.datetime64(x, "s").astype("int64"))).replace(tzinfo=UTC)
              for x in vt]

    vals = np.asarray(da.values, dtype=float)
    dims = list(da.dims)
    # normalkan ke (number, step, nlat, nlon)
    if "number" in dims:
        vals = np.moveaxis(vals, dims.index("number"), 0)
        numbers = [int(n) for n in np.atleast_1d(da["number"].values)]
    else:
        vals = vals[None, ...]
        numbers = [0]
    if vals.ndim == 3:            # (number, nlat, nlon) -> sisipkan sumbu step
        vals = vals[:, None, :, :]
    nstep = vals.shape[1]

    out = {}
    for ni, num in enumerate(numbers):
        arr = np.empty((nstep, len(lats)), dtype=float)
        for pi, (la, lo) in enumerate(zip(lats, lons)):
            arr[:, pi] = _bilinear(vals[ni], sub_lat, sub_lon, la, lo)
        out[num] = arr
    return vt_utc, out


# ---------------------------------------------------------------------------
# inti: bangun struktur data per titik
# ---------------------------------------------------------------------------
def collect_members(run_kwargs, members, add_control, source, cache_dir, keep_grib):
    from ecmwf.opendata import Client

    client = Client(source=source)
    lats = [s[2] for s in C.ALL_POINTS]
    lons = [s[3] for s in C.ALL_POINTS]

    per_param = {}
    valid_ref = None
    for param in C.PARAMS:
        log(f"parameter {param}")
        try:
            pf_path, cf_path = download_param(client, run_kwargs, param, members, add_control, cache_dir)
            vt, mdata = load_param_grid(pf_path, lats, lons)   # member 1..50
            if cf_path:
                try:
                    _vt_cf, cf_map = load_param_grid(cf_path, lats, lons)
                    mdata[0] = cf_map[0]                       # control -> member 0
                except Exception as e:  # noqa
                    log(f"  info: gagal decode control {param}: {str(e)[:120]}")
            per_param[param] = {mid: (vt, arr) for mid, arr in mdata.items()}
            valid_ref = valid_ref or vt
            if not keep_grib:
                for p in (pf_path, cf_path):
                    if p and os.path.exists(p):
                        os.remove(p)
            log(f"  {param}: {len(mdata)} member terkumpul, {len(vt)} langkah native")
        except Exception as e:  # noqa
            log(f"  !! parameter {param} GAGAL total ({str(e)[:160]}) - dilewati")

    if "tp" not in per_param:
        raise RuntimeError("parameter 'tp' (curah hujan) wajib ada tapi gagal diunduh - batalkan")
    return per_param, valid_ref


def build_payload(per_param, run_utc, horizon_h):
    steps_local = build_local_steps(run_utc, horizon_h)
    step_strs = [fmt_step(t) for t in steps_local]
    nstep = len(steps_local)

    have_temp = "2t" in per_param
    have_wind = "10u" in per_param and "10v" in per_param

    # id member gabungan (irisan param yang tersedia)
    avail = [per_param["tp"]]
    if have_temp:
        avail.append(per_param["2t"])
    if have_wind:
        avail += [per_param["10u"], per_param["10v"]]
    member_ids = sorted(set.intersection(*[set(d.keys()) for d in avail]))
    n_members = len(member_ids)

    points_out = {}
    for pi, (sid, sname, slat, slon) in enumerate(C.ALL_POINTS):
        is_named = sid in C.STATION_IDS
        # ---- curah hujan 3-jam per member ----
        precip_members = []  # [member][step]
        for mid in member_ids:
            vt, arr = per_param["tp"][mid]
            tp_series = [float(arr[k, pi]) if k < arr.shape[0] else None for k in range(len(vt))]
            row = []
            for t in steps_local:
                ts = t.astimezone(UTC)
                mm = precip_window_mm(vt, tp_series, ts, ts + dt.timedelta(hours=3))
                row.append(None if mm is None else max(0.0, mm))
            precip_members.append(row)

        # ---- suhu per member (sesaat, interp) ----
        temp_members = []
        if have_temp:
            for mid in member_ids:
                vt, arr = per_param["2t"][mid]
                k_series = [float(arr[k, pi]) - 273.15 if k < arr.shape[0] else None for k in range(len(vt))]
                temp_members.append([interp_instant(vt, k_series, t.astimezone(UTC)) for t in steps_local])
        else:
            temp_members = [[None] * nstep]

        # ---- angin per member ----
        ws_members, wd_members = [], []
        if have_wind:
            for mid in member_ids:
                vtu, ua = per_param["10u"][mid]
                vtv, va = per_param["10v"][mid]
                u_series = [float(ua[k, pi]) if k < ua.shape[0] else None for k in range(len(vtu))]
                v_series = [float(va[k, pi]) if k < va.shape[0] else None for k in range(len(vtv))]
                ws_row, wd_row = [], []
                for t in steps_local:
                    tu = t.astimezone(UTC)
                    u = interp_instant(vtu, u_series, tu)
                    v = interp_instant(vtv, v_series, tu)
                    if u is None or v is None:
                        ws_row.append(None); wd_row.append(None)
                    else:
                        s, d = wind_speed_dir(u, v)
                        ws_row.append(s); wd_row.append(d)
                ws_members.append(ws_row); wd_members.append(wd_row)
        else:
            ws_members = [[None] * nstep]
            wd_members = [[None] * nstep]

        # ---- ringkasan per step ----
        def summarize(members_rows, want_minmax=True):
            out = {"mean": [], "min": [], "max": []}
            for p in C.PERCENTILES:
                out[f"p{p}"] = []
            for si in range(nstep):
                col = [mr[si] for mr in members_rows]
                col = [x for x in col if x is not None and not (isinstance(x, float) and math.isnan(x))]
                if not col:
                    for kk in out:
                        out[kk].append(None)
                    continue
                out["mean"].append(r1(sum(col) / len(col)))
                out["min"].append(r1(min(col)) if want_minmax else None)
                out["max"].append(r1(max(col)) if want_minmax else None)
                for p in C.PERCENTILES:
                    out[f"p{p}"].append(r1(pct(col, p)))
            return out

        precip_sum = summarize(precip_members)
        precip_sum["poe"] = {}
        for thr in C.PRECIP_POE_THRESHOLDS_MM:
            frac_row = []
            for si in range(nstep):
                col = [mr[si] for mr in precip_members if mr[si] is not None]
                frac_row.append(None if not col else round(sum(1 for x in col if x >= thr) / len(col), 3))
            precip_sum["poe"][str(thr)] = frac_row

        temp_sum = summarize(temp_members)
        ws_sum = summarize(ws_members)
        wd_mean = []
        for si in range(nstep):
            wd_mean.append(r1(circular_mean_deg([mr[si] for mr in wd_members])))

        entry = {
            "name": sname,
            "lat": slat, "lon": slon,
            "precip3": precip_sum,
            "temp": {k: temp_sum[k] for k in temp_sum},
            "wind_speed": {k: ws_sum[k] for k in ws_sum},
            "wind_dir": {"mean": wd_mean},
        }
        # member mentah hanya untuk titik bernama (32) — titik grid cukup ringkasan
        if C.KEEP_RAW_MEMBERS_PRECIP and is_named:
            entry["precip3"]["members"] = [[r1(x) for x in row] for row in precip_members]
        points_out[sid] = entry

    payload = {
        "schema": "mosaic-ecmwf-ens/1",
        "model": "ECMWF IFS ENS (open data)",
        "license": "CC-BY-4.0 (ECMWF)",
        "run": run_utc.strftime("%Y-%m-%dT%H:00:00Z"),
        "generated": dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": "Asia/Makassar (UTC+8)",
        "n_members": n_members,
        "horizon_hours": horizon_h,
        "thresholds_mm": C.PRECIP_POE_THRESHOLDS_MM,
        "percentiles": C.PERCENTILES,
        "steps": step_strs,
        "points": points_out,
    }
    return payload


# ---------------------------------------------------------------------------
# mock (tanpa unduh) - untuk uji integrasi HTML offline
# ---------------------------------------------------------------------------
def build_mock(run_utc, horizon_h, n_members=51):
    rng = np.random.default_rng(42)
    steps_local = build_local_steps(run_utc, horizon_h)
    step_strs = [fmt_step(t) for t in steps_local]
    nstep = len(steps_local)
    points_out = {}
    for (sid, sname, slat, slon) in C.ALL_POINTS:
        base_t = 27.0 + rng.normal(0, 0.6)
        pm = []
        for _m in range(n_members):
            row = []
            for si, t in enumerate(steps_local):
                hod = t.hour
                # puncak konveksi sore (15-18 WITA)
                diur = math.exp(-((hod - 16) ** 2) / 18.0)
                lam = 0.4 + 6.0 * diur * (0.6 + rng.random())
                row.append(round(float(rng.gamma(0.7, lam) if rng.random() < 0.55 else 0.0), 1))
            pm.append(row)

        def summ(matrix, mm=True):
            o = {"mean": [], "min": [], "max": []}
            for p in C.PERCENTILES:
                o[f"p{p}"] = []
            for si in range(nstep):
                col = np.array([r[si] for r in matrix], dtype=float)
                o["mean"].append(round(float(col.mean()), 1))
                o["min"].append(round(float(col.min()), 1) if mm else None)
                o["max"].append(round(float(col.max()), 1) if mm else None)
                for p in C.PERCENTILES:
                    o[f"p{p}"].append(round(float(np.percentile(col, p)), 1))
            return o

        tm = [[round(base_t + 3.0 * math.sin((t.hour - 9) / 24 * 2 * math.pi) + rng.normal(0, 0.8), 1)
               for t in steps_local] for _ in range(n_members)]
        wm = [[round(abs(rng.normal(12, 5)), 1) for _ in steps_local] for _ in range(n_members)]
        wd = [round(float((90 + 30 * math.sin(si / 6)) % 360), 1) for si in range(nstep)]

        p_sum = summ(pm)
        p_sum["poe"] = {str(thr): [round(float(np.mean(np.array([r[si] for r in pm]) >= thr)), 3)
                                   for si in range(nstep)]
                        for thr in C.PRECIP_POE_THRESHOLDS_MM}
        if sid in C.STATION_IDS:
            p_sum["members"] = pm
        points_out[sid] = {
            "name": sname, "lat": slat, "lon": slon,
            "precip3": p_sum, "temp": summ(tm), "wind_speed": summ(wm),
            "wind_dir": {"mean": wd},
        }
    return {
        "schema": "mosaic-ecmwf-ens/1",
        "model": "ECMWF IFS ENS (MOCK - data sintetis)",
        "license": "CC-BY-4.0 (ECMWF)",
        "run": run_utc.strftime("%Y-%m-%dT%H:00:00Z"),
        "generated": dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": "Asia/Makassar (UTC+8)",
        "n_members": n_members, "horizon_hours": horizon_h,
        "thresholds_mm": C.PRECIP_POE_THRESHOLDS_MM, "percentiles": C.PERCENTILES,
        "steps": step_strs, "points": points_out, "mock": True,
    }


# ---------------------------------------------------------------------------
def write_js(payload, path):
    js = "// dibuat otomatis oleh pipeline/ingest_ecmwf_ens.py - JANGAN diedit tangan\n"
    js += "// run ECMWF: " + payload["run"] + " | dibuat: " + payload["generated"] + "\n"
    js += "window.ECMWF_ENS_DATA = " + json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(js)
    kb = os.path.getsize(path) / 1024
    log(f"tulis {path}  ({kb:.0f} KB, {payload['n_members']} member, {len(payload['steps'])} langkah)")


def parse_run_arg(s):
    """'20260902/00' atau '2026-09-02/12' -> (dict run_kwargs, datetime run_utc)."""
    if not s:
        return {}, None
    date_part, hh = s.split("/")
    date_part = date_part.replace("-", "")
    d = dt.datetime.strptime(date_part, "%Y%m%d").replace(tzinfo=UTC)
    run_utc = d + dt.timedelta(hours=int(hh))
    return {"date": date_part, "time": int(hh)}, run_utc


def main():
    ap = argparse.ArgumentParser(description="Ingest ECMWF IFS ENS -> ecmwf_ens.js untuk MOSAIC")
    ap.add_argument("--source", default=C.SOURCE, choices=["aws", "ecmwf", "azure"])
    ap.add_argument("--max-members", type=int, default=None, help="batasi jumlah member perturbed")
    ap.add_argument("--run", default=None, help="paksa run tertentu, mis. 20260902/00")
    ap.add_argument("--out", default=C.OUTPUT_JS)
    ap.add_argument("--keep-grib", action="store_true", help="jangan hapus file GRIB (debug)")
    ap.add_argument("--mock", action="store_true", help="data sintetis, tanpa unduh apa pun")
    ap.add_argument("--selftest", action="store_true", help="unduh mini 3 member/2 step lalu berhenti")
    ap.add_argument("--force", action="store_true", help="proses walau run sama dengan sebelumnya")
    ap.add_argument("--fast", action="store_true",
                    help="langkah waktu dipangkas: 3-jam s/d H+3, lalu 12-jam s/d H+7 (unduhan jauh lebih ringan)")
    ap.add_argument("--dl-timeout", type=int, default=0,
                    help="batas detik per unduhan parameter; lewat batas -> gagal cepat (POSIX). 0 = tanpa batas")
    args = ap.parse_args()

    global DL_TIMEOUT
    DL_TIMEOUT = args.dl_timeout

    run_kwargs, run_utc = parse_run_arg(args.run)

    if args.mock:
        if run_utc is None:
            now = dt.datetime.now(UTC)
            run_hh = 12 if now.hour >= 12 else 0
            run_utc = now.replace(hour=run_hh, minute=0, second=0, microsecond=0)
        payload = build_mock(run_utc, 168)
        write_js(payload, args.out)
        return 0

    members = list(C.MEMBERS)
    if args.max_members:
        members = members[: args.max_members]

    if args.fast:
        C.STEP_HOURS[:] = list(range(0, 73, 3)) + [84, 96, 108, 120, 132, 144, 156, 168]
        log(f"FAST: {len(C.STEP_HOURS)} langkah waktu (dari 53)")

    if args.selftest:
        members = members[:3]
        C.STEP_HOURS[:] = [24, 27]
        log("SELFTEST: 3 member, step 24 & 27")

    # tentukan run kalau tidak dipaksa: pakai penemuan otomatis ecmwf-opendata
    from ecmwf.opendata import Client
    client = Client(source=args.source)
    if run_utc is None:
        latest = client.latest(stream="enfo", type="pf", param="2t", step=24)
        run_utc = latest.replace(tzinfo=UTC) if latest.tzinfo is None else latest
        run_kwargs = {"date": run_utc.strftime("%Y%m%d"), "time": run_utc.hour}
        log(f"run terbaru terdeteksi: {run_utc:%Y-%m-%d %H}:00 UTC")

    # 06/18 UTC hanya sampai 144 jam
    horizon = 168 if run_utc.hour in (0, 12) else 144
    if run_utc.hour not in (0, 12):
        C.STEP_HOURS[:] = [h for h in C.STEP_HOURS if h <= 144]

    # skip kalau run sama
    prev = None
    if os.path.exists(C.STATE_FILE):
        prev = open(C.STATE_FILE).read().strip()
    tag = run_utc.strftime("%Y%m%d%H")
    if prev == tag and not args.force and not args.selftest:
        log(f"run {tag} sudah diproses (pakai --force untuk ulang). Keluar.")
        return 0

    t0 = time.time()
    per_param, _valid_ref = collect_members(
        run_kwargs, members, C.ADD_CONTROL, args.source, C.GRIB_CACHE_DIR, args.keep_grib
    )
    if args.selftest:
        got = {p: len(per_param[p]) for p in per_param}
        log(f"SELFTEST OK - member per param: {got}")
        return 0

    payload = build_payload(per_param, run_utc, horizon)
    write_js(payload, args.out)
    with open(C.STATE_FILE, "w") as f:
        f.write(tag)
    log(f"selesai dalam {time.time() - t0:.0f} dtk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
