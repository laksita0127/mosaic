/* ==========================================================================
   MOSAIC — EKSTRAKTOR ARSIP "HASIL ANALISIS" (dijalankan DI DALAM halaman, lewat pipeline/archive_analisis.mjs)
   Memakai fungsi halaman yang sama dengan yang dilihat prakirawan (slotAgg, anEnv, …) sehingga rumus tidak diduplikasi.
   Hasil: satu objek per tanggal terbit (hari ini WITA) untuk H+0..H+3:
     env[grup]          = { mode, score, pro, con }        skor kondisi atmosfer per wilayah
     st[id].ana / .avg  = pangkat kategori cuaca per slot (02..23 WITA) untuk "Hasil analisis" & "Kesepakatan"  (>=4 = hujan)
     st[id].mm          = hujan 3 jam MENTAH tiap model [ECMWF,GFS,ICON,AIFS] per slot
     st[id].p1          = peluang gabungan ensemble >=1 mm MENTAH (sebelum kalibrasi) per slot
   Catatan: buletin BMKG yang ditempel manual tidak ada di server — skor atmosfer di arsip hanya memakai indeks otomatis.
   Uji manual di browser: muat halaman, lalu jalankan isi berkas ini di konsol -> await window.__mosaicArsip()
   ========================================================================== */
window.__mosaicArsip = async function(maxWaitMs){
  const wait = ms => new Promise(r=>setTimeout(r, ms));
  const t0 = Date.now(), limit = maxWaitMs || 90000;
  while(Date.now()-t0 < limit && !(state && state.pointsData && state.pointsData.length && window.anEnv)) await wait(500);
  if(!(state.pointsData && state.pointsData.length)) throw new Error('data prakiraan halaman tidak termuat');
  const today = new Date(Date.now() + 8*3600e3).toISOString().slice(0,10);
  // tunggu data lapisan atas (analisis.js memuatnya async); tanpa itu skor atmosfer selalu netral
  while(Date.now()-t0 < limit && /belum tersedia/.test(window.anEnv(today, 'KABUPATEN BIMA').note || '')) await wait(500);
  const levelsOk = !/belum tersedia/.test(window.anEnv(today, 'KABUPATEN BIMA').note || '');
  const hidx = buildHourIndex(), GRPS = ['KOTA BIMA','KABUPATEN BIMA','KABUPATEN DOMPU'];
  const r2 = x => x==null ? null : Math.round(x*100)/100;
  const out = { issue: today, made: new Date().toISOString(), levels_ok: levelsOk,
    det: window.DET_DATA ? window.DET_DATA.generated : null, ens: ENS_MULTI ? ENS_MULTI.generated : null,
    models: MODELS.map(m=>m.key), slots: PRODUK_SLOTS, days: {} };
  for(let L=0; L<4; L++){
    const date = addDays(today, L), day = { env:{}, st:{} };
    GRPS.forEach(g=>{ const e = window.anEnv(date, g); day.env[g] = { mode:e.mode, score:e.score, pro:e.pro, con:e.con }; });
    STATION_POINTS.forEach((sp, pi)=>{
      const rec = { ana:[], avg:[], mm:[], p1:[] };
      const P = ENS_MULTI && ENS_MULTI.pooled && ENS_MULTI.pooled.points ? ENS_MULTI.pooled.points[sp.id] : null;
      PRODUK_SLOTS.forEach(sh=>{
        const a = slotAgg(pi, hidx, date, sh, 'ana'), b = slotAgg(pi, hidx, date, sh, 'avg');
        rec.ana.push(a && a.wcat ? a.wcat.rank : null);
        rec.avg.push(b && b.wcat ? b.wcat.rank : null);
        rec.mm.push(MODELS.map(m=>{
          let s = 0, n = 0;
          for(let k=1;k<=3;k++){
            let hh = sh+k, dd = date; if(hh>=24){ hh -= 24; dd = addDays(date, 1); }
            const r = hidx[pi].get(`${dd}T${String(hh).padStart(2,'0')}:00`), x = r && r[m.key];
            if(x && x.precip!=null){ s += x.precip; n++; }
          }
          return n===3 ? r2(s) : null;
        }));
        const si = ENS_MULTI ? ENS_MULTI.steps.indexOf(`${date}T${String(sh).padStart(2,'0')}:00`) : -1;
        rec.p1.push(P && si>=0 && P.precip3.poe['1'] ? P.precip3.poe['1'][si] : null);
      });
      day.st[sp.id] = rec;
    });
    out.days[date] = day;
  }
  return out;
};
