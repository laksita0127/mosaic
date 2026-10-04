@echo off
rem Unduh berkas DATA terbaru (ensemble, sinoptik, deterministik, indeks) dari cabang "site" ke folder ini, untuk dipakai lokal (file://).
cd /d "%~dp0"
git fetch origin site
for %%f in (ecmwf_ens.js ens_multi.js dinamika.js sinoptik.js det_data.js) do git show origin/site:%%f > %%f
echo Selesai. Buka prakiraan-wilayah-bima-dompu-peta.html
pause
