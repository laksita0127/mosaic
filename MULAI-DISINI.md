# Langkah menaikkan BDMA ke GitHub (dari nol)

Ikuti berurutan. Bagian **terminal** = buka **Git Bash** atau **Command Prompt**
di folder `D:\LAKSITA\MOSAIC`. Bagian **web** = di browser, github.com.

Ganti `USERNAME` dengan nama akun GitHub-mu. Nama repo di contoh ini: `bdma`.

---

## A. Punya akun GitHub

Kalau belum: buka <https://github.com> → **Sign up** (gratis). Catat username-nya.

---

## B. Buat repository kosong  (web)

1. Login github.com → klik tombol **+** kanan atas → **New repository**
2. **Repository name:** `bdma`
3. Pilih **Public**
   *(akun gratis: GitHub Pages hanya untuk repo Public)*
4. **JANGAN** centang "Add a README", ".gitignore", atau "license"
5. Klik **Create repository**
6. Muncul halaman berisi perintah — abaikan, pakai perintah di bawah.

---

## C. Sambungkan folder lokal ke repo  (terminal)

Pindah ke folder:

```
cd D:\LAKSITA\MOSAIC
```

Sambungkan ke repo GitHub (ganti USERNAME):

```
git remote add origin https://github.com/USERNAME/bdma.git
```

> Kalau muncul `error: remote origin already exists`, pakai ini:
> `git remote set-url origin https://github.com/USERNAME/bdma.git`

Pastikan nama branch `main`:

```
git branch -M main
```

Kirim ke GitHub:

```
git push -u origin main
```

Saat diminta login: pilih **Sign in with browser**, login sekali, tutup tab,
kembali ke terminal. Selesai → refresh halaman repo di browser, semua file
sudah muncul.

---

## D. Nyalakan GitHub Pages  (web)

1. Repo → **Settings** (tab atas kanan)
2. Menu kiri → **Pages**
3. **Build and deployment → Source:** pilih **Deploy from a branch**
4. **Branch:** `main`  ·  folder: **/ (root)**  →  **Save**
5. Tunggu 1–2 menit, refresh halaman ini. Muncul kotak hijau:
   **"Your site is live at `https://USERNAME.github.io/bdma/`"**
6. Buka URL itu → BDMA jalan. (Data ECMWF masih bertanda **CONTOH** untuk saat ini.)

---

## E. Nyalakan Actions & isi data ECMWF asli  (web)

1. Repo → tab **Actions**
2. Kalau ada tombol hijau **"I understand my workflows, go ahead and enable them"** → klik
3. Panel kiri → klik **"Update ECMWF ENS data"**
4. Kanan → tombol **Run workflow** → **Run workflow** (hijau)
5. Tunggu 20–40 menit. Kalau selesai dengan centang hijau:
   `ecmwf_ens.js` sudah berisi data asli, situs otomatis ter-update.

Setelah ini workflow jalan sendiri tiap hari jam **09:30 & 21:30 UTC**
(16:30 & 04:30 WITA). Tidak ada lagi yang perlu disentuh.

---

## F. Kalau nanti mengedit file

Perubahan di PC **tidak** otomatis ke GitHub. Setelah mengedit:

- **Dobel-klik `push.bat`**  (di folder ini), atau
- terminal: `push.bat "keterangan singkat perubahan"`

`push.bat` otomatis: tarik update dari Actions → commit perubahanmu → push →
GitHub Pages re-deploy.

---

## Kalau macet

| Masalah | Solusi |
|---|---|
| `git push` → *authentication failed* | ulangi, pastikan pop-up "Sign in with browser" selesai. Atau buat Personal Access Token: Settings akun → Developer settings → Personal access tokens → Tokens (classic) → Generate, scope `repo`. Pakai token itu sebagai password. |
| URL Pages **404** | cek Source = branch `main`, folder `/root`. Tunggu beberapa menit, refresh. |
| Actions **merah / gagal** | buka run yang gagal → tombol **Re-run jobs** (portal ECMWF kadang sibuk). Kalau tetap gagal, turunkan `--max-members 25` jadi `15` di `.github/workflows/ingest.yml`. |
| `push.bat` bilang *belum ada remote origin* | kamu belum menyelesaikan bagian **C**. |
