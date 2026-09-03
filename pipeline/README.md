# Pipeline ECMWF IFS ENS untuk MOSAIC

Menambahkan **ensemble ECMWF asli (50–51 member)** ke tool
`prakiraan-wilayah-bima-dompu-peta.html`.

Kenapa perlu pipeline terpisah (tidak cukup dari browser):

| Sumber | ECMWF ensemble? |
|---|---|
| Open-Meteo `ensemble-api` (dipakai HTML untuk GFS/ICON) | **Tidak** — cuma 1 control run ECMWF, resolusi kasar |
| **ECMWF Open Data** (dipakai pipeline ini) | **Ya** — 50 member perturbed + control, 0.25°, GRATIS (CC-BY-4.0) |

ECMWF Open Data hanya menyajikan file **GRIB2** → harus di-decode di sisi
Python (cfgrib/eccodes), tidak bisa di browser. Jadi alurnya:

```
run 00/12 UTC  ─►  ingest_ecmwf_ens.py  ─►  ../ecmwf_ens.js  ─►  HTML baca via <script src>
   (ECMWF)          (unduh + decode +          (window.               (kartu + tabel
                     ekstrak 32 titik)          ECMWF_ENS_DATA)         ECMWF ENS)
```

---

## 1. Instalasi (sekali)

```bat
cd D:\LAKSITA\MOSAIC\pipeline
pip install -r requirements.txt
python -m cfgrib selfcheck
```

`cfgrib selfcheck` harus mencetak **"Your system is ready."** Paket `eccodes`
di PyPI sudah membawa binari ecCodes — tidak perlu conda / instalasi terpisah
di Windows.

---

## 2. Menjalankan

```bat
python ingest_ecmwf_ens.py
```

atau lewat wrapper (dipakai Task Scheduler):

```bat
run_ingest.bat
```

Hasil: menimpa **`..\ecmwf_ens.js`** (satu folder di atas, sebelah file HTML).
Buka lagi `prakiraan-wilayah-bima-dompu-peta.html` → panel **ECMWF ENS** terisi.

### Opsi berguna

| Perintah | Fungsi |
|---|---|
| `--mock` | Tulis data **sintetis** tanpa mengunduh apa pun (untuk uji tampilan HTML offline). File keluaran diberi tanda `MOCK`. |
| `--max-members 20` | Batasi jumlah member (hemat bandwidth). |
| `--source ecmwf` | Ganti mirror (`aws` default, `ecmwf`, `azure`). |
| `--run 20260902/00` | Paksa run tertentu, bukan yang terbaru. |
| `--selftest` | Unduh mini (3 member, 2 step) untuk memastikan rantai jalan. |
| `--force` | Proses ulang walau run sama dengan sebelumnya. |
| `--keep-grib` | Jangan hapus file GRIB (debug). |

> **File `ecmwf_ens.js` saat ini masih MOCK.** Jalankan tanpa `--mock` untuk
> mengganti dengan data ECMWF asli.

---

## 3. Cara HTML membacanya

Baris yang ditambahkan di `prakiraan-wilayah-bima-dompu-peta.html`:

```html
<script src="ecmwf_ens.js" onerror="window.__ecmwfEnsMissing=true;"></script>
```

* `ecmwf_ens.js` **harus di folder yang sama** dengan file HTML.
* Lewat `<script src>` (bukan `fetch`) supaya **jalan langsung dari `file://`** —
  cukup dobel-klik file HTML-nya.
* Kalau file tidak ada, panel ECMWF ENS otomatis menampilkan pesan
  "belum aktif" dan sisa tool tetap normal.
* Kalau HTML dijalankan di dalam sandbox yang memblokir `file://` sibling,
  jalankan server statis kecil:
  `python -m http.server 8777` lalu buka `http://127.0.0.1:8777/...`.

Yang muncul di HTML setelah aktif:
1. **Kartu "ECMWF ENS (51)"** di baris model — rata², P10–P90, dan
   P(hujan ≥ 1 / 10 / 20 mm) untuk titik & jam terpilih.
2. **Tabel "ECMWF ENS per 3 jam"** di seksi *Sebaran ensemble* — batang
   P10–P90 + min/maks + POE, per jam untuk hari terpilih. Tampil otomatis,
   tanpa tombol.
3. **Kolom ECMWF ENS** ikut muncul di tabel GFS/ICON setelah tombol
   "Muat GFS + ICON" ditekan.

---

## 4. Penjadwalan (Task Scheduler)

Run 00 UTC biasanya lengkap ~06–08 UTC; run 12 UTC ~18–20 UTC.
WITA = UTC+8, jadi jadwalkan:

| Task | Waktu WITA | Menangkap run |
|---|---|---|
| A | 15:30 | 00 UTC |
| B | 03:30 | 12 UTC |

PowerShell (jalankan sebagai admin, sesuaikan path bila perlu):

```powershell
$py = "C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe"
$script = "D:\LAKSITA\MOSAIC\pipeline\ingest_ecmwf_ens.py"
$act = New-ScheduledTaskAction -Execute $py -Argument $script -WorkingDirectory "D:\LAKSITA\MOSAIC\pipeline"
$t1 = New-ScheduledTaskTrigger -Daily -At 15:30
$t2 = New-ScheduledTaskTrigger -Daily -At 03:30
Register-ScheduledTask -TaskName "MOSAIC ECMWF ENS ingest" -Action $act -Trigger $t1,$t2 -RunLevel Limited
```

---

## 5. Ukuran unduhan & waktu

Default = 50 member × ~53 langkah × 4 parameter (`tp`, `2t`, `10u`, `10v`),
field global 0.25° (tidak ada subsetting server-side di open-data).

* Perkiraan volume: **~4–7 GB per run.**
* Waktu: beberapa menit bila mirror lancar; bisa jauh lebih lama saat portal
  ramai (dibatasi 500 koneksi). Kalau lambat: pakai `--max-members`, kurangi
  `PARAMS`/`STEP_HOURS` di `config.py`, atau ganti `--source`.
* Pipeline hanya memproses ulang bila run berubah (state di `last_run.txt`).

---

## 6. Skema `ecmwf_ens.js`

```js
window.ECMWF_ENS_DATA = {
  schema: "mosaic-ecmwf-ens/1",
  run: "2026-09-02T00:00:00Z",
  generated: "...Z",
  n_members: 51,               // 50 perturbed (+ control kalau tersedia)
  thresholds_mm: [0.5,1,2,5,10,20,50],
  percentiles: [10,25,50,75,90],
  steps: ["2026-09-02T09:00", ...],   // WITA, sama persis dg state.steps[].time di HTML
  points: {
    bandara: {
      name, lat, lon,
      precip3: { mean:[], min:[], max:[], p10:[], p25:[], p50:[], p75:[], p90:[],
                 poe: { "1":[], "10":[], ... },   // fraksi member 0..1
                 members: [[..55..], ...] },       // 51 baris, nilai mentah per step (mm/3jam)
      temp:       { mean:[], min:[], max:[], p10:[], p50:[], p90:[] },   // °C
      wind_speed: { mean:[], min:[], max:[], p10:[], p50:[], p90:[] },   // km/j
      wind_dir:   { mean:[] }                                            // derajat (FROM)
    }, ...
  }
};
```

---

## 7. Batasan & langkah berikutnya

* **Control run (cf)** sering tidak ada di mirror AWS untuk stream `enfo` →
  pipeline lanjut dengan 50 member perturbed (tetap ensemble sah). Coba
  `--source ecmwf` bila mau control-nya.
* **Tidak ada RH/dewpoint** di IFS ENS open-data. Panel RH di HTML tetap
  memakai ensemble GFS/ICON.
* **Curah hujan 3-jam** direkonstruksi dari `tp` akumulatif dengan asumsi
  laju hujan seragam di tiap interval native (3 jam; 6 jam untuk >H+6), lalu
  diintegralkan ke jendela lokal WITA. Timing sub-3-jam hilang.
* **Belum ada kalibrasi.** Ini output model mentah. Langkah paling berdampak
  untuk Bima-Dompu: koreksi bias diurnal curah hujan per slot 3-jam terhadap
  GPM IMERG / observasi BMKG, lalu quantile mapping. Sisipkan sebelum
  `build_payload()` menulis JSON.
* **Multi-model**: menambah NOAA GEFS (31 member, 3-jam s/d D+10, gratis) akan
  menutup celah H+6..H+7 dan memberi pembanding independen.
