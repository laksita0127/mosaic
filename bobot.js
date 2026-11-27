/* ==========================================================================
   MOSAIC — BOBOT MODEL DARI HASIL VERIFIKASI (window.MODEL_W)
   Kesepakatan 4 model & peluang ensemble gabungan semula memakai bobot SAMA. Modul ini menghitung bobot per model
   dari kinerja nyatanya (CSI hujan >=1 mm/3 jam vs CMORPH) pada N hari terakhir, per lead time (hari ke-0..3).
   Karena jendela berjalan (30 hari), bobot otomatis mengikuti musim (kemarau -> peralihan -> hujan).

   Rumus (sengaja sederhana & bisa dijelaskan):
     r_k   = CSI_k / rata²(CSI)               (kinerja relatif model k)
     λ     = E / (E + 40)                     (E = jumlah kejadian hujan; sampel kecil -> bobot ditarik ke 1)
     w_k   = 1 + λ (r_k - 1), dibatasi 0,5..1,6, lalu dinormalkan sehingga rata² bobot = 1 (jumlah = 4)
   Dipakai HANYA untuk rata² curah hujan 4 model (srcHour 'avg'). Suara "≥2 model basah" & peluang ensemble tetap bobot sama:
   uji jujur 27 Okt–26 Nov 2026 (137 kejadian) -> rata² berbobot CSI 0,33->0,34, suara berbobot 0,30->0,27 (lebih buruk).
   Data verifikasi kosong / lama (>10 hari) / kejadian <10 -> bobot sama (1) = perilaku lama.

   Ekspor: window.MODEL_W = { enabled(), setEnabled(b), get(lead), forDate(dateStr), rolling(i, lead), info(lead), leadFor(dateStr) }
   ========================================================================== */
(function(){
'use strict';
const PARAM = { ecmwf:'ecmwf_ifs025', gfs:'gfs_seamless', icon:'icon_seamless', aifs:'ecmwf_aifs025_single' };
const KEYS = Object.keys(PARAM);
const WIN_DAYS = 30, THR = 1.0, K_SHRINK = 40, MIN_EV = 10, W_MIN = 0.5, W_MAX = 1.6, STALE_DAYS = 10;
const LS = 'mosaic.bobotModel';
const H3 = 3*3600e3;
const EQUAL = () => Object.fromEntries(KEYS.map(k=>[k,1]));

function store(get, val){ try{ return get ? localStorage.getItem(LS) : localStorage.setItem(LS, val); }catch(e){ return null; } }
let on = store(true) !== '0';                           // bawaan: aktif

function V(){ return window.VERIF || null; }
function startMs(){ return Date.parse(V().start); }          // "2026-09-27T00:00Z"
function lastObsIdx(){
  const v = V(); let last = -1;
  v.pts.forEach(p=>{ const o = v.obs[p.id]; for(let i=o.length-1;i>last;i--) if(o[i]!=null){ last = i; break; } });
  return last;
}

// skor CSI tiap model pada jendela verifikasi [from, to) untuk satu lead
function csiRange(from, to, lead){
  const v = V(), L = String(lead), c = Object.fromEntries(KEYS.map(k=>[k,{h:0,m:0,f:0}]));
  let ev = 0, n = 0;
  v.pts.forEach(p=>{
    const o = v.obs[p.id];
    for(let i=Math.max(0,from); i<Math.min(to, v.n); i++){
      if(o[i]==null) continue;
      const f = KEYS.map(k=>v.fc[p.id][PARAM[k]] && v.fc[p.id][PARAM[k]][L] ? v.fc[p.id][PARAM[k]][L][i] : null);
      if(f.some(x=>x==null)) continue;
      const ob = o[i] >= THR; n++; if(ob) ev++;
      KEYS.forEach((k,j)=>{ const fc = f[j] >= THR, s = c[k]; if(ob&&fc) s.h++; else if(ob) s.m++; else if(fc) s.f++; });
    }
  });
  const csi = Object.fromEntries(KEYS.map(k=>{ const s = c[k], d = s.h+s.m+s.f; return [k, d ? s.h/d : null]; }));
  return { csi, ev, n };
}
function toWeights(sc){
  const vals = KEYS.map(k=>sc.csi[k]);
  if(sc.ev < MIN_EV || vals.some(x=>x==null)) return null;
  const mean = vals.reduce((a,b)=>a+b,0)/vals.length; if(!(mean>0)) return null;
  const lam = sc.ev/(sc.ev+K_SHRINK);
  const w = KEYS.map(k=>Math.max(W_MIN, Math.min(W_MAX, 1 + lam*(sc.csi[k]/mean - 1))));
  const s = w.reduce((a,b)=>a+b,0)/w.length;
  return Object.fromEntries(KEYS.map((k,j)=>[k, w[j]/s]));
}

// bobot operasional (dipakai di peta/tabel): N hari terakhir yang ada pengamatannya
const cache = {};
function compute(lead){
  const v = V();
  const res = { w: EQUAL(), active:false, reason:'', ev:0, n:0, csi:null, from:null, to:null, lead };
  if(!v || !v.fc){ res.reason = 'data verifikasi belum tersedia'; return res; }
  lead = Math.max(0, Math.min(3, lead|0)); res.lead = lead;
  const last = lastObsIdx(); if(last < 0){ res.reason = 'belum ada pengamatan'; return res; }
  const lastMs = startMs() + last*H3;
  res.to = new Date(lastMs + 8*3600e3).toISOString().slice(0,10);
  if((Date.now() - lastMs)/86400e3 > STALE_DAYS){ res.reason = `data verifikasi lama (pengamatan terakhir ${res.to})`; return res; }
  const from = last + 1 - WIN_DAYS*8;
  res.from = new Date(startMs() + Math.max(0,from)*H3 + 8*3600e3).toISOString().slice(0,10);
  const sc = csiRange(from, last+1, lead); res.ev = sc.ev; res.n = sc.n; res.csi = sc.csi;
  const w = toWeights(sc);
  if(!w){ res.reason = `kejadian hujan baru ${sc.ev} (<${MIN_EV}) — belum cukup untuk membedakan model`; return res; }
  res.w = w; res.active = true; return res;
}
function info(lead){ const k = Math.max(0, Math.min(3, lead|0)); return cache[k] || (cache[k] = compute(k)); }

// lead (hari) suatu tanggal produk relatif hari ini WITA: hari ini = 0 (0–24 jam), besok = 1, …; >3 pakai bobot lead 3
function leadFor(dateStr){
  const today = new Date(Date.now() + 8*3600e3).toISOString().slice(0,10);
  const d = Math.round((Date.parse(dateStr+'T00:00:00Z') - Date.parse(today+'T00:00:00Z'))/86400e3);
  return Math.max(0, Math.min(3, isNaN(d) ? 0 : d));
}
function get(lead){ return on ? info(lead).w : EQUAL(); }
function forDate(dateStr){ return get(leadFor(dateStr)); }

// bobot "jujur" untuk uji ulang di tab Verifikasi: hanya memakai pengamatan yang SUDAH ada saat prakiraan jendela i dibuat
// (jendela < i - (lead+1) hari), sehingga skor kesepakatan berbobot tidak curang (bukan in-sample).
const rcache = {};
function rolling(i, lead){
  const key = i+':'+lead; if(rcache[key]) return rcache[key];
  const to = i - (lead+1)*8, sc = csiRange(to - WIN_DAYS*8, to, lead);
  return (rcache[key] = toWeights(sc) || EQUAL());
}

/* ---------- 2) KALIBRASI PELUANG HUJAN ENSEMBLE (≥1 mm/3 jam) ----------
   Pasangan (peluang gabungan, hujan CMORPH) dari ens_archive.json -> tabel keandalan per kelas peluang.
   Frekuensi teramati tiap kelas ditarik ke diagonal (A_SHR sampel semu), dibuat monoton (PAV), lalu dipakai sebagai peta
   peluang mentah -> peluang terkalibrasi (interpolasi linear). Aktif bila ≥300 pasangan & ≥20 kejadian; selain itu peluang mentah. */
const PB = [0, 0.05, 0.15, 0.25, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0001], A_SHR = 10, CAL_MIN_N = 300, CAL_MIN_EV = 20, CAL_DAYS = 45;
const LSC = 'mosaic.kalibrasiPeluang';
let onCal = (()=>{ try{ return localStorage.getItem(LSC) !== '0'; }catch(e){ return true; } })();
function relRange(from, to, lead){
  const v = V(); if(!v || !v.ens) return null;
  const nb = PB.length-1, n = Array(nb).fill(0), k = Array(nb).fill(0), sp = Array(nb).fill(0); let N = 0, E = 0;
  v.pts.forEach(p=>{
    const e = v.ens[p.id] && v.ens[p.id][String(lead)], o = v.obs[p.id]; if(!e) return;
    for(let i=Math.max(0,from); i<Math.min(to, v.n); i++){
      const f = e[i], ob = o[i]; if(f==null || ob==null) continue;
      let b = 0; while(b < nb-1 && f >= PB[b+1]) b++;
      n[b]++; sp[b] += f; N++; if(ob >= THR){ k[b]++; E++; }
    }
  });
  return { n, k, sp, N, E };
}
function fitCal(r){
  if(!r || r.N < CAL_MIN_N || r.E < CAL_MIN_EV) return null;
  const blocks = [];
  r.n.forEach((n,b)=>{
    const x = n ? r.sp[b]/n : (PB[b]+Math.min(1,PB[b+1]))/2;
    blocks.push({ y:(r.k[b] + A_SHR*x)/(n + A_SHR), w:n + A_SHR, xs:[x] });
    while(blocks.length>1 && blocks[blocks.length-2].y > blocks[blocks.length-1].y){
      const b2 = blocks.pop(), a = blocks.pop();
      blocks.push({ y:(a.y*a.w + b2.y*b2.w)/(a.w+b2.w), w:a.w+b2.w, xs:a.xs.concat(b2.xs) });
    }
  });
  const xy = []; blocks.forEach(b=>b.xs.forEach(x=>xy.push([x, b.y])));
  return [[0, xy[0][1]]].concat(xy, [[1, xy[xy.length-1][1]]]);
}
function applyCal(xy, p){
  if(!xy || p==null) return p;
  for(let j=1;j<xy.length;j++) if(p <= xy[j][0]){
    const [x0,y0] = xy[j-1], [x1,y1] = xy[j]; return Math.max(0, Math.min(1, x1>x0 ? y0 + (y1-y0)*(p-x0)/(x1-x0) : y1));
  }
  return xy[xy.length-1][1];
}
const ccache = {};
function calInfo(lead){
  lead = Math.max(0, Math.min(3, lead|0)); if(ccache[lead]) return ccache[lead];
  const v = V(), res = { lead, active:false, reason:'', N:0, E:0, rel:null, xy:null, days:0 };
  if(!v || !v.ens){ res.reason = 'arsip peluang ensemble belum ada (mulai terkumpul sejak pipeline ensemble menyimpannya)'; return (ccache[lead] = res); }
  const last = lastObsIdx(), r = relRange(last + 1 - CAL_DAYS*8, last + 1, lead);
  res.N = r.N; res.E = r.E; res.rel = r; res.issues = v.ens_issues || 0;
  if((Date.now() - (startMs() + last*H3))/86400e3 > STALE_DAYS){ res.reason = 'data verifikasi lama'; return (ccache[lead] = res); }
  res.xy = fitCal(r);
  if(!res.xy){ res.reason = `mengumpulkan arsip — ${r.N} pasangan / ${r.E} kejadian (perlu ≥${CAL_MIN_N} & ≥${CAL_MIN_EV})`; return (ccache[lead] = res); }
  res.active = true; return (ccache[lead] = res);
}
function poeCal(p, dateStr){ if(!onCal || p==null) return p; const I = calInfo(leadFor(dateStr)); return I.active ? applyCal(I.xy, p) : p; }
// uji jujur: kalibrasi untuk jendela i hanya dari pasangan yang pengamatannya sudah ada saat prakiraan dibuat
const crc = {};
function calRolling(i, lead){
  const d = Math.floor(i/8), key = d+':'+lead;
  if(!(key in crc)){ const to = d*8 - (lead+1)*8 + 8; crc[key] = fitCal(relRange(to - CAL_DAYS*8, to - 8, lead)); }
  return crc[key];
}

/* ---------- 3) KOREKSI BIAS PER JAM (slot WITA) ----------
   Per model & slot: faktor pengali f sehingga frekuensi "model ≥1 mm" = frekuensi hujan teramati di slot itu (quantile mapping di
   ambang 1 mm). f dibatasi 0,33..3 dan ditarik ke 1 bila kejadian sedikit (λ = E/(E+20), di ruang log). Butuh ≥40 sampel per slot. */
const SLOTS = [2,5,8,11,14,17,20,23], DIUR_DAYS = 30, LSD = 'mosaic.koreksiJam';
// Bawaan MATI — uji jujur 13 Okt–26 Nov 2026 (11 titik): hujan >=1 mm tidak membaik (CSI kesepakatan 0,32 -> 0,32, rata² 0,35 -> 0,33,
// alarm palsu naik); hujan >=5 mm sedikit naik (0,03 -> 0,08) tetapi hanya 3 -> 8 kejadian tepat. Prakirawan bisa menyalakannya di tab Verifikasi.
const DIUR_DEFAULT = false;
let onDiur = (()=>{ try{ const x = localStorage.getItem(LSD); return x==null ? DIUR_DEFAULT : x==='1'; }catch(e){ return DIUR_DEFAULT; } })();
function slotOfWin(i){ return new Date(startMs() + i*H3 + 8*3600e3).getUTCHours(); }
function diurFactors(from, to, lead){
  const v = V(), L = String(lead), acc = {};
  KEYS.forEach(k=>{ acc[k] = {}; SLOTS.forEach(s=>acc[k][s] = { fc:[], ev:0 }); });
  v.pts.forEach(p=>{
    const o = v.obs[p.id];
    for(let i=Math.max(0,from); i<Math.min(to, v.n); i++){
      if(o[i]==null) continue; const s = slotOfWin(i);
      KEYS.forEach(k=>{ const a = v.fc[p.id][PARAM[k]], f = a && a[L] ? a[L][i] : null; if(f==null) return; const r = acc[k][s]; r.fc.push(f); if(o[i]>=THR) r.ev++; });
    }
  });
  const out = {}, ev = {};
  KEYS.forEach(k=>{ out[k] = {}; ev[k] = {}; SLOTS.forEach(s=>{
    const r = acc[k][s], n = r.fc.length; let f = 1; ev[k][s] = r.ev;
    if(n >= 40){
      const fo = (r.ev + 0.5)/(n + 1), srt = r.fc.slice().sort((a,b)=>b-a), q = srt[Math.min(n-1, Math.floor(fo*n))];
      const raw = q > 0.05 ? THR/q : 3, lam = r.ev/(r.ev + 20);
      f = Math.exp(lam*Math.log(Math.max(0.33, Math.min(3, raw))));
    }
    out[k][s] = f;
  }); });
  return { f: out, ev };
}
const dcache = {};
function diurInfo(lead){
  lead = Math.max(0, Math.min(3, lead|0)); if(dcache[lead]) return dcache[lead];
  const v = V(); if(!v || !v.fc) return (dcache[lead] = { lead, active:false, f:null, reason:'data verifikasi belum tersedia' });
  const last = lastObsIdx();
  if(last < 0 || (Date.now() - (startMs() + last*H3))/86400e3 > STALE_DAYS) return (dcache[lead] = { lead, active:false, f:null, reason:'data verifikasi lama' });
  const r = diurFactors(last + 1 - DIUR_DAYS*8, last + 1, lead);
  return (dcache[lead] = { lead, active:true, f:r.f, ev:r.ev, reason:'' });
}
// faktor untuk model k pada slot (jam mulai WITA) tanggal dateStr; 1 bila dimatikan / data tidak cukup
function diur(k, dateStr, slotHour){
  if(!onDiur) return 1; const I = diurInfo(leadFor(dateStr));
  return I.active && I.f[k] ? (I.f[k][slotHour] || 1) : 1;
}
// jam data per jam Open-Meteo (presipitasi jam SEBELUMNYA) -> slot 3 jam yang memuatnya: jendela [T,T+3) = jam T+1..T+3
function slotOfHour(H){ const t = H - 1 - (((H - 1 - 2) % 3) + 3) % 3; return (t + 24) % 24; }
const drc = {};
function diurRolling(i, lead){
  const d = Math.floor(i/8), key = d+':'+lead;
  if(!(key in drc)){ const to = d*8 - (lead+1)*8; drc[key] = diurFactors(to - DIUR_DAYS*8, to, lead).f; }
  return drc[key];
}

window.MODEL_W = {
  keys: KEYS, param: PARAM, winDays: WIN_DAYS, calDays: CAL_DAYS, diurDays: DIUR_DAYS, slots: SLOTS, bins: PB,
  enabled: () => on,
  setEnabled(b){ on = !!b; store(false, on ? '1' : '0'); },
  get, forDate, rolling, info, leadFor,
  // kalibrasi peluang ensemble
  calEnabled: () => onCal, setCalEnabled(b){ onCal = !!b; try{ localStorage.setItem(LSC, onCal?'1':'0'); }catch(e){} },
  calInfo, poeCal, calRolling, applyCal,
  // koreksi per jam
  diurEnabled: () => onDiur, setDiurEnabled(b){ onDiur = !!b; try{ localStorage.setItem(LSD, onDiur?'1':'0'); }catch(e){} },
  diurInfo, diur, diurRolling, slotOfHour, slotOfWin,
};
})();
