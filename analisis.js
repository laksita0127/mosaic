/* ==========================================================================
   MOSAIC — ANALISIS HARIAN (Kota Bima · Kab. Bima · Kab. Dompu)
   A. Dinamika atmosfer : buletin BMKG ditempel prakirawan + interpretasi berbasis aturan
   B. Kelembapan lapisan 850/700/500/200 hPa (Open-Meteo, ECMWF·GFS·ICON)
   C. Hujan / suhu / angin per kecamatan (ensemble gabungan bila ada)
   D. Narasi otomatis berbasis aturan — boleh diedit prakirawan
   Dimuat sebelum skrip utama; memakai global halaman utama (MODELS, state, ENS_MULTI, slotAgg, …)
   hanya saat dipanggil. Ekspor: window.initAnalisis, window.renderAnalisis.
   ========================================================================== */
(function(){
'use strict';
const KEY_DYN = 'mosaic-dinamika', KEY_NARR = 'mosaic-analisis', KEY_WAVE = 'mosaic-gelombang';
const WAVE_TXT = { near:'mendekat (≤2 hari)', over:'di sekitar NTB' };
const waveManual = date => load(KEY_WAVE, {})[date] || {};
// ambang [kering bila < a, lembap bila >= b] — usulan awal, sesuaikan dengan praktik stasiun
const TH = { rh850:[60,80], rh700:[50,70], rh500:[40,60], rh200:[40,70], pw:[35,50] };
const PTS = [
  { id:'bima',  name:'Bima (Bandara WADB)', lat:-8.5418, lon:118.6922, regs:['KOTA BIMA','KABUPATEN BIMA'] },
  { id:'dompu', name:'Dompu',               lat:-8.5401, lon:118.4647, regs:['KABUPATEN DOMPU'] }
];
const REGS = { all:'Seluruh Bima–Dompu', 'KOTA BIMA':'Kota Bima', 'KABUPATEN BIMA':'Kab. Bima', 'KABUPATEN DOMPU':'Kab. Dompu' };
const COMPASS_ID = { N:'utara',NNE:'utara-timur laut',NE:'timur laut',ENE:'timur-timur laut',E:'timur',ESE:'timur-tenggara',SE:'tenggara',SSE:'selatan-tenggara',
  S:'selatan',SSW:'selatan-barat daya',SW:'barat daya',WSW:'barat-barat daya',W:'barat',WNW:'barat-barat laut',NW:'barat laut',NNW:'utara-barat laut' };
const cmp = d => COMPASS_ID[d] || d;
let LEVELS = null, LEVELS_ERR = null;

const load = (k,def)=>{ try{ const v=localStorage.getItem(k); return v?JSON.parse(v):def; }catch(e){ return def; } };
const save = (k,v)=>{ try{ localStorage.setItem(k,JSON.stringify(v)); }catch(e){} };
const fmt = (v,d=0)=> v==null||isNaN(v) ? '—' : Number(v).toLocaleString('id-ID',{minimumFractionDigits:d,maximumFractionDigits:d});
const avg = a => { const v=a.filter(x=>x!=null&&!isNaN(x)); return v.length? v.reduce((s,x)=>s+x,0)/v.length : null; };
const $ = id => document.getElementById(id);
const pct = v => v==null ? '—' : Math.round(v*100)+'%';
const dateLong = (d,o) => new Date(d+'T00:00:00').toLocaleDateString('id-ID', o||{weekday:'long',day:'numeric',month:'long',year:'numeric'});
const esc = s => String(s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// RH terhadap es -> terhadap air (ECMWF/GFS melaporkan RH basis es pada T < -23 °C; ICON basis air)
function rhIceToWater(rh, t){
  const esw = 6.112*Math.exp(17.62*t/(243.12+t)), esi = 6.112*Math.exp(22.46*t/(272.62+t));
  return Math.min(100, rh*esi/esw);
}
async function fetchLevels(){
  const vars = ['relative_humidity_850hPa','relative_humidity_700hPa','relative_humidity_500hPa','relative_humidity_200hPa','temperature_200hPa',
    'wind_speed_850hPa','wind_direction_850hPa','wind_speed_200hPa','wind_direction_200hPa','cape','total_column_integrated_water_vapour'];
  const url = `https://api.open-meteo.com/v1/forecast?latitude=${PTS.map(p=>p.lat).join(',')}&longitude=${PTS.map(p=>p.lon).join(',')}`
    + `&hourly=${vars.join(',')}&models=${MODELS.map(m=>m.param).join(',')}&forecast_days=8&timezone=Asia%2FMakassar&wind_speed_unit=kmh`;
  const res = await fetch(url);
  if(!res.ok) throw new Error('HTTP '+res.status);
  let j = await res.json(); j = Array.isArray(j) ? j : [j];
  LEVELS = j.map((entry,i)=>{
    const h = entry.hourly, m = {};
    MODELS.forEach(mm=>{
      const g = v => h[`${v}_${mm.param}`] || null;
      const o = { rh850:g('relative_humidity_850hPa'), rh700:g('relative_humidity_700hPa'), rh500:g('relative_humidity_500hPa'), rh200:g('relative_humidity_200hPa'),
        t200:g('temperature_200hPa'), ws850:g('wind_speed_850hPa'), wd850:g('wind_direction_850hPa'), ws200:g('wind_speed_200hPa'), wd200:g('wind_direction_200hPa'),
        cape:g('cape'), pw:g('total_column_integrated_water_vapour') };
      if(mm.key!=='icon' && o.rh200 && o.t200) o.rh200 = o.rh200.map((v,k)=> (v==null||o.t200[k]==null) ? v : (o.t200[k] < -23 ? rhIceToWater(v,o.t200[k]) : v));
      m[mm.key] = o;
    });
    return Object.assign({}, PTS[i], { times:h.time, m });
  });
}
const levelPts = reg => LEVELS ? LEVELS.filter(p=> reg==='all' || p.regs.includes(reg)) : [];
// deret 24 jam (indeks = jam WITA) satu variabel/model untuk wilayah (rata-rata titik)
function daySeries(reg, mk, field, date){
  const pts = levelPts(reg); if(!pts.length) return null;
  const idx = []; pts[0].times.forEach((t,i)=>{ if(t.slice(0,10)===date) idx.push(i); });
  if(idx.length < 24) return null;
  return idx.map(i=> avg(pts.map(p=> p.m[mk] && p.m[mk][field] ? p.m[mk][field][i] : null)));
}
function rhClass(level, v){
  if(v==null) return null; const [lo,hi] = TH[level];
  return v < lo ? 'kering' : (v >= hi ? 'lembap' : 'sedang');
}
const RH_CLR = { kering:'#f6dcb0', sedang:'#fbf1c4', lembap:'#bfe3d4' };
const RH_CHIP = { kering:'c-warn', sedang:'c-neutral', lembap:'c-good' };
function vecMean(speeds, dirs){
  let sx=0, sy=0, n=0;
  speeds.forEach((s,i)=>{ const d=dirs[i]; if(s==null||d==null) return; const r=d*Math.PI/180; sx+=s*Math.sin(r); sy+=s*Math.cos(r); n++; });
  if(!n) return null; sx/=n; sy/=n;
  return { spd:Math.hypot(sx,sy), dir:(Math.atan2(sx,sy)*180/Math.PI+360)%360 };
}

/* ---------- B. kelembapan lapisan ---------- */
function levelStats(reg, date){
  if(!LEVELS) return null;
  const LV = [['rh850','850 hPa'],['rh700','700 hPa'],['rh500','500 hPa'],['rh200','200 hPa']];
  const out = { levels:[], heat:{}, extra:{} };
  LV.forEach(([f,lab])=>{
    const per = {};
    MODELS.forEach(m=>{
      const s = daySeries(reg, m.key, f, date), v = s ? s.filter(x=>x!=null) : [];
      per[m.key] = v.length ? { mean:avg(v), min:Math.min(...v), max:Math.max(...v), s } : null;
    });
    const avgMean = avg(MODELS.map(m=>per[m.key] && per[m.key].mean));
    const cls = MODELS.map(m=>per[m.key] ? rhClass(f, per[m.key].mean) : null).filter(Boolean);
    out.levels.push({ f, lab, per, avgMean, cls:rhClass(f,avgMean), agree: cls.length>0 && cls.every(c=>c===cls[0]) });
    out.heat[f] = PRODUK_SLOTS.map(sh=> avg(MODELS.map(m=>{ const s = per[m.key] && per[m.key].s; return s ? s[sh] : null; })));
  });
  if(out.levels.every(l=>l.avgMean==null)) return null;
  const ex = out.extra; ex.pw = {}; ex.cape = {};
  MODELS.forEach(m=>{
    const p = daySeries(reg, m.key, 'pw', date), c = daySeries(reg, m.key, 'cape', date);
    ex.pw[m.key] = p && p.some(x=>x!=null) ? avg(p) : null;
    ex.cape[m.key] = c && c.some(x=>x!=null) ? Math.max(...c.filter(x=>x!=null)) : null;
  });
  ex.pwAvg = avg(Object.values(ex.pw));
  ['850','200'].forEach(L=>{
    const sp = [], dr = [];
    MODELS.forEach(m=>{ const a=daySeries(reg,m.key,'ws'+L,date), b=daySeries(reg,m.key,'wd'+L,date); if(a&&b) a.forEach((v,i)=>{ sp.push(v); dr.push(b[i]); }); });
    ex['w'+L] = vecMean(sp, dr);
  });
  const shear = [];
  MODELS.forEach(m=>{
    const a=daySeries(reg,m.key,'ws850',date), b=daySeries(reg,m.key,'wd850',date), c=daySeries(reg,m.key,'ws200',date), d=daySeries(reg,m.key,'wd200',date);
    if(!(a&&b&&c&&d)) return;
    a.forEach((_,i)=>{
      if([a[i],b[i],c[i],d[i]].some(x=>x==null)) return;
      const r = x=>x*Math.PI/180;
      shear.push(Math.hypot(c[i]*Math.sin(r(d[i]))-a[i]*Math.sin(r(b[i])), c[i]*Math.cos(r(d[i]))-a[i]*Math.cos(r(b[i]))));
    });
  });
  ex.shear = avg(shear);
  return out;
}
function profileSentence(lv){
  const c = Object.fromEntries(lv.levels.map(l=>[l.f,l.cls]));
  let s;
  if(c.rh850==='lembap' && c.rh700==='lembap' && c.rh500!=='kering') s = 'Atmosfer lembap hingga lapisan menengah — mendukung pertumbuhan awan hujan.';
  else if(c.rh850==='lembap' && (c.rh700==='kering' || c.rh500==='kering')) s = 'Kelembapan hanya di lapisan bawah; udara kering di lapisan menengah menghambat pertumbuhan awan konvektif tinggi (hujan terbatas/ringan).';
  else if(c.rh850==='kering' && c.rh700==='kering' && c.rh500==='kering') s = 'Atmosfer kering di semua lapisan — hujan sangat terbatas.';
  else if(c.rh850==='kering') s = 'Lapisan bawah kering — suplai uap air untuk awan hujan terbatas.';
  else s = 'Kelembapan campuran antar lapisan — pertumbuhan awan hujan bersifat lokal.';
  if(c.rh200==='lembap') s += ' Lapisan atas (200 hPa) lembap — berpotensi awan tinggi (cirrus/anvil).';
  return s;
}
function renderHum(reg, date){
  const el = $('anHum'); if(!el) return null;
  if(!LEVELS){
    el.innerHTML = `<h4>Kelembapan lapisan atas</h4><div class="si-sub">${LEVELS_ERR ? 'Gagal memuat data lapisan (Open-Meteo): '+esc(LEVELS_ERR)+' — <a href="#" id="anRetry">coba lagi</a>' : 'Memuat data lapisan 850/700/500/200 hPa…'}</div>`;
    const r = $('anRetry'); if(r) r.onclick = e=>{ e.preventDefault(); loadLevels(); };
    return null;
  }
  const lv = levelStats(reg, date);
  if(!lv){ el.innerHTML = `<h4>Kelembapan lapisan atas</h4><div class="si-sub">Data lapisan atas tidak tersedia untuk hari ini.</div>`; return null; }
  const cell = pm => pm ? `${fmt(pm.mean)}% <span class="dim">(${fmt(pm.min)}–${fmt(pm.max)})</span>` : '—';
  const rows = lv.levels.map(l=>`<tr><td><b>${l.lab}</b></td>${MODELS.map(m=>`<td>${cell(l.per[m.key])}</td>`).join('')}`
    + `<td><b>${fmt(l.avgMean)}%</b></td><td><span class="si-chip ${RH_CHIP[l.cls]||'c-neutral'}">${l.cls||'—'}</span>${l.agree?'':' <span title="model berbeda kelas" style="color:var(--warn)">*</span>'}</td></tr>`).join('');
  const ex = lv.extra;
  const pwCls = ex.pwAvg==null ? null : (ex.pwAvg < TH.pw[0] ? 'kering' : (ex.pwAvg >= TH.pw[1] ? 'lembap' : 'sedang'));
  const wTxt = w => w ? `${cmp(deg16(w.dir))} (${fmt(w.spd)} km/j)` : '—';
  const heat = ['rh200','rh500','rh700','rh850'].map(f=>{
    const lab = lv.levels.find(l=>l.f===f).lab;
    return `<tr><td><b>${lab}</b></td>${lv.heat[f].map(v=>{ const c=rhClass(f,v); return `<td style="background:${c?RH_CLR[c]:'transparent'};text-align:center">${fmt(v)}</td>`; }).join('')}</tr>`;
  }).join('');
  el.innerHTML = `<h4>Kelembapan lapisan atas — ${REGS[reg]}</h4>
    <div class="produk-wrap"><table class="an-tbl"><thead><tr><th>Lapisan</th>${MODELS.map(m=>`<th>${m.label}</th>`).join('')}<th>Rata²</th><th>Status</th></tr></thead><tbody>${rows}
      <tr><td><b>Uap air total</b></td>${MODELS.map(m=>`<td>${ex.pw[m.key]==null?'—':fmt(ex.pw[m.key])+' mm'}</td>`).join('')}<td><b>${ex.pwAvg==null?'—':fmt(ex.pwAvg)+' mm'}</b></td><td>${pwCls?`<span class="si-chip ${RH_CHIP[pwCls]}">${pwCls}</span>`:'—'}</td></tr>
      <tr><td><b>CAPE maks</b></td>${MODELS.map(m=>`<td>${ex.cape[m.key]==null?'—':fmt(ex.cape[m.key])+' J/kg'}</td>`).join('')}<td colspan="2" class="dim">definisi antar model beda</td></tr>
    </tbody></table></div>
    <div class="si-sub" style="margin:8px 0"><b>Angin 850 hPa:</b> dari ${wTxt(ex.w850)} · <b>200 hPa:</b> dari ${wTxt(ex.w200)} · <b>geser 850–200:</b> ${ex.shear==null?'—':fmt(ex.shear)+' km/j'}</div>
    <div class="si-sub" style="margin-bottom:6px"><b>Profil per jam</b> (rata² model, RH %) — kolom = jam WITA</div>
    <div class="produk-wrap"><table class="an-tbl"><thead><tr><th></th>${PRODUK_SLOTS.map(h=>`<th>${String(h).padStart(2,'0')}</th>`).join('')}</tr></thead><tbody>${heat}</tbody></table></div>
    <div class="si-sub" style="margin-top:8px;line-height:1.5">${profileSentence(lv)}<br>
      <span class="dim">Ambang kering/lembap: 850 hPa &lt;${TH.rh850[0]}/≥${TH.rh850[1]}%, 700 hPa &lt;${TH.rh700[0]}/≥${TH.rh700[1]}%, 500 hPa &lt;${TH.rh500[0]}/≥${TH.rh500[1]}%, 200 hPa &lt;${TH.rh200[0]}/≥${TH.rh200[1]}%, uap air &lt;${TH.pw[0]}/≥${TH.pw[1]} mm (usulan awal). RH 200 hPa ECMWF/GFS dikonversi dari basis es ke air agar sebanding dengan ICON. Titik acuan: ${levelPts(reg).map(p=>p.name).join(' + ')}. Tanda * = model berbeda kelas.</span></div>`;
  return lv;
}

/* ---------- A. dinamika atmosfer ---------- */
const BLN = { januari:1,februari:2,maret:3,april:4,mei:5,juni:6,juli:7,agustus:8,september:9,oktober:10,november:11,desember:12 };
const num = s => s==null ? null : parseFloat(String(s).replace('−','-').replace(',','.'));
const NUM = '([-+−]?\\d+(?:[.,]\\d+)?)';
function parseBulletin(text){
  const t = text.replace(/[—–]+>|-->|→/g,'->').replace(/\r/g,'');
  const pick = re => { const m = t.match(re); return m ? m[1] : null; };
  const dm = t.match(/tanggal\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})/i);
  const date = dm && BLN[dm[2].toLowerCase()] ? `${dm[3]}-${String(BLN[dm[2].toLowerCase()]).padStart(2,'0')}-${String(dm[1]).padStart(2,'0')}` : null;
  const mjoM = t.match(/MJO\s*:[^\n]*/i), mjoLine = mjoM ? mjoM[0] : '';
  return {
    date,
    soi:  num(pick(new RegExp('\\bSOI\\s*:\\s*'+NUM,'i'))),
    nino: num(pick(new RegExp('NI[NÑ]O\\s*3\\.?4\\s*:\\s*'+NUM,'i'))),
    dmi:  num(pick(new RegExp('\\bDMI\\s*:\\s*'+NUM,'i'))),
    mjoPhase: num(pick(/MJO\s*:\s*Fase\s*(\d)/i)),
    mjoInactive: /tidak\s+(aktif|berkontribusi|signifikan)/i.test(mjoLine),
    surge: num(pick(new RegExp('Indeks\\s*Surge\\s*:\\s*'+NUM,'i'))),
    kelvin: pick(/Kelvin[^\n]*?->\s*([^\n]*)/i), rossby: pick(/Rossby[^\n]*?->\s*([^\n]*)/i),
    belokan: pick(/(?:Belokan|Konvergensi)[^\n]*?->\s*([^\n]*)/i), sst: pick(/SST[^\n]*?->\s*([^\n]*)/i)
  };
}
function interpret(p){
  const items = [], add = (k,lab,val,side,txt)=> items.push({k,lab,val,side,txt});
  if(p.soiStd!=null) add('soi','SOI (CPC)',fmt(p.soiStd,1), p.soiStd>=0.7?'wet':(p.soiStd<=-0.7?'dry':'neu'), p.soiStd>=0.7?'mendukung peningkatan hujan':(p.soiStd<=-0.7?'fase El Niño — cenderung mengurangi hujan':'netral'));
  else if(p.soi!=null) add('soi','SOI',fmt(p.soi,1), p.soi>=7?'wet':(p.soi<=-7?'dry':'neu'), p.soi>=7?'mendukung peningkatan hujan':(p.soi<=-7?'fase El Niño — cenderung mengurangi hujan':'netral'));
  if(p.nino!=null) add('nino','Niño 3.4',fmt(p.nino,2), p.nino<=-0.8?'wet':(p.nino>=0.8?'dry':'neu'), p.nino<=-0.8?'La Niña — cenderung menambah hujan':(p.nino>=0.8?'El Niño — cenderung mengurangi hujan':'netral'));
  if(p.dmi!=null) add('dmi','DMI',fmt(p.dmi,2), p.dmi<=-0.4?'wet':(p.dmi>=0.4?'dry':'neu'), p.dmi<=-0.4?'IOD negatif — cenderung menambah hujan':(p.dmi>=0.4?'IOD positif — cenderung mengurangi hujan':'netral'));
  if(p.mjoPhase!=null){
    const ph = p.mjoPhase, side = p.mjoInactive ? 'neu' : ([4,5].includes(ph)?'wet':([1,2,7,8].includes(ph)?'dry':'neu'));
    add('mjo','MJO',`fase ${ph}${p.mjoAmp!=null?' · amp '+fmt(p.mjoAmp,2):''}`, side, p.mjoInactive?'lemah (amp < 1) — tidak berkontribusi':(side==='wet'?'aktif di Benua Maritim — mendukung hujan':(side==='dry'?'menekan konveksi di Benua Maritim':'pengaruh sebagian')));
  }
  [['kelvin','Kelvin',p.kelvinMan],['er','Rossby ekuator',p.erMan]].forEach(([k,lab,v])=>{
    if(v) add(k,lab,WAVE_TXT[v],'wet', 'fase konvektif aktif — mendukung hujan');
  });
  if(p.surge!=null) add('surge','Indeks surge',fmt(p.surge,1), p.surge>=10?'wet':'neu', p.surge>=10?'surge signifikan':'tidak signifikan');
  return items;
}
function dynOverall(items){
  if(!items.length) return null;
  const dry = items.filter(i=>i.side==='dry').length, wet = items.filter(i=>i.side==='wet').length;
  if(dry>=2 && wet===0) return { cls:'c-warn', txt:'Faktor skala besar cenderung mengurangi hujan' };
  if(wet>=2 && dry===0) return { cls:'c-good', txt:'Faktor skala besar cenderung mendukung hujan' };
  if(dry===0 && wet===0) return { cls:'c-neutral', txt:'Faktor skala besar netral' };
  return { cls:'c-neutral', txt:'Sinyal skala besar campuran' };
}
// indeks otomatis dari NOAA (dinamika.js) — dasar; buletin yang ditempel menimpa per indeks
function autoParams(){
  const D = window.DINAMIKA; if(!D) return null;
  const p = {};
  if(D.nino34) p.nino = D.nino34.value;
  if(D.soi) p.soiStd = D.soi.value;
  if(D.dmi) p.dmi = D.dmi.value;
  if(D.mjo){ p.mjoPhase = D.mjo.phase; p.mjoAmp = D.mjo.amp; p.mjoInactive = D.mjo.amp < 1; p.mjoDate = D.mjo.date; }
  return p;
}
function mergedParams(b, date){
  const a = autoParams() || {}, pb = b ? parseBulletin(b.text) : {};
  const p = Object.assign({}, a);
  Object.keys(pb).forEach(k=>{ if(pb[k]!=null && pb[k]!==false) p[k]=pb[k]; });
  if(pb.soi!=null) p.soiStd = null;
  const wm = waveManual(date); p.kelvinMan = wm.kelvin || null; p.erMan = wm.er || null;
  return p;
}
function autoNote(b){
  const D = window.DINAMIKA; if(!D) return '';
  const bits = [];
  const fromBul = k => b && parseBulletin(b.text)[k]!=null;
  if(D.nino34 && !fromBul('nino')) bits.push(`Niño 3.4: ${D.nino34.src}, minggu ${D.nino34.date}`);
  if(D.soi && !fromBul('soi')) bits.push(`SOI: ${D.soi.src}, bulan ${D.soi.month}`);
  if(D.mjo && !fromBul('mjoPhase')) bits.push(`MJO: ${D.mjo.src}, ${D.mjo.date}`);
  if(D.dmi && !fromBul('dmi')) bits.push(`DMI: ${D.dmi.src}, bulan ${D.dmi.month} (terlambat 1–2 bulan)`);
  return bits.length ? `<div class="si-sub dim" style="margin-top:6px">Otomatis (bukan buletin BMKG): ${bits.join(' · ')}. Tempel buletin BMKG untuk menimpa dan menambah surge, Kelvin/Rossby, belokan angin, SST.</div>` : '';
}
function bulletinFor(date){
  return load(KEY_DYN, []).filter(b=>b.date && b.date <= date).sort((a,b)=>b.date.localeCompare(a.date))[0] || null;
}
function regionMention(p){
  const txt = [p.belokan,p.sst,p.kelvin,p.rossby].filter(Boolean).join(' ; ');
  return { hit: /NTB|Nusa\s*Tenggara|Nusra|Bima|Dompu|Sumbawa/i.test(txt), text: txt };
}
function renderDyn(date){
  const view = $('anDynView'); if(!view) return null;
  const b = bulletinFor(date), auto = autoParams();
  if(!b && !auto){ view.innerHTML = `<div class="si-sub">Belum ada data dinamika. Tempel teks <b>Informasi Dinamika Atmosfer</b> BMKG di kotak bawah lalu simpan.</div>`; return null; }
  const p = mergedParams(b, date), items = interpret(p), ov = dynOverall(items), mn = regionMention(p);
  const tag = { wet:'c-good', dry:'c-warn', neu:'c-neutral' };
  const age = b ? Math.round((Date.parse(date)-Date.parse(b.date))/86400000) : 0;
  view.innerHTML = (b ? `<div class="si-sub" style="margin-bottom:6px">Buletin tanggal <b>${dateLong(b.date,{day:'numeric',month:'long',year:'numeric'})}</b>${age>0?` <span style="color:var(--warn)">(${age} hari sebelum hari analisis — kondisi saat itu, bukan prakiraan)</span>`:''}</div>`
      : `<div class="si-sub" style="margin-bottom:6px">Belum ada buletin BMKG untuk tanggal ini — memakai indeks otomatis.</div>`)
    + `<div class="an-chips">${items.map(i=>`<div class="an-chip"><div class="k">${i.lab}</div><div class="v">${i.val}</div><span class="si-chip ${tag[i.side]}">${i.txt}</span></div>`).join('')}</div>`
    + (ov?`<div style="margin:8px 0"><span class="si-chip ${ov.cls}">${ov.txt}</span></div>`:'')
    + (b ? `<div class="si-sub" style="line-height:1.5">${mn.hit
      ? '⚠ Buletin menyebut wilayah NTB/Nusa Tenggara pada belokan/konvergensi/SST/gelombang: <i>'+esc(mn.text.slice(0,240))+'</i>'
      : 'Belokan angin/konvergensi, gelombang atmosfer, dan SST anomali pada buletin <b>tidak mencakup NTB</b> (Bima–Dompu).'}</div>` : '')
    + autoNote(b);
  return { p, items, ov, mn, b };
}
function initDynControls(){
  const list = $('anDynList'); if(!list) return;
  const refresh = ()=>{
    const L = load(KEY_DYN, []).sort((a,b)=>b.date.localeCompare(a.date));
    list.innerHTML = L.length ? L.map(b=>`<option value="${b.date}">${b.date}</option>`).join('') : '<option value="">(belum ada)</option>';
  };
  refresh();
  $('anDynSave').onclick = ()=>{
    const ta = $('anDynText'), msg = $('anDynMsg');
    if(!ta.value.trim()){ msg.textContent = 'Kotak masih kosong.'; return; }
    const p = parseBulletin(ta.value);
    if(!p.date){ msg.textContent = 'Tanggal tidak terbaca — pastikan ada kalimat "…tanggal 04 Oktober 2026".'; return; }
    const L = load(KEY_DYN, []).filter(b=>b.date!==p.date); L.push({ date:p.date, text:ta.value, ts:Date.now() });
    save(KEY_DYN, L); ta.value=''; msg.textContent = `Tersimpan untuk ${p.date}.`; refresh(); render();
  };
  $('anDynDel').onclick = ()=>{
    const d = list.value; if(!d) return;
    save(KEY_DYN, load(KEY_DYN, []).filter(b=>b.date!==d)); refresh(); render();
  };
  list.onchange = ()=>{ const b = load(KEY_DYN,[]).find(x=>x.date===list.value); if(b) $('anDynText').value = b.text; };
}

/* ---------- C. hujan / suhu / angin per kecamatan ---------- */
function rainStats(date, reg){
  const hidx = buildHourIndex();
  const groups = reg==='all' ? ['KOTA BIMA','KABUPATEN BIMA','KABUPATEN DOMPU'] : [reg];
  const rows = [], slotAcc = {}; PRODUK_SLOTS.forEach(sh=>slotAcc[sh]={s:0,n:0});
  let pooledUsed = false, ensUsed = false;
  STATION_POINTS.forEach((p,pi)=>{
    const g = stationGroup(p.name); if(!groups.includes(g)) return;
    let best1=-1, bestSlot=null, best10=-1, rainDet=0, dis=0, cells=0;
    PRODUK_SLOTS.forEach(sh=>{
      const key = `${date}T${String(sh).padStart(2,'0')}:00`;
      const pooled = ENS_MULTI ? ensPooledAt(p.id, key) : null;
      const e = ecmwfEnsAt(p.id, key);
      let p1=null, p10=null;
      if(pooled && pooled.nm>=2 && pooled.poe['1']!=null){ p1=pooled.poe['1']; p10=pooled.poe['10']; pooledUsed=true; }
      else if(e && e.precip && e.precip.poe && e.precip.poe['1']!=null){ p1=e.precip.poe['1']; p10=e.precip.poe['10']; ensUsed=true; }
      if(p1!=null){ if(p1>best1){ best1=p1; bestSlot=sh; } slotAcc[sh].s+=p1; slotAcc[sh].n++; }
      if(p10!=null && p10>best10) best10=p10;
      const a = slotAgg(pi,hidx,date,sh,'avg');
      if(a){ cells++; if(a.precip3!=null) rainDet=Math.max(rainDet,a.precip3); }
      if(slotDisagree(pi,hidx,date,sh)) dis++;
    });
    rows.push({ pi, id:p.id, name:shortKec(p.name), grp:g, poe1:best1<0?null:best1, slot:bestSlot, poe10:best10<0?null:best10, rainDet, dis, cells, ext:dayExtent(pi,hidx,date,'avg') });
  });
  return { rows, slotAcc, src: pooledUsed ? 'gabungan' : (ensUsed ? 'ECMWF' : null) };
}
const poeChip = v => v==null ? '—' : `<span class="si-chip ${v>=0.6?'c-bad':v>=0.3?'c-warn':v>=0.1?'c-neutral':'c-good'}">${Math.round(v*100)}%</span>`;
function renderRain(date, reg){
  const el = $('anRain'); if(!el) return null;
  const R = rainStats(date, reg);
  const sorted = R.rows.slice().sort((a,b)=> (b.poe1??-1)-(a.poe1??-1) || b.rainDet-a.rainDet);
  const body = sorted.map(r=>`<tr><td class="kec"><b>${esc(r.name)}</b></td><td>${poeChip(r.poe1)}</td><td>${r.slot==null?'—':String(r.slot).padStart(2,'0')+'.00'}</td><td>${pct(r.poe10)}</td>`
    + `<td>${fmt(r.rainDet,1)} mm</td><td>${r.ext.tmin??'—'}–${r.ext.tmax??'—'} °C</td><td>${r.ext.arah} ${r.ext.kts??'—'} km/j</td><td>${r.dis?`<span style="color:var(--warn)">${r.dis}/${r.cells} *</span>`:'0'}</td></tr>`).join('');
  const srcTxt = R.src==='gabungan' ? 'ensemble <b>gabungan</b> ECMWF·AIFS·GEFS·ICON (bobot sama per model)' : (R.src==='ECMWF' ? 'ensemble ECMWF' : '<b>tidak ada data ensemble</b> untuk hari ini (hanya deterministik)');
  el.innerHTML = `<h4>Hujan, suhu &amp; angin per kecamatan — ${REGS[reg]}</h4>
    <div class="produk-wrap"><table class="an-tbl"><thead><tr><th>Kecamatan</th><th>Peluang hujan maks (≥1 mm/3 jam)</th><th>Jam puncak</th><th>Peluang ≥10 mm</th><th>Hujan 3 jam maks (det.)</th><th>Suhu</th><th>Angin maks</th><th>Sel *</th></tr></thead><tbody>${body}</tbody></table></div>
    <div class="si-sub" style="margin-top:6px">Peluang = ${srcTxt}. Hujan 3 jam maks = rata-rata model deterministik; suhu/angin = rata-rata 4 model; sel * = jumlah slot (dari 8) saat 4 model tak sepakat ada/tidaknya hujan.</div>`;
  return R;
}

/* ---------- D. narasi otomatis: faktor pendukung / penghambat + kesimpulan 3 hari ---------- */
const NARR_DAYS = 3;
const dLong = d => dateLong(d, {weekday:'long', day:'numeric', month:'long', year:'numeric'});
const regName = reg => reg==='all' ? 'Bima–Dompu' : REGS[reg];
const dShort = d => dateLong(d, {weekday:'short', day:'numeric', month:'short'});
const GRP_SHORT = { 'KOTA BIMA':'Kota Bima', 'KABUPATEN BIMA':'Kab. Bima', 'KABUPATEN DOMPU':'Kab. Dompu' };

function rainPhrase(peak, peak10, rainDet){
  if(peak==null){
    if(rainDet<0.5) return 'tidak berpotensi hujan signifikan (model deterministik)';
    if(rainDet<10) return 'berpotensi hujan ringan lokal (model deterministik)';
    return 'berpotensi hujan sedang–lebat lokal (model deterministik)';
  }
  let s = peak<0.10 ? 'praktis tidak berpotensi hujan' : peak<0.25 ? 'hujan hanya berpeluang kecil dan bersifat lokal (ringan)'
    : peak<0.50 ? 'berpotensi hujan ringan lokal di sebagian wilayah' : peak<0.75 ? 'berpotensi hujan ringan–sedang di sebagian wilayah'
    : 'berpotensi hujan di sebagian besar wilayah';
  if(peak10!=null && peak10>=0.25) s += `, dengan potensi hujan lebat lokal (≥10 mm/3 jam, peluang hingga ${Math.round(peak10*100)}%)`;
  return s;
}
// cuaca singkat untuk kesimpulan akhir
function wxShort(peak, peak10, rainDet){
  if(peak==null) return rainDet<0.5 ? 'cerah berawan hingga berawan' : rainDet<10 ? 'berawan dengan hujan ringan lokal' : 'berawan dengan hujan sedang–lebat lokal';
  if(peak<0.10) return 'cerah berawan hingga berawan tanpa hujan signifikan';
  if(peak<0.25) return 'cerah berawan hingga berawan, hujan ringan hanya lokal dan berpeluang kecil';
  if(peak<0.50) return 'berawan dengan hujan ringan lokal';
  if(peak<0.75) return 'berawan hingga hujan ringan–sedang di sebagian wilayah';
  return 'hujan di sebagian besar wilayah' + (peak10!=null && peak10>=0.25 ? ', lokal lebat' : '');
}

// faktor lokal (lapisan atas, CAPE, angin 850, geser, ensemble) satu hari -> [{side:'pro'|'con'|'neu', txt}]
function localFactors(lv, R, date){
  const F = [], add = (side, txt)=> F.push({ side, txt });
  if(lv){
    const L = Object.fromEntries(lv.levels.map(l=>[l.f,l]));
    const rh = (k, lab, pro, con)=>{
      const l = L[k]; if(!l || l.avgMean==null) return;
      const t = `${lab} RH ${fmt(l.avgMean)}% (${l.cls})`;
      add(l.cls==='lembap'?'pro':(l.cls==='kering'?'con':'neu'), l.cls==='lembap' ? `${t} — ${pro}` : (l.cls==='kering' ? `${t} — ${con}` : `${t}`));
    };
    rh('rh850','850 hPa','lapisan bawah lembap, suplai uap air cukup','lapisan bawah kering, suplai uap air terbatas');
    rh('rh700','700 hPa','lembap, awan konvektif bisa tumbuh vertikal','kering, menghambat pertumbuhan awan konvektif');
    rh('rh500','500 hPa','lembap, mendukung awan hujan tebal','kering, menghambat awan hujan tebal');
    if(L.rh200 && L.rh200.avgMean!=null) add('neu', `200 hPa RH ${fmt(L.rh200.avgMean)}% (${L.rh200.cls}) — ${L.rh200.cls==='lembap'?'awan tinggi (cirrus/anvil) berpeluang banyak':'awan tinggi relatif sedikit'}`);
    const ex = lv.extra;
    if(ex.pwAvg!=null) add(ex.pwAvg>=TH.pw[1]?'pro':(ex.pwAvg<TH.pw[0]?'con':'neu'), `Uap air total ${fmt(ex.pwAvg)} mm — ${ex.pwAvg>=TH.pw[1]?'cukup untuk hujan':(ex.pwAvg<TH.pw[0]?'rendah (udara kering)':'sedang')}`);
    const capes = Object.values(ex.cape).filter(v=>v!=null);
    if(capes.length){ const c = avg(capes); add(c>=1000?'pro':(c<250?'con':'neu'), `CAPE rata² model ${fmt(c)} J/kg — ${c>=1000?'atmosfer labil, konveksi kuat mungkin':(c<250?'atmosfer stabil, konveksi lemah':'labilitas sedang')}`); }
    if(ex.w850){
      const d = ex.w850.dir, mon = new Date(date+'T00:00:00').getMonth()+1, dryMon = mon>=4 && mon<=10;
      const txt = `Angin 850 hPa dari ${cmp(deg16(d))} (${fmt(ex.w850.spd)} km/jam)`;
      if(d>=225 && d<=315) add('pro', `${txt} — baratan, membawa udara lembap dari Samudra Hindia/laut sekitar`);
      else if(dryMon && d>=45 && d<=180) add('con', `${txt} — arus timuran/tenggara (monsun Australia) yang kering pada musim kemarau`);
      else add('neu', txt);
    }
    if(ex.shear!=null) add(ex.shear>50?'con':'neu', `Geser angin 850–200 hPa ${fmt(ex.shear)} km/jam — ${ex.shear>50?'kuat, menghambat organisasi awan konvektif':'tidak menghambat secara berarti'}`);
  }
  if(R){
    const withP = R.rows.filter(r=>r.poe1!=null);
    if(withP.length){
      const pk = Math.max(...withP.map(r=>r.poe1));
      add(pk>=0.5?'pro':(pk<0.15?'con':'neu'), `Peluang ensemble ≥1 mm/3 jam tertinggi ${Math.round(pk*100)}% — ${pk>=0.5?'tinggi':(pk<0.15?'rendah':'sedang')}`);
    }
  }
  return F;
}
function bulletList(arr, mark){ return arr.length ? arr.map(f=>`  ${mark} ${f.txt}`).join('\n') : '  (tidak ada)'; }

function dayBlock(date, idx, reg, dyn){
  const lv = levelStats(reg, date), R = rainStats(date, reg), F = localFactors(lv, R, date);
  const pro = F.filter(f=>f.side==='pro'), con = F.filter(f=>f.side==='con'), neu = F.filter(f=>f.side==='neu');
  const lines = [`HARI ${idx+1} — ${dLong(date)}`];
  lines.push('Faktor yang mendukung hujan:', bulletList(pro,'✔'));
  lines.push('Faktor yang menghambat hujan:', bulletList(con,'✘'));
  lines.push('Faktor netral / catatan:', bulletList(neu,'•'));
  const info = { date, pro:pro.length, con:con.length, R, lv };
  if(R && R.rows.length){
    const withP = R.rows.filter(r=>r.poe1!=null).sort((a,b)=>b.poe1-a.poe1);
    const peak = withP.length ? withP[0].poe1 : null;
    const p10 = R.rows.reduce((m,r)=> r.poe10!=null ? Math.max(m,r.poe10) : m, -1);
    const rainDet = Math.max(...R.rows.map(r=>r.rainDet));
    let s = `Hujan: ${rainPhrase(peak, p10<0?null:p10, rainDet)}`;
    let sl = null, top = [];
    if(peak!=null && peak>=0.10){
      top = withP.filter(r=>r.poe1>=Math.max(0.10, peak*0.7)).slice(0,4).map(r=>r.name);
      sl = PRODUK_SLOTS.map(sh=>({sh, v: R.slotAcc[sh].n ? R.slotAcc[sh].s/R.slotAcc[sh].n : -1})).sort((a,b)=>b.v-a.v)[0];
      s += `; peluang tertinggi ${Math.round(peak*100)}% di ${top.join(', ')}, umumnya pukul ${String(sl.sh).padStart(2,'0')}.00–${String((sl.sh+3)%24).padStart(2,'0')}.00 WITA`;
    }
    s += '.';
    if(reg==='all' && peak!=null){
      const gm = {}; R.rows.forEach(r=>{ if(r.poe1!=null) gm[r.grp] = Math.max(gm[r.grp]||0, r.poe1); });
      const parts = Object.entries(gm).map(([g,v])=>`${GRP_SHORT[g]||g} ${Math.round(v*100)}%`);
      if(parts.length) s += ` Peluang tertinggi per wilayah: ${parts.join(', ')}.`;
    }
    if(withP.length && peak>=0.10 && ENS_MULTI){
      const w = withP[0], key = `${date}T${String(w.slot).padStart(2,'0')}:00`;
      const vals = ENS_ORDER.map(k=>{ const x = k==='ecmwf' ? ecmwfEnsAt(w.id,key) : ensModelAt(k,w.id,key); const v = x && x.precip && x.precip.poe ? x.precip.poe['1'] : null; return v==null?null:{k,v}; }).filter(Boolean);
      if(vals.length>=2){
        const hi = Math.max(...vals.map(x=>x.v)), lo = Math.min(...vals.map(x=>x.v));
        if(hi-lo>=0.3) s += ` Ensemble tidak sepakat di ${w.name} pukul ${String(w.slot).padStart(2,'0')}.00: ${vals.map(x=>`${(ENS_MULTI.models[x.k]&&ENS_MULTI.models[x.k].short)||x.k} ${Math.round(x.v*100)}%`).join(', ')}.`;
      }
    }
    lines.push(s);
    const withT = R.rows.filter(r=>r.ext.tmin!=null && r.ext.tmax!=null);
    const tmin = withT.slice().sort((a,b)=>a.ext.tmin-b.ext.tmin)[0], tmax = withT.slice().sort((a,b)=>b.ext.tmax-a.ext.tmax)[0];
    const kts = R.rows.filter(r=>r.ext.kts!=null).sort((a,b)=>b.ext.kts-a.ext.kts)[0];
    if(tmin && tmax) lines.push(`Suhu udara ${tmin.ext.tmin}–${tmax.ext.tmax} °C (terendah di ${tmin.name}, tertinggi di ${tmax.name})`
      + (kts ? `; angin permukaan umumnya dari ${cmp(kts.ext.arah)}, maksimum ${kts.ext.kts} km/jam di ${kts.name}.` : '.'));
    const cells = R.rows.reduce((a,r)=>a+r.cells,0), dis = R.rows.reduce((a,r)=>a+r.dis,0), frac = cells ? dis/cells : 0;
    const conf = frac<0.05 ? 'tinggi' : frac<0.20 ? 'sedang' : 'rendah';
    lines.push(`Keyakinan: ${conf} (${dis} dari ${cells} sel kecamatan×jam model deterministik tidak sepakat soal hujan).`);
    const bal = info.pro > info.con ? 'faktor pendukung lebih banyak daripada penghambat' : (info.pro < info.con ? 'faktor penghambat lebih banyak daripada pendukung' : 'faktor pendukung dan penghambat berimbang');
    lines.push(`Kesimpulan hari ke-${idx+1}: ${bal} (${info.pro} pendukung, ${info.con} penghambat) → ${rainPhrase(peak, p10<0?null:p10, rainDet)}.`);
    Object.assign(info, { peak, p10: p10<0?null:p10, rainDet, top, slot: sl && sl.sh, tmin: tmin && tmin.ext.tmin, tmax: tmax && tmax.ext.tmax, conf });
  } else lines.push('Hujan: data ensemble/deterministik hari ini belum tersedia.');
  return { text: lines.join('\n'), info };
}

function buildNarrative(date, reg, dyn, lv, R){
  const opts = [...$('anDay').options].map(o=>o.value), i0 = Math.max(0, opts.indexOf(date));
  const days = opts.slice(i0, i0+NARR_DAYS);
  const out = [`ANALISIS & PRAKIRAAN CUACA ${regName(reg).toUpperCase()} — ${dShort(days[0])}${days.length>1?' s.d. '+dShort(days[days.length-1]):''} ${new Date(days[0]+'T00:00:00').getFullYear()}`, ''];
  // 1. skala besar
  out.push('A. FAKTOR SKALA BESAR (berlaku untuk beberapa hari ke depan)');
  if(dyn && dyn.items.length){
    const pro = dyn.items.filter(i=>i.side==='wet').map(i=>({txt:`${i.lab} ${i.val} — ${i.txt}`}));
    const con = dyn.items.filter(i=>i.side==='dry').map(i=>({txt:`${i.lab} ${i.val} — ${i.txt}`}));
    const neu = dyn.items.filter(i=>i.side==='neu').map(i=>({txt:`${i.lab} ${i.val} — ${i.txt}`}));
    out.push(`Sumber: ${dyn.b ? 'buletin BMKG '+dateLong(dyn.b.date,{day:'numeric',month:'long'})+' + indeks otomatis NOAA' : 'indeks otomatis NOAA (bukan buletin BMKG)'}.`);
    out.push('Mendukung hujan:', bulletList(pro,'✔'), 'Menghambat hujan:', bulletList(con,'✘'), 'Netral:', bulletList(neu,'•'));
    if(dyn.b) out.push(dyn.mn.hit ? 'Belokan angin/konvergensi/SST/gelombang pada buletin menyebut wilayah NTB (mendukung).' : 'Belokan angin/konvergensi, gelombang atmosfer, dan SST anomali pada buletin tidak mencakup NTB.');
    if(dyn.ov) out.push(`Ringkasan: ${dyn.ov.txt.toLowerCase()}.`);
  } else out.push('  Belum ada data dinamika atmosfer.');
  out.push('');
  // 2. per hari
  const infos = [];
  days.forEach((d,i)=>{ const b = dayBlock(d, i, reg, dyn); out.push('B'+(i+1)+'. '+b.text, ''); infos.push(b.info); });
  // 3. kesimpulan
  const c = [];
  c.push(`C. KESIMPULAN CUACA WILAYAH ${regName(reg).toUpperCase()}, ${dShort(days[0])}${days.length>1?' – '+dShort(days[days.length-1]):''}`);
  const ok = infos.filter(x=>x.peak!==undefined);
  if(ok.length){
    const peaks = ok.map(x=>x.peak==null?0:x.peak), rainiest = ok[peaks.indexOf(Math.max(...peaks))];
    let s = `Pada ${dShort(days[0])}${days.length>1?' hingga '+dShort(days[days.length-1]):''}, wilayah ${regName(reg)} secara umum `;
    const allLow = peaks.every(p=>p<0.25), anyHigh = peaks.some(p=>p>=0.5);
    s += anyHigh ? 'berpotensi mengalami hujan yang cukup berarti pada sebagian hari' : (allLow ? 'didominasi cuaca cerah berawan hingga berawan dengan peluang hujan kecil' : 'berawan dengan hujan ringan yang bersifat lokal pada sebagian hari');
    s += '.';
    c.push(s);
    ok.forEach((x,i)=>{
      c.push(`• ${dShort(x.date)}: ${wxShort(x.peak, x.p10, x.rainDet)}${x.peak!=null && x.peak>=0.10 ? ` (peluang hujan hingga ${Math.round(x.peak*100)}%${x.top&&x.top.length?` di ${x.top.slice(0,3).join(', ')}`:''}${x.slot!=null?`, sekitar pukul ${String(x.slot).padStart(2,'0')}.00–${String((x.slot+3)%24).padStart(2,'0')}.00 WITA`:''})` : ''}; suhu ${x.tmin??'—'}–${x.tmax??'—'} °C; keyakinan ${x.conf}.`);
    });
    const trend = peaks.length>1 ? (peaks[peaks.length-1] > peaks[0]+0.15 ? 'Tren: peluang hujan meningkat menjelang akhir periode.' : (peaks[peaks.length-1] < peaks[0]-0.15 ? 'Tren: peluang hujan menurun menjelang akhir periode.' : 'Tren: peluang hujan relatif stabil sepanjang periode.')) : '';
    if(trend) c.push(trend);
    c.push(`Hari dengan peluang hujan tertinggi: ${dLong(rainiest.date)}${rainiest.peak!=null?` (${Math.round(rainiest.peak*100)}%)`:''}.`);
    const lowConf = ok.filter(x=>x.conf==='rendah').map(x=>dShort(x.date));
    if(lowConf.length) c.push(`Catatan: keyakinan rendah pada ${lowConf.join(', ')} — model tidak sepakat; pantau pembaruan model dan lakukan justifikasi pada sel bertanda *.`);
  } else c.push('Data belum cukup untuk menyusun kesimpulan.');
  out.push(c.join('\n'));
  return out.join('\n');
}

/* ---------- render utama ---------- */
function render(){
  const sec = $('analisisSection'); if(!sec || !state.pointsData.length) return;
  const daySel = $('anDay');
  const dates = [...new Set(state.pointsData[0].hours.map(h=>h.date))].sort();
  if(daySel.options.length !== dates.length){
    daySel.innerHTML = dates.map((d,i)=>`<option value="${d}">Hari ${i+1} — ${dateLong(d,{weekday:'short',day:'numeric',month:'short'})}</option>`).join('');
  }
  const date = daySel.value || dates[0], reg = $('anReg').value;
  const dyn = renderDyn(date), lv = renderHum(reg, date), R = renderRain(date, reg);
  const auto = buildNarrative(date, reg, dyn, lv, R);
  const saved = load(KEY_NARR, {})[`${date}|${reg}`];
  const ta = $('anNarrText');
  ta.value = saved && saved.text ? saved.text : auto;
  $('anNarrMsg').textContent = saved && saved.text ? 'Menampilkan versi yang kamu edit. "Susun ulang" untuk kembali ke otomatis.' : 'Disusun otomatis dari data di atas — boleh diedit lalu disimpan.';
}
async function loadLevels(){
  LEVELS_ERR = null; LEVELS = null; render();
  try{ await fetchLevels(); }catch(e){ LEVELS_ERR = e.message; }
  render();
}
function initWave(){
  if(!$('anWave')) return;
  const img = $('waveImg'), msg = $('waveMsg');
  const upd = ()=>{
    const v = $('waveVar').value, w = $('waveType').value, a = $('waveAvg').value;
    const url = `https://ncics.org/pub/mjo/v2/map/${v}.cfs.${w}.indonesia.${a}.png`;
    msg.innerHTML = `Memuat peta… <a href="${url}" target="_blank" rel="noopener">buka gambar</a>`;
    img.onload = ()=>{ msg.innerHTML = `Kiri: observasi 4 hari terakhir, kanan: prakiraan CFS 4 hari ke depan; kontur −12/−36 W m⁻² = fase konvektif aktif tiap gelombang (hitam MJO, biru Kelvin, merah ER, ungu Low). Sumber: <a href="https://ncics.org/mjo/" target="_blank" rel="noopener">NCICS/NC State — Carl Schreck</a> (diperbarui harian ±16 UTC). Bukan produk BMKG.`; };
    img.onerror = ()=>{ msg.innerHTML = `Gambar NCICS tidak dapat dimuat (server NCICS/koneksi). <a href="${url}" target="_blank" rel="noopener">Coba buka langsung</a>.`; };
    img.src = url + '?h=' + new Date().toISOString().slice(0,13);
  };
  ['waveVar','waveType','waveAvg'].forEach(id=>$(id).addEventListener('change', upd));
  const sync = ()=>{ const w = waveManual($('anDay').value); $('waveKelvin').value = w.kelvin||''; $('waveER').value = w.er||''; };
  const store = ()=>{ const all = load(KEY_WAVE, {}), d = $('anDay').value; all[d] = { kelvin:$('waveKelvin').value, er:$('waveER').value }; if(!all[d].kelvin && !all[d].er) delete all[d]; save(KEY_WAVE, all); render(); };
  $('waveKelvin').addEventListener('change', store); $('waveER').addEventListener('change', store);
  $('anDay').addEventListener('change', sync); sync(); upd();
}
function init(){
  if(!$('analisisSection')) return;
  $('anReg').innerHTML = Object.entries(REGS).map(([k,v])=>`<option value="${k}">${v}</option>`).join('');
  $('anDay').addEventListener('change', render);
  $('anReg').addEventListener('change', render);
  $('anNarrSave').onclick = ()=>{
    const date = $('anDay').value, reg = $('anReg').value, all = load(KEY_NARR, {});
    all[`${date}|${reg}`] = { text:$('anNarrText').value, ts:Date.now() }; save(KEY_NARR, all);
    flashBtn('anNarrSave','Tersimpan ✓'); $('anNarrMsg').textContent = 'Versi yang kamu edit tersimpan di browser ini.';
  };
  $('anNarrReset').onclick = ()=>{
    const date = $('anDay').value, reg = $('anReg').value, all = load(KEY_NARR, {}); delete all[`${date}|${reg}`]; save(KEY_NARR, all); render();
  };
  $('anNarrCopy').onclick = async ()=>{
    try{ await navigator.clipboard.writeText($('anNarrText').value); flashBtn('anNarrCopy','Tersalin ✓'); }
    catch(e){ flashBtn('anNarrCopy','Clipboard diblokir'); }
  };
  initDynControls();
  render();
  initWave();
  loadLevels();
}
window.initAnalisis = init;
window.renderAnalisis = render;
})();
