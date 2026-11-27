// archive_analisis.mjs — buka halaman MOSAIC di Chromium tanpa layar, jalankan pipeline/arsip_extract.js, tambahkan hasilnya ke arsip.
// Arsip = produk "Hasil analisis" PERSIS seperti yang dihitung halaman (rumus tidak diduplikasi), untuk diverifikasi ingest_verif.py.
//
//   node pipeline/archive_analisis.mjs <url halaman> <analisis_archive.json>
// Dipakai oleh .github/workflows/archive_analisis.yml (halaman + data dari cabang `site`, disajikan python -m http.server).
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const [url, out] = process.argv.slice(2);
if (!url || !out) { console.error('pakai: node archive_analisis.mjs <url> <arsip.json>'); process.exit(2); }
const KEEP_DAYS = 75;
const here = path.dirname(fileURLToPath(import.meta.url));
const extractor = fs.readFileSync(path.join(here, 'arsip_extract.js'), 'utf8');

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ timezoneId: 'Asia/Makassar' });
  page.on('pageerror', e => console.log('  [galat halaman]', String(e).slice(0, 200)));
  await page.goto(url, { waitUntil: 'load', timeout: 120000 });
  await page.addScriptTag({ content: extractor });
  const res = await page.evaluate(() => window.__mosaicArsip(150000));
  if (!res.levels_ok) console.log('PERINGATAN: data lapisan atas tidak termuat — skor atmosfer netral');
  let arc = { schema: 'mosaic-analisis-archive/1', issues: {} };
  try { arc = JSON.parse(fs.readFileSync(out, 'utf8')); } catch { /* arsip baru */ }
  arc.issues[res.issue] = res;                                   // satu arsip per tanggal terbit (run terakhir hari itu menimpa)
  const cut = new Date(Date.now() - KEEP_DAYS * 86400e3).toISOString().slice(0, 10);
  arc.issues = Object.fromEntries(Object.entries(arc.issues).filter(([k]) => k >= cut).sort());
  fs.writeFileSync(out, JSON.stringify(arc));
  const nRain = Object.values(res.days).map(d => Object.values(d.st).reduce((n, r) => n + r.ana.filter(x => x >= 4).length, 0));
  console.log(`arsip ${res.issue}: det ${res.det}, ens ${res.ens}, lapisan atas ${res.levels_ok ? 'ok' : 'TIDAK ADA'}, `
    + `slot hujan H+0..3 = ${nRain.join('/')}; total ${Object.keys(arc.issues).length} hari, ${(fs.statSync(out).size / 1024).toFixed(0)} KB`);
} finally {
  await browser.close();
}
