# -*- coding: utf-8 -*-
"""
ingest_waves.py — analisis gelombang atmosfer (MJO, Kelvin, Rossby ekuator/ER, Low) di sekitar Bima dari peta NCICS -> waves.js

Sumber: peta OLR NCICS (Carl Schreck, NC State) https://ncics.org/pub/mjo/v2/map/olr.cfs.<gelombang>.indonesia.1.png
  - 8 panel: 4 hari terakhir (observasi, kiri) + 4 hari prakiraan CFS (kanan; hari-0 = tanggal gambar dibuat)
  - kontur berwarna = OLR tersaring per gelombang tiap 12 W/m2: GARIS PENUH = fase konvektif aktif (OLR negatif),
    garis putus = fase penekan (OLR positif)
Peta tidak punya data angka terbuka, jadi gambar dianalisis: posisi Bima dihitung dari geometri panel (80-170 BT, 10 LU-10 LS),
lalu dicari kontur garis-penuh terdekat.
Status per gelombang per hari:  inside (di dalam kontur aktif) | near (<=3 derajat) | approaching (<=8) | far
Ini estimasi dari gambar, bukan produk resmi — dipakai sebagai petunjuk & dapat dikoreksi prakirawan di halaman.

    python pipeline/ingest_waves.py
"""
import collections
import datetime as dt
import email.utils
import io
import json
import math
import os
import sys
import urllib.request

import numpy as np
from PIL import Image

BASE = "https://ncics.org/pub/mjo/v2/map/olr.cfs.{w}.indonesia.1.png"
WAVES = ["mjo", "kelvin", "er", "low"]
LABEL = {"mjo": "MJO", "kelvin": "Kelvin", "er": "Rossby ekuator (ER)", "low": "Low (frekuensi rendah)"}
POINT = {"bima": (-8.54, 118.69), "dompu": (-8.54, 118.46)}
LON0, LON1, LAT_N, LAT_S = 80.0, 170.0, 10.0, -10.0
UA = {"User-Agent": "Mozilla/5.0 mosaic-bima-dompu/1.0"}
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "waves.js")
IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "waves")      # salinan gambar NCICS (dilayani dari situs sendiri)
MIN_SOLID = 45            # piksel minimum agar komponen kontur dianggap garis penuh (putus-putus terpecah jadi potongan kecil)
NEAR_DEG, APPR_DEG = 3.0, 8.0


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read(), r.headers.get("Last-Modified")


def runs(idx):
    out, s = [], None
    for i, v in enumerate(idx):
        if s is None:
            s = p = v
        elif v == p + 1:
            p = v
        else:
            out.append((s, p)); s = p = v
    if s is not None:
        out.append((s, p))
    return out


def find_panels(im):
    """-> list 8 panel: (kolom, baris, x0, x1, y0, y1); kolom 0=kiri(observasi) 1=kanan(prakiraan); baris 0..3 = hari tertua..terbaru."""
    dark = im.sum(axis=2) < 150
    H, W = dark.shape
    ys = [y for y in range(H) if dark[y, :].sum() > 400]
    yr = runs(ys)
    if len(yr) < 8:
        raise RuntimeError(f"bingkai panel tak terdeteksi ({len(yr)} garis)")
    tops = [yr[i][0] for i in range(0, 8, 2)]
    bots = [yr[i][1] for i in range(1, 8, 2)]
    band = dark[tops[0] + 3:bots[0] - 3, :]
    xs = [x for x in range(W) if band[:, x].sum() > 0.9 * band.shape[0]]
    xr = runs(xs)
    if len(xr) < 4:
        raise RuntimeError(f"kolom panel tak terdeteksi ({len(xr)})")
    cols = [(xr[0][1], xr[1][0]), (xr[-2][1], xr[-1][0])]
    panels = []
    for c, (x0, x1) in enumerate(cols):
        for r in range(4):
            panels.append((c, r, x0, x1, tops[r], bots[r]))
    return panels


def classify(im, kind):
    r, g, b = im[:, :, 0], im[:, :, 1], im[:, :, 2]
    if kind == "kelvin":
        return (b > 180) & (r < 100) & (g < 100)
    if kind == "er":
        return (r > 180) & (g < 90) & (b < 90)
    if kind == "low":
        return (r > 110) & (r < 210) & (g < 90) & (b > 170)
    return (r + g + b) < 90                     # mjo: hitam


def components(mask):
    H, W = mask.shape
    seen = np.zeros_like(mask, bool)
    comps = []
    pts = np.argwhere(mask)
    for y, x in pts:
        if seen[y, x]:
            continue
        q = collections.deque([(y, x)]); seen[y, x] = True; cur = []
        while q:
            cy, cx = q.popleft(); cur.append((cy, cx))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True; q.append((ny, nx))
        comps.append(cur)
    return comps


def inside_closed(wall, start, limit):
    """Isi dari titik `start` dibatasi dinding (kontur penuh + bingkai panel). Terkurung & kecil -> dianggap di dalam kontur."""
    H, W = wall.shape
    if wall[start]:
        return False
    seen = np.zeros_like(wall, bool); q = collections.deque([start]); seen[start] = True; n = 0
    while q:
        y, x = q.popleft(); n += 1
        if n > limit:
            return False
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < W and not wall[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True; q.append((ny, nx))
    return True


def analyse(kind):
    data, lm = fetch(BASE.format(w=kind))
    try:
        os.makedirs(IMG_DIR, exist_ok=True)
        with open(os.path.join(IMG_DIR, f"olr.cfs.{kind}.indonesia.1.png"), "wb") as f:
            f.write(data)
    except OSError as e:
        print("gagal simpan gambar", kind, e, file=sys.stderr)
    im = np.array(Image.open(io.BytesIO(data)).convert("RGB")).astype(int)
    stamp = email.utils.parsedate_to_datetime(lm).astimezone(dt.timezone.utc) if lm else dt.datetime.now(dt.timezone.utc)
    mask_all = classify(im, kind)
    res = {}
    for (c, r, x0, x1, y0, y1) in find_panels(im):
        ix0, ix1, iy0, iy1 = x0 + 4, x1 - 4, y0 + 4, y1 - 4           # buang bingkai
        sub = mask_all[iy0:iy1, ix0:ix1]                                # potongan panel (h x w)
        h, w = sub.shape
        pxdeg = (x1 - x0) / (LON1 - LON0)
        comps = components(sub)
        solid = [np.array(cp) for cp in comps if len(cp) >= MIN_SOLID]
        dash = [np.array(cp) for cp in comps if len(cp) < MIN_SOLID]
        wall = np.zeros((h, w), bool)
        for a_ in solid:
            for (yy, xx) in a_:
                wall[max(0, yy - 1):yy + 2, max(0, xx - 1):xx + 2] = True
        wall[0, :] = wall[-1, :] = wall[:, 0] = wall[:, -1] = True      # bingkai panel = dinding
        out = {}
        for pname, (lat, lon) in POINT.items():
            px = x0 + (lon - LON0) / (LON1 - LON0) * (x1 - x0)
            py = y0 + (LAT_N - lat) / (LAT_N - LAT_S) * (y1 - y0)
            sy, sx = int(round(py)) - iy0, int(round(px)) - ix0         # koordinat dalam potongan
            def mind(cl):
                if not cl:
                    return None
                return min(float(np.hypot(a_[:, 0] - sy, a_[:, 1] - sx).min()) for a_ in cl) / pxdeg
            ds, dd = mind(solid), mind(dash)
            inside = bool(solid) and inside_closed(wall, (sy, sx), 0.30 * h * w)
            status = "inside" if inside else ("near" if ds is not None and ds <= NEAR_DEG else ("approaching" if ds is not None and ds <= APPR_DEG else "far"))
            out[pname] = {"status": status, "dist": None if ds is None else round(ds, 1), "suppressed_near": bool(dd is not None and dd <= NEAR_DEG and ds is None)}
        res[(c, r)] = out
    return stamp, res


def save_all_image():
    """Gambar gabungan (MJO+Kelvin+ER+Low dalam satu peta) — hanya disalin untuk ditampilkan, tidak dianalisis."""
    try:
        data, _ = fetch(BASE.format(w="all"))
        os.makedirs(IMG_DIR, exist_ok=True)
        with open(os.path.join(IMG_DIR, "olr.cfs.all.indonesia.1.png"), "wb") as f:
            f.write(data)
    except Exception as e:
        print("gagal simpan gambar all", e, file=sys.stderr)


def main():
    days, stamp0, per = {}, None, {}
    save_all_image()
    for w in WAVES:
        try:
            stamp, res = analyse(w)
        except Exception as e:                   # satu gelombang gagal tidak menggagalkan yang lain
            print("GAGAL", w, e, file=sys.stderr); continue
        stamp0 = stamp0 or stamp
        d0 = stamp.date()                        # panel prakiraan hari-0 = tanggal gambar dibuat (UTC)
        for (c, r), v in res.items():
            date = (d0 + dt.timedelta(days=(r if c == 1 else r - 4))).isoformat()
            days.setdefault(date, {"obs": c == 0})
            days[date][w] = v
        print(w, {k: v["bima"]["status"] + (f" {v['bima']['dist']}" if v["bima"]["dist"] is not None else "") for k, v in sorted(res.items())})
    if not days:
        return 1
    out = {"generated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "image_time": stamp0.strftime("%Y-%m-%dT%H:%MZ"),
           "src": "NCICS (Carl Schreck, NC State) — OLR tersaring, prakiraan CFS", "labels": LABEL,
           "thresholds_deg": {"near": NEAR_DEG, "approaching": APPR_DEG}, "days": dict(sorted(days.items()))}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// dibuat otomatis oleh pipeline/ingest_waves.py - JANGAN diedit tangan" + chr(10))
        f.write("window.WAVES = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";" + chr(10))
    print("tulis", OUT, os.path.getsize(OUT), "byte")
    return 0


if __name__ == "__main__":
    sys.exit(main())
