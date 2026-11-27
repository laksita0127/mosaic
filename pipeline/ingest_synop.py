# -*- coding: utf-8 -*-
"""
ingest_synop.py — arsip SYNOP Stasiun Meteorologi Sultan Muhammad Salahuddin Bima (WMO 97270), per jam, dari Ogimet.

SYNOP dikirim BMKG ke jaringan WMO (GTS) sehingga tersedia publik di Ogimet (tanpa akun). Dipakai untuk:
  - verifikasi hujan dengan penakar asli (kelompok 6RRRtR: 6/12/24 jam) dan uji aturan "Hujan Petir" (ww 17, 29, 91–99; awan CB)
  - pengamatan terkini otomatis untuk tab TAF (angin, jarak pandang, cuaca, awan) — pengganti tempel METAR manual
Penyimpanan inkremental: synop_97270.json (dipulihkan dari cabang `site`). Keluaran halaman: synop.js (window.SYNOP_WADB, 15 hari terakhir).

    python pipeline/ingest_synop.py              # ambil yang belum ada (pertama kali: 120 hari)
    SYNOP_DAYS=30 python pipeline/ingest_synop.py
Ogimet layanan gratis: ambil seperlunya (1x/hari cukup), potongan 30 hari, jeda antar permintaan.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request

import config as C

STATION = "97270"
URL = "https://www.ogimet.com/cgi-bin/getsynop?block={st}&begin={b}&end={e}"
UA = {"User-Agent": "mosaic-bima-dompu/1.0 (verifikasi prakiraan Stamet Bima; github.com/laksita0127/mosaic)"}
DAYS = int(os.environ.get("SYNOP_DAYS", "120"))
KEEP_DAYS = 400
STORE = os.path.join(C.PROJECT_DIR, "synop_97270.json")
OUT = os.path.join(C.PROJECT_DIR, "synop.js")
TS_WW = {17, 29} | set(range(91, 100))          # badai guntur / petir (pada jam pengamatan atau jam sebelumnya)


def log(m):
    print(f"[{dt.datetime.utcnow():%H:%M:%S}Z] {m}", flush=True)


def http(url, tries=4):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:  # noqa
            last = e
            log(f"  ulang {i + 1}/{tries} ({str(e)[:80]})")
            time.sleep(30 * (i + 1))
    raise last


def vis_m(vv):
    if vv <= 50: return vv * 100
    if 56 <= vv <= 80: return (vv - 50) * 1000
    if 81 <= vv <= 88: return (30 + (vv - 80) * 5) * 1000
    if vv == 89: return 75000
    return {90: 40, 91: 50, 92: 200, 93: 500, 94: 1000, 95: 2000, 96: 4000, 97: 10000, 98: 20000, 99: 50000}.get(vv)


def temp(g):
    if len(g) != 5 or not g[2:].isdigit() or g[1] not in "01": return None
    v = int(g[2:]) / 10
    return -v if g[1] == "1" else v


def rrr(g):
    """6RRRtR -> (mm, jam)"""
    if len(g) != 5 or not g[1:].isdigit(): return None
    R = int(g[1:4]); t = int(g[4])
    mm = 0.0 if R == 0 else (0.05 if R == 990 else ((R - 990) / 10 if R > 990 else float(R)))
    hrs = {1: 6, 2: 12, 3: 18, 4: 24, 5: 1, 6: 2, 7: 3, 8: 9, 9: 15}.get(t)
    return (mm, hrs)


def parse(msg):
    """satu pesan AAXX -> dict (None bila tak terbaca)"""
    g = msg.replace("=", " ").split()
    if len(g) < 5 or g[0] != "AAXX" or g[2] != STATION: return None
    iw = g[1][4]
    i3 = g[3]; iR, ix, vv = i3[0], i3[1], i3[3:]
    nd = g[4]
    rec = {"N": int(nd[0]) if nd[0].isdigit() else None, "dir": int(nd[1:3]) * 10 if nd[1:3].isdigit() else None,
           "spd": int(nd[3:5]) if nd[3:5].isdigit() else None, "vis": vis_m(int(vv)) if vv.isdigit() else None,
           "T": None, "Td": None, "ww": None, "W": None, "rr": None, "rr_h": None, "cb": False, "Tx": None, "Tn": None}
    if rec["spd"] is not None and iw in "01": rec["spd"] = round(rec["spd"] * 1.944)      # m/s -> kt
    rest = g[5:]
    sec = 1
    for x in rest:
        if x == "333": sec = 3; continue
        if x in ("555", "444", "222"): sec = int(x[0]); continue
        if len(x) != 5: continue
        k = x[0]
        if sec == 1:
            if k == "1": rec["T"] = temp(x)
            elif k == "2": rec["Td"] = temp(x)
            elif k == "6":
                r = rrr(x)
                if r: rec["rr"], rec["rr_h"] = r
            elif k == "7" and x[1:3].isdigit():
                rec["ww"] = int(x[1:3]); rec["W"] = x[3:5]
            elif k == "8":
                if x[2] == "9": rec["cb"] = True                                    # CL = 9 -> Cumulonimbus
        elif sec == 3:
            if k == "1": rec["Tx"] = temp(x)
            elif k == "2": rec["Tn"] = temp(x)
            elif k == "6" and rec["rr"] is None:
                r = rrr(x)
                if r: rec["rr"], rec["rr_h"] = r
            elif k == "8" and x[2] == "9": rec["cb"] = True                          # 8NsChshs, C = 9 (Cb)
    if rec["ww"] is None and iR == "3" and rec["rr"] is None:
        rec["rr"], rec["rr_h"] = 0.0, None                                           # tidak ada hujan (iR=3)
    rec["ts"] = rec["ww"] in TS_WW                                                   # petir saat / satu jam sebelum pengamatan
    rec["ts_past"] = rec["W"] is not None and rec["W"][:1] == "9"                   # W1 = 9: badai guntur dalam periode lalu (3–6 jam)
    rec["manned_ww"] = ix in "12"
    return rec


def main():
    try:
        store = json.load(open(STORE, encoding="utf-8"))
    except Exception:
        store = {"station": STATION, "hours": {}}
    hrs = store["hours"]
    now = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = now - dt.timedelta(days=DAYS)
    if hrs:
        start = max(start, dt.datetime.strptime(max(hrs), "%Y-%m-%dT%H:%MZ") - dt.timedelta(days=2))
    log(f"ambil SYNOP {STATION} {start:%Y-%m-%d %H} .. {now:%Y-%m-%d %H} UTC (tersimpan {len(hrs)} jam)")
    b = start; new = 0
    while b < now:
        e = min(b + dt.timedelta(days=30), now)
        txt = http(URL.format(st=STATION, b=b.strftime("%Y%m%d%H%M"), e=e.strftime("%Y%m%d%H%M")))
        for line in txt.splitlines():
            f = line.strip().split(",", 6)
            if len(f) < 7 or f[0] != STATION: continue
            key = f"{f[1]}-{f[2]}-{f[3]}T{f[4]}:{f[5]}Z"
            r = parse(f[6])
            if r is None: continue
            r["raw"] = f[6].strip()
            if key not in hrs: new += 1
            hrs[key] = r
        b = e
        time.sleep(10)
    cut = (now - dt.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%MZ")
    store["hours"] = {k: v for k, v in sorted(hrs.items()) if k >= cut}
    json.dump(store, open(STORE, "w", encoding="utf-8"), separators=(",", ":"))
    recent_cut = (now - dt.timedelta(days=15)).strftime("%Y-%m-%dT%H:%MZ")
    recent = {k: {kk: vv for kk, vv in v.items() if kk != "manned_ww"} for k, v in store["hours"].items() if k >= recent_cut}
    payload = {"generated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "station": STATION, "name": "Bima (WADB)",
               "src": "SYNOP WMO 97270 via Ogimet", "hours": recent}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// dibuat otomatis oleh pipeline/ingest_synop.py - JANGAN diedit tangan" + chr(10))
        f.write("window.SYNOP_WADB = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";" + chr(10))
    nts = sum(1 for v in store["hours"].values() if v.get("ts"))
    log(f"{new} jam baru; tersimpan {len(store['hours'])} jam ({nts} jam dengan laporan petir); tulis {OUT} ({len(recent)} jam)")
    return 0 if store["hours"] else 1


if __name__ == "__main__":
    sys.exit(main())
