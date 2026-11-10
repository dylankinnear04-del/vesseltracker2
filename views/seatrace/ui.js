(function () {
  'use strict';
  var E = ENGINE, D = E.build(), V = D.byId, H = E.H, DAY = E.DAY;
  var $ = function (id) { return document.getElementById(id); };
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function p2(n) { return String(n).padStart(2, '0'); }
  function fD(t) { var d = new Date(t); return p2(d.getUTCDate()) + ' ' + MON[d.getUTCMonth()] + ' ' + d.getUTCFullYear(); }
  function fDs(t) { var d = new Date(t); return p2(d.getUTCDate()) + ' ' + MON[d.getUTCMonth()]; }
  function fDT(t) { var d = new Date(t); return fD(t) + ' ' + p2(d.getUTCHours()) + ':' + p2(d.getUTCMinutes()) + 'Z'; }
  function iso(t) { return new Date(t).toISOString().slice(0, 16) + 'Z'; }
  function nlon(l) { return ((l + 180) % 360 + 360) % 360 - 180; }
  function fLat(v) { return Math.abs(v).toFixed(2) + '°' + (v >= 0 ? 'N' : 'S'); }
  function fLon(v) { v = nlon(v); return Math.abs(v).toFixed(2) + '°' + (v >= 0 ? 'E' : 'W'); }
  function dm(v, pos, neg) { var a = Math.abs(v), d = Math.floor(a), m = (a - d) * 60; return d + '°' + m.toFixed(1).padStart(4, '0') + '′' + (v >= 0 ? pos : neg); }
  var dur = E.fmtDur;
  function f1(x) { return (Math.round(x * 10) / 10).toFixed(1); }
  var TIERC = { P1: '#ff5f56', P2: '#f4a93b', P3: '#5aa9d6', P4: '#748797' };
  var ZC = { POLYMETALLIC_NODULE: '#38c2b0', RARE_EARTH_MUD: '#a585ff', COBALT_RICH_CRUST: '#d4955e', SEAFLOOR_MASSIVE_SULFIDE: '#ee6fa5' };
  var KEYCAPS = { DP: 1, RISER: 1, DRILL: 1, COLL: 1, LIFT: 1, HOV: 1 };

  /* ---------- local persistence (one browser only) ---------- */
  var store = (function () {
    var key = 'seatrace.v1', d = { cases: {}, watch: {}, intro: false };
    try { var s = localStorage.getItem(key); if (s) { var o = JSON.parse(s); d.cases = o.cases || {}; d.watch = o.watch || {}; d.intro = !!o.intro; } } catch (e) { }
    return { d: d, save: function () { try { localStorage.setItem(key, JSON.stringify(d)); } catch (e) { } } };
  })();
  function isWatch(v) { return store.d.watch[v.id] !== undefined ? store.d.watch[v.id] : !!v.watch; }
  function caseOf(id) { return store.d.cases[id] || { state: 'NEW', note: '' }; }
  var EVI = {}; D.events.forEach(function (e) { EVI[e.id] = e; });
  (function () { var tt = document.createElement('div'); tt.className = 'tltip'; tt.id = 'tltip'; document.body.appendChild(tt); })();

  /* ---------- state ---------- */
  var top = D.events[0] || null;   /* Survey Detector: a season can have no detections */
  var S = {
    tab: 'fleet', q: '', f: { flagged: false, watch: false, ret: false, active: false }, open: {}, sel: new Set(),
    focus: top ? top.vessel : (D.vessels[0] ? D.vessels[0].id : null), ev: top ? top.id : null, t: E.AS_OF, playing: false, timer: null,
    pri: { P1: true, P2: true, P3: true, P4: true }, model: 'ALL', brief: -1,
    layers: { zones: true, eez: true, ree: true, hot: true, grat: true, tracks: true, events: true, gaps: true, calls: true, known: false, coord: true, gfw: true },
    view: 'map', trackFrom: null, walk: null, showRef: false, layersSaved: null
  };
  D.events.forEach(function (e) { if (e.tier === 'P1' || e.tier === 'P2') S.sel.add(e.vessel); });
  if (top) S.open[V[top.vessel].flag] = true; S.open.JP = true;

  /* ---------- header stats ---------- */
  function renderStats() {
    var p12 = D.events.filter(function (e) { return e.tier === 'P1' || e.tier === 'P2'; }).length;
    $('stats').innerHTML =
      '<div class="stat opt"><b>' + D.stats.vessels + '</b><span>vessels</span></div>' +
      '<div class="stat opt"><b>' + D.events.length + '</b><span>detections</span></div>' +
      '<div class="stat p1"><b>' + p12 + '</b><span>P1–P2</span></div>' +
      '<div class="stat act"><b>' + D.stats.positionsRaw.toLocaleString() + '</b><span>AIS fixes</span></div>' +
      '<div class="stat opt"><b>' + fDs(E.T_START) + '–' + fDs(E.AS_OF) + '</b><span>' + (new Date(E.T_START).getUTCFullYear() === new Date(E.AS_OF).getUTCFullYear() ? new Date(E.AS_OF).getUTCFullYear() : new Date(E.T_START).getUTCFullYear() + '–' + new Date(E.AS_OF).getUTCFullYear()) + '</span></div>';
  }

  /* ---------- fleet browser ---------- */
  var FCH = [['flagged', 'Has detections'], ['ret', 'Same-port return'], ['watch', 'Mining watchlist']];
  function renderFChips() { $('fchips').innerHTML = FCH.map(function (c) { return '<button class="chip" type="button" data-f="' + c[0] + '" aria-pressed="' + S.f[c[0]] + '">' + c[1] + '</button>'; }).join(''); }
  function vMatch(v) {
    var q = S.q.trim().toLowerCase();
    if (q) { var hay = [v.name, v.mmsi, v.imo, v.callsign, E.CLASS[v.cls].label, v.country, v.flag].join(' ').toLowerCase(); if (hay.indexOf(q) < 0) return false; }
    if (S.f.flagged && !v.events.length) return false;
    if (S.f.active && !v.activeEv) return false;
    if (S.f.ret && !v.sameReturns) return false;
    if (S.f.watch && !isWatch(v)) return false;
    return true;
  }
  function stPill(v) {
    var s = v.activeEv ? '<span class="st act">' + esc(v.status) + '</span>' : v.inPort ? '<span class="st port">IN PORT</span>' : '<span class="st uw">' + esc(v.status) + '</span>';
    if (v.stale) s += ' <span class="st stale">STALE</span>';
    return s;
  }
  function renderFleet() {
    var list = D.vessels.filter(vMatch), groups = {};
    list.forEach(function (v) { (groups[v.flag] = groups[v.flag] || []).push(v); });
    var keys = Object.keys(groups).sort(function (a, b) { return groups[b].length - groups[a].length || E.COUNTRY[a].localeCompare(E.COUNTRY[b]); });
    var q = S.q.trim() !== '';
    var html = keys.map(function (k) {
      var vs = groups[k].sort(function (a, b) { return ((b.top && b.top.priScore) || 0) - ((a.top && a.top.priScore) || 0) || a.name.localeCompare(b.name); });
      var open = q || !!S.open[k], nev = vs.reduce(function (s, v) { return s + v.events.length; }, 0);
      var allSel = vs.every(function (v) { return S.sel.has(v.id); });
      var rows = !open ? '' : '<div class="grp-sel"><button class="link" type="button" data-grpsel="' + k + '">' + (allSel ? 'Clear all from ' : 'Show all from ') + esc(E.COUNTRY[k]) + '</button></div>' + vs.map(function (v) {
        return '<div class="vrow' + (S.focus === v.id ? ' is-focus' : '') + '">' +
          '<input type="checkbox" id="cb-' + v.id + '" data-sel="' + v.id + '"' + (S.sel.has(v.id) ? ' checked' : '') + ' aria-label="Show ' + esc(v.name) + ' track on map">' +
          '<button class="vbtn" type="button" data-focus="' + v.id + '"><span class="nm">' + (isWatch(v) ? '★ ' : '') + esc(v.name) + '</span><span class="sub">' + stPill(v) + ' ' + esc(E.CLASS[v.cls].label.replace(' vessel', '')) + '</span></button>' +
          (v.top ? '<span class="ptag ' + v.top.tier + '" title="Top priority">' + v.top.tier + '</span>' : '<span class="ptag none" title="No detections">–</span>') + '</div>';
      }).join('');
      return '<div class="grp"><button class="grp-h" type="button" data-grp="' + k + '" aria-expanded="' + open + '"><svg class="chev" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M3 1l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.6"/></svg><span class="flag">' + k + '</span><span class="nm">' + esc(E.COUNTRY[k]) + '</span><span class="evc">' + (nev ? nev + ' det' : '') + '</span><span class="cnt">' + vs.length + '</span></button>' + rows + '</div>';
    }).join('');
    $('fleet').innerHTML = html || '<div class="empty">No vessels match. Clear the search or filters.</div>';
    $('ct-fleet').textContent = list.length;
    $('selcount').textContent = S.sel.size + ' on map';
  }

  /* ---------- alert queue ---------- */
  function renderAChips() {
    $('achips').innerHTML = ['P1', 'P2', 'P3', 'P4'].map(function (p) { var n = D.events.filter(function (e) { return e.tier === p; }).length; return '<button class="chip pr ' + p + '" type="button" data-pri="' + p + '" aria-pressed="' + S.pri[p] + '">' + p + ' · ' + n + '</button>'; }).join('');
    $('mchips').innerHTML = [['ALL', 'All models'], ['LAWNMOWER_SURVEY', 'Survey'], ['STATIONKEEPING_OPERATION', 'Stationkeeping'], ['PILOT_COLLECTION', 'Collection']].map(function (m) { return '<button class="chip" type="button" data-model="' + m[0] + '" aria-pressed="' + (S.model === m[0]) + '">' + m[1] + '</button>'; }).join('');
  }
  function alertList() { return D.events.filter(function (e) { return S.pri[e.tier] && (S.model === 'ALL' || e.model === S.model); }); }
  function renderAlerts() {
    var w = E.WATCH.filter(function (x) { return V[x.vessel]; }).map(function (x) { return '<button class="watchcard" type="button" data-watch="' + x.id + '"><span class="k">WATCH WINDOW · ' + esc(x.window) + '</span><b>' + esc(V[x.vessel].name) + ': ' + esc(x.title) + '</b><span class="muted" style="font-size:11.5px">' + esc(x.basis) + '</span></button>'; }).join('');
    var list = alertList();
    var html = w + '<div class="secthead">Detections by priority · ' + list.length + '</div>' + list.map(function (e) {
      var v = V[e.vessel], c = caseOf(e.id);
      return '<button class="alert ' + e.tier + (S.ev === e.id ? ' is-focus' : '') + '" type="button" data-ev="' + e.id + '"><span class="bar"></span><span class="bd">' +
        '<span class="r1"><span class="ptag ' + e.tier + '">' + e.tier + '</span><span class="nm">' + esc(v.name) + '</span><span class="flag">' + v.flag + '</span></span>' +
        '<span class="r2"><span class="model ' + e.model + '" style="line-height:16px;font-size:9.5px">' + E.MODEL[e.model].short + '</span><span class="num">' + fDs(e.t0) + ' → ' + (e.active ? 'now' : fDs(e.t1)) + '</span><span class="num">conf ' + e.confScore.toFixed(2) + '</span><span class="case ' + c.state + '">' + c.state + '</span></span>' +
        '<span class="why">' + esc(e.why.slice(0, 4).join(' · ')) + '</span></span></button>';
    }).join('');
    if (D.screened.length) html += '<div class="secthead">Rejected by the survey detector · ' + D.screened.length + ' (latest 25)</div>' + D.screened.slice().sort(function (a, b) { return b.t0 - a.t0; }).slice(0, 25).map(function (s) { return '<button class="alert" type="button" data-focus="' + s.vessel + '"><span class="bar" style="background:var(--line-2)"></span><span class="bd"><span class="r1"><span class="nm">' + esc(V[s.vessel].name) + '</span><span class="flag">' + V[s.vessel].flag + '</span></span><span class="r2"><span class="num">' + fDs(s.t0) + '</span><span class="num">' + s.n + ' lines</span></span><span class="why">' + esc(s.reason) + '</span></span></button>'; }).join('');
    $('alerts').innerHTML = html;
    $('ct-alerts').textContent = D.events.length;
  }
  function setTab(t) {
    S.tab = t; $('tab-fleet').setAttribute('aria-selected', t === 'fleet'); $('tab-alerts').setAttribute('aria-selected', t === 'alerts');
    $('left-fleet').classList.toggle('hide', t !== 'fleet'); $('left-alerts').classList.toggle('hide', t !== 'alerts');
  }

  /* ---------- map ---------- */
  var map = L.map('map', { zoomControl: false, attributionControl: false, preferCanvas: true, minZoom: 2, maxZoom: 13, maxBounds: [[-82, -150], [86, 400]], maxBoundsViscosity: 0.7, zoomSnap: 0.25 });
  map.fitBounds([[-40, 30], [62, 250]]);
  L.control.zoom({ position: 'bottomright' }).addTo(map);
  L.control.scale({ position: 'bottomright', imperial: false, maxWidth: 110 }).addTo(map);
  [['land', 250], ['zones', 300], ['tracks', 420], ['events', 440]].forEach(function (p) { map.createPane(p[0]).style.zIndex = p[1]; });
  map.getPane('land').style.pointerEvents = 'none';
  var rLand = L.canvas({ pane: 'land', padding: 0.4 }), rZone = L.canvas({ pane: 'zones', padding: 0.4 }), rTrk = L.canvas({ pane: 'tracks', padding: 0.4 }), rEvt = L.canvas({ pane: 'events', padding: 0.4, tolerance: 4 });

  (function drawLand() {
    var W = window.__WORLD;
    if (!W || !W.features) { $('mapnote').style.display = 'block'; return; }
    var sc = W.UTF8Scale || 1024;
    function dp(c, o) { var r = [], px = o[0], py = o[1]; for (var i = 0; i < c.length; i += 2) { var x = c.charCodeAt(i) - 64, y = c.charCodeAt(i + 1) - 64; x = (x >> 1) ^ (-(x & 1)); y = (y >> 1) ^ (-(y & 1)); x += px; y += py; px = x; py = y; r.push([x / sc, y / sc]); } return r; }
    var rings = [];
    W.features.forEach(function (f) {
      var g = f.geometry; if (!g) return;
      var polys = g.type === 'Polygon' ? [g.coordinates.map(function (c, i) { return W.UTF8Encoding ? dp(c, g.encodeOffsets[i]) : c; })] : g.coordinates.map(function (poly, i) { return poly.map(function (c, j) { return W.UTF8Encoding ? dp(c, g.encodeOffsets[i][j]) : c; }); });
      polys.forEach(function (poly) {
        poly = poly.map(function (ring) { var mn = Infinity, mx = -Infinity; ring.forEach(function (p) { mn = Math.min(mn, p[0]); mx = Math.max(mx, p[0]); }); return mx - mn > 180 ? ring.map(function (p) { return [p[0] < 0 ? p[0] + 360 : p[0], p[1]]; }) : ring; });
        rings.push(poly);
      });
    });
    [-360, 0, 360].forEach(function (off) {
      var ll = rings.map(function (poly) { return poly.map(function (ring) { return ring.map(function (p) { return [p[1], p[0] + off]; }); }); });
      L.polygon(ll, { renderer: rLand, interactive: false, color: '#2a3e4d', weight: 0.7, fillColor: '#16242e', fillOpacity: 1 }).addTo(map);
    });
  })();

  var gGrat = L.layerGroup(), gEez = L.layerGroup(), gZones = L.layerGroup(), gRee = L.layerGroup(), gHot = L.layerGroup(), gKnown = L.layerGroup(), gDyn = L.layerGroup().addTo(map), gMk = L.layerGroup().addTo(map), gNote = L.layerGroup().addTo(map);
  (function staticLayers() {
    var st = { renderer: rLand, interactive: false, color: '#5cc8ff', weight: 0.5, opacity: 0.12 };
    for (var la = -60; la <= 80; la += 20) gGrat.addLayer(L.polyline([[la, -150], [la, 400]], st));
    for (var lo = -150; lo <= 390; lo += 30) gGrat.addLayer(L.polyline([[-82, lo], [86, lo]], st));
    D.eezLines.forEach(function (l) {
      var t = l.t, unsettled = /unsettled|disputed|claim/i.test(t), joint = /joint/i.test(t), arc = t === '200 NM';
      var col = unsettled ? '#f4a93b' : joint ? '#38c2b0' : arc ? '#7fa9c4' : '#9cc3da';
      var runs = [[]]; l.c.forEach(function (q, k) { if (k && Math.abs(q[1] - l.c[k - 1][1]) > 90) runs.push([]); runs[runs.length - 1].push(q); });
      [-360, 0, 360].forEach(function (off) { gEez.addLayer(L.polyline(runs.map(function (r) { return r.map(function (q) { return [q[0], q[1] + off]; }); }), { renderer: rZone, color: col, weight: unsettled ? 1.3 : 0.9, opacity: arc ? 0.5 : 0.75, dashArray: arc ? '2 5' : unsettled ? '6 4' : null }).bindTooltip('<b>' + esc(l.n) + '</b><br>' + esc(t) + ' · Marine Regions EEZ v12', { sticky: true })); });
    });
    E.ZONES.forEach(function (z) {
      var c = ZC[z.type], p = L.polygon(z.rings.map(function (r) { return [r]; }), { renderer: rZone, color: c, weight: 1.1, opacity: 0.9, fillColor: c, fillOpacity: 0.16 });
      p.bindTooltip('<b>' + esc(z.contractor) + '</b><br>ISA ' + esc(E.ZONE_TYPES[z.type].label) + ' exploration contract ' + esc(z.id) + '<br>Sponsoring state: ' + esc(z.sponsor || '—') + ' · ' + z.km2.toLocaleString() + ' km²', { sticky: true });
      gZones.addLayer(p);
      gZones.addLayer(L.tooltip({ permanent: true, direction: 'center', className: 'lbl zone', interactive: false }).setLatLng(z.label).setContent(esc(E.ZONE_TYPES[z.type].short + ' · ' + z.contractor.replace(/ (Ltd\.|Inc\.|Corporation|Pte Ltd\.|NV|Co\.)$/, '').slice(0, 34))));
    });
    D.ree.forEach(function (r) { gRee.addLayer(L.circleMarker([r.lat, r.lon], { renderer: rEvt, radius: r.type === 'deposit' ? 6 : 4, color: '#a585ff', weight: 1.5, fillColor: '#a585ff', fillOpacity: 0.35 }).bindTooltip('<b>' + esc(r.name) + '</b><br>' + esc(r.type + (r.status ? ' · ' + r.status : '') + (r.country ? ' · ' + r.country : '')) + '<br><span style="color:#a1b5c3">' + esc(r.notes || '') + '</span>')); });
    D.hotspots.forEach(function (h) { gHot.addLayer(L.circle([h.lat, h.lon], { radius: 60000, renderer: rZone, color: '#ffd34d', weight: 1.2, dashArray: '2 5', fillColor: '#ffd34d', fillOpacity: 0.05 }).bindTooltip('<b>Survey hotspot ' + h.id + '</b> (team detector)<br>' + esc(h.vessels) + (h.together ? '<br>Surveyed at the same time' : ''))); });
    E.PORTS.forEach(function (p) { gKnown.addLayer(L.circleMarker([p.lat, p.lon], { renderer: rEvt, radius: 2, color: '#a1b5c3', weight: 1, fillColor: '#07121a', fillOpacity: 1 }).bindTooltip(esc(p.name) + ' · ' + esc(p.cc) + ' · WPI')); });
  })();
  function applyStaticLayers() {
    [[gGrat, 'grat'], [gEez, 'eez'], [gZones, 'zones'], [gRee, 'ree'], [gHot, 'hot']].forEach(function (x) { if (S.layers[x[1]]) { if (!map.hasLayer(x[0])) x[0].addTo(map); } else map.removeLayer(x[0]); });
    var showKnown = S.layers.known && map.getZoom() >= 5; if (showKnown) { if (!map.hasLayer(gKnown)) gKnown.addTo(map); } else map.removeLayer(gKnown);
  }
  map.on('zoomend', function () { var z = map.getZoom(), c = map.getContainer(); c.classList.toggle('z4', z >= 4); c.classList.toggle('z6', z >= 6); applyStaticLayers(); });
  var zcss = document.createElement('style'); zcss.textContent = '.lbl.zone{display:none}.z4 .lbl.zone{display:block}.lbl.port{display:none}.z4 .lbl.port{display:block}'; document.head.appendChild(zcss);
  map.on('mousemove', function (e) { $('coords').textContent = dm(e.latlng.lat, 'N', 'S') + '  ' + dm(nlon(e.latlng.lng), 'E', 'W'); });

  function idxAt(v, t) { var P = v.pts, lo = 0, hi = P.length - 1; if (t < P[0].t) return -1; if (t >= P[hi].t) return hi; while (lo < hi) { var m = (lo + hi + 1) >> 1; if (P[m].t <= t) lo = m; else hi = m - 1; } return lo; }
  function posAt(v, t) {
    var i = idxAt(v, t); if (i < 0) return null; var P = v.pts, a = P[i];
    if (i === P.length - 1 || t === a.t) return { lat: a.lat, lon: a.lon, cog: a.cog, sog: a.sog, i: i };
    var b = P[i + 1], f = (t - a.t) / (b.t - a.t); return { lat: a.lat + (b.lat - a.lat) * f, lon: a.lon + (b.lon - a.lon) * f, cog: b.cog, sog: b.sog, i: i, gap: (b.t - a.t) > 10 * H };
  }
  function ll(v, i0, i1) { var r = []; for (var i = i0; i <= i1; i++) r.push([v.pts[i].lat, v.pts[i].lon]); return r; }
  function vColor(v) { return v.top ? TIERC[v.top.tier] : '#9fb3c1'; }
  function icon(v, p, focused) {
    var c = vColor(v), s = focused ? 30 : 18, stroke = focused ? '#fff' : '#07121a', op = v.stale && S.t >= v.last.t ? 0.55 : 1;
    var shape = p.sog < 0.8 ? '<circle r="4.6" fill="' + c + '" stroke="' + stroke + '" stroke-width="1.6"/>' : '<path d="M0,-8 L5.2,6 L0,3 L-5.2,6 Z" fill="' + c + '" stroke="' + stroke + '" stroke-width="1.4" transform="rotate(' + Math.round(p.cog || 0) + ')"/>';
    var ring = focused ? '<circle r="9.5" fill="none" stroke="#fff" stroke-width="1.2" opacity=".85"/>' : '';
    return L.divIcon({ className: 'vmk', iconSize: [s, s], iconAnchor: [s / 2, s / 2], html: '<svg viewBox="-10 -10 20 20" width="' + s + '" height="' + s + '" style="opacity:' + op + '">' + ring + shape + '</svg>' });
  }

  function evtGeom(e, v, strong, t) {
    var out = [];
    if (e.L) {
      var col = '#ffd34d';
      if (strong) e.L.lines.forEach(function (l) { if (l.t0 <= t) out.push(L.polyline([l.a, l.b], { renderer: rEvt, color: col, weight: 2.2, opacity: 0.95, interactive: false })); });
      if (e.t0 <= t && e.L.hull.length > 2) out.push(L.polygon(e.L.hull, { renderer: rEvt, color: col, weight: strong ? 1.2 : 1, opacity: strong ? 0.8 : 0.6, dashArray: '4 3', fillColor: col, fillOpacity: strong ? 0.07 : 0.12 }).bindTooltip(esc(v.name) + ' · ' + E.MODEL[e.model].label + '<br>' + Math.round(e.L.area) + ' km² · ' + e.L.n + ' lines'));
      else if (e.t0 <= t) out.push(L.circle(e.center, { radius: 15000, renderer: rEvt, color: col, weight: 1, dashArray: '4 3', fillOpacity: 0.08 }));
    }
    if (e.S && e.t0 <= t) {
      var c = '#a585ff', r = Math.max(e.S.r95 * 1000, 250);
      if (strong) e.S.cloud.forEach(function (q) { out.push(L.rectangle([[q[0] - 0.005, q[1] - 0.005], [q[0] + 0.005, q[1] + 0.005]], { renderer: rEvt, weight: 0.6, color: c, fillColor: c, fillOpacity: 0.35, interactive: false })); });
      out.push(L.circle(e.S.center, { radius: r, renderer: rEvt, color: c, weight: strong ? 2 : 1.4, fillColor: c, fillOpacity: 0.12 }).bindTooltip(esc(v.name) + ' · stationkeeping<br>' + dur(e.S.onHours) + ' within ' + Math.round(e.S.r95 * 1000) + ' m'));
      out.push(L.circle(e.S.center, { radius: Math.max(6000, r * 6), renderer: rEvt, color: c, weight: 1, opacity: 0.6, dashArray: '2 4', fill: false, interactive: false }));
    }
    if (e.C && e.t0 <= t) {
      var cc = '#ff5f56';
      if (strong) e.C.LA.forEach(function (la) { la.lines.forEach(function (l) { if (v.pts[l.i0].t <= t) out.push(L.polyline(ll(v, l.i0, Math.min(l.i1, idxAt(v, t))), { renderer: rEvt, color: cc, weight: 1.2, opacity: 0.9, interactive: false })); }); });
      out.push(L.polygon(e.C.hull, { renderer: rEvt, color: cc, weight: 1.4, dashArray: '4 3', fillColor: cc, fillOpacity: 0.15 }).bindTooltip(esc(v.name) + ' · pilot collection footprint<br>' + e.C.lanes + ' lanes · ' + (e.C.area * 100).toFixed(0) + ' ha'));
      out.push(L.circle(e.C.center, { radius: 9000, renderer: rEvt, color: cc, weight: 1, opacity: 0.6, dashArray: '2 4', fill: false, interactive: false }));
    }
    return out;
  }

  function renderMap() {
    gDyn.clearLayers(); gMk.clearLayers();
    var t = S.t, fv = S.focus ? V[S.focus] : null;
    // tracks
    if (S.layers.tracks) {
      S.sel.forEach(function (id) {
        var v = V[id], iT = idxAt(v, t); if (iT < 0) return;
        if (S.walk && id === EVI[S.walk.ev].vessel) return;
        var foc = id === S.focus, iF = S.trackFrom ? Math.max(0, idxAt(v, S.trackFrom)) : 0;
        v.segments.forEach(function (sg) { var a = Math.max(sg[0], iF), b = Math.min(sg[1], iT); if (b <= a) return; gDyn.addLayer(L.polyline(ll(v, a, b), { renderer: rTrk, color: foc ? '#ffffff' : '#7fb6d6', weight: foc ? 2 : 1.2, opacity: foc ? 0.9 : 0.55, interactive: false })); });
        if (S.layers.gaps) v.gaps.forEach(function (g) { if (g.t0 <= t && Math.abs(g.a[1] - g.b[1]) < 90) gDyn.addLayer(L.polyline([g.a, g.b], { renderer: rTrk, color: '#ff5f56', weight: foc ? 2.2 : 1.5, dashArray: '2 6', opacity: 0.95 }).bindTooltip('AIS gap · ' + dur(g.hours) + ' · ' + Math.round(g.km) + ' km unreported (' + f1(g.kn) + ' kn implied)')); });
      });
    }
    // events
    if (S.walk) walkGeom();
    if (S.layers.events && !S.walk) {
      D.events.forEach(function (e) {
        if (!S.sel.has(e.vessel) && e.vessel !== S.focus) return;
        evtGeom(e, V[e.vessel], e.vessel === S.focus, t).forEach(function (l) { gDyn.addLayer(l); });
      });
    }
    // coordination links
    if (S.layers.coord && fv) fv.events.forEach(function (e) { if (e.t0 > t) return; e.coord.forEach(function (k) { var o = EVI[k.id]; gDyn.addLayer(L.polyline([e.center, o.center], { renderer: rEvt, color: '#ffffff', weight: 1.2, dashArray: '1 5', opacity: 0.85 }).bindTooltip('Concurrent activity · ' + esc(V[o.vessel].name) + ' · ' + Math.round(k.km) + ' km apart · ' + dur(k.overlapH) + ' overlap')); }); });
    // independent GFW loitering events (focus: 24 h and longer; other selected ships: 48 h and longer)
    if (S.layers.gfw && !S.walk) S.sel.forEach(function (id) {
      var v = V[id], foc = id === S.focus;
      v.gfw.events.forEach(function (g) {
        if (g.k !== 'L' || g.h < (foc ? 24 : 48) || g.t0 > t) return;
        var pre = g.t1 < E.T_START;
        gDyn.addLayer(L.circleMarker([g.lat, g.lon], { renderer: rEvt, radius: foc ? 6.5 : 4.5, color: '#4fc58b', weight: foc ? 1.8 : 1.2, dashArray: pre ? '2 3' : null, fillColor: '#4fc58b', fillOpacity: 0.14 })
          .bindTooltip('<b>' + esc(v.name) + '</b> · GFW loitering event' + (pre ? ' (before our AIS window)' : '') + '<br>' + fDT(g.t0) + ' → ' + fDT(g.t1) + '<br>' + dur(g.h) + ', ' + f1(g.km) + ' km total movement, ' + g.kn.toFixed(2) + ' kn average'));
      });
    });
    // observed port calls
    if (S.layers.calls) {
      var seen = {};
      S.sel.forEach(function (id) { V[id].calls.forEach(function (c) { if (c.t0 > t) return; var k = c.port; seen[k] = seen[k] || { n: 0, focus: false, vs: {} }; seen[k].n++; seen[k].vs[V[id].name] = 1; if (id === S.focus) seen[k].focus = true; }); });
      Object.keys(seen).forEach(function (k) {
        var p = E.PORT[k], s = seen[k];
        var m = L.circleMarker([p.lat, p.lon], { renderer: rEvt, radius: s.focus ? 7 : 5, color: '#ffffff', weight: s.focus ? 2 : 1.4, fillColor: '#07121a', fillOpacity: 1 }).bindTooltip('<b>' + esc(p.name) + '</b> · observed port calls<br>' + esc(Object.keys(s.vs).join(', ')));
        gDyn.addLayer(m); gDyn.addLayer(L.circleMarker([p.lat, p.lon], { renderer: rEvt, radius: 2, stroke: false, fillColor: '#fff', fillOpacity: 1, interactive: false }));
        if (s.focus) gDyn.addLayer(L.tooltip({ permanent: true, direction: 'right', offset: [8, 0], className: 'lbl port', interactive: false }).setLatLng([p.lat, p.lon]).setContent(esc(p.name)));
      });
    }
    // watch window expectation
    if (fv) E.WATCH.forEach(function (w) { if (w.vessel !== fv.id || fv.home == null) return; var home = E.PORT[fv.home], ce = [D.ree[0].lat, D.ree[0].lon]; gDyn.addLayer(L.polyline([[home.lat, home.lon], ce], { renderer: rEvt, color: '#a585ff', weight: 1.6, dashArray: '8 6', opacity: 0.9 }).bindTooltip('Watch window: home port to Minamitorishima · ' + esc(w.title) + ' (' + esc(w.window) + ')')); });
    if (((fv && fv.id === 'chikyu') || S.showRef) && E.REFERENCE.chikyu && E.REFERENCE.chikyu.gfw) { var gs = E.REFERENCE.chikyu.gfw.site;
      gDyn.addLayer(L.circle([gs.lat, gs.lon], { radius: 3600, renderer: rEvt, color: '#a585ff', weight: 2, fillColor: '#a585ff', fillOpacity: 0.2 }).bindTooltip('<b>Chikyu rare-earth mud test site</b><br>GFW loitering ' + fD(gs.t0) + '–' + fD(gs.t1) + ' · ' + ((gs.t1 - gs.t0) / DAY).toFixed(1) + ' d · ' + Math.round(-gs.depth).toLocaleString() + ' m deep'));
      gDyn.addLayer(L.circle([gs.lat, gs.lon], { radius: 30000, renderer: rEvt, color: '#a585ff', weight: 1, dashArray: '2 4', fill: false, interactive: false }));
      if (S.brief < 0) gDyn.addLayer(L.tooltip({ permanent: true, direction: 'right', offset: [12, 0], className: 'lbl', interactive: false }).setLatLng([gs.lat, gs.lon]).setContent('REE TEST SITE · ' + (MON[new Date(gs.t0).getUTCMonth()] + '–' + monY(gs.t1)).toUpperCase()));
    }
    // vessel markers
    D.vessels.forEach(function (v) {
      if (!vMatch(v) && v.id !== S.focus && !S.sel.has(v.id)) return;
      if (S.brief >= 0 && v.id !== S.focus && !S.sel.has(v.id)) return;
      var p = posAt(v, t); if (!p) return;
      var foc = v.id === S.focus;
      var m = L.marker([p.lat, p.lon], { icon: icon(v, p, foc), zIndexOffset: foc ? 1000 : (S.sel.has(v.id) ? 500 : 0), keyboard: false });
      m.bindTooltip('<b>' + esc(v.name) + '</b> · ' + v.flag + '<br>' + esc(v.status) + (v.top ? ' · ' + v.top.tier : ''), { direction: 'top', offset: [0, -8] });
      m.on('click', function () { focusVessel(v.id, null, false); });
      gMk.addLayer(m);
      if (foc) gMk.addLayer(L.tooltip({ permanent: true, direction: 'right', offset: [14, 0], className: 'lbl', interactive: false }).setLatLng([p.lat, p.lon]).setContent(esc(v.name)));
    });
  }

  /* ---------- layers control ---------- */
  var LAYERS = [
    ['h', 'Context'], ['eez', 'EEZ boundaries', 'dash:#9cc3da'], ['zones', 'ISA contract areas', 'linear-gradient(90deg,#38c2b0 0 33%,#d4955e 33% 66%,#ee6fa5 66%)'], ['ree', 'Rare-earth sites', 'dot:#a585ff'], ['hot', 'Survey hotspots', 'dash:#ffd34d'], ['known', 'WPI ports (zoom in)', 'dot:#a1b5c3'], ['grat', 'Graticule', 'line:#5cc8ff55'],
    ['h', 'Vessels'], ['tracks', 'Tracks (selected)', 'line:#7fb6d6'], ['events', 'Detections', 'line:#ffd34d'], ['gaps', 'AIS gaps', 'dash:#ff5f56'], ['calls', 'Observed port calls', 'ring'], ['coord', 'Concurrent activity links', 'dash:#ffffff'], ['gfw', 'GFW loitering (independent)', 'dot:#4fc58b']
  ];
  function renderLayers() {
    $('lbody').innerHTML = LAYERS.map(function (l) {
      if (l[0] === 'h') return '<div class="lh">' + l[1] + '</div>';
      var sw = l[2], swh;
      if (sw.indexOf('line:') === 0) swh = '<span class="sw line" style="border-color:' + sw.slice(5) + '"></span>';
      else if (sw.indexOf('dash:') === 0) swh = '<span class="sw dash" style="border-color:' + sw.slice(5) + '"></span>';
      else if (sw.indexOf('dot:') === 0) swh = '<span class="sw" style="width:6px;height:6px;border-radius:50%;margin:0 5px;border:1px solid ' + sw.slice(4) + '"></span>';
      else if (sw === 'ring') swh = '<span class="sw" style="width:10px;height:10px;border-radius:50%;margin:0 3px;border:2px solid #fff"></span>';
      else swh = '<span class="sw" style="background:' + sw + '"></span>';
      return '<label><input type="checkbox" id="ly-' + l[0] + '" data-layer="' + l[0] + '"' + (S.layers[l[0]] ? ' checked' : '') + '>' + swh + l[1] + '</label>';
    }).join('');
  }

  /* ---------- timeline ---------- */
  var tr = $('trange'); tr.min = E.T_START; tr.max = E.AS_OF; tr.step = H; tr.value = S.t;
  function drawHist() {
    var cv = $('hist'), r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1; if (!r.width) return;
    cv.width = r.width * dpr; cv.height = r.height * dpr; var c = cv.getContext('2d'); c.scale(dpr, dpr);
    var hst = D.hist, mx = Math.max.apply(null, hst.concat([1])), w = r.width / hst.length, base = r.height - 14, topY = 11;
    c.fillStyle = '#1c3141'; c.fillRect(0, base, r.width, 1);
    for (var i = 0; i < hst.length; i++) { if (!hst[i]) continue; var hh = (hst[i] / mx) * (base - topY); c.fillStyle = '#5cc8ff55'; c.fillRect(i * w, base - hh, Math.max(1, w - 0.3), hh); }
    var fv = S.focus ? V[S.focus] : null, span = E.AS_OF - E.T_START;
    if (fv) fv.events.forEach(function (e) { var x0 = (e.t0 - E.T_START) / span * r.width, x1 = (e.t1 - E.T_START) / span * r.width; c.fillStyle = TIERC[e.tier]; c.fillRect(x0, base - 3, Math.max(2, x1 - x0), 4); });
    c.fillStyle = '#6f8797'; c.font = '9px "IBM Plex Mono", monospace'; c.textBaseline = 'top';
    monthStarts(E.T_START, E.AS_OF).forEach(function (tm) { var x = (tm - E.T_START) / span * r.width; c.fillStyle = '#1c3141'; c.fillRect(x, 0, 1, base); c.fillStyle = '#6f8797'; if (r.width > 360) c.fillText(MON[new Date(tm).getUTCMonth()].toUpperCase(), x + 3, 0); });
  }
  function setTime(t, fromUser) {
    S.t = Math.max(E.T_START, Math.min(E.AS_OF, t)); tr.value = S.t;
    $('tdate').textContent = fDT(S.t); var live = S.t >= E.AS_OF; $('live').setAttribute('aria-pressed', live);
    renderMap(); if (fromUser !== 'quiet') renderAIS();
  }
  function play(on) {
    S.playing = on; $('playico').setAttribute('d', on ? 'M2 1h3v10H2zM7 1h3v10H7z' : 'M2 1l9 5-9 5z'); $('play').setAttribute('aria-label', on ? 'Pause' : 'Play');
    clearInterval(S.timer);
    if (on) { if (S.t >= E.AS_OF) setTime(E.T_START); S.timer = setInterval(function () { var n = S.t + parseFloat($('tspeed').value) * DAY; if (n >= E.AS_OF) { setTime(E.AS_OF); play(false); } else setTime(n, 'quiet'); }, 110); }
    else renderAIS();
  }

  /* ---------- intelligence panel ---------- */
  function bars(list, cls) {
    return '<div class="bars ' + (cls || '') + '">' + list.map(function (c) { return '<div class="barrow"><span class="bl">' + esc(c.label) + '</span><span class="bt"><i style="width:' + Math.round(c.v * 100) + '%"></i></span><span class="bv">' + c.v.toFixed(2) + '</span><span class="bd">' + esc(c.detail) + ' · weight ' + Math.round(c.w * 100) + '%</span></div>'; }).join('') + '</div>';
  }
  function kv(pairs) { return '<dl class="grid2">' + pairs.map(function (p) { return '<div class="kv"><dt>' + esc(p[0]) + '</dt><dd>' + p[1] + '</dd></div>'; }).join('') + '</dl>'; }
  function metrics(e) {
    if (e.L) { var L = e.L, days = (e.t1 - e.t0) / DAY; return kv([['Survey lines', L.n + ' in ' + L.blocks + ' block' + (L.blocks > 1 ? 's' : '')], ['Line spacing', f1(L.spacing) + ' km'], ['Mean line length', f1(L.meanLen) + ' km'], ['Total line distance', Math.round(L.totalLen).toLocaleString() + ' km'], ['Footprint', Math.round(L.area).toLocaleString() + ' km²'], ['Survey speed', f1(L.speed) + ' kn'], ['Line axis', L.axisCompass + ' (' + Math.round(L.axis) + '°)'], ['Pass rate', f1(L.n / Math.max(days, 0.04)) + ' lines/day'], ['Offshore', Math.round(L.offshore) + ' km'], ['Detector score', L.score.toFixed(3) + ' (' + L.detConf + ')']]); }
    if (e.S) { var S2 = e.S; return kv([['On station', dur(S2.onHours)], ['Window', dur(S2.totalHours)], ['Radius (95%)', Math.round(S2.r95 * 1000) + ' m'], ['Radius (median)', Math.round(S2.r50 * 1000) + ' m'], ['Median speed', S2.medSog.toFixed(1) + ' kn'], ['Net displacement', Math.round(S2.net * 1000) + ' m'], ['Grid cells used', S2.cells + ' × 0.01°'], ['Nearest port', Math.round(S2.portKm) + ' km'], ['Centre', fLat(S2.center[0]) + ' ' + fLon(S2.center[1])], ['Time on station', Math.round(S2.onFrac * 100) + '% of window']]) + '<p class="muted" style="margin:0;font-size:11.5px">Positions come on a ~1 km grid, so radii under about 1 km cannot be resolved.</p>'; }
    if (e.C) { var C = e.C; return kv([['Collector lanes', C.lanes], ['Lane spacing', Math.round(C.spacing * 1000) + ' m'], ['Lane speed', f1(C.laneSpeed) + ' kn'], ['Stationkeeping', dur(C.stationH)], ['Footprint', (C.area * 100).toFixed(0) + ' ha'], ['Hold radius', Math.round(C.r95 * 1000) + ' m (95%)']]) + '<div class="list">' + C.phases.map(function (p) { return '<div class="li"><span>' + esc(p.label) + '</span><span class="s">' + fDs(p.t0) + ' · ' + dur((p.t1 - p.t0) / H) + '</span></div>'; }).join('') + '</div>'; }
    return '';
  }
  function cycleStrip(e, v) {
    var vy = e.voyage; if (!vy) return '';
    var evs = v.events.filter(function (x) { return x.t0 >= vy.t0 && x.t0 <= vy.t1; }).sort(function (a, b) { return a.t0 - b.t0; });
    var cells = ['<div class="cyc port"><span class="k">Depart</span><span class="v">' + esc(E.PORT[vy.from].name) + '</span><span class="d">' + fDs(vy.t0) + '</span></div>'], cur = vy.t0;
    evs.forEach(function (x) {
      var gap = v.gaps.filter(function (g) { return g.t0 >= cur && g.t1 <= x.t0 + 6 * H; })[0];
      cells.push('<div class="cyc"><span class="k">Transit</span><span class="v">' + dur((x.t0 - cur) / H) + '</span><span class="d">' + (gap ? '<span style="color:var(--gap)">' + dur(gap.hours) + ' dark</span>' : '&nbsp;') + '</span></div>');
      cells.push('<div class="cyc op ' + x.model + '"' + (x.id === e.id ? ' style="background:var(--raise)"' : '') + '><span class="k">' + E.MODEL[x.model].short + '</span><span class="v">' + dur((x.t1 - x.t0) / H) + '</span><span class="d">' + fDs(x.t0) + '</span></div>');
      cur = x.t1;
    });
    if (vy.to) { cells.push('<div class="cyc"><span class="k">Transit</span><span class="v">' + dur((vy.t1 - cur) / H) + '</span><span class="d">&nbsp;</span></div>'); cells.push('<div class="cyc port"><span class="k">Arrive</span><span class="v">' + esc(E.PORT[vy.to].name) + '</span><span class="d">' + fDs(vy.t1) + '</span></div>'); }
    else cells.push('<div class="cyc"><span class="k">At sea</span><span class="v">' + (e.active ? 'On site' : 'Underway') + '</span><span class="d">' + fDs(vy.t1) + '</span></div>');
    var badge = vy.to ? (vy.same ? '<span class="badge ok">SAME-PORT RETURN · ' + esc(E.PORT[vy.to].name) + '</span>' : '<span class="badge warn">ENDED IN DIFFERENT PORT · ' + esc(E.PORT[vy.to].name) + '</span>') : '<span class="badge warn">VOYAGE OPEN</span>';
    var cyc = v.voyages.filter(function (x) { return x.same && v.events.some(function (q) { return q.t0 >= x.t0 && q.t0 <= x.t1; }); }).length;
    return '<div class="sec"><h4>Operational cycle · ' + f1(vy.days) + ' d voyage</h4><div class="cycle">' + cells.join('') + '</div><div style="display:flex;gap:6px;flex-wrap:wrap">' + badge + (cyc > 1 ? '<span class="badge ree">' + cyc + ' COMPLETE CYCLES FROM ' + esc(E.PORT[vy.from].name.toUpperCase()) + '</span>' : '') + '</div></div>';
  }
  function contextSec(e, v) {
    var rows = [];
    rows.push(['ISA contract area', e.zone ? esc(e.zone.contractor) + '<br><span class="muted">' + esc(E.ZONE_TYPES[e.zone.type].label) + ' · sponsor ' + esc(e.zone.sponsor || '—') + '</span>' : (e.nearZone ? 'None. ' + Math.round(e.nearZoneKm).toLocaleString() + ' km to ' + esc(e.nearZone.contractor) + ' (' + E.ZONE_TYPES[e.nearZone.type].short + ')' : 'None')]);
    rows.push(['EEZ', e.eez ? esc(e.eez.name) + '<br><span class="muted">' + esc(e.eez.type) + ' · ' + esc(e.eez.sov.join(' / ')) + '</span>' : 'None (high seas)']);
    if (e.boundary) rows.push(['Nearest foreign boundary', Math.round(e.boundary.km) + ' km · ' + esc(e.boundary.name) + '<br><span class="muted">' + esc(e.boundary.type) + '</span>']);
    rows.push(['Water depth', e.depth === null || e.depth === undefined ? '—' : e.depth < 0 ? Math.round(-e.depth).toLocaleString() + ' m (GEBCO)' : 'Land/intertidal cell (' + e.depth + ' m)']);
    if (e.anchorage) rows.push(['Check', '<span style="color:var(--p2)">Shallow and near port: may be anchoring</span>']);
    if (e.mntKm < 600) rows.push(['Rare-earth mud', Math.round(e.mntKm) + ' km from Minamitorishima']);
    var fp = E.PORT[e.foreign.port]; rows.push(['Nearest foreign port', fp ? esc(fp.name) + ', ' + esc(e.foreign.country) + ' · ' + Math.round(e.foreign.km) + ' km' : '—']);
    var np = E.PORT[e.nearestPort.port]; rows.push(['Nearest port', np ? esc(np.name) + ', ' + esc(np.cc) + ' · ' + Math.round(e.nearestPort.km) + ' km' : '—']);
    rows.push(['Concurrent vessels', e.coord.length ? e.coord.map(function (k) { return '<button class="link" type="button" data-ev="' + k.id + '">' + esc(V[k.vessel].name) + '</button> · ' + Math.round(k.km) + ' km, ' + dur(k.overlapH) + ' overlap'; }).join('<br>') : 'None within 80 km']);
    rows.push(['Repeat visits', e.revisits.length ? e.revisits.map(function (id) { return '<button class="link" type="button" data-ev="' + id + '">' + id + '</button> (' + fDs(EVI[id].t0) + ')'; }).join(', ') : 'First visit in this window']);
    if (e.otherVisits.length) rows.push(['Other vessels here', e.otherVisits.map(function (id) { return '<button class="link" type="button" data-ev="' + id + '">' + esc(V[EVI[id].vessel].name) + '</button> (' + fDs(EVI[id].t0) + ')'; }).join('<br>')]);
    if (e.S) rows.push(['Independent check', e.gfw ? '<span style="color:var(--ok)">GFW loitering event, ' + dur(e.gfw.hours) + ', ' + Math.round(e.gfw.overlap * 100) + '% overlap</span>' : 'No GFW loitering event overlaps']);
    rows.push(['AIS continuity', e.gaps.length ? e.gaps.map(function (g) { return '<span style="color:var(--gap)">' + dur(g.hours) + ' gap</span>, ' + Math.round(g.km) + ' km unreported'; }).join('<br>') : 'Continuous']);
    return '<div class="sec"><h4>Context</h4><div class="list">' + rows.map(function (r) { return '<div class="li"><span class="muted">' + r[0] + '</span><span style="text-align:right">' + r[1] + '</span></div>'; }).join('') + '</div></div>';
  }
  function renderAIS() {
    var el = $('ais'); if (!el || !S.focus) return; var v = V[S.focus], L0 = v.last, ip = v.inPort;
    var html = '<dt>Latest report</dt><dd>' + fDT(L0.t) + (v.stale ? ' <span class="st stale">STALE ' + Math.round((E.AS_OF - L0.t) / DAY) + ' D</span>' : '') + '</dd>' +
      '<dt>Position</dt><dd>' + fLat(L0.lat) + ' ' + fLon(L0.lon) + '</dd>' +
      '<dt>SOG / COG</dt><dd>' + L0.sog.toFixed(1) + ' kn / ' + Math.round(L0.cog) + '°</dd>' +
      '<dt>State</dt><dd>' + (ip ? 'In port · ' + esc(ip.name) : v.activeEv ? esc(E.MODEL[v.activeEv.model].label) + ' in progress' : 'At sea') + '</dd>';
    if (S.t < E.AS_OF) { var p = posAt(v, S.t); html += '<dt style="color:var(--accent)">At map time</dt><dd style="color:var(--accent)">' + (p ? fLat(p.lat) + ' ' + fLon(p.lon) + ' · ' + p.sog.toFixed(1) + ' kn' : 'No track yet') + '</dd>'; }
    el.innerHTML = html;
  }
  function renderIntel() {
    var el = $('intel');
    if (!S.focus) { el.innerHTML = overview(); return; }
    var v = V[S.focus], e = v.events.filter(function (x) { return x.id === S.ev; })[0] || v.top;
    if (e) S.ev = e.id;
    var html = '<div class="idhead"><div class="r"><span class="flag" style="margin-top:4px">' + v.flag + '</span><h2>' + esc(v.name) + '</h2><button class="star" type="button" id="star" aria-pressed="' + isWatch(v) + '" aria-label="Watchlist" title="Watchlist"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M7 1l1.8 3.8 4.2.5-3.1 2.9.8 4.1L7 10.3 3.3 12.3l.8-4.1L1 5.3l4.2-.5z" fill="' + (isWatch(v) ? 'currentColor' : 'none') + '" stroke="currentColor" stroke-width="1.2"/></svg></button><button class="x" type="button" id="unfocus" aria-label="Close vessel"><svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" stroke-width="1.5"/></svg></button></div>' +
      '<div class="meta">' + esc(E.CLASS[v.cls].label) + (v.gfw.owner ? ' <span class="muted">· registry owner</span> ' + esc(tc(v.gfw.owner)) + (v.gfw.ownerFlag ? ' <span class="muted">(' + esc(v.gfw.ownerFlag) + ')</span>' : '') : ' <span class="muted">(class inferred from public name; no registry record in GFW)</span>') + '</div>' +
      '<div class="meta2"><span>Flag <b>' + esc(v.country) + '</b></span><span>MMSI <b class="mono">' + (v.mmsi || '—') + '</b></span><span>IMO <b class="mono">' + (v.imo || '—') + '</b></span><span>Call sign <b class="mono">' + esc(v.callsign || '—') + '</b></span><span>Home <b>' + (v.home != null && E.PORT[v.home] ? esc(E.PORT[v.home].name) : '—') + '</b></span><span>Fixes <b class="mono">' + v.nRaw.toLocaleString() + '</b></span><span>GFW type <b>' + esc(v.gfw.type || '—') + '</b></span><span>Size <b class="mono">' + (v.gfw.lengthM ? v.gfw.lengthM + ' m' : '—') + (v.gfw.gt ? ' · ' + v.gfw.gt.toLocaleString() + ' GT' : '') + (v.gfw.registry ? '' : (v.gfw.lengthM ? ' est.' : '')) + '</b></span></div>' +
      '<div class="caps">' + (v.watch ? '<span class="cap key">Deep-sea mining watchlist</span>' : '') + (v.mmsi ? '<a class="cap" href="https://www.marinetraffic.com/en/ais/details/ships/mmsi:' + v.mmsi + '" target="_blank" rel="noopener" style="text-decoration:none">MarineTraffic ↗</a>' : '') + '</div></div>' +
      '<dl class="ais" id="ais"></dl>';
    var ref = E.REFERENCE[v.id];
    if (ref) html += '<div class="sec"><div class="refbox"><h4 style="color:#c4b0ff">Reference case · public reporting</h4><ol>' + ref.events.map(function (x) { return '<li><span>' + fD(x.t) + '</span>' + esc(x.label) + '</li>'; }).join('') + '</ol>' + (ref.gfw ? '<h4 style="color:#c4b0ff;margin-top:4px">Confirmed in Global Fishing Watch events</h4><ol>' + ref.gfw.events.filter(function (x) { return x.t0 > Date.parse('2026-01-08T00:00Z'); }).map(function (x) { return '<li><span>' + fDs(x.t0) + ' 2026</span>' + esc(x.kind + ': ' + x.label) + '</li>'; }).join('') + '</ol><p class="muted" style="margin:0;font-size:11.5px">Site ' + fLat(ref.gfw.site.lat) + ' ' + fLon(ref.gfw.site.lon) + ', ' + Math.round(-ref.gfw.site.depth).toLocaleString() + ' m deep (GEBCO), ' + ref.gfw.site.mntKm + ' km from Minamitorishima. <button class="link" type="button" id="z-ref">Show on map</button></p>' : '') + '<p class="muted" style="margin:0;font-size:11.5px">' + esc(ref.notes) + '</p><div style="display:grid;gap:2px;font-size:11.5px">' + ref.sources.map(function (s) { return '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.title) + '</a>'; }).join('') + '</div></div></div>';
    E.WATCH.filter(function (w) { return w.vessel === v.id; }).forEach(function (w) { html += '<div class="sec"><h4 style="color:#c4b0ff">Watch window · ' + esc(w.window) + '</h4><div><b>' + esc(w.title) + '</b></div><p class="muted" style="margin:0">' + esc(w.expect) + '</p><p class="muted" style="margin:0;font-size:11.5px">' + esc(w.basis) + '</p></div>'; });
    html += gfwSec(v);
    if (!v.events.length) {
      html += '<div class="sec"><h4>Detections</h4><p class="muted" style="margin:0">No behavior model triggered between ' + fDs(E.T_START) + ' and ' + fDs(E.AS_OF) + '.' + (v.screened.length ? ' The survey detector examined and rejected ' + v.screened.length + ' line pattern' + (v.screened.length > 1 ? 's' : '') + ':' : '') + '</p>' + v.screened.slice(0, 6).map(function (s) { return '<div class="list"><div class="li"><span><b>Rejected</b> · ' + fDs(s.t0) + '<br><span class="muted">' + esc(s.reason) + '</span></span><span></span></div></div>'; }).join('') + '</div>';
    } else {
      if (v.events.length > 1) html += '<div class="evtabs" role="tablist">' + v.events.slice().sort(function (a, b) { return a.t0 - b.t0; }).map(function (x) { return '<button class="evtab" role="tab" type="button" data-ev="' + x.id + '" aria-selected="' + (x.id === e.id) + '"><span class="ptag ' + x.tier + '">' + x.tier + '</span>' + E.MODEL[x.model].short + ' · ' + fDs(x.t0) + '</button>'; }).join('') + '</div>';
      var c = caseOf(e.id);
      html += '<div class="sec"><div class="evhead"><span class="model ' + e.model + '">' + E.MODEL[e.model].label.toUpperCase() + '</span><span class="st ' + (e.active ? 'act' : 'port') + '">' + e.status + '</span><span class="muted mono" style="font-size:11px;margin-left:auto">' + e.id + '</span></div>' +
        '<div class="evdates">' + fDT(e.t0) + ' → ' + (e.active ? 'ongoing' : fDT(e.t1)) + ' · ' + dur((e.t1 - e.t0) / H) + '</div>' +
        '<div class="scores"><div class="score"><span class="lab">Detection confidence</span><span class="big"><b>' + e.confScore.toFixed(2) + '</b><span>' + e.confLabel + '</span></span><span class="sub">' + esc(e.confSource) + '</span></div>' +
        '<div class="score pri ' + e.tier + '"><span class="lab">Analyst priority</span><span class="big"><b>' + e.tier + '</b><span>' + e.priScore.toFixed(2) + '</span></span><span class="sub">Resource context, vessel class, geography, history</span></div></div>' +
        '<div><h4 style="margin-bottom:6px">Why flagged</h4><ul class="why">' + e.why.map(function (w) { return '<li><span>' + esc(w) + '</span></li>'; }).join('') + '</ul></div>' +
        '<details class="more"><summary>Confidence evidence (' + e.conf.length + ' components)</summary>' + bars(e.conf) + '</details>' +
        '<details class="more"><summary>Priority factors (' + e.pri.length + ')</summary>' + bars(e.pri, 'pri') + '</details></div>' +
        '<div class="sec"><h4>Measurements</h4>' + metrics(e) + '</div>' + cycleStrip(e, v) + contextSec(e, v) +
        '<div class="sec"><h4>Case</h4><div class="casebar">' + ['NEW', 'REVIEWING', 'CONFIRMED', 'DISMISSED', 'ESCALATED'].map(function (s) { return '<button class="cbtn" type="button" data-case="' + s + '" aria-pressed="' + (c.state === s) + '">' + s + '</button>'; }).join('') + '</div>' +
        '<textarea class="note" id="note" placeholder="Analyst note for ' + e.id + '" aria-label="Analyst note">' + esc(c.note) + '</textarea><span class="muted" style="font-size:11px">CONFIRMED and DISMISSED count as review labels in the Validation view. Saved in this browser only.</span><button class="link" type="button" id="next-unrev" style="justify-self:start">Next unreviewed detection →</button>' +
        '<div class="actions"><button class="abtn" type="button" id="z-ev">Zoom to detection</button><button class="abtn" type="button" id="z-tr">Zoom to track</button><button class="abtn" type="button" id="cp-brief">Copy text brief</button><button class="abtn" type="button" id="cp-geo">Copy GeoJSON</button></div></div>';
    }
    html += '<div class="sec"><h4>Port history · ' + v.calls.length + ' observed calls (WPI, 12 km)</h4><div class="list">' + v.calls.slice().reverse().slice(0, 40).map(function (c) { return '<div class="li"><span>' + esc(E.PORT[c.port].name) + ' <span class="muted">' + E.PORT[c.port].cc + '</span></span><span class="s">' + (c.arrObserved ? fDs(c.t0) : 'before ' + fDs(c.t0)) + ' → ' + (c.open ? 'present' : fDs(c.t1)) + ' · ' + dur(c.dwellH) + '</span></div>'; }).join('') + '</div></div>';
    el.innerHTML = html; renderAIS(); drawShipTL(v);
  }
  function tc(s) { return String(s || '').toLowerCase().replace(/\b([a-z])/g, function (m) { return m.toUpperCase(); }).replace(/\b(Jsc|Uk|Usa|Ifremer|Jamstec|Kiost|Fio|Tio|Ev|Md|Ii)\b/gi, function (m) { return m.toUpperCase(); }).replace(/\bGovt\b/g, 'Govt.').replace(/^Chinacoastguard(\d+)/, 'China Coast Guard $1'); }
  function gfwSec(v) {
    var G = v.gfw;
    if (!G.ids.length) return '<div class="sec"><h4>Global Fishing Watch</h4><p class="muted" style="margin:0">No GFW identity passed the track check for this ship.</p></div>';
    var Ls = G.events.filter(function (g) { return g.k === 'L'; }), Ps = G.events.filter(function (g) { return g.k === 'P'; }), Gs = G.events.filter(function (g) { return g.k === 'G'; });
    var days = Ls.reduce(function (s, g) { return s + g.h; }, 0) / 24, top = Ls.slice().sort(function (a, b) { return b.h - a.h; }).slice(0, 6);
    return '<div class="sec"><h4>Activity timeline · ' + monY(TL0) + ' – ' + monY(TL1) + '</h4><canvas class="shiptl" id="shiptl" aria-label="Activity timeline for ' + esc(v.name) + '"></canvas>' +
      '<div class="legend"><span><i style="background:#ffd34d"></i>Survey</span><span><i style="background:#a585ff"></i>Station</span><span><i style="background:#4fc58b"></i>GFW loitering</span><span><i style="background:#304656"></i>Port (GFW)</span><span><i style="background:#ff5f56"></i>AIS gap</span></div>' +
      '<p class="muted" style="margin:0;font-size:11.5px">The shaded band is our ' + fD(E.T_START) + ' – ' + fD(E.AS_OF) + ' AIS window. Outside it, only Global Fishing Watch events are known. Click the strip to set the map time.</p>' +
      kv([['GFW loitering (≥ 6 h)', Ls.length + ' events · ' + f1(days) + ' d'], ['GFW port visits', Ps.length], ['GFW AIS-gap events', Gs.length], ['GFW identities matched', G.ids.length]]) +
      (top.length ? '<div class="list">' + top.map(function (g) { return '<div class="li"><span>' + fDs(g.t0) + ' · ' + dur(g.h) + ' <span class="muted">' + fLat(g.lat) + ' ' + fLon(g.lon) + (g.portKm != null ? ' · ' + g.portKm + ' km from port' : '') + '</span></span><button class="link" type="button" data-gfwz="' + g.lat + ',' + g.lon + '">Show</button></div>'; }).join('') + '</div>' : '') + '</div>';
  }
  function overview() {
    var t = { P1: 0, P2: 0, P3: 0, P4: 0 }; D.events.forEach(function (e) { t[e.tier]++; });
    return '<div class="overview"><h2>Theatre overview</h2><p class="muted" style="margin:0">' + D.stats.vessels + ' vessels, ' + D.stats.positionsRaw.toLocaleString() + ' real AIS fixes from ' + fD(E.T_START) + ' to ' + fD(E.AS_OF) + '. ' + D.events.length + ' detections: ' + D.stats.surveys + ' lawnmower surveys and ' + D.stats.stations + ' stationkeeping operations. Pick a vessel or an alert to see its assessment.</p><div class="tiers">' + ['P1', 'P2', 'P3', 'P4'].map(function (p) { return '<div class="tier ' + p + '"><b>' + t[p] + '</b><span>' + p + '</span></div>'; }).join('') + '</div><div class="list">' + D.events.slice(0, 6).map(function (e) { return '<button class="alert ' + e.tier + '" type="button" data-ev="' + e.id + '"><span class="bar"></span><span class="bd"><span class="r1"><span class="ptag ' + e.tier + '">' + e.tier + '</span><span class="nm">' + esc(V[e.vessel].name) + '</span></span><span class="why">' + esc(e.why.slice(0, 3).join(' · ')) + '</span></span></button>'; }).join('') + '</div></div>';
  }

  /* ---------- navigation ---------- */
  function pad() { var b = S.brief >= 0 && window.innerWidth > 860, bw = b ? ($('brief').offsetWidth || 420) + 30 : 40; return { paddingTopLeft: [bw, 40], paddingBottomRight: [b ? 30 : (window.innerWidth > 860 ? 240 : 30), 80] }; }
  function evBounds(e) {
    var pts = [];
    if (e.L) { pts = e.L.hull.length > 2 ? e.L.hull.slice() : []; e.L.lines.forEach(function (l) { pts.push(l.a, l.b); }); if (!pts.length) pts = [E.offset(e.center[0], e.center[1], -20, -20), E.offset(e.center[0], e.center[1], 20, 20)]; }
    if (e.S) { var r = Math.max(8, e.S.r95 * 8); pts = [E.offset(e.S.center[0], e.S.center[1], -r, -r), E.offset(e.S.center[0], e.S.center[1], r, r)]; }
    if (e.coord) e.coord.forEach(function (k) { pts.push(EVI[k.id].center); });
    return L.latLngBounds(pts);
  }
  function flyEvent(e, maxZ) { var o = pad(); o.maxZoom = maxZ || 10; o.duration = 0.9; map.flyToBounds(evBounds(e), o); }
  function flyTrack(v) { var o = pad(); o.maxZoom = 8; o.duration = 0.9; map.flyToBounds(L.latLngBounds(v.pts.map(function (p) { return [p.lat, p.lon]; })), o); }
  function focusVessel(id, evId, fly) {
    S.focus = id; var v = V[id]; S.sel.add(id); S.ev = evId || (v.top ? v.top.id : null); S.open[v.flag] = true;
    renderFleet(); renderAlerts(); renderIntel(); renderMap(); drawHist();
    if (fly !== false) { var e = S.ev ? EVI[S.ev] : null; if (e) flyEvent(e); else flyTrack(v); }
  }
  function focusEvent(id, fly) { var e = EVI[id]; focusVessel(e.vessel, id, fly); }

  /* ---------- briefing ---------- */
  function ev(vid, model) { return D.events.filter(function (e) { return e.vessel === vid && (!model || e.model === model); }).sort(function (a, b) { return b.priScore - a.priScore; })[0]; }
  /* ---------- briefing v3: BLUF, one claim per step, replay, annotations, detector walkthrough ---------- */
  function ev(vid, model) { return D.events.filter(function (e) { return e.vessel === vid && (!model || e.model === model); }).sort(function (a, b) { return b.priScore - a.priScore; })[0]; }
  function evs(f) { return D.events.filter(f).sort(function (a, b) { return a.t0 - b.t0; }); }
  function boundsOf(list, extra) { var pts = []; list.forEach(function (e) { var b = evBounds(e); pts.push(b.getSouthWest(), b.getNorthEast()); }); (extra || []).forEach(function (p) { pts.push(L.latLng(p[0], p[1])); }); return L.latLngBounds(pts); }
  function uniq(a) { return a.filter(function (x, i) { return a.indexOf(x) === i; }); }
  function spread(notes, km) { var out = []; notes.forEach(function (n) { var near = out.filter(function (o) { return E.hav(o.at[0], o.at[1], n.at[0], n.at[1]) < km; })[0]; if (near) near.html += '<br>' + n.html; else out.push(n); }); return out; }
  function briefSteps() {
    var flagged = D.vessels.filter(function (v) { return v.events.length; }).map(function (v) { return v.id; });
    /* Survey Detector: live data, so the reference site, ships and numbers below may be absent or differ; each is checked */
    var GV = D.gfwVal, RG = E.REGRESSION, REF = (E.REFERENCE && E.REFERENCE.chikyu) || null, site = REF && REF.gfw && REF.gfw.site && V.chikyu ? REF.gfw.site : null;
    var bw = site ? (site.bbox[2] - site.bbox[0]) * 111.32 * Math.cos(site.lat * Math.PI / 180) : 0, bh = site ? (site.bbox[3] - site.bbox[1]) * 110.574 : 0;
    var siteDays = site ? ((site.t1 - site.t0) / DAY).toFixed(1) : '', siteWhen = site ? fDs(site.t0) + '–' + fDs(site.t1) : '';
    var MON = function (t) { return ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][new Date(t).getUTCMonth()]; };
    var months = Math.max(1, Math.round((E.AS_OF - E.T_START) / (30.4 * DAY)));
    var span = months + (months === 1 ? ' month' : ' months');
    var nAsia = D.events.filter(function (e) { return e.center[0] > 0 && e.center[0] < 46 && e.center[1] > 100 && e.center[1] < 158; }).length;
    var isa = evs(function (e) { return e.zone; });
    // judgment 1 material: Chinese geology surveys beside the China–Japan median line
    var ecs = evs(function (e) { return (e.vessel === 'haiyangdizhibahao' || e.vessel === 'haiyangdizhijiuhao') && e.L; });
    var ecsLines = ecs.reduce(function (s, e) { return s + e.L.n; }, 0);
    var bdk = ecs.filter(function (e) { return e.boundary; }).map(function (e) { return e.boundary.km; });
    var bmin = bdk.length ? Math.round(Math.min.apply(null, bdk)) : 0, bmax = bdk.length ? Math.round(Math.max.apply(null, bdk)) : 0;
    var conc = 0; ecs.forEach(function (e) { e.coord.forEach(function (k) { if (k.vessel === 'haiyangdizhibahao' || k.vessel === 'haiyangdizhijiuhao') conc = Math.max(conc, k.overlapH); }); });
    var walkE = ecs.filter(function (e) { return e.vessel === 'haiyangdizhibahao'; }).sort(function (a, b) { return b.L.n - a.L.n; })[0] || ecs[0];
    var mid = ecs.length ? [ecs.reduce(function (s, e) { return s + e.center[0]; }, 0) / ecs.length, ecs.reduce(function (s, e) { return s + e.center[1]; }, 0) / ecs.length] : null;
    // judgment 2: Japan around Chikyu's site
    var jp = site ? evs(function (e) { return (e.vessel === 'hakurei' || e.vessel === 'kaimei') && e.S && E.hav(e.center[0], e.center[1], site.lat, site.lon) < 250; }) : [];
    var jpBy = {}; jp.forEach(function (e) { (jpBy[e.vessel] = jpBy[e.vessel] || []).push(e); });
    var jpAllGfw = jp.length && jp.every(function (e) { return e.gfw; });
    // judgment 3: Chinese state ships inside other EEZs
    var fe = evs(function (e) { return V[e.vessel].country === 'China' && e.eez && e.eez.sov.indexOf('China') < 0; });
    var feBy = {}; fe.forEach(function (e) { var k = e.eez.name.replace(' Exclusive Economic Zone', ' EEZ'); (feBy[k] = feBy[k] || []).push(e); });
    var liu = fe.filter(function (e) { return e.vessel === 'haiyangdizhiliuhao'; })[0] || fe[0];
    var cdm = ev('cotesdelamanche');
    var chn = D.vessels.filter(function (v) { return v.country === 'China'; }).length;
    var nm = function (id) { return '<b>' + esc(tc(V[id] ? V[id].name : id)) + '</b>'; };
    var own = function (id) { return V[id] && V[id].gfw && V[id].gfw.owner ? esc(tc(V[id].gfw.owner)) : 'owner not in registry'; };
    var ecsIds = uniq(ecs.map(function (e) { return e.vessel; }));
    var steps = [];
    steps.push({ k: 'Bottom line up front', bluf: true, title: 'Judgments from ' + span + ' of real AIS', theatre: true, sel: flagged, kj: [],
      trust: '<b>Why trust the detections:</b> ' + (site ? 'the stationkeeping model matches Chikyu’s documented rare-earth mud test, and ' : '') + GV.skAgree + ' of ' + GV.sk + ' station detections coincide with Global Fishing Watch’s own, independently computed loitering events. The survey detector finds ' + RG.survey.tp + ' of ' + (RG.survey.tp + RG.survey.fn) + ' surveys in the labeled test set with no false alarms.' });
    steps.push({ k: 'The season', title: MON(E.T_START) + ' to ' + MON(E.AS_OF) + ' in 25 seconds', lapse: true,
      pts: [D.stats.vessels + ' ships and ' + D.stats.positionsRaw.toLocaleString() + ' real hourly AIS fixes from Global Fishing Watch.', 'Each ship trails its last four days. Yellow squares are surveys and purple dots are stationkeeping. Each one flashes when it starts.', 'Ship colours follow each ship’s highest priority: orange P2, blue P3, grey P4.'],
      so: nAsia + ' of ' + D.events.length + ' detections are in the East and South China Seas and the waters around Japan. Only ' + isa.length + ' fall inside ISA contract areas.' });
    if (walkE) {
      var L1 = walkE.L, wv = V[walkE.vessel], nFix = wv.pts.filter(function (p) { return p.t >= walkE.t0 && p.t <= walkE.t1; }).length;
      var top = walkE.L.hull.length ? walkE.L.hull.slice().sort(function (a, b) { return b[0] - a[0]; })[0] : walkE.center;
      var base = { ev: walkE.id, sel: [walkE.vessel], layers: { calls: false, gfw: false, hot: false, ree: false, zones: false } };
      steps.push(Object.assign({ k: 'How the survey detector works', title: 'Start from raw positions', walk: 0,
        pts: [nFix + ' hourly AIS reports from ' + nm(walkE.vessel) + ', ' + fDs(walkE.t0) + ' to ' + fDs(walkE.t1) + '.', 'Each dot is one position. On its own, this looks like a ship going back and forth.'],
        notes: [{ at: walkE.center, html: 'One dot = one hourly<br>AIS position report', dir: 'right' }] }, base));
      steps.push(Object.assign({ k: 'How the survey detector works', title: 'Find straight, steady passes', walk: 1,
        pts: ['The detector finds <b>' + L1.n + ' passes</b>, each about ' + f1(L1.meanLen) + ' km long, run at ' + f1(L1.speed) + ' kn.', 'Each turn reverses course by nearly 180° (on average ' + f1(L1.dev) + '° off).'],
        notes: [{ at: L1.lines[0].a, html: 'Each yellow line is<br>one straight pass', dir: 'left' }] }, base));
      steps.push(Object.assign({ k: 'How the survey detector works', title: 'Group the passes into a survey block', walk: 2,
        pts: ['Passes run ' + L1.axisCompass + ', <b>' + f1(L1.spacing) + ' km apart</b>, with very even spacing (CV ' + L1.spacingCV.toFixed(2) + ').', 'Together they cover <b>' + Math.round(L1.area).toLocaleString() + ' km²</b>, and ' + Math.round(L1.progression * 100) + '% of steps move onto new ground.'],
        notes: [{ at: top, html: '<b>Survey footprint</b><br>' + Math.round(L1.area).toLocaleString() + ' km² · ' + L1.n + ' passes', dir: 'top' }] }, base));
      steps.push(Object.assign({ k: 'How the survey detector works', title: 'Score the fit, then the importance', walk: 3,
        pts: ['Detection confidence <b>' + walkE.confScore.toFixed(2) + '</b> (' + walkE.confLabel + '), from the team’s detector.', 'Priority <b>' + walkE.tier + '</b> (' + walkE.priScore.toFixed(2) + ') is scored separately: location, vessel class, history.'],
        extra: '<details class="more" open><summary>Confidence evidence</summary>' + bars(walkE.conf) + '</details>',
        so: 'Confidence says “this is a survey.” Priority says “this one matters.” Clean geometry alone never makes a detection urgent.' }, base));
    }
    var J = {};
    if (ecs.length) {
      J.ecs = steps.length;
      steps.push({ k: 'Judgment 1', conf: 'HIGH', title: (ecsIds.length > 1 ? 'Two Chinese geology ships' : 'A Chinese geology ship') + ' mapped the seabed beside the China–Japan median line',
        pts: [ecsIds.map(function (id) { return nm(id) + ' (' + own(id) + ')'; }).join(' and ') + ' ran <b>' + ecs.length + ' survey blocks</b> and <b>' + ecsLines + ' lines</b>, ' + fDs(ecs[0].t0) + ' to ' + fDs(ecs.reduce(function (m, e) { return Math.max(m, e.t1); }, 0)) + '.',
          'Every block is <b>' + bmin + '–' + bmax + ' km</b> from the median line, inside China’s EEZ as mapped by Marine Regions.',
          conc ? 'The two ships surveyed the same area at the same time, for up to ' + dur(conc) + ' of overlap.' : 'The ships returned to the same blocks on separate voyages.'],
        so: 'This is systematic seabed mapping right up to a disputed maritime boundary. It is worth tasking higher-resolution collection.',
        sel: ecsIds, ev: ecs.slice().sort(function (a, b) { return b.L.n - a.L.n; })[0].id, bounds: boundsOf(ecs).pad(0.35), z: 8,
        replay: { t0: ecs[0].t0 - 2 * DAY, t1: ecs.reduce(function (m, e) { return Math.max(m, e.t1); }, 0) + DAY, ms: 8000 },
        layers: { hot: false, ree: false, zones: false, eez: true, gfw: false, calls: false },
        notes: [{ at: [mid[0] + 0.12, mid[1] + 0.42], html: '<b>China–Japan median line</b><br>' + bmin + '–' + bmax + ' km from the surveys', cls: 'warn', dir: 'top' }, { at: [mid[0] - 0.12, mid[1] - 0.18], html: '<b>' + ecsLines + ' survey lines</b><br>' + (ecsIds.length > 1 ? ecsIds.length + ' ships' : 'one ship') + ' · ' + ecs.length + ' blocks', dir: 'left' }] });
    }
    if (jp.length) {
      J.jp = steps.length;
      var jpNotes = [{ at: [site.lat, site.lon], html: '<b>Chikyu</b> · ' + siteWhen + '<br>' + siteDays + ' d at ' + Math.round(-site.depth).toLocaleString() + ' m (GFW)', cls: 'ree', dir: 'right' }];
      Object.keys(jpBy).forEach(function (id) { var L2 = jpBy[id]; jpNotes.push({ at: L2[0].center, html: '<b>' + esc(tc(V[id].name)) + '</b> · ' + L2.map(function (e) { return fDs(e.t0); }).join(', ') + '<br>' + L2.map(function (e) { return dur(e.S.onHours); }).join(' + ') + ' on station', dir: 'left' }); });
      steps.push({ k: 'Judgment 2', conf: 'HIGH', title: 'Japan is following up its rare-earth mud test near Minamitorishima',
        pts: [nm('chikyu') + ' held station for <b>' + siteDays + ' days</b> from ' + fDs(site.t0) + ', in ' + Math.round(-site.depth).toLocaleString() + ' m of water, ' + site.mntKm + ' km from the island (Global Fishing Watch event record).'].concat(Object.keys(jpBy).map(function (id) { var L2 = jpBy[id]; return nm(id) + ' (' + own(id) + '): ' + L2.length + ' stop' + (L2.length > 1 ? 's' : '') + ' of ' + L2.map(function (e) { return dur(e.S.onHours); }).join(' and ') + ' in ' + uniq(L2.map(function (e) { return MON[new Date(e.t0).getUTCMonth()]; })).join(' and ') + ', <b>' + Math.round(E.hav(L2[0].center[0], L2[0].center[1], site.lat, site.lon)) + ' km</b> from Chikyu’s site.'; }))
          .concat(['Stationkeeping model: ' + E.STATION_RULE + '.' + (jpAllGfw ? ' Each of these stops is also a GFW loitering event.' : '')]),
        so: (E.WATCH[0] ? esc(E.WATCH[0].basis) + ' ' : '') + 'These follow-on stops make this the site to watch.',
        sel: Object.keys(jpBy).concat(['chikyu']), ev: jp[0].id, win: [jp[0].t0 - 3 * DAY, jp.reduce(function (m, e) { return Math.max(m, e.t1); }, 0) + 2 * DAY], showRef: true, bounds: boundsOf(jp, [[site.lat, site.lon]]).pad(0.35), z: 9,
        layers: { ree: true, zones: false, hot: false, calls: false }, notes: spread(jpNotes.slice(1), 90).concat([jpNotes[0]]) });
    }
    if (fe.length) {
      J.fe = steps.length;
      steps.push({ k: 'Judgment 3', conf: 'MODERATE', title: 'Chinese state ships worked inside EEZs claimed by neighbours',
        pts: Object.keys(feBy).map(function (k) { var L3 = feBy[k]; return '<b>' + esc(k) + '</b>: ' + uniq(L3.map(function (e) { return esc(tc(V[e.vessel].name)) + ' (' + E.MODEL[e.model].short.toLowerCase() + ')'; })).join(', '); })
          .concat(['EEZs as mapped by Marine Regions. Several of these waters are disputed, and China does not accept all of these limits.']),
        so: 'Research surveys in another state’s EEZ normally need that state’s consent (UNCLOS Art. 246). Coast guard patterns are more likely patrols. Check the research-ship detections against published consents first.',
        sel: uniq(fe.map(function (e) { return e.vessel; })), ev: liu.id, win: [fe[0].t0 - 3 * DAY, E.AS_OF], bounds: boundsOf(fe).pad(0.12), z: 6,
        layers: { eez: true, zones: false, hot: false, calls: false, gfw: false },
        notes: spread(fe.map(function (e) { return { at: e.center, html: '<b>' + esc(tc(V[e.vessel].name)) + '</b> · ' + E.MODEL[e.model].short.toLowerCase(), dir: 'right', cls: 'warn' }; }), 160) });
    }
    if (isa.length) {
      J.isa = steps.length;
      steps.push({ k: 'Judgment 4', conf: 'MODERATE', title: 'Ships stopped inside ' + uniq(isa.map(function (e) { return e.zone.id; })).length + ' ISA contract area' + (uniq(isa.map(function (e) { return e.zone.id; })).length > 1 ? 's' : '') + '. No mining was seen.',
        pts: isa.map(function (e) { return nm(e.vessel) + ' held station for ' + dur(e.S ? e.S.onHours : (e.t1 - e.t0) / H) + ' inside the ' + esc(e.zone.contractor) + ' contract area (sponsor: ' + esc(e.zone.sponsor || '—') + '), ' + fDs(e.t0) + '.'; })
          .concat(['Nothing in ' + span + ' matches a collection pattern. But hourly positions on a 1 km grid cannot show 100 m collector lanes either.']),
        so: 'Absence of evidence is weak here. Ruling collection out would need higher-rate AIS or imagery.',
        sel: uniq(isa.map(function (e) { return e.vessel; })), ev: isa[0].id, win: [isa[0].t0 - 5 * DAY, E.AS_OF], bounds: boundsOf(isa).pad(0.25), z: 6,
        layers: { zones: true, eez: true, hot: false, calls: false },
        notes: isa.map(function (e) { return { at: e.center, html: '<b>' + esc(tc(V[e.vessel].name)) + '</b><br>inside ' + esc(e.zone.contractor), dir: 'right', cls: 'ree' }; }) });
    }
    if (cdm) steps.push({ k: 'Reading the scores', title: 'A clean survey that does not matter much',
      pts: [nm('cotesdelamanche') + ' ran a textbook survey' + (cdm.eez ? ' in the ' + esc(cdm.eez.name.replace(' Exclusive Economic Zone', ' EEZ')) : '') + ': detector score <b>' + cdm.confScore.toFixed(2) + '</b>.', 'It is a research ship near its home coast and far from any mineral area, so its priority is <b>' + cdm.tier + '</b>.'],
      so: 'Keeping the two scores apart stops clean geometry from flooding the queue.', ev: cdm.id, z: 8, sel: ['cotesdelamanche'], layers: { calls: false } });
    if (site) steps.push({ k: 'How we know', title: 'Three independent checks agree', refsite: true, showRef: true, sel: ['chikyu'], layers: { ree: true },
      pts: ['<b>Ground truth.</b> Chikyu’s ' + siteWhen + ' rare-earth test is a stationkeeping detection. GFW’s record puts the whole ' + siteDays + ' days inside a ' + bw.toFixed(2) + ' × ' + bh.toFixed(2) + ' km box.',
        '<b>Independent system.</b> ' + GV.skAgree + ' of ' + GV.sk + ' station detections overlap a GFW loitering event. We caught ' + (GV.gfwLong - GV.gfwMissed) + ' of ' + GV.gfwLong + ' long, tight GFW stops' + (GV.gfwMissed ? '; the misses are listed under Validation.' : '.'),
        '<b>Labeled test set.</b> The survey detector finds ' + RG.survey.tp + ' of ' + (RG.survey.tp + RG.survey.fn) + ' surveys' + (RG.survey.fp ? ' with ' + RG.survey.fp + ' false alarm' + (RG.survey.fp > 1 ? 's' : '') : ' with no false alarms') + '.'],
      so: '<b>Validation</b> in the header has every number, the misses, and the analyst review workflow.',
      notes: [{ at: [site.lat, site.lon], html: '<b>Chikyu test site</b><br>' + bw.toFixed(2) + ' × ' + bh.toFixed(2) + ' km for ' + siteDays + ' d', cls: 'ok', dir: 'right' }] });
    steps.push({ k: 'Limits & what to watch', title: 'What this data cannot show, and what comes next', theatre: true, sel: flagged,
      pts: ['Positions are hourly on a ~1 km grid. That is fine for survey lines and multi-day stops, but too coarse for dynamic positioning or collector lanes.', chn + ' of ' + D.stats.vessels + ' monitored ships are Chinese, so the share of Chinese activity partly reflects how the fleet was chosen.', 'Vessel class is still partly inferred. ' + D.stats.registry + ' ships have a registry owner in GFW.'],
      so: E.WATCH.length ? '<b>Watch:</b> ' + E.WATCH.map(function (w) { return esc(w.title) + ' (' + esc(w.window) + ')'; }).join('; ') + '.' : 'Watch the queue: new detections arrive with each weekly update.' });
    var kj = [];
    if (J.ecs !== undefined) kj.push({ step: J.ecs, conf: 'HIGH', t: (ecsIds.length > 1 ? 'Two Chinese geology ships' : 'A Chinese geology ship') + ' mapped the seabed beside the China–Japan median line.', s: ecsLines + ' survey lines in ' + ecs.length + ' blocks, ' + bmin + '–' + bmax + ' km from the line.' });
    if (J.jp !== undefined) kj.push({ step: J.jp, conf: 'HIGH', t: 'Japan is following up its rare-earth mud test near Minamitorishima.', s: 'After Chikyu’s ' + siteDays + '-day test, ' + Object.keys(jpBy).map(function (id) { return tc(V[id].name); }).join(' and ') + ' held station within ' + Math.round(Math.max.apply(null, jp.map(function (e) { return E.hav(e.center[0], e.center[1], site.lat, site.lon); }))) + ' km of the site.' });
    if (J.fe !== undefined) kj.push({ step: J.fe, conf: 'MODERATE', t: 'Chinese state ships worked inside EEZs claimed by neighbours.', s: Object.keys(feBy).map(function (k) { return k.replace(' EEZ', ''); }).join(', ') + '. Several of these waters are disputed.' });
    if (J.isa !== undefined) kj.push({ step: J.isa, conf: 'MODERATE', t: 'Ships stopped inside ISA contract areas. No mining was seen.', s: 'The data is too coarse to rule out collection.' });
    steps[0].kj = kj;
    return steps;
  }
  var STEPS = null, RP = { raf: 0 };
  function addNotes(list) {
    var W = map.getContainer().clientWidth, Hh = map.getContainer().clientHeight, bw = S.brief >= 0 ? ($('brief').offsetWidth || 400) + 12 : 0, NW = 240;
    var ns = (list || []).map(function (n) { var p = map.latLngToContainerPoint(n.at); return { n: n, x: p.x, y: p.y }; }).sort(function (a, b) { return a.x - b.x; });
    ns.forEach(function (q, k) {
      var prevX = k ? ns[k - 1].x : bw, nextX = k < ns.length - 1 ? ns[k + 1].x : W, near = function (o) { return o && Math.abs(o.y - q.y) < 70; };
      var roomR = (near(ns[k + 1]) ? nextX : W) - q.x, roomL = q.x - (near(ns[k - 1]) ? prevX : bw), dir;
      if (q.n.dir === 'top') dir = q.y < 120 ? 'bottom' : 'top';
      else if (roomR >= NW) dir = 'right';
      else if (roomL >= NW) dir = 'left';
      else dir = (k % 2) ? 'top' : 'bottom';
      if (dir === 'top' && q.y < 110) dir = 'bottom';
      gNote.addLayer(L.circleMarker(q.n.at, { renderer: rEvt, radius: 3, color: '#ffffff', weight: 1, fillColor: '#ffffff', fillOpacity: 1, interactive: false }));
      var off = dir === 'left' ? [-10, 0] : dir === 'top' ? [0, -8] : dir === 'bottom' ? [0, 8] : [10, 0];
      gNote.addLayer(L.tooltip({ permanent: true, direction: dir, offset: off, className: 'lbl note ' + (q.n.cls || ''), interactive: false }).setLatLng(q.n.at).setContent(q.n.html));
    });
  }
  function stopReplay() { if (RP.raf) cancelAnimationFrame(RP.raf); RP.raf = 0; }
  function runReplay(s) {
    if (!s || !s.replay) return; stopReplay();
    var r = s.replay, t0 = Math.max(E.T_START, r.t0), t1 = Math.min(E.AS_OF, r.t1), st = performance.now(), ms = r.ms || 6000, me = S.brief;
    S.trackFrom = t0;
    function f(now) { if (S.brief !== me) return; var a = Math.min(1, (now - st) / ms); setTime(t0 + (t1 - t0) * a, 'quiet'); if (a < 1) RP.raf = requestAnimationFrame(f); else { RP.raf = 0; renderAIS(); } }
    RP.raf = requestAnimationFrame(f);
  }
  function walkGeom() {
    var we = EVI[S.walk.ev], wv = V[we.vessel], st = S.walk.stage, i0 = Math.max(0, idxAt(wv, we.t0 - 6 * H)), i1 = idxAt(wv, we.t1 + 6 * H);
    if (st >= 2 && we.L.hull.length > 2) gDyn.addLayer(L.polygon(we.L.hull, { renderer: rEvt, color: '#ffd34d', weight: 1.4, dashArray: '5 4', fillColor: '#ffd34d', fillOpacity: 0.1, interactive: false }));
    if (st >= 1) { var path = []; for (var i = i0; i <= i1; i++) path.push([wv.pts[i].lat, wv.pts[i].lon]); gDyn.addLayer(L.polyline(path, { renderer: rTrk, color: '#7fb6d6', weight: 1, opacity: 0.35, interactive: false })); }
    for (var j = i0; j <= i1; j++) { var q = wv.pts[j]; gDyn.addLayer(L.circleMarker([q.lat, q.lon], { renderer: rEvt, radius: st === 0 ? 2.4 : 1.5, stroke: false, fillColor: st === 0 ? '#ffffff' : '#a1b5c3', fillOpacity: st === 0 ? 0.9 : 0.45, interactive: false })); }
    if (st >= 1) we.L.lines.forEach(function (l) { gDyn.addLayer(L.polyline([l.a, l.b], { renderer: rEvt, color: '#ffd34d', weight: 2.6, opacity: 0.95, interactive: false })); });
  }
  function briefCard(s, i) {
    var x = '<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" stroke-width="1.5"/></svg>';
    var head = '<div class="bh"><span class="k">' + (i + 1) + '/' + STEPS.length + ' · ' + esc(s.k.toUpperCase()) + '</span>' + (s.conf ? '<span class="cbadge ' + s.conf + '" title="Analytic confidence in this judgment">' + s.conf + ' CONFIDENCE</span>' : '') + '<span class="sp"></span><button class="x" type="button" id="b-x" aria-label="Close briefing">' + x + '</button></div>';
    var body;
    if (s.bluf) body = '<div class="bb"><div class="claim">' + s.title + '</div><div class="kj">' + s.kj.map(function (k, j) { return '<button type="button" data-bj="' + k.step + '"><span class="n">' + (j + 1) + '</span><span class="t">' + esc(k.t) + '<small>' + esc(k.s) + '</small></span><span class="cbadge ' + k.conf + '">' + k.conf + '</span></button>'; }).join('') + '</div><p class="trust">' + s.trust + '</p></div>';
    else body = '<div class="bb"><div class="claim">' + esc(s.title) + '</div>' +
      (s.walk !== undefined ? '<div class="walk">' + ['RAW FIXES', 'PASSES', 'BLOCK', 'SCORE'].map(function (w, j) { return '<span class="' + (j <= s.walk ? 'on' : '') + '">' + w + '</span>'; }).join('') + '</div>' : '') +
      (s.pts ? '<ul class="ev">' + s.pts.map(function (p) { return '<li><span>' + p + '</span></li>'; }).join('') + '</ul>' : '') + (s.extra || '') +
      (s.so ? '<p class="so"><span>SO WHAT</span>' + s.so + '</p>' : '') + '</div>';
    var foot = '<div class="bf"><div class="dots">' + STEPS.map(function (_, j) { return '<i class="' + (j <= i ? 'on' : '') + '"></i>'; }).join('') + '</div>' + (s.replay ? '<button class="tbtn" type="button" id="b-replay">Replay</button>' : '') + (i > 0 ? '<button class="tbtn" type="button" id="b-prev">Back</button>' : '') + '<button class="tbtn primary" type="button" id="b-next">' + (i === STEPS.length - 1 ? 'Finish' : i === 0 ? 'Start' : 'Next') + '</button></div>';
    return head + body + foot;
  }
  function brief(i) {
    STEPS = STEPS || briefSteps(); $('intro').classList.add('hide'); store.d.intro = true; store.save();
    stopLapse(true); stopReplay(); gNote.clearLayers(); S.walk = null; S.trackFrom = null; S.showRef = false;
    var mw = document.querySelector('.mapwrap');
    if (i < 0 || i >= STEPS.length) {
      S.brief = -1; $('brief').classList.remove('on'); mw.classList.remove('dim'); foldLayers(false);
      if (S.layersSaved) { S.layers = S.layersSaved; S.layersSaved = null; renderLayers(); applyStaticLayers(); }
      setTime(E.AS_OF); return;
    }
    if (S.view !== 'map') setView('map');
    if (!S.layersSaved) S.layersSaved = Object.assign({}, S.layers);
    var s = STEPS[i];
    S.layers = Object.assign({}, S.layersSaved, s.layers || {}); renderLayers(); applyStaticLayers(); mw.classList.add('dim'); foldLayers(true);
    S.brief = i; play(false); S.t = E.AS_OF;
    $('brief').className = 'brief on' + (s.bluf ? ' bluf' : ''); $('brief').innerHTML = briefCard(s, i);
    if (s.sel) S.sel = new Set(s.sel);
    S.showRef = !!s.showRef;
    var o = pad(); o.duration = 0.9;
    if (s.walk !== undefined) { S.walk = { ev: s.ev, stage: s.walk }; S.t = EVI[s.ev].t1; focusEvent(s.ev, false); var we = EVI[s.ev], hb = L.latLngBounds(we.L.hull.length > 2 ? we.L.hull : [E.offset(we.center[0], we.center[1], -20, -20), E.offset(we.center[0], we.center[1], 20, 20)]); o.maxZoom = 10; map.flyToBounds(hb.pad(0.25), o); }
    else if (s.lapse) { S.focus = null; S.ev = null; renderFleet(); renderAlerts(); renderIntel(); drawHist(); o.duration = 0.8; map.flyToBounds([[-40, 30], [62, 250]], o); setTimeout(function () { if (S.brief === i) startLapse({ dur: 25000 }); }, 850); }
    else if (s.refsite) { focusVessel('chikyu', null, false); var gs = E.REFERENCE.chikyu.gfw.site; o.maxZoom = 7; map.flyToBounds([E.offset(gs.lat, gs.lon, -260, -260), E.offset(gs.lat, gs.lon, 260, 260)], o); }
    else if (s.bounds) { if (s.ev) focusEvent(s.ev, false); o.maxZoom = s.z || 8; map.flyToBounds(s.bounds, o); }
    else if (s.ev) { focusEvent(s.ev, false); flyEvent(EVI[s.ev], s.z); }
    else { S.focus = null; S.ev = null; renderFleet(); renderAlerts(); renderIntel(); drawHist(); map.flyToBounds([[-40, 30], [62, 250]], o); }
    if (s.win) { S.trackFrom = s.win[0]; S.t = s.win[1]; }
    setTime(S.t, 'quiet');
    var me = i, placed = false; function place() { if (placed || S.brief !== me) return; placed = true; addNotes(s.notes); }
    map.once('moveend', place); setTimeout(place, 1300);
    if (s.replay) setTimeout(function () { if (S.brief === i) runReplay(s); }, 1000);
    var nb = $('b-next'); if (nb) nb.focus();
  }

  /* ---------- exports ---------- */
  function textBrief(e) {
    var v = V[e.vessel], c = caseOf(e.id), L0 = [];
    L0.push('SEATRACE · ACTIVITY BRIEF · AIS: GLOBAL FISHING WATCH (HOURLY, ~1 KM GRID)');
    L0.push(e.id + ' · ' + E.MODEL[e.model].label.toUpperCase() + ' · ' + e.status);
    L0.push('Vessel: ' + v.name + ' (' + v.country + ') · MMSI ' + v.mmsi + ' · IMO ' + v.imo + ' · ' + E.CLASS[v.cls].label);
    L0.push('Window: ' + iso(e.t0) + ' → ' + (e.active ? 'ongoing' : iso(e.t1)) + ' (' + dur((e.t1 - e.t0) / H) + ')');
    L0.push('Location: ' + fLat(e.center[0]) + ' ' + fLon(e.center[1]) + (e.zone ? ' · ISA ' + e.zone.contractor : ''));
    if (v.gfw.owner) L0.push('Registry owner (GFW): ' + v.gfw.owner + (v.gfw.ownerFlag ? ' (' + v.gfw.ownerFlag + ')' : ''));
    L0.push('Detection confidence: ' + e.confScore.toFixed(2) + ' (' + e.confLabel + ')');
    if (e.S) L0.push('Independent check: ' + (e.gfw ? 'GFW loitering event ' + dur(e.gfw.hours) + ', ' + Math.round(e.gfw.overlap * 100) + '% overlap' : 'no overlapping GFW loitering event'));
    L0.push('Analyst priority: ' + e.tier + ' (' + e.priScore.toFixed(2) + ')');
    L0.push('Why flagged: ' + e.why.join('; '));
    L0.push('Priority factors: ' + e.pri.map(function (p) { return p.label + ' ' + p.v.toFixed(2) + ' (' + p.detail + ')'; }).join('; '));
    if (e.voyage) L0.push('Voyage: ' + E.PORT[e.voyage.from].name + ' → ' + (e.voyage.to ? E.PORT[e.voyage.to].name : 'at sea') + (e.voyage.same ? ' (same-port return)' : ''));
    L0.push('Case status: ' + c.state + (c.note ? ' · Note: ' + c.note : ''));
    return L0.join('\n');
  }
  function geojson(e) {
    var v = V[e.vessel], f = [];
    var props = { event_id: e.id, vessel: v.name, mmsi: v.mmsi, imo: v.imo, flag: v.flag, model: e.model, status: e.status, start: iso(e.t0), end: iso(e.t1), confidence: +e.confScore.toFixed(3), priority: e.tier, priority_score: e.priScore, source: 'Global Fishing Watch AIS via vesseltracker-v2' };
    function lo(p) { return [+nlon(p[1]).toFixed(5), +p[0].toFixed(5)]; }
    var hull = e.L && e.L.hull.length > 2 ? e.L.hull : null;
    if (hull) f.push({ type: 'Feature', properties: Object.assign({ kind: 'footprint' }, props), geometry: { type: 'Polygon', coordinates: [hull.concat([hull[0]]).map(lo)] } });
    if (e.S) f.push({ type: 'Feature', properties: Object.assign({ kind: 'station_center', radius95_m: Math.round(e.S.r95 * 1000) }, props), geometry: { type: 'Point', coordinates: lo(e.S.center) } });
    if (e.L) e.L.lines.forEach(function (l) { f.push({ type: 'Feature', properties: { kind: 'survey_line', event_id: e.id, line: l.k, length_km: +l.len.toFixed(2), start: iso(l.t0), end: iso(l.t1) }, geometry: { type: 'LineString', coordinates: [lo(l.a), lo(l.b)] } }); });
    return JSON.stringify({ type: 'FeatureCollection', features: f }, null, 1);
  }
  function toast(msg) { var t = $('toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(t._h); t._h = setTimeout(function () { t.classList.remove('on'); }, 2200); }
  function copy(text, label) {
    function fallback() { showSheet(label, '<p>Your browser blocked clipboard access here. Select the text below and copy it.</p><textarea class="note" style="min-height:320px;font-family:var(--f-mono);font-size:11.5px" readonly id="cptxt">' + esc(text) + '</textarea>'); var ta = $('cptxt'); ta.focus(); ta.select(); }
    try { navigator.clipboard.writeText(text).then(function () { toast(label + ' copied'); }, fallback); } catch (err) { fallback(); }
  }

  /* ---------- method sheet ---------- */
  function showSheet(title, body) { $('sheet').innerHTML = '<header><h2>' + esc(title) + '</h2><button class="x" type="button" id="sheet-x" aria-label="Close"><svg width="12" height="12" viewBox="0 0 10 10" aria-hidden="true"><path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" stroke-width="1.5"/></svg></button></header><div class="body">' + body + '</div>'; $('method').classList.add('on'); $('sheet-x').focus(); }
  function methodSheet() {
    var st = D.stats, cnt = function (m) { return D.events.filter(function (e) { return e.model === m; }).length; };
    var tr = function (rows) { return rows.map(function (r) { return '<tr><td>' + r[0] + '</td><td class="n">' + (typeof r[1] === 'number' ? r[1].toLocaleString() : r[1]) + '</td></tr>'; }).join(''); };
    var b = '<section><h3>Where the data comes from</h3><div class="tw"><table class="t"><thead><tr><th>Layer</th><th>Source</th><th>Notes</th></tr></thead><tbody>' +
      '<tr><td><b>Vessel positions</b></td><td>Global Fishing Watch AIS (CC BY-NC 4.0), pulled weekly into the Survey Detector ship library</td><td>' + st.positionsRaw.toLocaleString() + ' fixes, hourly, 0.01° grid, ' + fD(E.T_START) + '–' + fD(E.AS_OF) + '. Simulated demo ships are left out. Repeated fixes in the same ~1 km cell are thinned for the page (' + st.positions.toLocaleString() + ' kept).</td></tr>' +
      '<tr><td><b>Vessel identity</b></td><td>Survey Detector ship library (library/vessels.csv): MMSI, IMO, call sign, flag. Registry owner, length and tonnage from GFW</td><td>Vessel class is inferred from the public name and operator. ' + st.registry + ' of ' + st.vessels + ' ships also carry a registry owner in GFW.</td></tr>' +
      '<tr><td><b>GFW events &amp; registry</b></td><td>Global Fishing Watch v3 API (loitering, port visits, AIS gaps, encounters; vessel identity), pulled weekly by <span class="mono">gfw_fetch.py --enrich</span></td><td>' + D.gfwVal.rows.toLocaleString() + ' events for ' + D.gfwVal.groupIds + ' ships over the last 12 months. Matched to our ships by MMSI. Loitering under 6 h is dropped (' + st.gfwEvents.toLocaleString() + ' kept).</td></tr>' +
      '<tr><td><b>Lawnmower surveys</b></td><td>The team’s <span class="mono">survey_pattern_detector.py</span> results in the export</td><td>' + cnt('LAWNMOWER_SURVEY') + ' survey areas, ' + st.surveyLines + ' survey lines, ' + st.screened + ' rejected patterns. Confidence is the detector’s own score.</td></tr>' +
      '<tr><td><b>Stationkeeping</b></td><td>Survey Detector <span class="mono">stationkeeping.py</span> on the same positions</td><td>' + cnt('STATIONKEEPING_OPERATION') + ' operations: ' + E.STATION_RULE + '.</td></tr>' +
      '<tr><td><b>Interface</b></td><td>SeaTrace, a JMU capstone prototype, adapted to the Survey Detector pipeline</td><td>Layout, scoring engine, briefing and review workflow from SeaTrace; data, ports, routes, uploads and model comparison from the Survey Detector.</td></tr>' +
      '<tr><td><b>Mineral contract areas</b></td><td>International Seabed Authority public map service, read live (not stored), <a href="https://www.isa.org.jm/maps" target="_blank" rel="noopener">isa.org.jm/maps</a></td><td>' + st.zones + ' active contracts: nodules (PMN), polymetallic sulphides (PMS), cobalt-rich crusts (CFC).</td></tr>' +
      '<tr><td><b>EEZs</b></td><td>Marine Regions World EEZ v12 (VLIZ), <a href="https://www.marineregions.org/" target="_blank" rel="noopener">marineregions.org</a></td><td>Each detection centre looked up against the EEZ polygons; ' + D.eezLines.length.toLocaleString() + ' boundary lines (200 nm limits, median lines, treaties, unsettled and joint-regime lines) drawn on the map, simplified to about 2 km.</td></tr>' +
      '<tr><td><b>Water depth</b></td><td>GEBCO 2020 grid via <a href="https://www.opentopodata.org/" target="_blank" rel="noopener">OpenTopoData</a></td><td>Depth sampled at each detection centre only (15 arc-second grid).</td></tr>' +
      '<tr><td><b>Ports</b></td><td>WPI-derived catalog (NGA Pub. 150) from the project folder</td><td>' + st.ports.toLocaleString() + ' ports. A port call is speed under 2 kn within 12 km of a port.</td></tr>' +
      '<tr><td><b>Rare-earth sites</b></td><td>The team’s curated <span class="mono">ree_sites</span> list, plus Minamitorishima</td><td>Locations approximate, per the source.</td></tr>' +
      '<tr><td><b>Coastlines</b></td><td>Apache ECharts world map</td><td>Display only.</td></tr></tbody></table></div></section>' +
      '<div class="cols"><section><h3>What was computed</h3><div class="tw"><table class="t"><tbody>' + tr([['Vessels', st.vessels], ['Detections', st.events], ['Lawnmower surveys', st.surveys], ['Stationkeeping operations', st.stations], ['Observed port calls', st.calls], ['Voyages', st.voyages], ['AIS gaps over 12 h at sea', st.gaps], ['Same-port returns after an operation', st.sameReturns], ['Detections with concurrent vessels', st.coord]]) + '</tbody></table></div></section>' +
      '<section><h3>Backend regression baseline</h3><div class="tw"><table class="t"><tbody>' + tr([['AIS positions', '2,778'], ['Survey areas', '6'], ['Survey lines', '48'], ['AIS gaps', '2'], ['Observed port calls', '17'], ['Voyages', '7'], ['Same-port returns', '2']]) + '</tbody></table></div><p>The Python pipeline’s synthetic test set. It is a regression test for the code and is not shown on the map.</p></section></div>' +
      '<section><h3>Priority factors</h3><div class="tw"><table class="t"><thead><tr><th>Factor</th><th>Weight</th><th>Scoring</th></tr></thead><tbody>' +
      [['Resource context', 22, 'Inside an ISA contract area scores by mineral type; within 300 km of Minamitorishima 0.8; within 300 km of an ISA area half; otherwise low.'], ['Vessel class', 22, 'Mining 1.0, drilling 0.9, resource survey and deep-submergence 0.75, offshore support and research 0.5, oil and gas 0.35, coast guard 0.25.'], ['EEZ / jurisdiction', 16, 'Inside a foreign EEZ 1.0; inside an overlapping claim 0.75; high seas in an area sponsored by another state 0.8; within 50 km of a foreign boundary 0.6; high seas 0.4; own EEZ 0.15.'], ['Water depth', 10, 'Deeper than 1,000 m 1.0; 200–1,000 m 0.6; shelf 0.15; land cell 0.05.'], ['Pattern of life', 10, 'Repeat visits, other vessels at the same site, several operations per voyage, same-port cycles.'], ['Multi-vessel activity', 8, 'Another detection within 80 km overlapping by at least 12 h.'], ['AIS gaps', 6, 'A gap over 12 h at sea within 7 days before or during the operation.'], ['Recency', 6, 'Relative to the latest fix in the data.']].map(function (r) { return '<tr><td><b>' + r[0] + '</b></td><td class="n">' + r[1] + '%</td><td>' + r[2] + '</td></tr>'; }).join('') +
      '</tbody></table></div><p>Tiers: P1 at 0.70 and above, P2 at 0.50, P3 at 0.35, P4 below. No detection in this window reaches P1. The weights are a starting point for analysts to tune.</p></section>' +
      '<section><h3>Limits</h3><p>Hourly, 1 km gridded positions cannot show dynamic-positioning corrections or collector lanes, so the pilot-collection model is not run. Vessel class is inferred. EEZ lookups follow Marine Regions, which does not encode every contested claim (for example, most South China Sea claims). Global Fishing Watch data is licensed for non-commercial use; check terms before government use.</p></section>';
    showSheet('Method & data', b);
  }

  function nextUnreviewed() {
    var L1 = alertList(), i = Math.max(0, L1.findIndex(function (x) { return x.id === S.ev; }));
    for (var k = 1; k <= L1.length; k++) { var e = L1[(i + k) % L1.length], st = caseOf(e.id).state; if (st !== 'CONFIRMED' && st !== 'DISMISSED') { setTab('alerts'); return focusEvent(e.id); } }
    toast('Every detection in the current filter has a review label');
  }
  function validationSheet() {
    var RG = E.REGRESSION, sv = RG.survey, pass = RG.rows.filter(function (r) { return r[4]; }).length;
    var lab = function (m) { var ev = D.events.filter(function (e) { return !m || e.model === m; }), tp = 0, fp = 0, un = 0; ev.forEach(function (e) { var st = caseOf(e.id).state; if (st === 'CONFIRMED') tp++; else if (st === 'DISMISSED') fp++; else un++; }); return { n: ev.length, tp: tp, fp: fp, un: un, prec: tp + fp ? tp / (tp + fp) : null }; };
    var all = lab(), sv2 = lab('LAWNMOWER_SURVEY'), sk = lab('STATIONKEEPING_OPERATION');
    var band = function (lo, hi) { var ev = D.events.filter(function (e) { return e.depth !== null && -e.depth >= lo && -e.depth < hi; }), tp = 0, fp = 0; ev.forEach(function (e) { var st = caseOf(e.id).state; if (st === 'CONFIRMED') tp++; else if (st === 'DISMISSED') fp++; }); return [ev.length, tp, fp, tp + fp ? Math.round(100 * tp / (tp + fp)) + '%' : '—']; };
    var pct = function (x) { return x === null ? '—' : Math.round(x * 100) + '%'; };
    var anch = D.events.filter(function (e) { return e.anchorage; }), near = D.events.filter(function (e) { return e.L && e.L.offshore < 50; }), land = D.events.filter(function (e) { return e.depth !== null && e.depth >= 0; });
    var ck = E.REFERENCE.chikyu;
    var b = '<section><h3>1 · Survey detector against a labeled test set</h3><p>' + RG.rows.length + ' test vessels with known behavior, run through the Python pipeline. Ground truth is each test set’s labels file.</p>' +
      '<div class="tiers" style="grid-template-columns:repeat(4,1fr)"><div class="tier P3"><b>' + Math.round(100 * sv.tp / (sv.tp + sv.fp)) + '%</b><span>PRECISION</span></div><div class="tier P3"><b>' + Math.round(100 * sv.tp / (sv.tp + sv.fn)) + '%</b><span>RECALL</span></div><div class="tier"><b>' + sv.tp + '/' + (sv.tp + sv.fn) + '</b><span>SURVEYS FOUND</span></div><div class="tier ' + (pass === RG.rows.length ? 'P3' : 'P2') + '"><b>' + pass + '/' + RG.rows.length + '</b><span>VESSELS FULLY CORRECT</span></div></div>' +
      '<div class="tw"><table class="t"><thead><tr><th>Vessel</th><th>Designed behavior</th><th>Pipeline result</th><th>Pass</th></tr></thead><tbody>' + RG.rows.map(function (r) { return '<tr><td class="mono">' + r[0] + '</td><td>' + esc(r[1]) + '</td><td>' + esc(r[3]) + '</td><td style="color:' + (r[4] ? 'var(--ok)' : 'var(--p1)') + ';font-weight:600">' + (r[4] ? 'Yes' : 'No') + '</td></tr>'; }).join('') + '</tbody></table></div>' +
      (RG.note ? '<p>' + RG.note + '</p>' : '<p><b>Fixed 6 Nov 2026:</b> the detector used to merge SYN009’s two survey episodes into one area, so revisits were missed. <span class="mono">survey_pattern_detector.py</span> now starts a new block after a 24 h pause and keeps blocks more than 48 h apart as separate areas. All 10 test vessels now pass. New baseline: 7 survey areas, 48 lines, 41 turn points, 7 survey-port links (see <span class="mono">REGRESSION_BASELINE.md</span>). The detections on the map still come from the deployed Streamlit detector, which needs the same change. The test set is small and clean, so treat 100% as a floor check, not field accuracy.</p><p class="muted" style="font-size:11.5px">' + esc(RG.source) + '</p></section>') +
      (!(ck && ck.gfw && ck.gfw.site) ? '' : function () { var g = ck.gfw, st = g.site, durH = (st.t1 - st.t0) / H, bw = (st.bbox[2] - st.bbox[0]) * 111.32 * Math.cos(st.lat * Math.PI / 180), bh = (st.bbox[3] - st.bbox[1]) * 110.574, chk = [
        ];   /* Survey Detector: every check below is computed from the reference events, GFW events and station thresholds */
        var SC2 = (E.EXTRAS && E.EXTRAS.stationCfg) || { min_hours: 48, max_median_kn: 1, min_port_km: 60, r95_km: 3 };
        var evAt = function (re) { return ck.events.filter(function (x) { return re.test(x.label); })[0]; };
        var arr = evAt(/arriv/i), dep = evAt(/depart/i);
        var back = g.events.filter(function (x) { return /port/i.test(x.kind) && x.t0 >= st.t1 && x.t0 - st.t1 < 30 * DAY; })[0];
        var shortStop = g.events.filter(function (x) { return /loiter/i.test(x.kind) && dep && x.t0 >= dep.t && x.t1 <= st.t0 && (x.t1 - x.t0) / H < SC2.min_hours; })[0];
        chk = [
        ['Starts within 24 h of reported arrival' + (arr ? ' (' + fDs(arr.t) + ')' : ''), fDT(st.t0), arr ? Math.abs(st.t0 - arr.t) < DAY : null],
        ['Dwell of at least ' + SC2.min_hours + ' h (model trigger) and 14 d (test)', dur(durH), durH >= 14 * 24],
        ['Median speed under ' + SC2.max_median_kn + ' kn', st.kn.toFixed(2) + ' kn average', st.kn < SC2.max_median_kn],
        ['Far from port (model: more than ' + SC2.min_port_km + ' km)', 'nearest land Minamitorishima ' + st.mntKm + ' km', st.mntKm > SC2.min_port_km],
        ['Water deeper than 5,000 m', Math.round(-st.depth).toLocaleString() + ' m (ETOPO)', st.depth < -5000],
        ['Returns to port after the test', back ? fDT(back.t0) + ' · ' + back.label : 'no port visit within 30 days', back ? true : null]]
        .concat(shortStop ? [['No false trigger on the short stop after departure', dur((shortStop.t1 - shortStop.t0) / H) + ', under the ' + SC2.min_hours + ' h minimum', true]] : [])
        .concat([['Stays within ' + SC2.r95_km + ' km of the anchor point', 'GFW bounding box ' + bw.toFixed(2) + ' × ' + bh.toFixed(2) + ' km for the whole ' + (durH / 24).toFixed(1) + ' d', bw < 2 * SC2.r95_km && bh < 2 * SC2.r95_km]]);
        return '<section><h3>2 · Stationkeeping model against a known operation</h3><p>Public reporting gives a dated ground-truth case: Chikyu’s rare-earth mud test. Global Fishing Watch’s own event record for Chikyu (MMSI 432522000), pulled from its events API, confirms the operation independently and gives its location: <b>' + fLat(st.lat) + ' ' + fLon(st.lon) + '</b>.</p>' +
        '<div class="tiers" style="grid-template-columns:repeat(3,1fr)"><div class="tier P3"><b>' + chk.filter(function (c) { return c[2] === true; }).length + '/' + chk.length + '</b><span>CRITERIA MET</span></div><div class="tier"><b>' + chk.filter(function (c) { return c[2] === null; }).length + '</b><span>NEED FULL TRACK</span></div><div class="tier"><b>' + chk.filter(function (c) { return c[2] === false; }).length + '</b><span>FAILED</span></div></div>' +
        '<div class="tw"><table class="t"><thead><tr><th>Pass criterion</th><th>Observed</th><th>Result</th></tr></thead><tbody>' + chk.map(function (c) { return '<tr><td>' + esc(c[0]) + '</td><td>' + esc(c[1]) + '</td><td style="font-weight:600;color:' + (c[2] === true ? 'var(--ok)' : c[2] === null ? 'var(--p2)' : 'var(--p1)') + '">' + (c[2] === true ? 'Pass' : c[2] === null ? 'Pending' : 'Fail') + '</td></tr>'; }).join('') + '</tbody></table></div>' +
        '<div class="tw"><table class="t"><thead><tr><th>GFW event</th><th>Window (UTC)</th><th>Detail</th></tr></thead><tbody>' + g.events.map(function (x) { return '<tr><td>' + esc(x.kind) + '</td><td class="mono">' + fDT(x.t0) + ' → ' + fDT(x.t1) + '</td><td>' + esc(x.label) + '</td></tr>'; }).join('') + '</tbody></table></div>' +
        '<p><b>Finding:</b> ' + (durH / 24).toFixed(1) + ' days nearly motionless in ' + Math.round(-st.depth).toLocaleString() + ' m of water' + (back ? ', then a return to port' : '') + '. GFW’s event record bounds every position in the event to ' + bw.toFixed(2) + ' × ' + bh.toFixed(2) + ' km. ' + chk.filter(function (c) { return c[2] === true; }).length + ' of ' + chk.length + ' criteria pass.</p><p class="muted" style="font-size:11.5px">' + esc(g.source) + '</p></section>'; }()) +
      gfwValSec() +
      '<section><h3>3 · Analyst review of the real detections</h3><p>Precision on real data needs human labels. In each detection’s Case panel, mark <b>CONFIRMED</b> for real survey or station work and <b>DISMISSED</b> for false alarms. The numbers below update as you go.</p>' +
      '<div class="tiers"><div class="tier"><b>' + (all.tp + all.fp) + '/' + all.n + '</b><span>REVIEWED</span></div><div class="tier P3"><b>' + pct(all.prec) + '</b><span>PRECISION · ALL</span></div><div class="tier P3"><b>' + pct(sv2.prec) + '</b><span>SURVEYS</span></div><div class="tier P3"><b>' + pct(sk.prec) + '</b><span>STATIONKEEPING</span></div></div>' +
      '<div class="tw"><table class="t"><thead><tr><th>Water depth</th><th>Detections</th><th>Confirmed</th><th>Dismissed</th><th>Precision</th></tr></thead><tbody>' + [['Shelf (< 200 m)', band(0, 200)], ['Slope (200–1,000 m)', band(200, 1000)], ['Deep (> 1,000 m)', band(1000, 99999)]].map(function (r) { return '<tr><td>' + r[0] + '</td>' + r[1].map(function (x) { return '<td class="n">' + x + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap"><button class="tbtn primary" type="button" id="v-review">Start reviewing</button><button class="tbtn" type="button" id="v-export">Copy labels as JSON</button></div><p class="muted" style="font-size:11.5px">Labels stay in this browser. Copy the JSON to share them with the team or feed them back into the scoring weights.</p></section>' +
      '<section><h3>4 · Automatic plausibility checks</h3><p>These are rules of thumb that flag detections worth a second look. They are not ground truth.</p><div class="tw"><table class="t"><tbody>' +
      '<tr><td>Stationkeeping in under 200 m of water within 150 km of a port (possible anchoring)</td><td class="n">' + anch.length + ' of ' + sk.n + '</td></tr>' +
      '<tr><td>Surveys less than 50 km offshore (possible coastal or harbor work)</td><td class="n">' + near.length + ' of ' + sv2.n + '</td></tr>' +
      '<tr><td>Detection centre falls on a GEBCO land or intertidal cell</td><td class="n">' + land.length + '</td></tr>' +
      '<tr><td>Line patterns the survey detector rejected</td><td class="n">' + D.stats.screened + '</td></tr></tbody></table></div></section>';
    showSheet('Validation', b);
  }

  function gfwValSec() {
    var G = D.gfwVal, noM = D.events.filter(function (e) { return e.S && !e.gfw; });
    var by = {}; G.missed.forEach(function (m) { by[m.vessel] = (by[m.vessel] || 0) + 1; });
    return '<section><h3>2b · Cross-check against Global Fishing Watch loitering events</h3><p>GFW computes its own loitering events from full-rate AIS with a different method. Where both systems see a ship stop, the detection is independently corroborated.</p>' +
      '<div class="tiers" style="grid-template-columns:repeat(4,1fr)"><div class="tier P3"><b>' + G.skAgree + '/' + G.sk + '</b><span>OUR STATION OPS GFW ALSO FLAGS</span></div><div class="tier P3"><b>' + (G.gfwLong - G.gfwMissed) + '/' + G.gfwLong + '</b><span>LONG, TIGHT GFW STOPS WE CAUGHT</span></div><div class="tier"><b>' + G.ids.accepted + '</b><span>GFW IDENTITIES ACCEPTED</span></div><div class="tier"><b>' + G.ids.rejected + '</b><span>IDENTITIES REJECTED</span></div></div>' +
      '<p><b>Recall check.</b> GFW lists ' + G.gfwLong + ' loitering events in our window that last at least 24 h and move less than 10 km in total. We caught ' + (G.gfwLong - G.gfwMissed) + '.' + (G.gfwMissed ? ' The ' + G.gfwMissed + ' misses are on ' + Object.keys(by).map(function (k) { return by[k] + ' × ' + esc(k); }).join(', ') + '; they are the first ones to check against our tracks.' : '') + ' A further ' + G.gfwDrift + ' GFW loitering events of 24 h or more drift more than 10 km and are not stationkeeping by our definition.</p>' +
      '<p><b>Precision check.</b> ' + noM.length + ' of our ' + G.sk + ' station detections have no overlapping GFW event: ' + noM.map(function (e) { return esc(tc(V[e.vessel].name)) + ' (' + fDs(e.t0) + ')'; }).join(', ') + '. These are the first ones to review by hand.</p>' +
      '<p><b>Identity check.</b> GFW events are matched to our ships by MMSI. Several MMSIs belong to more than one ship in GFW, so an event can occasionally belong to another vessel.</p><p class="muted" style="font-size:11.5px">GFW v3 events API (gfw_fetch.py --enrich), last 12 months, pulled ' + (G.pulled || 'not pulled yet') + '. ' + G.rows.toLocaleString() + ' events.</p></section>';
  }

  /* ---------- views: gallery and fleet timeline ---------- */
  /* Survey Detector: timeline bounds from the data (season + GFW events), not fixed to 2026 */
  var TL0 = (function () { var m = E.T_START; D.vessels.forEach(function (v) { (v.gfw && v.gfw.events || []).forEach(function (x) { if (x.t0 < m) m = x.t0; }); }); var d = new Date(m); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1); })();
  var TL1 = (function () { var m = E.AS_OF; D.vessels.forEach(function (v) { (v.gfw && v.gfw.events || []).forEach(function (x) { if (x.t1 > m) m = x.t1; }); }); return m + DAY; })();
  function monthStarts(a, b) { var d = new Date(a), out = [], t = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1); while (t < b) { out.push(t); d = new Date(t); t = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1); } return out; }
  function monY(t) { var d = new Date(t); return MON[d.getUTCMonth()] + ' ' + d.getUTCFullYear(); }
  var GAL = { model: 'ALL', sort: 'pri' }, TLV = { all: false, hits: [], rowsY: [] };
  function setView(vw) {
    if (vw !== 'map' && S.brief >= 0) brief(-1);
    if (vw !== 'map') stopLapse(true);
    S.view = vw; ['map', 'gallery', 'timeline'].forEach(function (k) { $('vw-' + k).setAttribute('aria-selected', k === vw); });
    var el = $('view');
    if (vw === 'map') { el.hidden = true; el.innerHTML = ''; $('tltip').style.display = 'none'; map.invalidateSize(); return; }
    el.hidden = false; if (vw === 'gallery') renderGallery(); else renderTimeline();
  }
  function ctxLine(e) {
    var a = e.zone ? 'ISA ' + E.ZONE_TYPES[e.zone.type].short + ' area · ' + e.zone.contractor : e.eez ? e.eez.name.replace(' Exclusive Economic Zone', ' EEZ') : 'High seas';
    if (e.boundary && e.boundary.km < 50) a += ' · ' + Math.round(e.boundary.km) + ' km from ' + e.boundary.name + ' ' + e.boundary.type.toLowerCase();
    if (e.depth != null && e.depth < 0) a += ' · ' + Math.round(-e.depth).toLocaleString() + ' m';
    return a;
  }
  function renderGallery() {
    var list = D.events.filter(function (e) { return GAL.model === 'ALL' || e.model === GAL.model; }).slice();
    list.sort(GAL.sort === 'conf' ? function (a, b) { return b.confScore - a.confScore; } : GAL.sort === 'date' ? function (a, b) { return a.t0 - b.t0; } : function (a, b) { return b.priScore - a.priScore || b.confScore - a.confScore; });
    var chips = [['ALL', 'All'], ['LAWNMOWER_SURVEY', 'Surveys'], ['STATIONKEEPING_OPERATION', 'Stationkeeping']].map(function (m) { return '<button class="chip" type="button" data-gm="' + m[0] + '" aria-pressed="' + (GAL.model === m[0]) + '">' + m[1] + '</button>'; }).join('') +
      '<span class="muted" style="margin:0 2px 0 8px;font-size:11.5px">Sort</span>' + [['pri', 'Priority'], ['conf', 'Confidence'], ['date', 'Date']].map(function (m) { return '<button class="chip" type="button" data-gs="' + m[0] + '" aria-pressed="' + (GAL.sort === m[0]) + '">' + m[1] + '</button>'; }).join('');
    $('view').innerHTML = '<div class="vhead"><h2>Signature gallery</h2><span class="muted">' + list.length + ' detections, each drawn from its own AIS fixes at its own scale. Yellow: survey lines. Purple: grid cells occupied on station. Click one to open it on the map.</span><span class="sp"></span><div class="chips">' + chips + '</div></div>' +
      '<div class="vbody"><div class="gal">' + list.map(function (e) {
        var v = V[e.vessel];
        return '<button class="gcard' + (S.ev === e.id ? ' is-focus' : '') + '" type="button" data-gev="' + e.id + '"><canvas id="th-' + e.id + '" width="424" height="280" aria-hidden="true"></canvas><span class="gc"><span class="g1"><span class="ptag ' + e.tier + '">' + e.tier + '</span><span class="nm">' + esc(v.name) + '</span><span class="flag">' + v.flag + '</span>' + (e.gfw ? '<span class="gfwok" title="A GFW loitering event overlaps this detection">GFW ✓</span>' : '') + '</span>' +
          '<span class="g2"><span class="model ' + e.model + '" style="line-height:16px;font-size:9.5px">' + E.MODEL[e.model].short + '</span>' + fDs(e.t0) + ' · ' + dur((e.t1 - e.t0) / H) + ' · conf ' + e.confScore.toFixed(2) + '</span><span class="g3">' + esc(ctxLine(e)) + '</span></span></button>';
      }).join('') + '</div></div>';
    list.forEach(function (e) { drawThumb($('th-' + e.id), e); });
  }
  function niceKm(x) { var c = [0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500]; for (var i = c.length - 1; i >= 0; i--) if (c[i] <= x) return c[i]; return 0.5; }
  function drawThumb(cv, e) {
    if (!cv) return; var c = cv.getContext('2d'), W = cv.width, Hh = cv.height, v = V[e.vessel];
    c.fillStyle = '#0a1923'; c.fillRect(0, 0, W, Hh);
    var g = [];
    if (e.L) { e.L.lines.forEach(function (l) { g.push(l.a, l.b); }); e.L.hull.forEach(function (p) { g.push(p); }); }
    if (e.S) e.S.cloud.forEach(function (q) { g.push(q); });
    if (!g.length) g.push(e.center);
    var la0 = Infinity, la1 = -Infinity, lo0 = Infinity, lo1 = -Infinity;
    g.forEach(function (p) { la0 = Math.min(la0, p[0]); la1 = Math.max(la1, p[0]); lo0 = Math.min(lo0, p[1]); lo1 = Math.max(lo1, p[1]); });
    var mla = (la0 + la1) / 2, mlo = (lo0 + lo1) / 2, kx = Math.cos(mla * Math.PI / 180);
    var minKm = e.L ? 14 : 5, hwKm = Math.max(minKm, (lo1 - lo0) * 111.32 * kx / 2 * 1.25, (la1 - la0) * 110.574 / 2 * 1.25 * W / Hh);
    var pxPerKm = (W / 2) / hwKm;
    function P(lat, lon) { return [W / 2 + (lon - mlo) * 111.32 * kx * pxPerKm, Hh / 2 - (lat - mla) * 110.574 * pxPerKm]; }
    // track around the event
    var i0 = Math.max(0, idxAt(v, e.t0 - 18 * H)), i1 = idxAt(v, e.t1 + 18 * H);
    c.lineWidth = 1.4; c.strokeStyle = 'rgba(127,182,214,0.5)'; c.beginPath();
    for (var i = i0; i <= i1; i++) { var q = v.pts[i], xy = P(q.lat, q.lon); if (i === i0 || v.pts[i].t - v.pts[i - 1].t > 10 * H || Math.abs(v.pts[i].lon - v.pts[i - 1].lon) > 90) c.moveTo(xy[0], xy[1]); else c.lineTo(xy[0], xy[1]); }
    c.stroke();
    c.fillStyle = 'rgba(221,232,239,0.7)';
    for (i = i0; i <= i1; i++) { q = v.pts[i]; if (q.t < e.t0 || q.t > e.t1) continue; xy = P(q.lat, q.lon); c.fillRect(xy[0] - 1.2, xy[1] - 1.2, 2.4, 2.4); }
    if (e.L) {
      if (e.L.hull.length > 2) { c.setLineDash([6, 5]); c.strokeStyle = 'rgba(255,211,77,0.7)'; c.lineWidth = 1.5; c.beginPath(); e.L.hull.forEach(function (p, k) { var xy = P(p[0], p[1]); if (k) c.lineTo(xy[0], xy[1]); else c.moveTo(xy[0], xy[1]); }); c.closePath(); c.stroke(); c.setLineDash([]); c.fillStyle = 'rgba(255,211,77,0.06)'; c.fill(); }
      c.strokeStyle = '#ffd34d'; c.lineWidth = 3; e.L.lines.forEach(function (l) { var a = P(l.a[0], l.a[1]), b = P(l.b[0], l.b[1]); c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(b[0], b[1]); c.stroke(); });
    }
    if (e.S) {
      var cell = 0.01 * 110.574 * pxPerKm;
      c.fillStyle = 'rgba(165,133,255,0.42)'; c.strokeStyle = '#a585ff'; c.lineWidth = 1;
      e.S.cloud.forEach(function (q) { var xy = P(q[0], q[1]); c.fillRect(xy[0] - cell / 2, xy[1] - cell / 2, cell, cell); c.strokeRect(xy[0] - cell / 2, xy[1] - cell / 2, cell, cell); });
      if (e.gfw) { var gx = P(e.center[0], e.center[1]); c.strokeStyle = '#4fc58b'; c.lineWidth = 2; c.beginPath(); c.arc(gx[0], gx[1], Math.max(cell * 1.6, 14), 0, Math.PI * 2); c.stroke(); }
    }
    // labels
    var km = niceKm(hwKm * 0.6), bw = km * pxPerKm;
    c.fillStyle = '#dde8ef'; c.fillRect(14, Hh - 18, bw, 3); c.font = '600 19px "IBM Plex Mono", monospace'; c.fillText(km + ' km', 14 + bw + 8, Hh - 12);
    c.fillStyle = e.L ? '#ffd34d' : '#c4b0ff'; c.fillText(e.L ? e.L.n + ' LINES · ' + f1(e.L.spacing) + ' KM APART' : dur(e.S.onHours).toUpperCase() + ' · ' + Math.round(e.S.r95 * 1000) + ' M R95', 14, 28);
  }

  function tlX(t, x0, w) { return x0 + (Math.max(TL0, Math.min(TL1, t)) - TL0) / (TL1 - TL0) * w; }
  function drawLane(c, v, x0, w, y, h, hits) {
    var X = function (t) { return tlX(t, x0, w); };
    c.fillStyle = '#2a4357'; c.fillRect(X(v.pts[0].t), y + h / 2 - 0.5, Math.max(1, X(v.last.t) - X(v.pts[0].t)), 1);
    function hit(a, b, txt, extra) { var o = { x: a - 1, y: y, w: Math.max(4, b - a) + 2, h: h, v: v.id, txt: txt }; for (var k in extra) o[k] = extra[k]; hits.push(o); }
    v.gfw.events.forEach(function (g) { if (g.k !== 'P' || g.t1 < TL0) return; var a = X(g.t0), b = X(g.t1); c.fillStyle = '#304656'; c.fillRect(a, y + 4, Math.max(1.5, b - a), h - 9); hit(a, b, '<b>' + esc(v.name) + '</b> · port visit (GFW)<br>' + esc(g.port || 'port') + ' · ' + fDs(g.t0) + ' → ' + fDs(g.t1) + ' · ' + dur(g.h), { t: g.t0 }); });
    v.gaps.forEach(function (gp) { var a = X(gp.t0), b = X(gp.t1); c.fillStyle = '#ff5f56'; c.fillRect(a, y + h / 2 - 2, Math.max(2, b - a), 4); hit(a, b, '<b>' + esc(v.name) + '</b> · AIS gap ' + dur(gp.hours) + '<br>' + fDs(gp.t0) + ' · ' + Math.round(gp.km) + ' km unreported', { t: gp.t0 }); });
    v.gfw.events.forEach(function (g) { if (g.k !== 'G') return; var a = X(g.t0), b = X(g.t1); c.strokeStyle = '#ff5f56'; c.lineWidth = 1; c.strokeRect(a, y + 2, Math.max(2, b - a), h - 5); hit(a, b, '<b>' + esc(v.name) + '</b> · AIS gap (GFW) ' + dur(g.h) + '<br>' + fDs(g.t0), { t: g.t0 }); });
    v.events.forEach(function (e) { var a = X(e.t0), b = X(e.t1); c.fillStyle = e.L ? '#ffd34d' : '#a585ff'; c.fillRect(a, y + 2, Math.max(3, b - a), h - 7); if (e.tier === 'P1' || e.tier === 'P2') { c.fillStyle = TIERC[e.tier]; c.fillRect(a, y, Math.max(3, b - a), 2); } hit(a, b, '<b>' + esc(v.name) + '</b> · ' + e.tier + ' ' + E.MODEL[e.model].label.toLowerCase() + '<br>' + fDs(e.t0) + ' → ' + fDs(e.t1) + ' · conf ' + e.confScore.toFixed(2) + '<br><span style="color:#a1b5c3">' + esc(ctxLine(e)) + '</span>', { ev: e.id, t: e.t0 }); });
    v.gfw.events.forEach(function (g) { if (g.k !== 'L' || g.h < 12) return; var a = X(g.t0), b = X(g.t1); c.fillStyle = g.h >= 48 ? '#4fc58b' : '#4fc58b77'; c.fillRect(a, y + h - 4, Math.max(1.5, b - a), 3); if (g.h >= 24) hit(a, b, '<b>' + esc(v.name) + '</b> · GFW loitering ' + dur(g.h) + '<br>' + fDs(g.t0) + ' → ' + fDs(g.t1) + ' · ' + f1(g.km) + ' km moved', { gfw: [g.lat, g.lon], t: g.t0 }); });
  }
  function tlAxis(c, x0, w, y0, y1, labels) {
    c.fillStyle = 'rgba(92,200,255,0.085)'; var a = tlX(E.T_START, x0, w), b = tlX(E.AS_OF, x0, w); c.fillRect(a, y0, b - a, y1 - y0);
    c.font = '9.5px "IBM Plex Mono", monospace'; c.textBaseline = 'top';
    monthStarts(TL0, TL1).forEach(function (tm) { var x = tlX(tm, x0, w); c.fillStyle = '#1c3141'; c.fillRect(x, y0, 1, y1 - y0); if (labels) { c.fillStyle = '#6f8797'; c.fillText(MON[new Date(tm).getUTCMonth()].toUpperCase(), x + 3, labels); } });
  }
  function renderTimeline() {
    var rows = D.vessels.filter(function (v) { return TLV.all || v.events.length || v.gfw.events.some(function (g) { return g.k === 'L' && g.h >= 48; }); }).sort(function (a, b) { return ((b.top && b.top.priScore) || 0) - ((a.top && a.top.priScore) || 0) || a.name.localeCompare(b.name); });
    $('view').innerHTML = '<div class="vhead"><h2>Fleet timeline</h2><div class="legend"><span><i style="background:#ffd34d"></i>Survey</span><span><i style="background:#a585ff"></i>Stationkeeping</span><span><i style="background:#ff5f56;height:3px"></i>P1/P2 marker</span><span><i style="background:#4fc58b;height:3px"></i>GFW loitering</span><span><i style="background:#304656"></i>Port visit (GFW)</span><span><i style="background:#ff5f56"></i>AIS gap</span><span><i style="background:rgba(92,200,255,.25)"></i>Our AIS window</span></div><span class="sp"></span><button class="chip" type="button" id="tl-all" aria-pressed="' + TLV.all + '">All ' + D.vessels.length + ' ships</button></div>' +
      '<div class="vbody"><div class="tlwrap" id="tlwrap"><canvas id="tlc"></canvas></div></div>';
    var wrap = $('tlwrap'), cv = $('tlc'), W = wrap.clientWidth || 900, LW = 178, RH = 22, TOP = 24, Hh = TOP + rows.length * RH + 8, dpr = window.devicePixelRatio || 1;
    cv.width = W * dpr; cv.height = Hh * dpr; cv.style.width = W + 'px'; cv.style.height = Hh + 'px';
    var c = cv.getContext('2d'); c.scale(dpr, dpr); var x0 = LW, w = W - LW - 16;
    tlAxis(c, x0, w, TOP - 6, Hh, 6);
    TLV.hits = []; TLV.rowsY = [];
    rows.forEach(function (v, k) {
      var y = TOP + k * RH;
      if (v.id === S.focus) { c.fillStyle = 'rgba(92,200,255,0.10)'; c.fillRect(0, y - 1, W, RH); }
      c.fillStyle = v.top ? TIERC[v.top.tier] : '#2a4357'; c.fillRect(8, y + 5, 22, 11); c.fillStyle = '#06121a'; c.font = '600 9px "IBM Plex Mono", monospace'; c.textBaseline = 'middle'; if (v.top) c.fillText(v.top.tier, 12, y + 11);
      c.fillStyle = '#dde8ef'; c.font = '12px "IBM Plex Sans", sans-serif'; var lbl = tc(v.name); while (lbl.length > 3 && c.measureText(lbl).width > LW - 64) lbl = lbl.slice(0, -2); if (lbl !== tc(v.name)) lbl += '…'; c.fillText(lbl, 36, y + 11); c.fillStyle = '#6f8797'; c.font = '9.5px "IBM Plex Mono", monospace'; c.fillText(v.flag, LW - 22, y + 11);
      c.fillStyle = '#1c3141'; c.fillRect(x0, y + RH - 1, w, 1);
      drawLane(c, v, x0, w, y + 2, RH - 4, TLV.hits);
      TLV.rowsY.push({ y: y, v: v.id });
    });
    var tip = $('tltip');
    cv.onmousemove = function (ev) { var r = cv.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top, h = hitAt(x, y); cv.style.cursor = h || x < LW ? 'pointer' : 'default'; if (h) { tip.innerHTML = h.txt; tip.style.display = 'block'; tip.style.left = Math.min(window.innerWidth - 310, ev.clientX + 14) + 'px'; tip.style.top = (ev.clientY + 14) + 'px'; } else tip.style.display = 'none'; };
    cv.onmouseleave = function () { tip.style.display = 'none'; };
    cv.onclick = function (ev) {
      var r = cv.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top, h = hitAt(x, y);
      if (!h && x < LW) { var row = TLV.rowsY.filter(function (q) { return y >= q.y && y < q.y + RH; })[0]; if (row) { setView('map'); focusVessel(row.v); } return; }
      if (!h) return; setView('map');
      if (h.ev) return focusEvent(h.ev);
      focusVessel(h.v, null, false); if (h.t >= E.T_START && h.t <= E.AS_OF) setTime(h.t);
      if (h.gfw) flyTo(h.gfw[0], h.gfw[1]); else flyTrack(V[h.v]);
    };
  }
  function hitAt(x, y) { for (var i = TLV.hits.length - 1; i >= 0; i--) { var h = TLV.hits[i]; if (x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h) return h; } return null; }
  function drawShipTL(v) {
    var cv = $('shiptl'); if (!cv) return; var r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1; if (!r.width) return;
    cv.width = r.width * dpr; cv.height = r.height * dpr; var c = cv.getContext('2d'); c.scale(dpr, dpr);
    tlAxis(c, 6, r.width - 12, 0, r.height, 2); var hits = []; drawLane(c, v, 6, r.width - 12, 16, r.height - 20, hits);
    var tip = $('tltip');
    cv.onmousemove = function (ev) { var b = cv.getBoundingClientRect(), x = ev.clientX - b.left, y = ev.clientY - b.top, h = null; for (var i = hits.length - 1; i >= 0; i--) { var q = hits[i]; if (x >= q.x && x <= q.x + q.w && y >= q.y - 4 && y <= q.y + q.h + 4) { h = q; break; } } if (h) { tip.innerHTML = h.txt; tip.style.display = 'block'; tip.style.left = Math.min(window.innerWidth - 310, ev.clientX - 150) + 'px'; tip.style.top = (ev.clientY + 16) + 'px'; } else tip.style.display = 'none'; };
    cv.onmouseleave = function () { tip.style.display = 'none'; };
    cv.onclick = function (ev) { var b = cv.getBoundingClientRect(), t = TL0 + (ev.clientX - b.left - 6) / (b.width - 12) * (TL1 - TL0); tip.style.display = 'none'; if (t < E.T_START) { toast('Before our AIS window (starts ' + fD(E.T_START) + '). GFW events are shown on the strip.'); return; } play(false); setTime(Math.min(E.AS_OF, t)); };
  }
  function flyTo(lat, lon) { var o = pad(); o.maxZoom = 8; o.duration = 0.9; map.flyToBounds([E.offset(lat, lon, -40, -40), E.offset(lat, lon, 40, 40)], o); var m = L.circleMarker([lat, lon], { renderer: rEvt, radius: 14, color: '#4fc58b', weight: 2, fill: false, interactive: false }); gNote.addLayer(m); setTimeout(function () { gNote.removeLayer(m); }, 4000); }

  var LAYOPEN = null;
  function foldLayers(fold) { var d = $('layers'); if (fold) { if (LAYOPEN === null) LAYOPEN = d.open; d.open = false; } else if (LAYOPEN !== null) { d.open = LAYOPEN; LAYOPEN = null; } }
  /* ---------- season time-lapse ---------- */
  var LP = { on: false, raf: 0 }, lc = $('lapse');
  function sizeLapse() { var r = map.getContainer().getBoundingClientRect(), dpr = window.devicePixelRatio || 1; lc.width = r.width * dpr; lc.height = r.height * dpr; lc.style.width = r.width + 'px'; lc.style.height = r.height + 'px'; LP.dpr = dpr; }
  function lapseProject() {
    var z = map.getZoom(); LP.zoom = z;
    LP.proj = D.vessels.map(function (v) { var n = v.pts.length, xs = new Float64Array(n), ys = new Float64Array(n); for (var i = 0; i < n; i++) { var p = map.project([v.pts[i].lat, v.pts[i].lon], z); xs[i] = p.x; ys[i] = p.y; } return { xs: xs, ys: ys }; });
    LP.ev = D.events.slice().sort(function (a, b) { return a.t0 - b.t0; }).map(function (e) { var p = map.project(e.center, z); return { x: p.x, y: p.y, e: e }; });
  }
  function startLapse(opts) {
    opts = opts || {}; stopLapse(true); play(false);
    LP.on = true; LP.onEnd = opts.onEnd || null; LP.fired = {}; LP.pulses = []; LP.paused = false; LP.dur = opts.dur || 26000; LP.elapsed = 0; LP.last = performance.now(); LP.done = false; LP.hudT = 0; LP.nsv = 0; LP.nsk = 0;
    map.removeLayer(gDyn); map.removeLayer(gMk); foldLayers(true);
    lc.classList.add('on'); var hud = $('hud'); hud.classList.add('on');
    hud.innerHTML = '<div class="d" id="hud-d"></div><div class="c"><span class="sv"><b id="hud-sv">0</b>surveys</span><span class="sk"><b id="hud-sk">0</b>station ops</span><span><b id="hud-n">0</b>ships reporting</span></div><div class="bar"><i id="hud-bar" style="width:0"></i></div><div class="last" id="hud-last">Trails show the last four days of each track. Detections flash when they start.</div><div class="row"><button class="tbtn" type="button" id="hud-pause">Pause</button><button class="tbtn" type="button" id="hud-again">Restart</button><button class="tbtn" type="button" id="hud-x">Close</button></div>';
    sizeLapse(); lapseProject(); LP.raf = requestAnimationFrame(lapseFrame);
  }
  function stopLapse(silent) {
    if (!LP.on) return; LP.on = false; cancelAnimationFrame(LP.raf); lc.classList.remove('on'); $('hud').classList.remove('on');
    if (!map.hasLayer(gDyn)) gDyn.addTo(map); if (!map.hasLayer(gMk)) gMk.addTo(map); if (S.brief < 0) foldLayers(false);
    if (!silent) setTime(E.AS_OF);
  }
  map.on('zoomend', function () { if (LP.on) { lapseProject(); drawLapse(performance.now()); } });
  map.on('move zoom', function () { if (LP.on && (LP.paused || LP.done)) drawLapse(performance.now()); });
  window.addEventListener('resize', function () { if (LP.on) { sizeLapse(); drawLapse(performance.now()); } });
  function lapseFrame(now) {
    if (!LP.on) return; var dt = Math.min(100, now - LP.last); LP.last = now;
    if (!LP.paused) LP.elapsed = Math.min(LP.dur, LP.elapsed + dt);
    LP.t = E.T_START + (E.AS_OF - E.T_START) * LP.elapsed / LP.dur;
    drawLapse(now);
    if (LP.elapsed >= LP.dur && !LP.done) { LP.done = true; $('hud-pause').textContent = 'Done'; if (LP.onEnd) LP.onEnd(); }
    if (!LP.done || LP.pulses.length) LP.raf = requestAnimationFrame(lapseFrame);
  }
  function drawLapse(now) {
    var c = lc.getContext('2d'), dpr = LP.dpr; c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, lc.width / dpr, lc.height / dpr);
    var rc = map.latLngToContainerPoint([0, 180]), rp = map.project([0, 180], LP.zoom), sc = map.getZoomScale(map.getZoom(), LP.zoom), X = function (px) { return (px - rp.x) * sc + rc.x; }, Y = function (py) { return (py - rp.y) * sc + rc.y; }, t = LP.t, TR = 4 * DAY, nRep = 0;
    D.vessels.forEach(function (v, k) {
      var P = v.pts, pr = LP.proj[k], i1 = idxAt(v, t); if (i1 < 0) return;
      if (t - P[i1].t > 2 * DAY) return; nRep++;
      var col = v.top ? TIERC[v.top.tier] : '#8fa6b6', i0 = i1; while (i0 > 0 && P[i0 - 1].t > t - TR) i0--;
      for (var b = 0; b < 4; b++) {
        c.beginPath(); var any = false;
        for (var j = Math.max(i0, 1); j <= i1; j++) { var fr = (P[j].t - (t - TR)) / TR, bb = Math.min(3, Math.floor(fr * 4)); if (bb !== b || P[j].t - P[j - 1].t > 10 * H || Math.abs(P[j].lon - P[j - 1].lon) > 90) continue; c.moveTo(X(pr.xs[j - 1]), Y(pr.ys[j - 1])); c.lineTo(X(pr.xs[j]), Y(pr.ys[j])); any = true; }
        if (any) { c.strokeStyle = col; c.globalAlpha = 0.12 + b * 0.22; c.lineWidth = v.top ? 1.6 : 1; c.stroke(); }
      }
      c.globalAlpha = 1; var hx = X(pr.xs[i1]), hy = Y(pr.ys[i1]);
      if (i1 < P.length - 1 && P[i1 + 1].t - P[i1].t < 10 * H && Math.abs(P[i1 + 1].lon - P[i1].lon) < 90) { var f = (t - P[i1].t) / (P[i1 + 1].t - P[i1].t); hx += (pr.xs[i1 + 1] - pr.xs[i1]) * f * sc; hy += (pr.ys[i1 + 1] - pr.ys[i1]) * f * sc; }
      c.fillStyle = col; c.beginPath(); c.arc(hx, hy, v.top ? 2.8 : 2, 0, Math.PI * 2); c.fill();
    });
    var last = null;
    LP.ev.forEach(function (q) {
      var e = q.e; if (e.t0 > t) return;
      if (!LP.fired[e.id]) { LP.fired[e.id] = 1; LP.pulses.push({ x: q.x, y: q.y, born: now, col: e.L ? '#ffd34d' : '#a585ff' }); if (e.L) LP.nsv++; else LP.nsk++; last = e; }
      var act = t <= e.t1, x = X(q.x), y = Y(q.y);
      c.globalAlpha = act ? 1 : 0.55; c.fillStyle = e.L ? '#ffd34d' : '#a585ff';
      if (e.L) c.fillRect(x - 3, y - 3, 6, 6); else { c.beginPath(); c.arc(x, y, 3.2, 0, Math.PI * 2); c.fill(); }
      if (act) { c.strokeStyle = c.fillStyle; c.lineWidth = 1; c.beginPath(); c.arc(x, y, 7, 0, Math.PI * 2); c.stroke(); }
    });
    c.globalAlpha = 1;
    LP.pulses = LP.pulses.filter(function (p) { var a = (now - p.born) / 1400; if (a >= 1) return false; c.strokeStyle = p.col; c.globalAlpha = 1 - a; c.lineWidth = 2; c.beginPath(); c.arc(X(p.x), Y(p.y), 5 + a * 34, 0, Math.PI * 2); c.stroke(); return true; });
    c.globalAlpha = 1;
    if (last) { var lv = V[last.vessel]; $('hud-last').innerHTML = '<b>' + esc(lv.name) + '</b> · ' + E.MODEL[last.model].label.toLowerCase() + ' · ' + last.tier + '<br>' + esc(ctxLine(last)); }
    if (now - LP.hudT > 90 || LP.done) { LP.hudT = now; $('hud-d').textContent = fD(t); $('hud-sv').textContent = LP.nsv; $('hud-sk').textContent = LP.nsk; $('hud-n').textContent = nRep; $('hud-bar').style.width = (100 * LP.elapsed / LP.dur).toFixed(1) + '%'; }
  }

  /* ---------- events ---------- */
  document.addEventListener('click', function (ev) {
    var t = ev.target.closest('button,input'); if (!t) return;
    var d = t.dataset;
    if (t.id === 'tab-fleet') return setTab('fleet');
    if (t.id === 'tab-alerts') return setTab('alerts');
    if (d.grp) { S.open[d.grp] = !S.open[d.grp]; return renderFleet(); }
    if (d.grpsel) { var vs = D.vessels.filter(function (v) { return v.flag === d.grpsel && vMatch(v); }), all = vs.every(function (v) { return S.sel.has(v.id); }); vs.forEach(function (v) { if (all) S.sel.delete(v.id); else S.sel.add(v.id); }); renderFleet(); return renderMap(); }
    if (d.sel) { if (t.checked) S.sel.add(d.sel); else S.sel.delete(d.sel); renderFleet(); return renderMap(); }
    if (d.focus) return focusVessel(d.focus);
    if (d.ev) return focusEvent(d.ev);
    if (d.watch) { var w = E.WATCH.filter(function (x) { return x.id === d.watch; })[0]; return focusVessel(w.vessel); }
    if (d.f) { S.f[d.f] = !S.f[d.f]; renderFChips(); renderFleet(); return renderMap(); }
    if (d.pri) { S.pri[d.pri] = !S.pri[d.pri]; renderAChips(); return renderAlerts(); }
    if (d.model) { S.model = d.model; renderAChips(); return renderAlerts(); }
    if (d.layer) { S.layers[d.layer] = t.checked; applyStaticLayers(); return renderMap(); }
    if (d.gev) { setView('map'); return focusEvent(d.gev); }
    if (d.gm) { GAL.model = d.gm; return renderGallery(); }
    if (d.gs) { GAL.sort = d.gs; return renderGallery(); }
    if (d.bj) return brief(+d.bj);
    if (d.walk) return brief(+d.walk);
    if (d.gfwz) { var gz = d.gfwz.split(','); return flyTo(+gz[0], +gz[1]); }
    if (d.case) { var c = caseOf(S.ev); c.state = d.case; store.d.cases[S.ev] = c; store.save(); renderIntel(); return renderAlerts(); }
    switch (t.id) {
      case 'sel-clear': S.sel = new Set(S.focus ? [S.focus] : []); renderFleet(); return renderMap();
      case 'sel-events': D.vessels.forEach(function (v) { if (v.events.length && vMatch(v)) S.sel.add(v.id); }); renderFleet(); return renderMap();
      case 'star': var v = V[S.focus]; store.d.watch[v.id] = !isWatch(v); store.save(); renderIntel(); return renderFleet();
      case 'unfocus': S.focus = null; S.ev = null; renderFleet(); renderAlerts(); renderIntel(); renderMap(); return drawHist();
      case 'z-ev': return flyEvent(EVI[S.ev]);
      case 'z-ref': if (!(E.REFERENCE.chikyu && E.REFERENCE.chikyu.gfw)) return; var gs = E.REFERENCE.chikyu.gfw.site, o2 = pad(); o2.maxZoom = 8; o2.duration = 0.9; return map.flyToBounds([E.offset(gs.lat, gs.lon, -60, -60), E.offset(gs.lat, gs.lon, 60, 60)], o2);
      case 'z-tr': return flyTrack(V[S.focus]);
      case 'cp-brief': return copy(textBrief(EVI[S.ev]), 'Text brief');
      case 'cp-geo': return copy(geojson(EVI[S.ev]), 'GeoJSON');
      case 'play': stopLapse(true); return play(!S.playing);
      case 'season': if (LP.on) return stopLapse(); if (S.brief >= 0) brief(-1); setView('map'); var o4 = pad(); o4.duration = 0.6; map.flyToBounds([[-40, 30], [62, 250]], o4); return setTimeout(function () { startLapse(); }, 650);
      case 'hud-pause': if (LP.done) return; LP.paused = !LP.paused; t.textContent = LP.paused ? 'Resume' : 'Pause'; if (!LP.paused) { LP.last = performance.now(); LP.raf = requestAnimationFrame(lapseFrame); } return;
      case 'hud-again': var oe = LP.onEnd, du = LP.dur; startLapse({ dur: du, onEnd: oe }); return;
      case 'hud-x': return stopLapse();
      case 'b-replay': return runReplay(STEPS[S.brief]);
      case 'vw-map': return setView('map');
      case 'vw-gallery': return setView('gallery');
      case 'vw-timeline': return setView('timeline');
      case 'tl-all': TLV.all = !TLV.all; return renderTimeline();
      case 'live': play(false); return setTime(E.AS_OF);
      case 'btn-brief': case 'intro-go': return brief(0);
      case 'intro-x': $('intro').classList.add('hide'); store.d.intro = true; return store.save();
      case 'b-next': return brief(S.brief + 1 >= STEPS.length ? -1 : S.brief + 1);
      case 'b-prev': return brief(S.brief - 1);
      case 'b-x': return brief(-1);
      case 'btn-method': return methodSheet();
      case 'btn-valid': return validationSheet();
      case 'next-unrev': return nextUnreviewed();
      case 'v-review': $('method').classList.remove('on'); return nextUnreviewed();
      case 'v-export': return copy(JSON.stringify(D.events.map(function (e) { var c = caseOf(e.id); return { event_id: e.id, vessel: V[e.vessel].name, mmsi: V[e.vessel].mmsi, model: e.model, start: iso(e.t0), end: iso(e.t1), lat: +e.center[0].toFixed(4), lon: +nlon(e.center[1]).toFixed(4), confidence: +e.confScore.toFixed(3), priority: e.tier, label: c.state === 'CONFIRMED' ? 'true_positive' : c.state === 'DISMISSED' ? 'false_positive' : null, case_state: c.state, note: c.note || '' }; }), null, 1), 'Review labels');
      case 'sheet-x': return $('method').classList.remove('on');
    }
  });
  $('method').addEventListener('click', function (e) { if (e.target.id === 'method') $('method').classList.remove('on'); });
  $('q').addEventListener('input', function (e) { S.q = e.target.value; renderFleet(); renderMap(); });
  tr.addEventListener('input', function () { play(false); setTime(+tr.value); });
  var noteT; document.addEventListener('input', function (e) { if (e.target.id !== 'note') return; clearTimeout(noteT); var id = S.ev, val = e.target.value; noteT = setTimeout(function () { var c = caseOf(id); c.note = val; store.d.cases[id] = c; store.save(); }, 300); });
  document.addEventListener('keydown', function (e) {
    var typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
    if (e.key === 'Escape') { if ($('method').classList.contains('on')) $('method').classList.remove('on'); else if (S.brief >= 0) brief(-1); else if (LP.on) stopLapse(); else if (S.view !== 'map') setView('map'); return; }
    if (typing) return;
    if (e.key === '/') { e.preventDefault(); setTab('fleet'); $('q').focus(); }
    else if (e.key === ' ') { e.preventDefault(); play(!S.playing); }
    else if (e.key === 'j' || e.key === 'k') { var L1 = alertList(), i = L1.findIndex(function (x) { return x.id === S.ev; }); i = e.key === 'j' ? Math.min(L1.length - 1, i + 1) : Math.max(0, i - 1); if (L1[i]) focusEvent(L1[i].id); }
    else if (S.brief >= 0 && e.key === 'ArrowRight') brief(S.brief + 1 >= STEPS.length ? -1 : S.brief + 1);
    else if (S.brief >= 0 && e.key === 'ArrowLeft') brief(Math.max(0, S.brief - 1));
  });
  window.addEventListener('resize', function () { drawHist(); map.invalidateSize(); if (S.view === 'timeline') renderTimeline(); });

  /* Survey Detector: hand the console's state and helpers to addons.js (our extra features) */
  window.SEATRACE = { E: E, D: D, V: V, S: S, EVI: EVI, map: map, LAYERS: LAYERS, store: store, renderLayers: renderLayers,
    renderIntel: renderIntel, renderAlerts: renderAlerts, renderFleet: renderFleet, renderMap: renderMap, focusEvent: focusEvent,
    focusVessel: focusVessel, setView: setView, caseOf: caseOf, toast: toast, copy: copy, esc: esc, fDs: fDs, fD: fD };

  /* ---------- init ---------- */
  renderStats(); renderFChips(); renderAChips(); renderLayers(); renderFleet(); renderAlerts(); renderIntel();
  applyStaticLayers(); setTime(E.AS_OF); drawHist();
  if (store.d.intro) $('intro').classList.add('hide');
  if (location.hash === '#briefing') setTimeout(function () { brief(0); }, 300);
})();
