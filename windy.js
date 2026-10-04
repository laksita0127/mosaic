/* ==========================================================================
   MOSAIC — ANIMASI ANGIN ala Windy: partikel mengalir mengikuti medan angin, warna = kecepatan.
   Lapisan Leaflet generik: new WindyLayer({ getUV:(lat,lon)=>[u,v] m/s | null, scale, vmax }).addTo(map)
   Medan kecepatan dicuplik ke grid piksel (10 px) tiap kali peta bergeser/zoom/berganti waktu, partikel membaca grid itu (murah).
   ========================================================================== */
(function(){
'use strict';
if(typeof L === 'undefined') return;
// palet kecepatan (m/s) -> warna terang, terbaca di peta gelap maupun terang
const STOPS = [[0,[110,150,255]],[3,[70,205,235]],[6,[90,225,150]],[10,[225,235,90]],[15,[255,170,70]],[22,[255,90,70]],[32,[255,70,200]]];
function colorAt(v){
  if(v <= STOPS[0][0]) return STOPS[0][1];
  for(let k=0;k<STOPS.length-1;k++){
    const [a,ca] = STOPS[k], [b,cb] = STOPS[k+1];
    if(v <= b){ const f = (v-a)/(b-a); return ca.map((c,i)=>Math.round(c+(cb[i]-c)*f)); }
  }
  return STOPS[STOPS.length-1][1];
}
const NB = 24;                                     // jumlah keranjang warna
const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

L.WindyLayer = L.Layer.extend({
  options: { scale:0.5, maxAge:90, fade:0.93, lineWidth:1.6, vmax:24, density:190, cell:10 },
  initialize(o){ L.setOptions(this, o); this._grid = null; this._parts = []; },
  onAdd(map){
    this._map = map;
    const c = this._c = L.DomUtil.create('canvas', 'windy-canvas');
    c.style.cssText = 'pointer-events:none;position:absolute;left:0;top:0;';
    map.getPanes().overlayPane.appendChild(c);
    this._legend = L.DomUtil.create('div', 'windy-legend', map.getContainer());
    const g = `linear-gradient(90deg,${STOPS.map(([v,cl])=>`rgb(${cl.join(',')}) ${Math.round(v/32*100)}%`).join(',')})`;
    this._legend.innerHTML = `<div style="font-size:10.5px;margin-bottom:3px">Kecepatan angin (km/jam)</div><div style="height:7px;background:${g};border-radius:3px"></div>`
      + `<div style="display:flex;justify-content:space-between;font-size:10px;margin-top:2px;opacity:.85"><span>0</span><span>11</span><span>22</span><span>36</span><span>54</span><span>80</span><span>115</span></div>`;
    map.on('moveend zoomend resize', this._reset, this);
    map.on('zoomstart', this._hide, this);
    this._reset(); this._running = true; this._loop();
  },
  onRemove(map){
    this._running = false; cancelAnimationFrame(this._raf);
    map.off('moveend zoomend resize', this._reset, this); map.off('zoomstart', this._hide, this);
    this._c.remove(); if(this._legend) this._legend.remove();
  },
  setField(fn){ this.options.getUV = fn; if(this._map) this._buildGrid(); },
  _hide(){ if(this._c) this._c.style.visibility = 'hidden'; },
  _reset(){
    const m = this._map; if(!m || !this._c) return;
    const sz = m.getSize(); if(!sz.x || !sz.y) return;
    const c = this._c; c.width = sz.x; c.height = sz.y; c.style.visibility = 'visible';
    L.DomUtil.setPosition(c, m.containerPointToLayerPoint([0,0]));
    this._ctx = c.getContext('2d'); this._ctx.clearRect(0,0,sz.x,sz.y);
    this._buildGrid();
    const n = Math.max(500, Math.min(3600, Math.round(sz.x*sz.y/this.options.density)));
    this._parts = Array.from({ length:n }, ()=>this._spawn({}, true));
  },
  _buildGrid(){
    const m = this._map, fn = this.options.getUV, sz = m.getSize(), cell = this.options.cell;
    if(!fn || !sz.x){ this._grid = null; return; }
    const nx = Math.ceil(sz.x/cell)+1, ny = Math.ceil(sz.y/cell)+1, u = new Float32Array(nx*ny), v = new Float32Array(nx*ny), ok = new Uint8Array(nx*ny);
    for(let j=0;j<ny;j++) for(let i=0;i<nx;i++){
      const ll = m.containerPointToLatLng([i*cell, j*cell]), r = fn(ll.lat, ll.lng);
      if(r){ const k = j*nx+i; u[k] = r[0]; v[k] = r[1]; ok[k] = 1; }
    }
    this._grid = { nx, ny, u, v, ok, cell, w:sz.x, h:sz.y };
  },
  _uv(x, y){                                        // bilinear di grid piksel
    const G = this._grid; if(!G) return null;
    const fx = x/G.cell, fy = y/G.cell, i = Math.floor(fx), j = Math.floor(fy);
    if(i < 0 || j < 0 || i >= G.nx-1 || j >= G.ny-1) return null;
    const a = j*G.nx+i, b = a+1, c = a+G.nx, d = c+1;
    if(!(G.ok[a] && G.ok[b] && G.ok[c] && G.ok[d])) return null;
    const wx = fx-i, wy = fy-j;
    return [ G.u[a]*(1-wx)*(1-wy) + G.u[b]*wx*(1-wy) + G.u[c]*(1-wx)*wy + G.u[d]*wx*wy, G.v[a]*(1-wx)*(1-wy) + G.v[b]*wx*(1-wy) + G.v[c]*(1-wx)*wy + G.v[d]*wx*wy ];
  },
  _spawn(p, randomAge){
    const G = this._grid, W = this._map.getSize();
    for(let t=0;t<6;t++){
      const x = Math.random()*W.x, y = Math.random()*W.y;
      if(this._uv(x, y)){ p.x = x; p.y = y; p.age = randomAge ? Math.floor(Math.random()*this.options.maxAge) : 0; p.ok = true; return p; }
    }
    p.ok = false; p.x = p.y = -10; p.age = 0; return p;
  },
  _loop(){
    if(!this._running) return;
    this._raf = requestAnimationFrame(()=>{ this._frame(); setTimeout(()=>this._loop(), 24); });      // ±30 fps
  },
  _frame(){
    const ctx = this._ctx, G = this._grid; if(!ctx || !G || reduceMotion || document.hidden || !this._map._container.offsetParent) return;
    const o = this.options, W = this._c.width, H = this._c.height;
    ctx.globalCompositeOperation = 'destination-in'; ctx.fillStyle = `rgba(0,0,0,${o.fade})`; ctx.fillRect(0, 0, W, H);     // ekor memudar
    if((this._n = (this._n||0)+1) % 5 === 0){            // bersihkan sisa alfa sangat tipis (pembulatan 8-bit membuat ekor tak pernah hilang total)
      const im = ctx.getImageData(0, 0, W, H), d = im.data;
      for(let i=3;i<d.length;i+=4) if(d[i] < 14) d[i] = 0;
      ctx.putImageData(im, 0, 0);
    }
    ctx.globalCompositeOperation = 'source-over'; ctx.lineWidth = o.lineWidth; ctx.lineCap = 'round';
    const buckets = Array.from({ length:NB }, ()=>[]);
    for(const p of this._parts){
      if(!p.ok || p.age++ > o.maxAge){ this._spawn(p); continue; }
      const uv = this._uv(p.x, p.y);
      if(!uv){ this._spawn(p); continue; }
      const sp = Math.hypot(uv[0], uv[1]), k = sp > 0.01 ? o.scale*Math.pow(sp, 0.75)/sp : 0;           // kompresi kecepatan: angin lemah tetap terlihat bergerak
      const nx = p.x + uv[0]*k, ny = p.y - uv[1]*k;                                                      // v positif = ke utara = y turun
      const b = Math.min(NB-1, Math.floor(sp/o.vmax*NB));
      buckets[b].push(p.x, p.y, nx, ny);
      p.x = nx; p.y = ny;
    }
    for(let b=0;b<NB;b++){
      const seg = buckets[b]; if(!seg.length) continue;
      const cl = colorAt((b+0.5)/NB*o.vmax);
      ctx.strokeStyle = `rgba(${cl[0]},${cl[1]},${cl[2]},0.92)`; ctx.beginPath();
      for(let k=0;k<seg.length;k+=4){ ctx.moveTo(seg[k], seg[k+1]); ctx.lineTo(seg[k+2], seg[k+3]); }
      ctx.stroke();
    }
  }
});
// peta dasar terang/gelap (Esri Canvas)
L.windyBase = function(dark){
  const k = dark ? 'Dark' : 'Light';
  return { base:`https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${k}_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
           ref:`https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${k}_Gray_Reference/MapServer/tile/{z}/{y}/{x}` };
};
})();
