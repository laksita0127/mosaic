/* ==========================================================================
   MOSAIC — VERIFIKASI OTOMATIS: prakiraan model vs hujan pengamatan satelit (CMORPH), jendela 3 jam = slot produk (WITA)
   Data: verifikasi.js (pipeline/ingest_verif.py, harian). Metrik dihitung di browser sehingga periode/lead/ambang/titik bisa diganti.
   Ekspor: window.initVerif()
   ========================================================================== */
(function(){
'use strict';
const $ = id => document.getElementById(id);
const H3 = 3*3600e3;
const LAB = { ecmwf_ifs025:'ECMWF', gfs_seamless:'GFS', icon_seamless:'ICON', ecmwf_aifs025_single:'AIFS', avg:'Rata² 4 model', vote:'Kesepakatan (≥2 model)' };
const CLR = { ecmwf_ifs025:'#2b6cb0', gfs_seamless:'#c9702a', icon_seamless:'#2f9e6e', ecmwf_aifs025_single:'#7c5cbf', avg:'#1b2530', vote:'#8a3226' };
const LEADTXT = { 0:'0–24 jam', 1:'24–48 jam', 2:'48–72 jam', 3:'72–96 jam' };
const f2 = v => (v==null || isNaN(v)) ? '—' : v.toFixed(2);
const pad = n => String(n).padStart(2,'0');
let V = null;

function winInfo(i){
  const ms = Date.parse(V.start.replace('Z',':00Z').replace(':00:00Z',':00Z')) + i*H3;
  const w = new Date(ms + 8*3600e3);
  return { ms, slot: w.getUTCHours(), day: w.toISOString().slice(0,10) };
}
function build(opts){
  const ids = opts.pt==='all' ? V.pts.map(p=>p.id) : [opts.pt], rows = [];
  const from = Math.max(0, V.n - opts.days*8);
  ids.forEach(pid=>{
    for(let i=from;i<V.n;i++){
      const o = V.obs[pid][i]; if(o==null) continue;
      const m = {}; let ok = true;
      V.models.forEach(k=>{ const v = V.fc[pid][k][String(opts.lead)][i]; if(v==null) ok = false; m[k] = v; });
      if(!ok) continue;
      const wi = winInfo(i), vals = V.models.map(k=>m[k]);
      rows.push({ o, m, avg: vals.reduce((a,b)=>a+b,0)/vals.length, i, pid, slot: wi.slot, day: wi.day });
    }
  });
  return rows;
}
const evt = (src, r, thr) => src==='avg' ? r.avg>=thr : (src==='vote' ? V.models.filter(k=>r.m[k]>=thr).length>=2 : r.m[src]>=thr);
const val = (src, r) => src==='avg' || src==='vote' ? r.avg : r.m[src];
function scores(rows, src, thr){
  let h=0, mi=0, fa=0, cn=0;
  rows.forEach(r=>{ const o = r.o>=thr, f = evt(src, r, thr); if(o&&f) h++; else if(o&&!f) mi++; else if(!o&&f) fa++; else cn++; });
  const pod = h+mi ? h/(h+mi) : null, far = h+fa ? fa/(h+fa) : null, csi = h+mi+fa ? h/(h+mi+fa) : null, bias = h+mi ? (h+fa)/(h+mi) : null;
  let corr = null, mae = null, mean = null;
  if(rows.length>2){
    const x = rows.map(r=>r.o), y = rows.map(r=>val(src,r)), mx = x.reduce((a,b)=>a+b,0)/x.length, my = y.reduce((a,b)=>a+b,0)/y.length;
    let sxy=0, sxx=0, syy=0; for(let k=0;k<x.length;k++){ sxy += (x[k]-mx)*(y[k]-my); sxx += (x[k]-mx)**2; syy += (y[k]-my)**2; }
    corr = sxx>0 && syy>0 ? sxy/Math.sqrt(sxx*syy) : null; mean = my; mae = y.reduce((a,b,k)=>a+Math.abs(b-x[k]),0)/y.length;
  }
  return { h, mi, fa, cn, pod, far, csi, bias, corr, mae, mean, events:h+mi };
}
const SRC = () => V.models.concat(['avg','vote']);
const bar = (v, c) => v==null ? '—' : `<div style="position:relative;min-width:84px"><div style="position:absolute;left:0;top:0;bottom:0;width:${Math.round(Math.max(0,Math.min(1,v))*100)}%;background:${c};opacity:.22"></div><span style="position:relative">${f2(v)}</span></div>`;

function render(){
  if(!V) return;
  const opts = { days:+$('vfPeriod').value, lead:+$('vfLead').value, thr:+$('vfThr').value, pt:$('vfPt').value };
  const rows = build(opts), thr = opts.thr;
  const evAll = rows.filter(r=>r.o>=thr).length, srcs = SRC();
  const sc = Object.fromEntries(srcs.map(s=>[s, scores(rows, s, thr)]));
  const obsMean = rows.length ? rows.reduce((a,r)=>a+r.o,0)/rows.length : 0;
  const gen = new Date(V.generated.replace('Z',':00Z'));
  $('vfInfo').innerHTML = `Pembanding: <b>CMORPH</b> (hujan satelit per jam, NOAA CPC) · prakiraan: arsip lead time Open-Meteo · diperbarui <b>${gen.toISOString().slice(0,16).replace('T',' ')} UTC</b> · sampel <b>${rows.length}</b> jendela 3 jam, kejadian hujan ≥${thr} mm: <b>${evAll}</b> · rata² pengamatan ${obsMean.toFixed(2)} mm/3 jam`;
  // ---- kesimpulan ----
  const ind = V.models, ranked = ind.map(k=>({ k, s:sc[k] })).filter(x=>x.s.csi!=null).sort((a,b)=>b.s.csi-a.s.csi);
  let v = '';
  if(!rows.length) v = 'Belum ada data yang cocok untuk pilihan ini.';
  else if(evAll < 8) v = `<b>Sampel hujan terlalu sedikit</b> (${evAll} kejadian ≥${thr} mm/3 jam) untuk menyimpulkan model mana yang paling sesuai. Coba periode lebih panjang, ambang lebih rendah, atau tunggu musim hujan.`;
  else {
    const best = ranked[0], second = ranked[1], bc = sc.vote;
    const close = second && (best.s.csi - second.s.csi) < 0.05;
    v = `Berdasarkan <b>CSI</b>, model yang paling sesuai: <b style="color:${CLR[best.k]}">${LAB[best.k]}</b> (${f2(best.s.csi)})` + (second ? `, diikuti ${ranked.slice(1,3).map(x=>`${LAB[x.k]} (${f2(x.s.csi)})`).join(', ')}` : '') + '. '
      + (close ? 'Selisih antar model <b>kecil</b> (<0,05) — belum cukup untuk menyebut satu model unggul. ' : '')
      + (sc.avg.csi!=null ? `Rata² 4 model: CSI ${f2(sc.avg.csi)}${sc.avg.csi>best.s.csi+0.02 ? ' — <b>lebih baik dari model tunggal mana pun</b>, jadi menggabungkan model memang menolong. ' : (sc.avg.csi>=best.s.csi-0.02 ? ' — setara model terbaik dan biasanya lebih stabil antar musim. ' : '. ')}` : '')
      + (bc.csi!=null ? `Kesepakatan ≥2 model: CSI ${f2(bc.csi)}.` : '')
      + (evAll < 30 ? ` <span style="color:var(--warn)">Sampel masih kecil (${evAll} kejadian) — anggap sebagai petunjuk.</span>` : '');
  }
  $('vfVerdict').innerHTML = v;
  // ---- tabel ----
  const best = k => { const arr = srcs.map(s=>sc[s][k]).filter(x=>x!=null); return arr.length ? arr : [0]; };
  const bestCsi = Math.max(...best('csi')), bestPod = Math.max(...best('pod'));
  const bestFar = Math.min(...srcs.map(s=>sc[s].far).filter(x=>x!=null).concat([1]));
  const body = srcs.map(s=>{
    const x = sc[s], biasTxt = x.bias==null ? '—' : f2(x.bias), biasCls = x.bias==null ? '' : (x.bias>1.3 ? 'color:var(--bad)' : (x.bias<0.7 ? 'color:var(--warn)' : ''));
    const isCons = s==='avg' || s==='vote';
    return `<tr${isCons?' style="background:var(--panel-alt)"':''}><td style="text-align:left"><b style="color:${CLR[s]}">●</b> <b>${LAB[s]}</b></td>`
      + `<td>${bar(x.csi, CLR[s])}${x.csi===bestCsi && x.csi!=null ? ' <b title="terbaik">★</b>' : ''}</td><td>${bar(x.pod, '#2f7d5a')}</td><td>${bar(x.far, '#b0402f')}</td>`
      + `<td style="${biasCls}">${biasTxt}</td><td>${s==='vote'?'—':f2(x.corr)}</td><td>${s==='vote'?'—':f2(x.mae)}</td><td class="dim" style="color:var(--text-faint)">${x.h}/${x.mi}/${x.fa}</td></tr>`;
  }).join('');
  $('vfTable').innerHTML = `<table class="an-tbl"><thead><tr><th style="text-align:left">Sumber</th><th title="Critical Success Index: kejadian tepat / (tepat + terlewat + alarm palsu). 1 = sempurna">CSI ↑</th><th title="Probability of Detection: berapa persen hujan yang terjadi berhasil diprakirakan">POD ↑</th><th title="False Alarm Ratio: berapa persen prakiraan hujan yang ternyata tidak hujan">FAR ↓</th><th title="Bias frekuensi: 1 = jumlah prakiraan hujan sama dengan kejadian; >1 terlalu sering, <1 terlalu jarang">Bias</th><th title="Korelasi jumlah hujan 3 jam">Korelasi</th><th title="Selisih rata² mm/3 jam">MAE mm</th><th title="tepat / terlewat / alarm palsu">T/L/AP</th></tr></thead><tbody>${body}</tbody></table>`;
  // ---- per jam (WITA) ----
  const slots = [2,5,8,11,14,17,20,23];
  const heat = srcs.filter(s=>s!=='vote'||true).map(s=>{
    const tds = slots.map(sl=>{
      const rr = rows.filter(r=>r.slot===sl), x = scores(rr, s, thr), ev = x.events;
      if(!rr.length) return '<td>—</td>';
      const c = x.csi, bg = c==null ? 'transparent' : `rgba(47,125,90,${(0.12+0.55*c).toFixed(2)})`;
      return `<td style="background:${bg};${ev<3?'opacity:.55':''}" title="${ev} kejadian hujan pada slot ini">${c==null?'·':f2(c)}</td>`;
    }).join('');
    return `<tr><td style="text-align:left"><b style="color:${CLR[s]}">●</b> ${LAB[s]}</td>${tds}</tr>`;
  }).join('');
  const nEv = slots.map(sl=>rows.filter(r=>r.slot===sl && r.o>=thr).length);
  $('vfSlots').innerHTML = `<table class="an-tbl"><thead><tr><th style="text-align:left">CSI per slot (jam mulai, WITA)</th>${slots.map(s=>`<th>${pad(s)}.00</th>`).join('')}</tr></thead><tbody>${heat}<tr><td style="text-align:left;color:var(--text-faint)">jumlah kejadian hujan</td>${nEv.map(n=>`<td style="color:var(--text-faint)">${n}</td>`).join('')}</tr></tbody></table>`;
  // ---- grafik harian ----
  const byDay = {};
  rows.forEach(r=>{ const d = byDay[r.day] = byDay[r.day] || { n:0, o:0, m:Object.fromEntries(V.models.map(k=>[k,0])), avg:0 }; d.n++; d.o += r.o; V.models.forEach(k=>d.m[k]+=r.m[k]); d.avg += r.avg; });
  const npt = opts.pt==='all' ? V.pts.length : 1;
  const days = Object.keys(byDay).sort().filter(d=>byDay[d].n === 8*npt).map(d=>({ d, o:byDay[d].o/npt, m:Object.fromEntries(V.models.map(k=>[k, byDay[d].m[k]/npt])), avg:byDay[d].avg/npt }));
  if(days.length<2) $('vfChart').innerHTML = '<div class="si-sub">Data harian lengkap belum cukup untuk grafik.</div>';
  else {
    const W = 760, Hh = 220, L = 38, R = 8, T = 10, B = 26, ymax = Math.max(5, ...days.map(x=>Math.max(x.o, x.avg, ...V.models.map(k=>x.m[k])))) * 1.1, bw = (W-L-R)/days.length;
    const X = i => L + bw*(i+0.5), Y = v => T + (Hh-T-B)*(1 - v/ymax);
    let g = '';
    for(let t=0;t<=4;t++){ const vv = ymax*t/4; g += `<line x1="${L}" x2="${W-R}" y1="${Y(vv)}" y2="${Y(vv)}" stroke="currentColor" stroke-opacity=".12"/><text x="${L-4}" y="${Y(vv)+3}" font-size="9" text-anchor="end" fill="currentColor" opacity=".6">${vv.toFixed(0)}</text>`; }
    g += days.map((x,i)=>`<rect x="${X(i)-bw*0.32}" y="${Y(x.o)}" width="${bw*0.64}" height="${Hh-B-Y(x.o)}" fill="#8994a0" opacity=".45"><title>${x.d}: pengamatan ${x.o.toFixed(1)} mm</title></rect>`).join('');
    const line = (k,c,w,dash)=>`<polyline fill="none" stroke="${c}" stroke-width="${w}" ${dash?'stroke-dasharray="4 3"':''} points="${days.map((x,i)=>`${X(i).toFixed(1)},${Y(k==='avg'?x.avg:x.m[k]).toFixed(1)}`).join(' ')}"/>`;
    g += V.models.map(k=>line(k,CLR[k],1.4)).join('') + line('avg', CLR.avg, 2.4);
    const step = Math.ceil(days.length/10);
    g += days.map((x,i)=> i%step===0 ? `<text x="${X(i)}" y="${Hh-8}" font-size="9" text-anchor="middle" fill="currentColor" opacity=".65">${x.d.slice(8)}/${x.d.slice(5,7)}</text>` : '').join('');
    const leg = [['Pengamatan (batang)','#8994a0']].concat(V.models.map(k=>[LAB[k],CLR[k]])).concat([['Rata² 4 model',CLR.avg]]).map(([t,c])=>`<span style="margin-right:12px;white-space:nowrap"><b style="color:${c}">●</b> ${t}</span>`).join('');
    $('vfChart').innerHTML = `<svg viewBox="0 0 ${W} ${Hh}" style="width:100%;height:auto;color:var(--text)" role="img" aria-label="Hujan harian: pengamatan vs model">${g}</svg><div class="si-sub" style="margin-top:2px">${leg}</div><div class="si-sub dim" style="color:var(--text-faint)">Hujan harian (mm/hari, hari WITA) rata² ${npt>1?'6 titik':'titik terpilih'}.</div>`;
  }
}
function init(){
  const root = $('verifAuto'); if(!root) return;
  V = window.VERIF;
  if(!V){ $('vfInfo').innerHTML = 'Data verifikasi (verifikasi.js) belum tersedia — jalankan workflow "Update verifikasi".'; return; }
  $('vfPt').innerHTML = '<option value="all">Semua titik (6)</option>' + V.pts.map(p=>`<option value="${p.id}">${p.name}</option>`).join('');
  $('vfLead').innerHTML = V.leads.map(l=>`<option value="${l}">${LEADTXT[l]||('hari-'+l)}</option>`).join('');
  const maxDays = Math.floor(V.n/8); const dOpts = [7,14,30,45].filter(d=>d<=maxDays+1);
  $('vfPeriod').innerHTML = (dOpts.length ? dOpts : [maxDays]).map(d=>`<option value="${d}">${d} hari terakhir</option>`).join('');
  $('vfPeriod').value = String(dOpts.includes(30) ? 30 : (dOpts[dOpts.length-1] || maxDays));
  ['vfPeriod','vfLead','vfThr','vfPt'].forEach(id=>$(id).addEventListener('change', render));
  render();
}
window.initVerif = init;
})();
