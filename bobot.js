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

window.MODEL_W = {
  keys: KEYS, param: PARAM, winDays: WIN_DAYS,
  enabled: () => on,
  setEnabled(b){ on = !!b; store(false, on ? '1' : '0'); },
  get, forDate, rolling, info, leadFor,
};
})();
