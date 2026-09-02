# Menaikkan BDMA ke web (GitHub Pages + Actions)

Hasil akhir: satu URL `https://<user>.github.io/<repo>/` yang bisa dibuka
prakirawan dari mana saja, dengan data ECMWF ensemble yang **update sendiri
2x/hari** tanpa ada yang perlu menjalankan apa pun.

Pembagian tugas:

| Bagian | Jalan di mana | Update |
|---|---|---|
| Halaman (HTML) + peta | GitHub Pages | permanen, sekali deploy |
| Data ECMWF/GFS/ICON + ensemble GFS/ICON | diambil live dari Open-Meteo tiap halaman dibuka | otomatis, tanpa perawatan |
| Data **ECMWF ENS 51 skenario** (`ecmwf_ens.js`) | GitHub Actions (cron cloud) → commit balik | otomatis 2x/hari |

---

## Langkah sekali setup

### 1. Buat repo & push

Di folder `D:\LAKSITA\MOSAIC` (git sudah di-`init` + commit pertama sudah dibuat):

```bash
git branch -M main
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

> Repo boleh **public** (Actions gratis tak terbatas) atau **private**
> (Actions 2000 menit/bulan — masih cukup). Untuk GitHub Pages gratis di
> akun Free, biasanya perlu **public**.

### 2. Aktifkan GitHub Pages

Repo → **Settings** → **Pages**:
- **Source:** Deploy from a branch
- **Branch:** `main` / `/ (root)` → **Save**

Tunggu ~1 menit. URL muncul di halaman itu:
`https://<user>.github.io/<repo>/`

### 3. Aktifkan Actions

Repo → tab **Actions** → kalau ada tombol "I understand my workflows, enable them", klik.
Workflow **"Update ECMWF ENS data"** akan jalan otomatis sesuai jadwal
(`.github/workflows/ingest.yml`: 09:30 & 21:30 UTC).

**Jalankan sekali sekarang** biar `ecmwf_ens.js` langsung berisi data asli
(bukan CONTOH): Actions → "Update ECMWF ENS data" → **Run workflow**.

Selesai. Setelah itu tidak ada lagi yang perlu disentuh.

---

## Mengubah setelan

| Mau | Ubah di |
|---|---|
| Jumlah skenario (member) di cloud | `--max-members 25` di `.github/workflows/ingest.yml` (naik = lebih halus tapi lebih lama & besar) |
| Jam update | baris `cron:` di workflow yang sama (format UTC) |
| Titik / parameter / langkah waktu | `pipeline/config.py` |

## Kalau mau versi 50 member penuh

Actions dibatasi ~2–3 GB unduhan biar aman. Untuk 50 member penuh (~5–6 GB),
jalankan `pipeline/ingest_ecmwf_ens.py` di PC stasiun (lihat
`pipeline/README.md`) lalu:

```bash
git add ecmwf_ens.js && git commit -m "data: ECMWF ENS full" && git push
```

Pages akan re-deploy otomatis.

## Catatan

- Halaman ini **bukan produk prakiraan resmi BMKG** — sudah tertulis di footer
  dan di kotak "Cara baca halaman ini".
- Log verifikasi sekarang pakai `localStorage`: tersimpan **per-browser**,
  tidak sinkron antar komputer/prakirawan. Untuk log bersama perlu backend
  terpisah (mis. Google Sheets / database kecil) — belum termasuk di sini.
