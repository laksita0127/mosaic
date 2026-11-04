/* ==========================================================================
   MOSAIC — DRAF TAF WADB (Bandara Sultan Muhammad Salahuddin, Bima)
   Mengikuti: Peraturan BMKG No. 6/2024 + SOP Aerodrome Forecast BMKG 2025
     • validitas 12/24/30 jam, siklus 00/06/12/18 UTC, dikirim 1 jam sebelum validitas (maks. +15 menit)
     • angin (VRB <3 kt; hembusan bila ≥10 kt di atas rata²), visibilitas (pembulatan SOP), cuaca signifikan (RA/+RA/TS…), awan <5000 ft + CB/TCU
     • BECMG 1–4 jam, TEMPO (<1 jam tiap kejadian, total < setengah jendela), PROB30/40 hanya bersama TEMPO, ambang perubahan signifikan SOP
   Bahan: konsensus 4 model deterministik (ECMWF·GFS·ICON·AIFS) titik bandara + peluang ensemble gabungan + METAR WADB yang ditempel.
   INI DRAF berbasis model — wajib diperiksa/diubah senior forecaster sebelum diterbitkan.  Ekspor: window.initTaf()
   ========================================================================== */
(function(){
'use strict';
const ICAO = 'WADB', KEY_METAR = 'mosaic-metar', KEY_OUT = 'mosaic-taf-edit';
const $ = id => document.getElementById(id);
const pad = (n,w=2) => String(n).padStart(w,'0');
const KT = 1/1.852, H = 3600e3;
const avg = a => { const v = a.filter(x=>x!=null && !isNaN(x)); return v.length ? v.reduce((s,x)=>s+x,0)/v.length : null; };
const load = (k,d)=>{ try{ const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; }catch(e){ return d; } };
const save = (k,v)=>{ try{ localStorage.setItem(k, JSON.stringify(v)); }catch(e){} };
const esc = s => String(s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const ddhh = ms => { const d = new Date(ms); return pad(d.getUTCDate()) + pad(d.getUTCHours()); };
const ddhhmm = ms => { const d = new Date(ms); return pad(d.getUTCDate()) + pad(d.getUTCHours()) + pad(d.getUTCMinutes()) + 'Z'; };
const hhmmUTC = ms => { const d = new Date(ms); return `${pad(d.getUTCDate())}/${pad(d.getUTCHours())}Z`; };
const witaStr = ms => { const d = new Date(ms + 8*H); return `${pad(d.getUTCDate())}/${pad(d.getUTCHours())}.00 WITA`; };

/* ---------------- data bandara ---------------- */
let AP = null;                                   // { t:[epoch UTC ms], idx:Map, models:[...] }
function loadAirport(){
  const D = window.DET_DATA && window.DET_DATA.airport;
  if(!D || !D.time) return null;
  const t = D.time.map(s=> Date.parse(s.slice(0,16)+':00Z') - 8*H);          // waktu data = WITA -> UTC
  const idx = new Map(); t.forEach((v,i)=>idx.set(v,i));
  return { t, idx, h:D.hourly, models: window.DET_DATA.models };
}
const col = (v, m, i) => { const a = AP.h[`${v}_${m}`]; return a ? a[i] : null; };
const meanVar = (v, i) => avg(AP.models.map(m=>col(v,m,i)));
function windAt(i){                               // vektor rata² model (kt), hembusan
  let sx=0, sy=0, n=0, s=0;
  AP.models.forEach(m=>{ const sp = col('wind_speed_10m',m,i), d = col('wind_direction_10m',m,i); if(sp==null||d==null) return;
    const r = d*Math.PI/180; sx += sp*Math.sin(r); sy += sp*Math.cos(r); s += sp; n++; });
  if(!n) return null;
  const spd = Math.hypot(sx/n, sy/n)*KT, mean = s/n*KT, dir = (Math.atan2(sx,sy)*180/Math.PI+360)%360;
  const R = Math.hypot(sx/n, sy/n)/(s/n || 1);                         // konsistensi arah (0..1)
  return { dir, spd: Math.max(spd, mean*0.6), mean, R, gust: (()=>{ const g = meanVar('wind_gusts_10m', i); return g==null ? null : g*KT; })() };
}
function ensPoe(ms){                              // peluang gabungan ≥1/5/10/20 mm per 3 jam untuk slot 3-jam UTC yang memuat jam ini
  if(typeof ensPooledAt !== 'function' || !window.ENS_MULTI) return null;
  const d = new Date(ms), h = d.getUTCHours(), start = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), h - h%3);
  const w = new Date(start + 8*H), key = `${w.getUTCFullYear()}-${pad(w.getUTCMonth()+1)}-${pad(w.getUTCDate())}T${pad(w.getUTCHours())}:00`;
  const p = ensPooledAt('bandara', key);
  return p && p.nm>=2 && p.poe ? { p1:p.poe['1'], p5:p.poe['5'], p10:p.poe['10'], p20:p.poe['20'], slot:start } : null;
}

/* ---------------- keadaan per jam ---------------- */
const roundVis = v => v>=9999 ? 9999 : (v<=800 ? Math.floor(v/50)*50 : (v<5000 ? Math.floor(v/100)*100 : (v<9999 ? Math.floor(v/1000)*1000 : 9999)));
function layerFrom(cover, base){
  const amt = cover>=87.5 ? 'OVC' : (cover>=50 ? 'BKN' : (cover>=25 ? 'SCT' : (cover>=12.5 ? 'FEW' : null)));
  return amt ? { amt, base } : null;
}
function stateAt(ms, opt){
  const i = AP.idx.get(ms); if(i==null) return null;
  const j = i+1;                                                   // precip Open-Meteo = jam sebelumnya -> jam [i,i+1) = nilai di i+1
  const w = windAt(i) || { dir:0, spd:0, mean:0, R:1, gust:null };
  const rain = meanVar('precipitation', j) ?? 0;
  const cape = meanVar('cape', i) ?? 0, T = meanVar('temperature_2m', i), Td = meanVar('dew_point_2m', i), RH = meanVar('relative_humidity_2m', i) ?? 70;
  const sm = v => avg([i-1,i,i+1].map(k=> (k>=0 && k<AP.t.length) ? meanVar(v,k) : null));      // haluskan 3 jam agar awan tidak berkedip
  const cl = sm('cloud_cover_low') ?? 0, cm = sm('cloud_cover_mid') ?? 0;
  const codes = AP.models.map(m=>col('weather_code', m, j)).filter(c=>c!=null);
  const tsVotes = codes.filter(c=>c>=95).length;
  const poe = ensPoe(ms);
  // --- cuaca signifikan ---
  let cls = 0, wx = '';                                           // 0 tidak ada, 0.5 ringan, 1 RA, 2 +RA, 3 TSRA
  if(rain >= 7.6 || (poe && poe.p20>=0.5)) cls = 2;
  else if(rain >= 2.5 || (poe && poe.p5>=0.5)) cls = 1;
  else if(rain >= 0.2 || (poe && poe.p1>=0.5)) cls = 0.5;
  const ts = (cape>=1000 && rain>=1) || tsVotes>=2 || (poe && poe.p10>=0.35 && cape>=600);
  if(ts) cls = Math.max(cls, 3);
  wx = cls===3 ? 'TSRA' : cls===2 ? '+RA' : cls===1 ? 'RA' : (cls===0.5 && opt.light) ? '-RA' : '';
  // --- visibilitas ---
  let vis = 9999, br = false;
  if(cls===3) vis = 4000; else if(cls===2) vis = 3000; else if(cls===1) vis = 5000; else if(cls===0.5) vis = 8000;
  if(!cls && RH>=96 && w.spd<4){ vis = 5000; br = true; }
  const gv = AP.h['visibility_gfs_seamless'] ? AP.h['visibility_gfs_seamless'][i] : null;
  if(gv!=null && gv<4500) vis = Math.min(vis, gv);
  vis = roundVis(vis);
  if(br && !wx) wx = 'BR';
  // --- awan ---
  const lcl = (T!=null && Td!=null) ? Math.min(3500, Math.max(1500, Math.round(125*Math.max(0,T-Td)*3.281/100)*100)) : 2000;   // dasar kumulus (LCL), dibatasi 1500–3500 ft
  let coverLow = cl; if(cls>=1) coverLow = Math.max(coverLow, 60); else if(cls===0.5) coverLow = Math.max(coverLow, 30);
  const layers = [];
  const L1 = layerFrom(coverLow, lcl); if(L1) layers.push(L1);
  let conv = null;
  if(ts) conv = { amt: cls>=2 ? 'SCT' : 'FEW', base: lcl, type:'CB' };
  else if(cape>=800 && rain>=0.5) conv = { amt:'FEW', base: lcl, type:'TCU' };
  const ceil = (()=>{ const c = layers.find(l=>l.amt==='BKN'||l.amt==='OVC'); return c ? c.base : 99999; })();
  return { ms, w, wx, cls, vis, layers, conv, ceil, cape, rain, poe, T, Td, RH, ts };
}

/* ---------------- METAR ---------------- */
function parseMetar(txt){
  const lines = txt.split(/\n+/).map(l=>l.trim()).filter(l=>/\b(METAR|SPECI)\b/.test(l) && new RegExp('\\b'+ICAO+'\\b').test(l));
  if(!lines.length) return null;
  const ln = lines[lines.length-1].replace(/=/g,'').split(/\s+/), r = { raw: ln.join(' '), layers:[], wx:[], vis:null, w:null, ms:null };
  ln.forEach(tk=>{
    let m;
    if((m = tk.match(/^(\d{2})(\d{2})(\d{2})Z$/))) r.t = { d:+m[1], h:+m[2], m:+m[3] };
    else if((m = tk.match(/^(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT$/))) r.w = { dir: m[1]==='VRB' ? null : +m[1], spd:+m[2], gust: m[3]?+m[3]:null };
    else if(tk==='CAVOK'){ r.vis = 9999; r.cavok = true; }
    else if(/^\d{4}$/.test(tk) && r.vis==null) r.vis = +tk;
    else if((m = tk.match(/^(FEW|SCT|BKN|OVC)(\d{3})(CB|TCU)?$/))) r.layers.push({ amt:m[1], base:+m[2]*100, type:m[3]||null });
    else if(/^(NSC|SKC|NCD)$/.test(tk)) r.nsc = true;
    else if(/^[+-]?(VC)?(TS|SH|DZ|RA|BR|HZ|FG|FU|SQ|GR)+$/.test(tk)) r.wx.push(tk);
    else if((m = tk.match(/^(M?\d{2})\/(M?\d{2})$/))) r.temp = m[1], r.dew = m[2];
  });
  return r;
}
function metarState(mt, base){                      // METAR -> bentuk keadaan jam yang sama
  const wxs = mt.wx.join(' '); const ts = /TS/.test(wxs);
  const cls = ts ? 3 : /\+RA|\+SHRA/.test(wxs) ? 2 : /(?<![+-])(RA|SHRA)/.test(wxs) ? 1 : /-RA|-SHRA|DZ/.test(wxs) ? 0.5 : 0;
  const conv = mt.layers.find(l=>l.type); const low = mt.layers.filter(l=>!l.type && l.base<5000);
  const w = mt.w ? { dir: mt.w.dir==null ? base.w.dir : mt.w.dir, spd: mt.w.spd, mean: mt.w.spd, R: mt.w.dir==null ? 0 : 1, gust: mt.w.gust } : base.w;
  return Object.assign({}, base, { w, vis: mt.vis!=null ? roundVis(mt.vis) : base.vis,
    cls, wx: ts ? 'TSRA' : cls===2 ? '+RA' : cls===1 ? 'RA' : cls===0.5 ? '-RA' : (/BR/.test(wxs) ? 'BR' : ''),
    layers: low.slice(0,3), conv: conv ? { amt:conv.amt, base:conv.base, type:conv.type } : null,
    ceil: (()=>{ const c = low.find(l=>l.amt==='BKN'||l.amt==='OVC'); return c ? c.base : 99999; })(), fromMetar:true, ts });
}

/* ---------------- kriteria perubahan signifikan (SOP 2025, butir 11.i) ---------------- */
const VIS_T = [150,350,600,800,1500,3000,5000], CIG_T = [100,200,500,1000,1500];
const bucket = (v, T) => T.filter(t=>v>=t).length;
function dirDiff(a,b){ const d = Math.abs(a-b)%360; return d>180 ? 360-d : d; }
function signif(a, b, opt){
  const why = [];
  const as = Math.round(a.w.spd), bs = Math.round(b.w.spd);
  if(dirDiff(a.w.dir, b.w.dir)>=60 && (as>=10 || bs>=10) && a.w.R>0.35 && b.w.R>0.35) why.push('arah angin');
  if(Math.abs(as-bs)>=10) why.push('kecepatan angin');
  const ga = gustOf(a), gb = gustOf(b);
  if((ga!=null) !== (gb!=null) && Math.max(as,bs)>=15) why.push('hembusan');
  if(bucket(a.vis, VIS_T) !== bucket(b.vis, VIS_T)) why.push('visibilitas');
  const cls = x => opt.light ? x.cls : (x.cls===0.5 ? 0 : x.cls);
  if(cls(a) !== cls(b)) why.push('cuaca');
  if(bucket(a.ceil, CIG_T) !== bucket(b.ceil, CIG_T)) why.push('dasar awan');
  const low = x => x.layers.some(l=>(l.amt==='BKN'||l.amt==='OVC') && l.base<1500);
  if(low(a) !== low(b)) why.push('jumlah awan');
  if(!!a.conv !== !!b.conv || (a.conv && b.conv && a.conv.type !== b.conv.type)) why.push('CB/TCU');
  return why;
}
function gustOf(s){ const g = s.w.gust; return (g!=null && g - s.w.spd >= 10 && g >= 15) ? Math.round(g) : null; }

/* ---------------- penyandian ---------------- */
function windCode(w){
  const spd = Math.round(w.spd), g = gustOf({ w });
  if(spd === 0) return '00000KT';
  const vrb = spd < 3 || w.R < 0.25;
  const d = vrb ? 'VRB' : pad(Math.round(w.dir/10)*10 % 360 || 360, 3);
  return d + pad(Math.min(spd,99)) + (g ? 'G' + pad(g) : '') + 'KT';
}
const baseCode = b => pad(Math.round(b/100), 3);
function cloudCodes(s){
  const out = s.layers.slice(0,3).map(l=>l.amt + baseCode(l.base));
  if(s.conv && !(s.layers.some(l=>l.base===s.conv.base && false))) out.push(s.conv.amt + baseCode(s.conv.base) + s.conv.type);
  return out;
}
function wxCodes(s){ return s.wx ? [s.wx] : []; }
function weatherBlock(s, opt, forceFull){
  const cav = s.vis>=9999 && !s.wx && !s.layers.length && !s.conv;
  if(cav) return ['CAVOK'];
  const c = cloudCodes(s);
  const wxs = wxCodes(s);
  const parts = [String(s.vis).padStart(4,'0')];
  if(wxs.length) parts.push(...wxs);
  parts.push(...(c.length ? c : ['NSC']));
  return parts;
}
/* ---------------- susun TAF ---------------- */
function buildTaf(start, hours, opt, metar){
  const S = [];
  for(let k=0;k<hours;k++){ const s = stateAt(start + k*H, opt); if(!s) return { err:`Data model bandara tidak mencakup ${witaStr(start + k*H)} — tunggu pembaruan data.` }; S.push(s); }
  const notes = [];
  if(metar){
    const age = (start - metarMs(metar, start))/H;
    if(age <= 3.5 && age >= -1){ const ms = metarState(metar, S[0]); S[0] = Object.assign({}, ms, { ms:S[0].ms }); S[1] = Object.assign({}, metarState(metar, S[1]), { ms:S[1].ms });
      notes.push(`Kondisi awal mengikuti ${metar.raw.slice(0,90)} (2 jam pertama), lalu mengikuti konsensus model.`); }
    else notes.push('METAR yang ditempel terlalu lama/di luar jendela penerbitan — tidak dipakai.');
  }
  // keadaan awal = median 3 jam pertama
  const ref0 = S[0].fromMetar ? S[0] : repr(S.slice(0,3));
  const groups = [];
  let ref = ref0, h = 1, lastBecmgTo = 0;
  while(h < hours){
    const why = signif(ref, S[h], opt);
    if(!why.length){ h++; continue; }
    let r = h;                                                         // rentang datar: jam-jam yang mirip S[h] (toleransi celah 1 jam)
    while(r+1 < hours){
      if(!signif(S[h], S[r+1], opt).length) r++;
      else if(r+2 < hours && !signif(S[h], S[r+2], opt).length) r += 2;
      else break;
    }
    const L = r - h + 1, st = repr(S.slice(h, r+1));
    const returns = r+1 < hours && !signif(ref, S[r+1], opt).length;   // kembali ke keadaan semula setelah rentang ini
    if(returns && L <= 2){                                             // fluktuasi sementara -> TEMPO (jendela > 2x durasi)
      const win = Math.max(2*L+1, 3);
      let from = Math.max(0, h-1), to = Math.min(hours, from + win);
      if(to - from < win) from = Math.max(0, to - win);
      groups.push({ type:'TEMPO', from, to, st, prev:ref, why, L });
    } else {                                                           // perubahan bertahan -> BECMG 2 jam (1–4 jam menurut SOP)
      let from = Math.max(lastBecmgTo, h-1), to = Math.min(hours, Math.max(from+1, h+1));
      if(from >= hours) break;
      groups.push({ type:'BECMG', from, to, st, prev:ref, why });
      lastBecmgTo = to; ref = st;
    }
    h = r+1;
  }
  // PROB30/40 TEMPO dari ensemble: peluang hujan sedang (>=5 mm/3 jam) 30–49% pada slot yang belum diprakirakan hujan
  for(let k=0;k<hours;k+=1){
    const s = S[k], p = s.poe; if(!p) continue;
    const slotIdx = Math.floor((s.ms - start)/H);
    if(s.cls >= 1 || p.p5 < 0.30 || p.p5 >= 0.50) continue;
    if(k>0 && S[k-1].poe && S[k-1].poe.slot === p.slot && S[k-1].cls < 1 && S[k-1].poe.p5>=0.30) continue;      // sudah dicakup slot yang sama
    const from = Math.max(0, Math.floor((p.slot - start)/H)), to = Math.min(hours, from + 3);
    if(to - from < 1) continue;
    if(groups.some(g=> g.from < to && g.to > from)) continue;                                              // hindari tumpang tindih
    const tsl = (p.p10 >= 0.2 && s.cape >= 800);
    const base = ref0; const st = Object.assign({}, base, { cls: tsl ? 3 : 1, wx: tsl ? 'TSRA' : 'RA', vis: tsl ? 4000 : 5000,
      conv: tsl ? { amt:'FEW', base: s.layers[0] ? s.layers[0].base : 1800, type:'CB' } : null,
      layers: [{ amt: tsl ? 'SCT' : 'BKN', base: s.layers[0] ? s.layers[0].base : 1800 }] });
    groups.push({ type:'PROB', pct: p.p5 >= 0.40 ? 40 : 30, from, to, st, prev: base, why:['peluang ensemble'] });
  }
  groups.sort((a,b)=>a.from-b.from || (a.type==='PROB') - (b.type==='PROB'));
  return { S, groups, ref0, notes };
}
function repr(arr){                      // keadaan representatif untuk satu rentang jam: unsur terburuk/terpenting
  const sp = avg(arr.map(x=>x.w.spd)), sx = avg(arr.map(x=>Math.sin(x.w.dir*Math.PI/180))), cx = avg(arr.map(x=>Math.cos(x.w.dir*Math.PI/180)));
  const gmax = Math.max(...arr.map(x=>x.w.gust==null ? 0 : x.w.gust));
  const worst = arr.reduce((m,x)=> x.cls>m.cls ? x : m, arr[0]);                 // cuaca terberat
  const cover = x => x.layers.reduce((t,l)=>Math.max(t, {FEW:1,SCT:3,BKN:5,OVC:8}[l.amt]), 0);
  const cloudy = arr.reduce((m,x)=> cover(x)>cover(m) ? x : m, arr[0]);          // lapisan awan terpadat
  const convS = arr.find(x=>x.conv && x.conv.type==='CB') || arr.find(x=>x.conv) || null;
  const o = Object.assign({}, worst);
  o.vis = Math.min(...arr.map(x=>x.vis));
  o.layers = worst.cls>=1 ? worst.layers : cloudy.layers;
  o.conv = convS ? convS.conv : null;
  o.ceil = Math.min(...arr.map(x=>x.ceil));
  o.w = { dir:(Math.atan2(sx,cx)*180/Math.PI+360)%360, spd:sp, mean:sp, R:Math.hypot(sx,cx), gust: gmax>0 ? gmax : null };
  return o;
}
function formatTaf(res, start, hours, issue, opt){
  const end = start + hours*H, L = [];
  const ref0 = res.ref0;
  let head = `TAF ${ICAO} ${ddhhmm(issue)} ${ddhh(start)}/${ddhh(end)} ${windCode(ref0.w)} `;
  head += weatherBlock(ref0, opt).join(' ');
  if(opt.tx){
    const T = res.S.map(s=>s.T), mx = Math.max(...T), mn = Math.min(...T), im = T.indexOf(mx), in_ = T.indexOf(mn);
    const tc = v => (v<0 ? 'M' : '') + pad(Math.abs(Math.round(v)));
    head += ` TX${tc(mx)}/${ddhh(res.S[im].ms)}Z TN${tc(mn)}/${ddhh(res.S[in_].ms)}Z`;
  }
  L.push(head);
  res.groups.forEach(g=>{
    const a = start + g.from*H, b = start + g.to*H, per = `${ddhh(a)}/${ddhh(b)}`;
    const prev = g.prev, s = g.st;
    const elems = { wind: signifWind(prev, s), wx: true };
    const wxChanged = prev.vis !== s.vis || prev.wx !== s.wx || cloudCodes(prev).join()!==cloudCodes(s).join();
    let body = '';
    if(elems.wind) body += windCode(s.w) + ' ';
    if(wxChanged || g.type==='PROB'){
      const wb = weatherBlock(s, opt);
      if(!s.wx && prev.wx){ const i = wb.indexOf(String(s.vis).padStart(4,'0')); if(i>=0) wb.splice(i+1, 0, 'NSW'); }
      body += wb.join(' ');
    } else if(!elems.wind) body += weatherBlock(s, opt).join(' ');
    const lead = g.type==='PROB' ? `PROB${g.pct} TEMPO ${per}` : `${g.type} ${per}`;
    L.push(`${lead} ${body.trim()}`);
  });
  L[L.length-1] += '=';
  return L.join('\n');
}
// angin dicantumkan di kelompok perubahan hanya bila berubah signifikan menurut SOP (≥60° dengan ≥10 kt, ≥10 kt, atau hembusan)
function signifWind(a,b){
  const as = Math.round(a.w.spd), bs = Math.round(b.w.spd), both = a.w.R>0.35 && b.w.R>0.35;
  return (both && dirDiff(a.w.dir,b.w.dir)>=60 && (as>=10 || bs>=10)) || Math.abs(as-bs)>=10 || ((gustOf(a)!=null)!==(gustOf(b)!=null) && Math.max(as,bs)>=15);
}
function metarMs(m, near){
  if(!m.t) return near;
  const d = new Date(near); let c = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), m.t.d, m.t.h, m.t.m);
  if(c - near > 15*24*H) c = Date.UTC(d.getUTCFullYear(), d.getUTCMonth()-1, m.t.d, m.t.h, m.t.m);
  if(near - c > 15*24*H) c = Date.UTC(d.getUTCFullYear(), d.getUTCMonth()+1, m.t.d, m.t.h, m.t.m);
  return c;
}

/* ---------------- pemeriksa aturan SOP ---------------- */
function checkTaf(txt, hours){
  const res = [], ok = (c,msg)=> res.push({ ok:!!c, msg });
  const t = txt.trim();
  ok(/^TAF (AMD |COR )?WADB \d{6}Z \d{4}\/\d{4} /.test(t), 'Awalan "TAF WADB DDHHMMZ Y1Y1G1G1/Y2Y2G2G2" benar');
  ok(/=$/.test(t), 'Diakhiri tanda sama dengan (=)');
  const m = t.match(/ (\d{2})(\d{2})\/(\d{2})(\d{2}) /);
  if(m){ const dur = ((+m[3] - +m[1] + 31) % 31)*24 + (+m[4] - +m[2]); ok([12,24,30].includes(dur), `Validitas ${dur} jam (harus 12/24/30)`); ok([0,6,12,18].includes(+m[2]), 'Validitas dimulai 00/06/12/18 UTC'); }
  const lines = t.split('\n');
  const first = lines[0];
  ok(/ (VRB|\d{3})\d{2}(G\d{2,3})?KT /.test(first), 'Kelompok angin dddff(Gff)KT ada');
  ok(/ (CAVOK|\d{4} )/.test(first), 'Visibilitas / CAVOK ada');
  const wxn = (first.match(/ ([+-]?(TS|RA|SH|BR|FG|HZ|SQ)+)/g) || []).length; ok(wxn <= 3, 'Cuaca signifikan ≤ 3 kelompok');
  const lay = (first.match(/(FEW|SCT|BKN|OVC)\d{3}(?!CB|TCU)/g) || []).length; ok(lay <= 3, 'Lapisan awan ≤ 3 (CB/TCU tambahan)');
  ok(!/CAVOK.*(FEW|SCT|BKN|OVC|NSC)/.test(first), 'CAVOK tidak dipadu dengan awan');
  let overlap = false, prev = null;
  lines.slice(1).forEach(l=>{
    const g = l.match(/^(?:PROB(30|40) TEMPO|BECMG|TEMPO|FM) ?(\d{4})\/(\d{4})/);
    if(!g) return;
    const a = +g[2], b = +g[3], len = ((b%100) - (a%100) + (Math.floor(b/100)-Math.floor(a/100))*24);
    if(/^BECMG/.test(l)) ok(len>=1 && len<=4, `BECMG ${g[2]}/${g[3]} lamanya ${len} jam (1–4)`);
    if(/^PROB/.test(l)) ok(/^PROB(30|40) TEMPO/.test(l), `PROB${g[1]} dipasangkan dengan TEMPO`);
    if(/^TEMPO|^PROB/.test(l)) ok(len>=1, `TEMPO ${g[2]}/${g[3]} jendela valid`);
    if(prev && !/^PROB/.test(l) && a < prev.b && !/^PROB/.test(prev.l) ) overlap = true;
    prev = { a, b, l };
  });
  ok(!overlap, 'Tidak ada kelompok perubahan yang tumpang tindih');
  ok(!/PROB(?!30|40)/.test(t) && !/PROB(30|40) (BECMG|FM)/.test(t), 'PROB hanya 30/40 dan tidak dengan BECMG/FM');
  return res;
}

/* ---------------- UI ---------------- */
function cycles(){
  const now = Date.now(), out = [];
  let t = Date.UTC(new Date(now).getUTCFullYear(), new Date(now).getUTCMonth(), new Date(now).getUTCDate(), 0);
  for(let k=-1; out.length<8; k++){ const s = t + k*6*H; if(s - 0.75*H > now - 6*H) out.push(s); if(k>20) break; }
  return out;
}
function defaultCycle(list){ const now = Date.now(); return list.find(s=> s - 0.75*H > now) || list[0]; }
function render(){
  const list = cycles(), sel = $('tafCycle');
  if(!sel.options.length){ sel.innerHTML = list.map(s=>`<option value="${s}">${hhmmUTC(s)} UTC (${witaStr(s)}) — kirim ${witaStr(s-H).replace('/', '/')} s.d. +15 mnt</option>`).join(''); sel.value = defaultCycle(list); }
  AP = loadAirport();
  const box = $('tafOut'), chk = $('tafChecks'), basis = $('tafBasis'), meta = $('tafMeta');
  if(!AP){ box.value = ''; meta.textContent = 'Data bandara (det_data.js › airport) belum tersedia — jalankan workflow "Update model deterministik".'; chk.innerHTML = ''; basis.innerHTML = ''; return; }
  const start = +sel.value, hours = +$('tafHours').value, opt = { light: $('tafLight').checked, tx: $('tafTX').checked };
  const metarTxt = $('tafMetar').value, metar = metarTxt.trim() ? parseMetar(metarTxt) : null;
  if(metarTxt.trim() && !metar) meta.textContent = 'METAR WADB tidak terbaca di kotak (pastikan baris diawali METAR/SPECI WADB …).'; else meta.textContent = '';
  const res = buildTaf(start, hours, opt, metar);
  if(res.err){ box.value = ''; meta.textContent = res.err; chk.innerHTML = ''; basis.innerHTML = ''; return; }
  const issue = start - 1*H;
  const auto = formatTaf(res, start, hours, issue, opt);
  const saved = (load(KEY_OUT, {}))[`${start}|${hours}`];
  box.dataset.auto = auto; box.value = saved && saved.text ? saved.text : auto;
  $('tafNote').textContent = (saved && saved.text ? 'Menampilkan versi yang kamu edit (tombol "Susun ulang" untuk kembali ke otomatis). ' : '') + res.notes.join(' ');
  updateChecks(hours);
  // tabel dasar penyusunan
  const rows = res.S.map((s,k)=>`<tr><td>${pad(new Date(s.ms).getUTCHours())}Z</td><td>${windCode(s.w)}</td><td>${s.vis}</td><td>${s.wx||'—'}</td><td>${[...cloudCodes(s)].join(' ')||'NSC'}</td><td>${s.poe ? Math.round(s.poe.p5*100)+'%' : '—'}</td><td>${Math.round(s.cape)}</td><td>${s.rain.toFixed(1)}</td></tr>`).join('');
  basis.innerHTML = `<details><summary style="cursor:pointer;font-size:12px;color:var(--text-dim)">Dasar penyusunan per jam (konsensus 4 model${metar?' + METAR':''})</summary>
    <div class="produk-wrap" style="margin-top:6px"><table class="an-tbl"><thead><tr><th>UTC</th><th>Angin</th><th>Vis</th><th>Cuaca</th><th>Awan</th><th>P(≥5 mm/3j)</th><th>CAPE</th><th>Hujan mm/j</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="si-sub dim" style="margin-top:4px;line-height:1.5">Visibilitas, dasar awan, dan CB/TCU diturunkan dengan aturan sederhana dari hujan, RH, selisih suhu–titik embun (LCL), tutupan awan, dan CAPE — model tidak memprakirakannya langsung. Periksa terhadap METAR, radar, dan satelit.</div></details>`;
}
function updateChecks(hours){
  const items = checkTaf($('tafOut').value, hours);
  $('tafChecks').innerHTML = items.map(i=>`<div class="si-sub" style="color:${i.ok?'#2f7d5a':'#b0402f'}">${i.ok?'✔':'✘'} ${esc(i.msg)}</div>`).join('');
}
function init(){
  if(!$('tafSection')) return;
  const refresh = ()=>render();
  ['tafCycle','tafHours','tafLight','tafTX'].forEach(id=>$(id).addEventListener('change', refresh));
  const mt = load(KEY_METAR, {}); $('tafMetar').value = mt.text || '';
  $('tafMetarSave').onclick = ()=>{ save(KEY_METAR, { text:$('tafMetar').value, ts:Date.now() }); render(); flash('tafMetarSave','Tersimpan ✓'); };
  $('tafBuild').onclick = ()=>{ const a = load(KEY_OUT, {}); delete a[`${$('tafCycle').value}|${$('tafHours').value}`]; save(KEY_OUT, a); render(); };
  $('tafSave').onclick = ()=>{ const a = load(KEY_OUT, {}); a[`${$('tafCycle').value}|${$('tafHours').value}`] = { text:$('tafOut').value, ts:Date.now() }; save(KEY_OUT, a); updateChecks(+$('tafHours').value); flash('tafSave','Tersimpan ✓'); };
  $('tafCopy').onclick = async ()=>{ try{ await navigator.clipboard.writeText($('tafOut').value); flash('tafCopy','Tersalin ✓'); }catch(e){ flash('tafCopy','Clipboard diblokir'); } };
  $('tafOut').addEventListener('input', ()=>updateChecks(+$('tafHours').value));
  render();
}
function flash(id,msg){ const b = $(id); if(!b) return; const o = b.dataset.o || b.textContent; b.dataset.o = o; b.textContent = msg; setTimeout(()=>{ b.textContent = o; }, 1500); }
window.initTaf = init;
window.__taf = { parseMetar, checkTaf };
})();
