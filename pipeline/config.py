# -*- coding: utf-8 -*-
"""
Konfigurasi pipeline ECMWF IFS ENS untuk MOSAIC
(Multi-model Output Spatial Analysis, Interactive Comparison) - Wilayah Bima-Dompu.

Semua angka yang mungkin ingin kamu ubah ada di file ini. Titik stasiun WAJIB
identik dengan STATION_POINTS di prakiraan-wilayah-bima-dompu-peta.html supaya
id-nya cocok saat HTML membaca ecmwf_ens.js.
"""

# --- Zona waktu tampilan -----------------------------------------------------
# WITA = UTC+8, tetap sepanjang tahun (tidak ada DST). Harus sama dengan
# timezone=Asia/Makassar yang dipakai HTML.
TZ_OFFSET_HOURS = 8

# --- Sumber & cakupan unduhan ----------------------------------------------
# source: "aws" (disarankan, tanpa batas koneksi) | "ecmwf" | "azure"
SOURCE = "aws"

# Anggota ensemble perturbed yang diambil (1..50). Kurangi kalau bandwidth
# terbatas, mis. list(range(1, 51, 2)) untuk 25 anggota.
MEMBERS = list(range(1, 51))

# Ikutkan control run (cf) sebagai "member 0". Kalau run tertentu tidak punya
# entri cf, pipeline otomatis lanjut dengan anggota perturbed saja.
ADD_CONTROL = True

# Parameter permukaan IFS ENS yang tersedia gratis di open-data:
#   tp  = total precipitation (akumulatif, m)   -> curah hujan
#   2t  = 2 m temperature (K)                   -> suhu
#   10u,10v = komponen angin 10 m (m/s)         -> kecepatan & arah angin
# (RH/dewpoint TIDAK tersedia di IFS ENS open-data; HTML tetap memakai
#  ensemble RH dari Open-Meteo ICON/GFS untuk itu.)
PARAMS = ["tp", "2t", "10u", "10v"]

# Langkah forecast (jam sejak run). 00/12 UTC: 0..144 tiap 3 jam, lalu 6 jam.
# 168 jam = H+7. 06/18 UTC hanya sampai 144 jam (pipeline otomatis memangkas).
STEP_HOURS = list(range(0, 145, 3)) + [150, 156, 162, 168]

# --- Produk yang ditulis ke JSON ------------------------------------------
# Ambang batas curah hujan 3-jam (mm) untuk probability-of-exceedance (POE).
PRECIP_POE_THRESHOLDS_MM = [0.5, 1, 2, 5, 10, 20, 50]

# Persentil yang disimpan untuk tiap variabel.
PERCENTILES = [10, 25, 50, 75, 90]

# Simpan nilai mentah tiap member untuk curah hujan (dipakai plot sebaran).
# Suhu/angin hanya disimpan ringkasannya supaya file kecil.
KEEP_RAW_MEMBERS_PRECIP = True

# --- Path keluaran --------------------------------------------------------
# ecmwf_ens.js ditaruh di folder yang sama dengan file HTML supaya bisa
# dimuat lewat <script src="ecmwf_ens.js"> tanpa server (jalan dari file://).
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE)
OUTPUT_JS = os.path.join(PROJECT_DIR, "ecmwf_ens.js")
GRIB_CACHE_DIR = os.path.join(_HERE, "grib_cache")
STATE_FILE = os.path.join(_HERE, "last_run.txt")

# --- Titik stasiun (SALIN PERSIS dari STATION_POINTS di HTML) ------------
# id, nama, lintang, bujur
STATION_POINTS = [
    ("asakota",   "Asakota (Kota Bima)",       -8.4384574, 118.7340556),
    ("mpunda",    "Mpunda (Kota Bima)",        -8.4583951, 118.7468712),
    ("raba",      "Raba (Kota Bima)",          -8.4666508, 118.7578140),
    ("rasanaeb",  "Rasanae Barat (Kota Bima)", -8.4540632, 118.7241865),
    ("rasanaet",  "Rasanae Timur (Kota Bima)", -8.4848559, 118.7712912),
    ("ambalawi",  "Ambalawi (Kab. Bima)",      -8.3264522, 118.7764962),
    ("belo",      "Belo (Kab. Bima)",          -8.6222979, 118.7248796),
    ("bolo",      "Bolo (Kab. Bima)",          -8.5064752, 118.6223796),
    ("donggo",    "Donggo (Kab. Bima)",        -8.4208895, 118.5966613),
    ("langgudu",  "Langgudu (Kab. Bima)",      -8.6949798, 118.8326843),
    ("lambitu",   "Lambitu (Kab. Bima)",       -8.5649700, 118.7899569),
    ("lambu",     "Lambu (Kab. Bima)",         -8.6983459, 119.0227159),
    ("madapangga","Madapangga (Kab. Bima)",    -8.5122620, 118.5877133),
    ("monta",     "Monta (Kab. Bima)",         -8.6899290, 118.6689537),
    ("palibelo",  "Palibelo (Kab. Bima)",      -8.5373439, 118.7375113),
    ("parado",    "Parado (Kab. Bima)",        -8.7638288, 118.5542359),
    ("sanggar",   "Sanggar (Kab. Bima)",       -8.3732956, 118.2954806),
    ("soromandi", "Soromandi (Kab. Bima)",     -8.3811867, 118.6901139),
    ("tambora",   "Tambora (Kab. Bima)",       -8.1709744, 117.9717606),
    ("wawo",      "Wawo (Kab. Bima)",          -8.5607035, 118.8638881),
    ("wera",      "Wera (Kab. Bima)",          -8.3387749, 118.9232124),
    ("woha",      "Woha (Kab. Bima)",          -8.5581257, 118.6964438),
    ("sape",      "Sape (Kab. Bima)",          -8.5664773, 118.9834956),
    ("dompu",     "Dompu (Kab. Dompu)",        -8.5401250, 118.4647211),
    ("huu",       "Hu'u (Kab. Dompu)",         -8.7399358, 118.4365634),
    ("kempo",     "Kempo (Kab. Dompu)",        -8.5396910, 118.2496396),
    ("kilo",      "Kilo (Kab. Dompu)",         -8.3098905, 118.3947476),
    ("manggelewa","Manggelewa (Kab. Dompu)",   -8.5188164, 118.3190713),
    ("pajo",      "Pajo (Kab. Dompu)",         -8.6081784, 118.4913610),
    ("pekat",     "Pekat (Kab. Dompu)",        -8.2605896, 117.7970165),
    ("woja",      "Woja (Kab. Dompu)",         -8.5470487, 118.4317451),
    ("bandara",   "Bandara WADB",              -8.5418159, 118.6921890),
]
