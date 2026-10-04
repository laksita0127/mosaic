/* ==========================================================================
   MOSAIC — PETA SINOPTIK per lapisan: kelembapan relatif (warna) + streamline angin + isobar MSL
   Lapisan: permukaan (10 m / 2 m), 850, 700, 500, 200 hPa.
   Data: sinoptik.js (ECMWF IFS HRES open data, 1°, langkah 6 jam, dipadatkan base64) — pipeline/ingest_synoptic.py
   Digambar sendiri di canvas Leaflet (tanpa pustaka tambahan). Ekspor: window.initSinoptik()
   ========================================================================== */
(function(){
'use strict';
let map, layer, S, stepSel, levelSel, rhChk, isoChk, strChk;
const cache = {};
const $ = id => document.getElementById(id);
const HARI = ['Min','Sen','Sel','Rab','Kam','Jum','Sab'], BLN = ['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'];
const witaOf = step => new Date(Date.parse(S.run) + (step+8)*3600e3);
const witaStr = step => { const d = witaOf(step); return `${HARI[d.getUTCDay()]} ${String(d.getUTCDate()).padStart(2,'0')} ${BLN[d.getUTCMonth()]} ${String(d.getUTCHours()).padStart(2,'0')}.00 WITA`; };
const witaDate = step => witaOf(step).toISOString().slice(0,10);
const LEVNAME = { '10':'Permukaan (angin 10 m, RH 2 m)', '850':'850 hPa', '700':'700 hPa', '500':'500 hPa', '200':'200 hPa' };
const VMAX = { '10':40, '850':60, '700':60, '500':80, '200':160 };      // km/jam untuk skala warna streamline

/* ---- decode paket base64 -> Float32Array [steps*nj*ni] ---- */
function decode(name){
  if(cache[name]) return cache[name];
  const bin = atob(S.fields[name]), n = bin.length, per = S.nj*S.ni;
  let out;
  if(name === 'msl'){
    out = new Float32Array(n/2);
    for(let i=0;i<out.length;i++){ let v = bin.charCodeAt(2*i) | (bin.charCodeAt(2*i+1)<<8); if(v>32767) v -= 65536; out[i] = v*S.scale.msl_mul + S.scale.msl_off; }
  } else {
    out = new Float32Array(n); const k = name[0]==='r' ? 1 : S.scale.wind;
    for(let i=0;i<n;i++){ let v = bin.charCodeAt(i); if(v>127) v -= 256; out[i] = v*k; }
  }
  return (cache[name] = { a:out, per });
}
const fieldAt = (name, si) => { const f = decode(name); return f.a.subarray(si*f.per, (si+1)*f.per); };
function sample(g, lat, lon){                 // bilinear pada grid flat [nj*ni], baris 0 = lat0 (utara)
  const fj = (S.lat0 - lat)/S.d, fi = (lon - S.lon0)/S.d;
  if(fj < 0 || fi < 0 || fj > S.nj-1 || fi > S.ni-1) return null;
  const j = Math.min(Math.floor(fj), S.nj-2), i = Math.min(Math.floor(fi), S.ni-2), wy = fj-j, wx = fi-i, N = S.ni;
  return g[j*N+i]*(1-wy)*(1-wx) + g[j*N+i+1]*(1-wy)*wx + g[(j+1)*N+i]*wy*(1-wx) + g[(j+1)*N+i+1]*wy*wx;
}
const speedColor = (kmh, vmax) => {            // biru -> hijau -> oranye -> merah
  const t = Math.max(0, Math.min(1, kmh/vmax)), stops = [[47,110,180],[40,160,140],[226,152,74],[200,70,55]];
  const x = t*(stops.length-1), k = Math.min(Math.floor(x), stops.length-2), f = x-k;
  return `rgb(${stops[k].map((c,i)=>Math.round(c+(stops[k+1][i]-c)*f)).join(',')})`;
};
// RH: coklat (kering) -> krem -> hijau muda -> biru-hijau (lembap)
const RH_STOPS = [[0,[140,90,43]],[20,[196,152,82]],[40,[240,222,160]],[60,[200,232,200]],[80,[110,196,190]],[100,[40,120,180]]];
function rhRGB(v){
  v = Math.max(0, Math.min(100, v));
  for(let k=0;k<RH_STOPS.length-1;k++){
    const [a,ca] = RH_STOPS[k], [b,cb] = RH_STOPS[k+1];
    if(v<=b){ const f = (v-a)/(b-a); return ca.map((c,i)=>Math.round(c+(cb[i]-c)*f)); }
  }
  return RH_STOPS[RH_STOPS.length-1][1];
}

/* ---- RH berwarna ---- */
function drawRH(ctx, m, g){
  const size = m.getSize(), K = 4, w = Math.ceil(size.x/K), h = Math.ceil(size.y/K);
  const off = document.createElement('canvas'); off.width = w; off.height = h;
  const o = off.getContext('2d'), img = o.createImageData(w,h);
  for(let y=0;y<h;y++) for(let x=0;x<w;x++){
    const ll = m.containerPointToLatLng([x*K+K/2, y*K+K/2]), v = sample(g, ll.lat, ll.lng); if(v==null) continue;
    const c = rhRGB(v), p = (y*w+x)*4; img.data[p]=c[0]; img.data[p+1]=c[1]; img.data[p+2]=c[2]; img.data[p+3]=165;
  }
  o.putImageData(img,0,0);
  ctx.imageSmoothingEnabled = true; ctx.drawImage(off, 0, 0, w*K, h*K);
}

/* ---- isobar: marching squares pada grid yang di-upsample 4x ---- */
function drawIsobars(ctx, m, g){
  const U = 4, nj = (S.nj-1)*U+1, ni = (S.ni-1)*U+1, V = new Float32Array(nj*ni);
  let mn = 1e9, mx = -1e9;
  for(let j=0;j<nj;j++) for(let i=0;i<ni;i++){
    const v = sample(g, S.lat0 - j*S.d/U, S.lon0 + i*S.d/U); V[j*ni+i] = v; if(v<mn) mn=v; if(v>mx) mx=v;
  }
  const P = (j,i)=> m.latLngToContainerPoint([S.lat0 - j*S.d/U, S.lon0 + i*S.d/U]);
  const size = m.getSize(), seen = {};
  ctx.font = '600 10.5px "IBM Plex Mono",monospace'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for(let lv = Math.ceil(mn/2)*2; lv <= mx; lv += 2){
    const major = lv % 4 === 0;
    ctx.strokeStyle = major ? '#2b3d52' : '#6b7d90'; ctx.lineWidth = major ? 1.4 : 0.9;
    ctx.beginPath();
    const labels = [];
    for(let j=0;j<nj-1;j++) for(let i=0;i<ni-1;i++){
      const a = V[j*ni+i], b = V[j*ni+i+1], c = V[(j+1)*ni+i+1], d = V[(j+1)*ni+i];
      const idx = (a>=lv?8:0)|(b>=lv?4:0)|(c>=lv?2:0)|(d>=lv?1:0);
      if(idx===0 || idx===15) continue;
      const pt = e => {                        // titik potong pada sisi e: 0 atas,1 kanan,2 bawah,3 kiri
        const [p0,p1,v0,v1] = e===0 ? [[j,i],[j,i+1],a,b] : e===1 ? [[j,i+1],[j+1,i+1],b,c] : e===2 ? [[j+1,i],[j+1,i+1],d,c] : [[j,i],[j+1,i],a,d];
        const t = (lv-v0)/(v1-v0), q0 = P(p0[0],p0[1]), q1 = P(p1[0],p1[1]);
        return [q0.x+(q1.x-q0.x)*t, q0.y+(q1.y-q0.y)*t];
      };
      const segs = { 1:[[3,2]], 2:[[2,1]], 3:[[3,1]], 4:[[0,1]], 5:[[0,3],[2,1]], 6:[[0,2]], 7:[[0,3]], 8:[[0,3]], 9:[[0,2]], 10:[[0,1],[3,2]], 11:[[0,1]], 12:[[3,1]], 13:[[2,1]], 14:[[3,2]] }[idx];
      segs.forEach(([e1,e2])=>{
        const p = pt(e1), q = pt(e2);
        if((p[0]<-20&&q[0]<-20)||(p[0]>size.x+20&&q[0]>size.x+20)||(p[1]<-20&&q[1]<-20)||(p[1]>size.y+20&&q[1]>size.y+20)) return;
        ctx.moveTo(p[0],p[1]); ctx.lineTo(q[0],q[1]);
        const mx_ = (p[0]+q[0])/2, my_ = (p[1]+q[1])/2, key = lv+'|'+Math.floor(mx_/260)+'|'+Math.floor(my_/200);
        if(major && !seen[key] && mx_>14 && mx_<size.x-14 && my_>10 && my_<size.y-10){ seen[key] = 1; labels.push([mx_,my_]); }
      });
    }
    ctx.stroke();
    labels.forEach(([x,y])=>{
      const t = String(lv); ctx.lineWidth = 3.5; ctx.strokeStyle = 'rgba(255,255,255,0.9)'; ctx.strokeText(t,x,y);
      ctx.fillStyle = '#1b2530'; ctx.fillText(t,x,y);
    });
  }
  // pusat tekanan rendah/tinggi (ekstrem lokal pada grid asli)
  for(let j=2;j<S.nj-2;j++) for(let i=2;i<S.ni-2;i++){
    const v = g[j*S.ni+i]; let lo = true, hi = true;
    for(let dj=-2;dj<=2&&(lo||hi);dj++) for(let di=-2;di<=2;di++){ if(!dj&&!di) continue; const w = g[(j+dj)*S.ni+i+di]; if(w<=v) lo=false; if(w>=v) hi=false; }
    if(!lo && !hi) continue;
    const p = m.latLngToContainerPoint([S.lat0 - j*S.d, S.lon0 + i*S.d]);
    if(p.x<0||p.y<0||p.x>size.x||p.y>size.y) continue;
    ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(255,255,255,0.9)';
    ctx.font = '700 15px "IBM Plex Sans",sans-serif'; ctx.fillStyle = lo ? '#c0392b' : '#2f6eb0';
    ctx.strokeText(lo?'L':'H',p.x,p.y-6); ctx.fillText(lo?'L':'H',p.x,p.y-6);
    ctx.font = '600 10px "IBM Plex Mono",monospace'; ctx.strokeText(String(Math.round(v)),p.x,p.y+7); ctx.fillStyle='#1b2530'; ctx.fillText(String(Math.round(v)),p.x,p.y+7);
  }
}

/* ---- streamline: seeded, jarak antar garis dijaga (occupancy grid) ---- */
function drawStreamlines(ctx, m, U, V, vmax, dark){
  const size = m.getSize(), CELL = 9, gw = Math.ceil(size.x/CELL), gh = Math.ceil(size.y/CELL), occ = new Uint8Array(gw*gh);
  const wind = (x,y)=>{
    const ll = m.containerPointToLatLng([x,y]), u = sample(U, ll.lat, ll.lng), v = sample(V, ll.lat, ll.lng);
    return u==null||v==null ? null : { u:u*3.6, v:v*3.6 };           // km/jam
  };
  const mark = (x,y)=>{ const i = Math.floor(x/CELL), j = Math.floor(y/CELL); if(i>=0&&j>=0&&i<gw&&j<gh) occ[j*gw+i] = 1; };
  const busy = (x,y,own)=>{ const i = Math.floor(x/CELL), j = Math.floor(y/CELL); return i<0||j<0||i>=gw||j>=gh ? true : (occ[j*gw+i] && !own.has(j*gw+i)); };
  const seeds = []; for(let y=10;y<size.y;y+=20) for(let x=10;x<size.x;x+=20) seeds.push([x+(Math.random()-.5)*12, y+(Math.random()-.5)*12]);
  for(let k=seeds.length-1;k>0;k--){ const r = Math.floor(Math.random()*(k+1)); [seeds[k],seeds[r]] = [seeds[r],seeds[k]]; }
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  const col = sp => dark ? '#1b2530' : speedColor(sp, vmax);          // di atas RH berwarna: garis gelap agar terbaca
  seeds.forEach(([sx,sy])=>{
    if(busy(sx,sy,new Set())) return;
    const w0 = wind(sx,sy); if(!w0) return;
    const own = new Set(), trace = dir=>{
      const pts = []; let x=sx, y=sy;
      for(let n=0;n<70;n++){
        const w = wind(x,y); if(!w) break; const sp = Math.hypot(w.u,w.v); if(sp<2) break;
        const nx = x + dir*w.u/sp*3, ny = y - dir*w.v/sp*3;
        if(busy(nx,ny,own)) break;
        own.add(Math.floor(ny/CELL)*gw+Math.floor(nx/CELL)); pts.push([nx,ny,sp]); x=nx; y=ny;
      }
      return pts;
    };
    const fw = trace(1), bw = trace(-1).reverse(), line = bw.concat([[sx,sy,Math.hypot(w0.u,w0.v)]], fw);
    if(line.length < 8) return;
    line.forEach(p=>mark(p[0],p[1]));
    for(let i=1;i<line.length;i++){
      ctx.strokeStyle = col(line[i][2]); ctx.lineWidth = dark ? 1.1 : 1.3;
      ctx.beginPath(); ctx.moveTo(line[i-1][0],line[i-1][1]); ctx.lineTo(line[i][0],line[i][1]); ctx.stroke();
    }
    [Math.floor(line.length*0.5), line.length-1].forEach(ai=>{        // panah di tengah & ujung
      if(ai<3) return; const a = line[ai], b = line[ai-3], ang = Math.atan2(a[1]-b[1], a[0]-b[0]);
      ctx.fillStyle = col(a[2]); ctx.beginPath(); ctx.moveTo(a[0],a[1]);
      ctx.lineTo(a[0]-6*Math.cos(ang-0.45), a[1]-6*Math.sin(ang-0.45)); ctx.lineTo(a[0]-6*Math.cos(ang+0.45), a[1]-6*Math.sin(ang+0.45)); ctx.closePath(); ctx.fill();
    });
  });
}

const SynLayer = L.Layer.extend({
  onAdd(m){ this._c = L.DomUtil.create('canvas','syn-canvas'); this._c.style.pointerEvents = 'none'; m.getPanes().overlayPane.appendChild(this._c);
    this._h = ()=>this.redraw(); m.on('moveend zoomend resize', this._h); this.redraw(); },
  onRemove(m){ m.off('moveend zoomend resize', this._h); this._c.remove(); },
  redraw(){
    const m = this._map; if(!m || !S) return;
    const sz = m.getSize(), c = this._c; c.width = sz.x; c.height = sz.y;
    L.DomUtil.setPosition(c, m.containerPointToLayerPoint([0,0]));
    const ctx = c.getContext('2d'); ctx.clearRect(0,0,sz.x,sz.y);
    const si = +stepSel.selectedIndex, lev = levelSel.value;
    if(rhChk.checked) drawRH(ctx, m, fieldAt('rh'+lev, si));
    if(strChk.checked) drawStreamlines(ctx, m, fieldAt('u'+lev, si), fieldAt('v'+lev, si), VMAX[lev], rhChk.checked);
    if(isoChk.checked) drawIsobars(ctx, m, fieldAt('msl', si));
    const grad = `linear-gradient(90deg,${RH_STOPS.map(([v,c])=>`rgb(${c.join(',')}) ${v}%`).join(',')})`;
    $('synLegend').innerHTML = `<b>${LEVNAME[lev]}</b> · ` + (rhChk.checked ? `RH (terhadap air): <span style="display:inline-block;vertical-align:middle;width:150px;height:10px;border:1px solid var(--border);background:${grad}"></span> 0→100% · ` : '')
      + (strChk.checked ? (rhChk.checked ? 'streamline angin (hitam) · ' : `streamline angin, warna = kecepatan: <span style="color:#2f6eb0">■</span> pelan → <span style="color:#28a08c">■</span> → <span style="color:#e2984a">■</span> → <span style="color:#c84637">■</span> ≥${VMAX[lev]} km/jam · `) : '')
      + (isoChk.checked ? 'isobar MSL tiap 2 hPa (tebal tiap 4), L/H = pusat tekanan rendah/tinggi' : '');
  }
});

function populateSteps(preferDate){
  stepSel.innerHTML = S.steps.map((st,i)=>`<option value="${i}">${witaStr(st)} (H+${st})</option>`).join('');
  if(preferDate){        // slot terdekat 14.00 WITA pada hari analisis
    let best = -1, bd = 1e12; S.steps.forEach((st,i)=>{ if(witaDate(st)===preferDate){ const d = Math.abs(witaOf(st).getUTCHours()-14); if(d<bd){ bd=d; best=i; } } });
    if(best>=0) stepSel.selectedIndex = best;
  }
}
function hover(e){
  const si = stepSel.selectedIndex, lev = levelSel.value, ll = e.latlng, r = sample(fieldAt('rh'+lev, si), ll.lat, ll.lng);
  if(r==null){ $('synHover').textContent = ''; return; }
  const u = sample(fieldAt('u'+lev, si), ll.lat, ll.lng)*3.6, v = sample(fieldAt('v'+lev, si), ll.lat, ll.lng)*3.6, p = sample(fieldAt('msl', si), ll.lat, ll.lng);
  const dir = (Math.atan2(-u,-v)*180/Math.PI+360)%360;
  $('synHover').textContent = `${ll.lat.toFixed(1)}°, ${ll.lng.toFixed(1)}° · RH ${Math.round(r)}% · angin dari ${typeof deg16==='function'?deg16(dir):Math.round(dir)+'°'} ${Math.round(Math.hypot(u,v))} km/jam · MSL ${p.toFixed(1)} hPa`;
}
function init(){
  const box = $('anSyn'); if(!box) return;
  S = window.SINOPTIK;
  if(!S || S.fmt !== 'packed1'){ $('synBody').innerHTML = '<div class="si-sub">Data sinoptik belum tersedia / format lama — jalankan workflow "Update peta sinoptik" lalu muat ulang.</div>'; return; }
  stepSel = $('synStep'); levelSel = $('synLevel'); rhChk = $('synRH'); isoChk = $('synIso'); strChk = $('synStr');
  populateSteps($('anDay') && $('anDay').value);
  map = L.map('synMap', { scrollWheelZoom:false, minZoom:4, maxZoom:8 }).setView([-6,118], 5);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', { attribution:'Tiles &copy; Esri · ECMWF open data (CC BY 4.0)', maxZoom:10 }).addTo(map);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}', { maxZoom:10 }).addTo(map);
  [['Bima',-8.5418,118.6922],['Dompu',-8.5401,118.4647]].forEach(([n,la,lo])=>L.circleMarker([la,lo],{radius:4,color:'#b0402f',weight:2,fillColor:'#fff',fillOpacity:1}).bindTooltip(n).addTo(map));
  layer = new SynLayer().addTo(map);
  const fresh = new Date(S.generated.replace('Z',':00Z'));
  $('synInfo').textContent = `${S.model} · run ${S.run.slice(0,10)} ${S.run.slice(11,13)}Z · diperbarui ${fresh.toISOString().slice(0,16).replace('T',' ')} UTC`;
  const refresh = ()=>layer.redraw();
  [stepSel, rhChk, isoChk, strChk].forEach(e=>e.addEventListener('change', refresh));
  levelSel.addEventListener('change', ()=>{ isoChk.checked = levelSel.value==='10'; refresh(); });   // isobar MSL hanya bermakna di permukaan
  isoChk.checked = levelSel.value==='10';
  const day = $('anDay'); if(day) day.addEventListener('change', ()=>{ populateSteps(day.value); refresh(); });
  $('synPrev').onclick = ()=>{ stepSel.selectedIndex = Math.max(0, stepSel.selectedIndex-1); refresh(); };
  $('synNext').onclick = ()=>{ stepSel.selectedIndex = Math.min(stepSel.options.length-1, stepSel.selectedIndex+1); refresh(); };
  map.on('mousemove', hover);
  setTimeout(()=>{ map.invalidateSize(); layer.redraw(); }, 200);
}
window.initSinoptik = init;
})();
