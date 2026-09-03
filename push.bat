@echo off
REM ==========================================================================
REM  push.bat  -  kirim semua perubahan lokal ke GitHub sekali klik
REM
REM  Cara pakai:
REM    - dobel-klik file ini, ATAU
REM    - dari terminal:  push.bat "keterangan perubahan"
REM
REM  Urutannya: ambil dulu commit dari GitHub (termasuk ecmwf_ens.js yang
REM  ditulis GitHub Actions 2x/hari) -> tandai perubahanmu -> commit -> push.
REM  Tidak peduli siapa yang mengedit (kamu, editor, VS Code, dll) -
REM  semua file yang berubah di folder ini ikut terkirim.
REM ==========================================================================
setlocal
cd /d "%~dp0"

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo [X] Folder ini bukan repo git.
  pause & exit /b 1
)

git remote get-url origin >nul 2>&1
if errorlevel 1 (
  echo [X] Belum ada remote 'origin'. Jalankan dulu satu kali:
  echo     git remote add origin https://github.com/USERNAME/mosaic.git
  echo     git branch -M main
  echo     git push -u origin main
  pause & exit /b 1
)

set "MSG=%~1"
if "%MSG%"=="" set "MSG=update %date% %time%"

echo.
echo == 1/4  Ambil perubahan terbaru dari GitHub ==
git rev-parse --abbrev-ref "@{u}" >nul 2>&1
if errorlevel 1 (
  echo      ^(branch belum terhubung ke GitHub - dilewati, akan disambung saat push^)
) else (
  git pull --rebase --autostash
  if errorlevel 1 (
    echo.
    echo [X] Gagal menggabungkan perubahan ^(kemungkinan konflik^).
    echo     Selesaikan manual, lalu jalankan push.bat lagi.
    pause & exit /b 1
  )
)

echo.
echo == 2/4  Tandai semua perubahan lokal ==
git add -A

git diff --cached --quiet
if not errorlevel 1 (
  echo      Tidak ada perubahan lokal untuk di-commit.
  echo.
  echo == Tetap sinkronkan ke GitHub ==
  git push -u origin HEAD
  echo.
  echo === Selesai. ===
  pause & exit /b 0
)

echo.
echo == 3/4  Commit: "%MSG%" ==
git commit -m "%MSG%"

echo.
echo == 4/4  Push ke GitHub ==
git push -u origin HEAD
if errorlevel 1 (
  echo.
  echo [X] Push gagal. Cek koneksi internet atau login GitHub.
  pause & exit /b 1
)

echo.
echo === BERES. GitHub Pages akan memuat ulang dalam ~1 menit. ===
pause
endlocal
