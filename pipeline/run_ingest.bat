@echo off
REM ==========================================================================
REM  MOSAIC - ambil ECMWF IFS ENS terbaru dan tulis ecmwf_ens.js
REM  Jadwalkan lewat Task Scheduler ~2x sehari:
REM    - 15:30 WITA  (setelah run 00 UTC mendarat)
REM    - 03:30 WITA  (setelah run 12 UTC mendarat)
REM ==========================================================================
setlocal
cd /d "%~dp0"

REM --- sesuaikan kalau python bukan di PATH ---
set PY=python
where %PY% >nul 2>&1 || set PY=C:\Users\Admin\AppData\Local\Programs\Python\Python310\python.exe

echo [%date% %time%] mulai ingest ECMWF ENS
"%PY%" ingest_ecmwf_ens.py %*
set RC=%errorlevel%
echo [%date% %time%] selesai (exit %RC%)

REM catat log ringkas
>> ingest.log echo %date% %time% exit=%RC%
endlocal & exit /b %RC%
