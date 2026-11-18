/* ===== Survey Detector additions to SeaTrace =====
   Everything the Survey Detector has that SeaTrace did not, in SeaTrace's own style:
   ship group + season selector, Analyst menu, Ports + routes and "likely surveying for" in the assessment,
   extra map layers (port routes, predicted next lines, seabed resource regions), review CSV export / import /
   labels in the alert queue, shareable links, watchlist ships without data, and notices.
   Reads window.SEATRACE (handed over at the end of ui.js) and E.EXTRAS (the data's "extras"). */
(function () {
  'use strict';
  var A = window.SEATRACE;
  if (!A) return;
  var E = A.E, D = A.D, V = A.V, S = A.S, map = A.map, esc = A.esc, X = E.EXTRAS || {};
  var $ = function (id) { return document.getElementById(id); };
  var CAT = { home: '#5cc8ff', 'home-ree': '#a585ff', ree: '#a585ff', near: '#748797' };
  var OFFS = [-360, 0, 360];

  /* ---------- styles, in SeaTrace's tokens ---------- */
  var css = document.createElement('style');
  css.textContent =
    '.stx-head{display:flex;align-items:center;gap:6px}.stx-head .seg button{font:500 11.5px var(--f-body)}' +
    '.stx-sel{background:var(--panel-2);border:1px solid var(--line-2);color:var(--ink);border-radius:6px;height:28px;padding:0 4px;font:500 11.5px var(--f-body);max-width:118px}' +
    'header.top .brand small{display:block;max-width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
    '@media (max-width:1500px){header.top .brand small{display:none}}' +
    '.stx-menu{position:relative}.stx-menu summary{list-style:none;cursor:pointer}.stx-menu summary::-webkit-details-marker{display:none}' +
    '.stx-menu .menu{position:absolute;right:0;top:34px;z-index:3000;background:var(--panel);border:1px solid var(--line-2);border-radius:8px;padding:6px;min-width:220px;box-shadow:0 10px 30px #0008}' +
    '.stx-menu .menu a{display:block;padding:7px 10px;border-radius:5px;color:var(--ink);text-decoration:none;font-size:12.5px}.stx-menu .menu a:hover{background:var(--raise)}' +
    '.stx-menu .menu small{display:block;color:var(--ink-3);font-size:11px}' +
    '.stx-ports{display:grid;gap:4px}.stx-port{display:grid;grid-template-columns:10px 1fr auto;gap:8px;align-items:baseline;font-size:12px}' +
    '.stx-port i{width:8px;height:8px;border-radius:50%;display:inline-block}.stx-port .km{font-family:var(--f-mono);color:var(--ink-2);font-size:11.5px}' +
    '.stx-port small{color:var(--ink-3)}.stx-tgt b{color:var(--ink)}.stx-tgt{font-size:12.5px;color:var(--ink-2)}' +
    '.stx-tools{display:flex;gap:6px;flex-wrap:wrap;padding:0 0 8px}.stx-tools .tbtn{height:26px;font-size:11px}' +
    '.stx-watch{opacity:.55}.stx-watch .vrow{cursor:default}.stx-link{display:flex;gap:6px}' +
    '.stx-chain{display:grid;gap:5px;font-size:12px;color:var(--ink-2)}.stx-chain b{color:var(--ink);font-weight:600}' +
    '.stx-chain .lab{font:600 10px var(--f-mono);letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);margin-right:6px}' +
    '.stx-chain .src{color:var(--ink-3);font-size:11px}.stx-chain .arrow{color:var(--ink-3);padding-left:4px}' +
    '.stx-hit{display:inline-flex;align-items:center;gap:4px;border-radius:10px;padding:1px 8px;font-size:11px;font-weight:600;margin:2px 4px 2px 0;text-decoration:none}' +
    '.stx-hit.confirmed{background:var(--p1);color:#160404}.stx-hit.likely{background:var(--p2);color:#1a1002}.stx-hit.possible{border:1px dashed var(--ink-3);color:var(--ink-2)}' +
    '.stx-badge{border:1px solid var(--line-2);border-radius:9px;padding:0 6px;font-size:10.5px;color:var(--ink-2);margin-left:4px}' +
    '.stx-min{display:grid;grid-template-columns:1fr auto;gap:2px 8px;font-size:12px}.stx-min .pct{font-family:var(--f-mono);color:var(--ink)}' +
    '#left-entities .scroll{padding:6px 8px}.stx-ent{border-bottom:1px solid var(--line);padding:8px 4px;cursor:pointer}.stx-ent:hover{background:var(--raise)}' +
    '.stx-ent .nm{color:var(--ink);font-weight:600;font-size:12.5px}.stx-ent .sub{color:var(--ink-3);font-size:11px;display:block;margin-top:2px}' +
    '.stx-ent .ships{display:none;margin-top:6px;gap:3px}.stx-ent.open .ships{display:grid}.stx-ent .ships button{all:unset;cursor:pointer;color:var(--accent);font-size:12px}' +
    '.stx-ent .nums{font-family:var(--f-mono);font-size:11px;color:var(--ink-2)}' +
    '.cbtag{display:inline-grid;place-items:center;height:16px;padding:0 5px;border-radius:2px;background:#2ec4d633;color:#8fe6f0;font:600 9.5px var(--f-mono);letter-spacing:.05em;cursor:help;margin-left:4px}' +
    '.cbbadge{display:inline-block;padding:0 4px;border-radius:2px;background:#2ec4d633;color:#8fe6f0;font:600 9px/14px var(--f-mono);letter-spacing:.05em;vertical-align:1px;cursor:help}' +
    '.sftag{display:inline-grid;place-items:center;height:16px;padding:0 5px;border-radius:2px;background:#8d6e6333;color:#d7b9a8;font:600 9.5px var(--f-mono);letter-spacing:.05em;cursor:help}';
  document.head.appendChild(css);

  /* ---------- header: ship group + season, Analyst menu ---------- */
  (function header() {
    var vw = X.view || {}, top = document.querySelector('header.top');
    if (!top || !vw.groups) return;
    var groups = Object.keys(vw.groups).map(function (k) {
      return '<option value="' + k + '"' + (k === vw.group ? ' selected' : '') + '>' + esc(vw.groups[k]) + '</option>';
    }).join('');
    var times = Object.keys(vw.windows).map(function (k) {
      return '<option value="' + k + '"' + (k === vw.time ? ' selected' : '') + '>' + esc(vw.windows[k]) + '</option>';
    }).join('');
    var menu = [['analyst_upload', 'Upload your own track', 'Run both detectors on your AIS files'],
                ['analyst_settings', 'Detection settings', 'Model, thresholds, port matching'],
                ['analyst_compare', 'Compare models', 'Benchmarks, labels, precision'],
                ['analyst_data', 'Data & downloads', 'Tables, Excel, ZIP, GeoJSON']]
      .map(function (m) { return '<a href="' + m[0] + '" data-stpage="' + m[0] + '">' + m[1] + '<small>' + m[2] + '</small></a>'; }).join('');
    var box = document.createElement('div');
    box.className = 'stx-head';
    box.innerHTML = '<select class="stx-sel" id="st-group" aria-label="Ship group">' + groups + '</select>' +
      '<select class="stx-sel" id="st-time" aria-label="Season">' + times + '</select>' +
      '<details class="stx-menu" id="st-analyst"><summary class="tbtn">Analyst ▾</summary><div class="menu">' + menu + '</div></details>';
    var valid = $('btn-valid');
    top.insertBefore(box, valid || null);
    /* Streamlit's iframe sandbox has no allow-top-navigation, but it is same-origin: act in the top document.
       Analyst pages: click Streamlit's own (hidden) navigation link, so the visit and its settings are kept.
       Group / season: a link clicked in the top document (a fresh page load with the new query). */
    function topClick(href) {
      var doc = window.top.document, a = doc.createElement('a');
      a.href = href; a.style.display = 'none'; doc.body.appendChild(a); a.click(); setTimeout(function () { a.remove(); }, 1000);
    }
    function go(group, time) {
      var url = '?group=' + encodeURIComponent(group) + '&time=' + encodeURIComponent(time);
      if ((window.ST_NOTICES || []).some(function (n) { return /Custom detection settings|uploaded files/.test(n); }) &&
          !confirm('Changing ships or season reloads SeaTrace and resets your custom settings or uploaded files. Continue?')) return;
      try { topClick(url); } catch (e) { A.toast('Could not change the view: ' + e.message); }
    }
    function openPage(path) {
      try {
        var doc = window.top.document;
        var link = [].filter.call(doc.querySelectorAll('a[href]'), function (x) {
          return new URL(x.href, doc.baseURI).pathname.replace(/\/$/, '').split('/').pop() === path;
        })[0];
        if (link) { link.click(); return; }
        topClick(path);
      } catch (e) { A.toast('Could not open ' + path + ': ' + e.message); }
    }
    box.addEventListener('click', function (e) {
      var a = e.target.closest('[data-stpage]'); if (!a) return;
      e.preventDefault(); $('st-analyst').removeAttribute('open'); openPage(a.getAttribute('data-stpage'));
    });
    $('st-group').addEventListener('change', function (e) { go(e.target.value, vw.time); });
    $('st-time').addEventListener('change', function (e) { go(vw.group, e.target.value); });
  })();

  /* ---------- extra layers ---------- */
  var gRoutes = L.layerGroup(), gPred = L.layerGroup(), gRegions = L.layerGroup();
  /* Seafloor shading from GEBCO's public WMS, under the land; Leaflet repeats tiles round the globe by itself */
  map.createPane('seafloor').style.zIndex = 200; map.getPane('seafloor').style.pointerEvents = 'none';
  var gSeafloor = L.tileLayer.wms('https://wms.gebco.net/mapserv', { layers: 'GEBCO_LATEST', format: 'image/png', pane: 'seafloor', opacity: 0.85, attribution: 'GEBCO Compilation Group, GEBCO Grid' });
  var EXTRA_LAYERS = [['routes', 'Port routes (selected survey)', 'dash:#5cc8ff'], ['pred', 'Predicted next lines', 'dash:#ff7ec3'],
                      ['regions', 'Seabed resource regions', 'linear-gradient(90deg,#1e88e5,#d81b60)'],
                      ['seafloor', 'Seafloor (GEBCO)', 'linear-gradient(90deg,#0b2a4a,#3a7bb8,#a8d1e8)'],
                      ['cables', 'Submarine cables', 'line:#2ec4d6'], ['cablewatch', 'Cable watch (flagged ships)', 'dot:#ff5d5d']];
  /* Submarine cables (TeleGeography; schematic routes) and cable-watch episodes */
  var gCables = L.layerGroup(), gCableWatch = L.layerGroup();
  (X.cables || []).forEach(function (c) {
    var tip = '<b>' + esc(c.name) + '</b>' + (c.planned ? ' · planned' : '') + (c.rfs ? ' · in service ' + esc(c.rfs) : '') +
      (c.owners ? '<br><span style="color:#a1b5c3">Owners: ' + esc(c.owners) + '</span>' : '') + (c.landings ? '<br><span style="color:#a1b5c3">Lands at: ' + esc(c.landings) + '</span>' : '');
    OFFS.forEach(function (o) {
      gCables.addLayer(L.polyline(c.c.map(function (l) { return l.map(function (q) { return [q[0], q[1] + o]; }); }),
        { color: '#2ec4d6', weight: 1.2, opacity: c.planned ? 0.45 : 0.75, dashArray: c.planned ? '4 4' : null, stxCable: true }).bindTooltip(tip, { sticky: true }));
    });
  });
  var CW_COL = { stopped: '#ff5d5d', slow: '#ffb347', dark: '#b48cff' };
  function drawCableWatch() {
    gCableWatch.clearLayers();
    var cw = X.cableWatch || {}, norm = X.cableNorm || 1;
    Object.keys(cw).forEach(function (vid) {
      var v = V[vid], aff = (X.cableAffinity || {})[vid] || {};
      if (!v || !(aff.flag || S.focus === vid)) return;
      cw[vid].forEach(function (ep) {
        var col = ep.cableShip ? '#9fb3c1' : CW_COL[ep.kind] || '#ffb347', c = ep.cables[0] || {};
        var tip = '<b>' + esc(v.name) + '</b> · ' + Math.round(ep.hours) + ' h ' + (ep.kind === 'dark' ? 'dark (no AIS)' : ep.kind) + ' on ' + esc(c.name || 'a cable') +
          '<br>' + A.fDs(E.T_START + ep.t0 * E.H) + ' → ' + A.fDs(E.T_START + ep.t1 * E.H) + ' · usual crossing ' + (Math.round(norm * 10) / 10) + ' h' +
          (aff.ratio ? '<br>Stops on cables ' + aff.ratio + '× more than chance' : '') + (ep.cableShip ? '<br>Cable ship · likely maintenance' : '');
        OFFS.forEach(function (o) {
          gCableWatch.addLayer(L.circleMarker([ep.center[0], ep.center[1] + o], { radius: 5, color: col, weight: 1.5, fillColor: col, fillOpacity: 0.45 })
            .bindTooltip(tip).on('click', function () { A.focusVessel(vid); }));
        });
      });
    });
  }
  (function layers() {
    var at = A.LAYERS.findIndex(function (l) { return l[0] === 'grat'; });
    A.LAYERS.splice.apply(A.LAYERS, [at < 0 ? A.LAYERS.length : at, 0].concat(EXTRA_LAYERS));
    S.layers.routes = true; S.layers.pred = true; S.layers.regions = false; S.layers.seafloor = false; S.layers.cables = false; S.layers.cablewatch = true; drawCableWatch();
    A.renderLayers();
    (X.pred || []).forEach(function (p) {
      OFFS.forEach(function (o) {
        gPred.addLayer(L.polyline(p.c.map(function (q) { return [q[0], q[1] + o]; }), { color: '#ff7ec3', weight: 2, dashArray: '5 5', opacity: 0.95 })
          .bindTooltip('Predicted next line · ' + esc(V[p.vessel] ? V[p.vessel].name : p.vessel), { sticky: true }));
      });
    });
    (X.regions || []).forEach(function (r) {
      OFFS.forEach(function (o) {
        gRegions.addLayer(L.rectangle([[r.box[0], r.box[1] + o], [r.box[2], r.box[3] + o]], { color: r.color, weight: 1, opacity: 0.8, fillColor: r.color, fillOpacity: 0.07, dashArray: '3 4' })
          .bindTooltip('<b>' + esc(r.name) + '</b><br>' + esc(r.category) + ' · ' + esc(r.commodities) + '<br>' + esc(r.depth) + ' (approximate region)', { sticky: true }));
      });
    });
  })();
  function drawRoutes() {
    gRoutes.clearLayers();
    var rr = (X.routes || {})[S.ev] || [];
    rr.forEach(function (r) {
      var c = CAT[r.cat] || '#748797';
      var runs = [[]];
      r.c.forEach(function (q, k) { if (k && Math.abs(q[1] - r.c[k - 1][1]) > 180) runs.push([]); runs[runs.length - 1].push(q); });
      OFFS.forEach(function (o) {
        gRoutes.addLayer(L.polyline(runs.map(function (run) { return run.map(function (q) { return [q[0], q[1] + o]; }); }),
          { color: c, weight: 2, dashArray: '6 5', opacity: 0.9 }).bindTooltip(esc(r.port) + ' · ' + Math.round(r.km || 0).toLocaleString() + ' km by sea', { sticky: true }));
      });
    });
  }
  function applyLayers() {
    [[gRoutes, 'routes'], [gPred, 'pred'], [gRegions, 'regions'], [gSeafloor, 'seafloor'], [gCables, 'cables'], [gCableWatch, 'cablewatch']].forEach(function (x) {
      if (S.layers[x[1]]) { if (!map.hasLayer(x[0])) x[0].addTo(map); } else map.removeLayer(x[0]);
    });
  }
  document.addEventListener('click', function (e) {
    var t = e.target; if (!t || !t.getAttribute) return;
    var k = t.getAttribute('data-layer');
    if (k === 'routes' || k === 'pred' || k === 'regions' || k === 'seafloor' || k === 'cables' || k === 'cablewatch') setTimeout(applyLayers, 0);
  });

  /* ---------- assessment pane: likely target, ports, copy link ---------- */
  function portRow(p) {
    return '<div class="stx-port"><i style="background:' + (CAT[p.cat] || '#748797') + '"></i><span>' + esc(p.name) + ' <small>' + esc(p.country) +
      (p.link ? ' · ' + esc(p.link) : '') + '</small></span><span class="km">' + Math.round(p.km || 0).toLocaleString() + ' km · ' + Math.round(p.h || 0) + ' h</span></div>';
  }
  function extraSection() {
    var e = A.EVI[S.ev]; if (!e || !S.focus) return '';
    var tg = (X.target || {})[e.id], pp = (X.ports || {})[e.id], out = '';
    if (tg) out += '<div class="stx-tgt"><b>Likely surveying for:</b> ' + esc(tg.likely) + (tg.basis ? '<br><span class="muted" style="font-size:11.5px">' + esc(tg.basis) + '</span>' : '') +
      (tg.alternatives ? '<br><span class="muted" style="font-size:11.5px">Also possible: ' + esc(tg.alternatives) + '</span>' : '') + '</div>';
    if (pp) {
      var parts = [['Home-country ports', pp.home], ['Rare-earth linked ports', pp.ree], ['Nearest ports', pp.near]];
      out += parts.filter(function (x) { return x[1] && x[1].length; }).map(function (x) {
        return '<div class="stx-ports"><span class="muted" style="font-size:11px">' + x[0] + '</span>' + x[1].map(portRow).join('') + '</div>';
      }).join('');
      out += '<span class="muted" style="font-size:11px">Distances follow shipping lanes and go around land; hours at 10 kn. Routes are on the map (Layers ▸ Port routes).</span>';
    }
    out += '<div class="stx-link"><button class="tbtn" type="button" id="stx-copylink">Copy link to this detection</button></div>';
    return '<div class="sec stx-x"><h4>Ports &amp; target · Survey Detector</h4>' + out + '</div>';
  }
  /* ---------- supply chain card ---------- */
  var SUP = X.supply || null;
  var LEVEL = { confirmed: 'Confirmed', likely: 'Likely', possible: 'Possible · verify' };
  function webUrl(u) { u = String(u || ''); return /^https?:\/\//i.test(u) ? u : ''; }
  function hitChip(h) {
    var tip = h.entry + ' — ' + h.source + (h.program ? ' (' + h.program + ')' : '') + (h.date ? ', listed ' + h.date : '') + (h.score < 1 ? ', name similarity ' + Math.round(h.score * 100) + '%' : '');
    var inner = esc(LEVEL[h.level] || h.level) + ': ' + esc(h.list);
    return webUrl(h.url) ? '<a class="stx-hit ' + esc(h.level) + '" href="' + esc(h.url) + '" target="_blank" rel="noopener" title="' + esc(tip) + '">' + inner + '</a>'
                 : '<span class="stx-hit ' + esc(h.level) + '" title="' + esc(tip) + '">' + inner + '</span>';
  }
  function hitsFor(c, who) {
    var hs = c.hits.filter(function (h) { return h.matched === who; });
    return hs.length ? '<div>' + hs.map(hitChip).join('') + '</div>' : '';
  }
  function supplySection() {
    var e = A.EVI[S.ev]; if (!SUP || !e || !S.focus) return '';
    var c = SUP.ships[e.vessel], a = SUP.areas[e.id];
    if (!c && !a) return '';
    var out = '<div class="stx-chain">';
    if (c) {
      var v = V[e.vessel] || {};
      out += '<div><span class="lab">Ship</span><b>' + esc(v.name || e.vessel) + '</b>' + (c.ship_hits.length ? ' ' + c.ship_hits.map(hitChip).join('') : '') + '</div>';
      /* lists the team verified (entity_links.csv) but the name match did not find: shown on the parent, else the owner */
      var extra = c.verified_lists.filter(function (l) { return !c.hits.some(function (h) { return h.list === l; }); });
      var verifiedHtml = extra.length ? '<div>' + extra.map(function (l) { return '<span class="stx-hit confirmed" title="Verified by the team (entity_links.csv)">Confirmed: ' + esc(l) + '</span>'; }).join('') + '</div>' : '';
      if (c.owner) out += '<div class="arrow">↓</div><div><span class="lab">Owner</span><b>' + esc(c.owner) + '</b> <span class="src">' + esc(c.owner_source) + '</span>' + hitsFor(c, 'owner') + (c.parent ? '' : verifiedHtml) + '</div>';
      if (c.parent) out += '<div class="arrow">↓</div><div><span class="lab">Parent</span><b>' + esc(c.parent) + '</b>' + (c.state_owned ? '<span class="stx-badge">state-owned' + (c.country ? ' · ' + esc(c.country) : '') + '</span>' : '') + hitsFor(c, 'parent') + verifiedHtml + '</div>';
      if (c.ultimate_owner && c.ultimate_owner !== c.parent) out += '<div class="arrow">↓</div><div><span class="lab">Ultimate owner</span><b>' + esc(c.ultimate_owner) + '</b>' + hitsFor(c, 'ultimate_owner') + '</div>';
      if (!SUP.listDate) out += '<div class="src">Screening list not loaded: this ship and its owners have not been screened.</div>';
      else if (!c.hits.length && !c.ship_hits.length && !c.verified_lists.length && c.owner) out += '<div class="src">No restricted-list match for the ship, owner or parents.</div>';
      c.notes.forEach(function (n) { out += '<div class="src">' + esc(n) + '</div>'; });
      if (c.link_note) out += '<div class="src">' + esc(c.link_note) + (webUrl(c.link_url) ? ' · <a href="' + esc(c.link_url) + '" target="_blank" rel="noopener" style="color:var(--accent)">source</a>' : '') + '</div>';
    }
    if (a) {
      out += '<div style="height:6px"></div>';
      if (a.contract) out += '<div><span class="lab">Area</span><b>' + esc(a.contractor || a.contract) + '</b> <span class="src">' + (a.basis === 'near' ? 'near ' : '') + 'ISA contract ' + esc(a.contract) + (a.sponsor ? ' · sponsor ' + esc(a.sponsor) : '') + '</span></div>';
      else if (a.region) out += '<div><span class="lab">Area</span><b>' + esc(a.region) + '</b> <span class="src">seabed resource region (no ISA contract within 300 km)</span></div>';
      if (a.minerals.length) {
        out += '<div class="arrow">↓</div><div><span class="lab">Minerals · US import reliance</span><div class="stx-min">' + a.minerals.map(function (m) {
          return '<span>' + esc(m.name) + (m.critical ? '<span class="stx-badge">critical</span>' : '') + (m.top_sources ? ' <span class="src">' + esc(m.top_sources) + '</span>' : '') + '</span><span class="pct">' + (m.reliance_pct ? esc(m.reliance_pct) + '%' : '—') + '</span>';
        }).join('') + '</div><span class="src">USGS Mineral Commodity Summaries' + (a.minerals[0].year ? ' (' + esc(a.minerals[0].year) + ' data)' : '') + '</span></div>';
      }
      if (a.processing.length) out += '<div class="arrow">↓</div><div><span class="lab">Processed at</span>' + a.processing.slice(0, 4).map(function (p) { return esc(p.site) + ' <span class="src">' + esc(p.operator) + ', ' + esc(p.country) + '</span>'; }).join('<br>') + (a.processing.length > 4 ? '<br><span class="src">+' + (a.processing.length - 4) + ' more</span>' : '') + '</div>';
      a.notes.forEach(function (n) { out += '<div class="src">' + esc(n) + '</div>'; });
    }
    out += '<div class="src">Screening list as of ' + esc(SUP.listDate || 'not loaded') + '. Matches are leads for an analyst to verify, not findings.</div></div>';
    return '<div class="sec stx-supply"><h4>Supply chain · Survey Detector</h4>' + out + '</div>';
  }

  var busy = false;
  function decorateIntel() {
    if (busy) return; busy = true;
    var el = $('intel');
    if (el && !el.querySelector('.stx-x')) {
      var html = extraSection();
      if (html) {
        var secs = el.querySelectorAll('.sec'), anchor = null;
        for (var i = 0; i < secs.length; i++) { var h = secs[i].querySelector('h4'); if (h && /^Context/.test(h.textContent)) { anchor = secs[i]; break; } }
        var div = document.createElement('div'); div.innerHTML = html;
        var node = div.firstChild;
        if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(node, anchor.nextSibling);
        else (el.querySelector('.scroll') || el).appendChild(node);
      }
    }
    if (el && !el.querySelector('.stx-supply')) {
      var sh = supplySection(), after = el.querySelector('.stx-x');
      if (sh) {
        var d2 = document.createElement('div'); d2.innerHTML = sh;
        if (after && after.parentNode) after.parentNode.insertBefore(d2.firstChild, after.nextSibling);
        else (el.querySelector('.scroll') || el).appendChild(d2.firstChild);
      }
    }
    drawRoutes(); drawCableWatch(); writeHash();
    busy = false;
  }
  new MutationObserver(function () { decorateIntel(); }).observe($('intel'), { childList: true });
  document.addEventListener('click', function (e) {
    if (e.target && e.target.id === 'stx-copylink') { try { A.copy(window.top.location.href, 'Link'); } catch (err) { A.copy(location.href, 'Link'); } }
  });

  /* ---------- shareable links: #v=ship&e=detection&view=… in the page address ---------- */
  var acted = false;     /* the URL gets a selection only once someone picks one (a reload must not fly to our default) */
  ['pointerdown', 'keydown'].forEach(function (k) { document.addEventListener(k, function () { acted = true; }, true); });
  function writeHash() {
    if (!acted) return;
    var h = '#' + [S.focus ? 'v=' + encodeURIComponent(S.focus) : '', S.ev ? 'e=' + encodeURIComponent(S.ev) : '', S.view && S.view !== 'map' ? 'view=' + S.view : '']
      .filter(Boolean).join('&');
    try { var w = window.top; if (w.location.hash !== h) w.history.replaceState(null, '', w.location.pathname + w.location.search + h); } catch (err) { }
  }
  function readHash() {
    var h = ''; try { h = window.top.location.hash; } catch (err) { h = location.hash; }
    var q = {}; h.replace(/^#/, '').split('&').forEach(function (kv) { var p = kv.split('='); if (p[0]) q[p[0]] = decodeURIComponent(p[1] || ''); });
    return q;
  }
  document.addEventListener('click', function (e) {
    if (e.target && e.target.closest && e.target.closest('[role=tab][id^=vw-]')) setTimeout(writeHash, 0);
  });

  /* ---------- alert queue: reviews out and in ---------- */
  var STATUS = ['NEW', 'REVIEWING', 'CONFIRMED', 'DISMISSED', 'ESCALATED'];
  function title(s) { return s.charAt(0) + s.slice(1).toLowerCase(); }
  function csvCell(x) { x = String(x == null ? '' : x); return /[",\n]/.test(x) ? '"' + x.replace(/"/g, '""') + '"' : x; }
  function download(name, text) {
    try {
      var a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' })); a.download = name;
      document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    } catch (err) { A.copy(text, name); }
  }
  function reviewsCsv() {
    var cases = A.store.d.cases, rows = [['id', 'vessel', 'status', 'note']];
    Object.keys(cases).forEach(function (id) { var e = A.EVI[id]; rows.push([id, e ? (X.analysisVessel || {})[e.vessel] || e.vessel : '', title(cases[id].state || 'NEW'), cases[id].note || '']); });
    return rows.map(function (r) { return r.map(csvCell).join(','); }).join('\n') + '\n';
  }
  function labelsCsv() {
    var by = {};
    Object.keys(A.store.d.cases).forEach(function (id) {
      var e = A.EVI[id], st = A.store.d.cases[id].state; if (!e) return;
      var key = (X.analysisVessel || {})[e.vessel] || e.vessel;
      if (st === 'CONFIRMED') by[key] = 1; else if (st === 'DISMISSED' && by[key] === undefined) by[key] = 0;
    });
    return 'vessel,is_survey\n' + Object.keys(by).map(function (k) { return csvCell(k) + ',' + by[k]; }).join('\n') + '\n';
  }
  function parseCsv(text) {
    var rows = [], row = [], cell = '', q = false;
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (q) { if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') q = false; else cell += c; }
      else if (c === '"') q = true; else if (c === ',') { row.push(cell); cell = ''; }
      else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cell); rows.push(row); row = []; cell = ''; }
      else cell += c;
    }
    if (cell || row.length) { row.push(cell); rows.push(row); }
    return rows.filter(function (r) { return r.length > 1 || r[0]; });
  }
  function importCsv(text) {
    var rows = parseCsv(text); if (!rows.length) { A.toast('Nothing to import'); return; }
    var hd = rows[0].map(function (h) { return h.trim().toLowerCase(); }), iId = hd.indexOf('id'), iSt = hd.indexOf('status'), iNote = hd.indexOf('note');
    if (iId < 0 || iSt < 0) { A.toast('A reviews file needs the columns id and status'); return; }
    var ok = 0, unknown = 0, bad = 0;
    rows.slice(1).forEach(function (r) {
      var id = r[iId], st = String(r[iSt] || '').trim().toUpperCase();
      if (!A.EVI[id]) { unknown++; return; }
      if (STATUS.indexOf(st) < 0) { bad++; return; }
      A.store.d.cases[id] = { state: st, note: iNote >= 0 ? r[iNote] || '' : '' }; ok++;
    });
    A.store.save(); A.renderAlerts(); A.renderIntel();
    A.toast('Imported ' + ok + ' review' + (ok === 1 ? '' : 's') + (unknown ? ' · ' + unknown + ' not in this season' : '') + (bad ? ' · ' + bad + ' unknown status' : ''));
  }
  (function queueTools() {
    var host = document.querySelector('#left-alerts .tools'); if (!host) return;
    var bar = document.createElement('div'); bar.className = 'stx-tools';
    bar.innerHTML = '<button class="tbtn" type="button" id="q-export">Export reviews</button><button class="tbtn" type="button" id="q-import">Import reviews</button>' +
      '<button class="tbtn" type="button" id="q-labels">Download as labels</button><input type="file" id="q-file" accept=".csv,text/csv" hidden>';
    host.insertBefore(bar, host.firstChild);
    $('q-export').addEventListener('click', function () { download('seatrace_reviews.csv', reviewsCsv()); });
    $('q-labels').addEventListener('click', function () { download('seatrace_labels.csv', labelsCsv()); });
    $('q-import').addEventListener('click', function () { $('q-file').click(); });
    $('q-file').addEventListener('change', function (e) {
      var f = e.target.files[0]; if (!f) return;
      var rd = new FileReader(); rd.onload = function () { importCsv(String(rd.result)); e.target.value = ''; }; rd.readAsText(f);
    });
  })();

  /* ---------- fleet: watchlist ships without tracking data ---------- */
  function decorateFleet() {
    var el = $('fleet'), w = X.watchNoData || [];
    if (!el || !w.length || el.querySelector('.stx-watch')) return;
    var div = document.createElement('div'); div.className = 'grp stx-watch';
    div.innerHTML = '<div class="secthead">Watchlist · no tracking data yet · ' + w.length + '</div>' + w.map(function (s) {
      return '<div class="vrow"><span></span><span class="vbtn"><span class="nm">' + (s.mining ? '★ ' : '') + esc(s.name) + '</span><span class="sub">' + esc(s.country) + ' · ' + esc(s.type || '') + '</span></span></div>';
    }).join('');
    el.appendChild(div);
  }
  new MutationObserver(decorateFleet).observe($('fleet'), { childList: true });

  /* ---------- Entities tab: who is behind the surveys ---------- */
  (function entitiesTab() {
    var tabs = document.querySelector('.pane.left .tabs'), host = document.querySelector('.pane.left');
    if (!SUP || !tabs || !host) return;
    var ents = SUP.entities || [];
    var btn = document.createElement('button');
    btn.className = 'tab'; btn.id = 'tab-entities'; btn.type = 'button'; btn.setAttribute('role', 'tab'); btn.setAttribute('aria-selected', 'false');
    btn.innerHTML = 'Entities<span class="ct" id="ct-entities">' + ents.length + '</span>';
    tabs.appendChild(btn);
    var pane = document.createElement('div');
    pane.id = 'left-entities'; pane.className = 'pane hide'; pane.style.flex = '1';
    pane.innerHTML = '<div class="tools"><span class="muted" style="font-size:11.5px">Parent companies and owners behind the ships, listed entities first.</span>' +
      '<button class="tbtn" type="button" id="ent-csv" style="height:26px;font-size:11px">Download CSV</button></div><div class="scroll" id="entities"></div>';
    host.appendChild(pane);
    function p1(r) { return r.events.filter(function (id) { var e = A.EVI[id]; return e && (e.tier === 'P1' || e.tier === 'P2'); }).length; }
    var ROLE = { ship: 'ship', owner: 'owner', parent: 'parent', ultimate_owner: 'ultimate owner' };
    function lists(r) {      /* each chip in its own level's colour, saying which link of the chain it is about */
      return r.chips.map(function (c) {
        var about = c.matched === r.kind ? '' : ' · ' + (ROLE[c.matched] || c.matched);
        return '<span class="stx-hit ' + esc(c.level) + '" title="' + esc(LEVEL[c.level] || c.level) + '">' + esc(c.list) + esc(about) + '</span>';
      }).join('');
    }
    $('entities').innerHTML = ents.length ? ents.map(function (r, i) {
      return '<div class="stx-ent" data-ent="' + i + '"><span class="nm">' + esc(r.name) + '</span>' +
        (r.state_owned ? '<span class="stx-badge">state-owned</span>' : '') + (r.country ? '<span class="stx-badge">' + esc(r.country) + '</span>' : '') +
        '<span class="sub">' + (r.kind === 'parent' ? 'parent company' : 'owner') + (r.best ? ' · ' + esc(LEVEL[r.best]) : ' · no list match') + '</span>' +
        (r.chips.length ? '<div>' + lists(r) + '</div>' : '') +
        '<span class="nums">' + r.ships.length + ' ship' + (r.ships.length === 1 ? '' : 's') + ' · ' + r.detections + ' detection' + (r.detections === 1 ? '' : 's') + ' · ' + p1(r) + ' P1–P2</span>' +
        (r.minerals.length ? '<span class="sub">Minerals surveyed: ' + esc(r.minerals.join(', ')) + '</span>' : '') +
        '<div class="ships">' + r.ships.map(function (vid) { return '<button type="button" data-vid="' + esc(vid) + '">' + esc((V[vid] || {}).name || vid) + '</button>'; }).join('') + '</div></div>';
    }).join('') : '<div class="empty">No owners known for these ships.</div>';
    function show(on) {
      btn.setAttribute('aria-selected', on ? 'true' : 'false'); pane.classList.toggle('hide', !on);
      if (on) { $('tab-fleet').setAttribute('aria-selected', 'false'); $('tab-alerts').setAttribute('aria-selected', 'false');
        $('left-fleet').classList.add('hide'); $('left-alerts').classList.add('hide'); }
    }
    btn.addEventListener('click', function () { show(true); });
    ['tab-fleet', 'tab-alerts'].forEach(function (id) { $(id).addEventListener('click', function () { show(false); }); });
    $('entities').addEventListener('click', function (e) {
      var t = e.target, vid = t && t.getAttribute && t.getAttribute('data-vid');
      if (vid) { if (V[vid]) A.focusVessel(vid, null, true); return; }
      var row = t && t.closest && t.closest('.stx-ent'); if (row) row.classList.toggle('open');
    });
    function q(x) { x = String(x == null ? '' : x); return /[",\n]/.test(x) ? '"' + x.replace(/"/g, '""') + '"' : x; }
    $('ent-csv').addEventListener('click', function () {
      var head = 'name,kind,country,state_owned,lists,best_match,ships,detections,p1_p2,minerals';
      var rows = ents.map(function (r) {
        return [r.name, r.kind, r.country || '', r.state_owned === true ? 'yes' : r.state_owned === false ? 'no' : '', r.lists.join('; '), r.best || '',
                r.ships.map(function (v) { return (V[v] || {}).name || v; }).join('; '), r.detections, p1(r), r.minerals.join('; ')].map(q).join(',');
      });
      download('seatrace_entities.csv', [head].concat(rows).join('\n'));
    });
  })();

  /* ---------- a map you can turn all the way round ---------- */
  /* The camera stays within one world-width centred on HOME (dragging past it jumps by 360°, to the identical
     picture), and every layer SeaTrace draws once is repeated in the neighbouring world copies on screen. */
  var HOME = 90, gMirror = L.layerGroup().addTo(map);
  function shiftLL(ll, off) { return Array.isArray(ll) ? ll.map(function (x) { return shiftLL(x, off); }) : L.latLng(ll.lat, ll.lng + off); }
  function lngRange(l) {
    if (l.getBounds) { try { var b = l.getBounds(); if (b.isValid()) return [b.getWest(), b.getEast()]; } catch (e) { } return null; }
    if (l.getLatLng) { var p = l.getLatLng(); return p ? [p.lng, p.lng] : null; }
    return null;
  }
  function cloneAt(l, off) {
    var c = null;
    if (l instanceof L.LayerGroup) { c = L.layerGroup(); l.eachLayer(function (x) { var y = cloneAt(x, off); if (y) c.addLayer(y); }); return c; }
    if (l instanceof L.Polygon) c = L.polygon(shiftLL(l.getLatLngs(), off), l.options);
    else if (l instanceof L.Polyline) c = L.polyline(shiftLL(l.getLatLngs(), off), l.options);
    else if (l instanceof L.Circle) c = L.circle(shiftLL(l.getLatLng(), off), l.options);
    else if (l instanceof L.CircleMarker) c = L.circleMarker(shiftLL(l.getLatLng(), off), l.options);
    else if (l instanceof L.Marker) c = L.marker(shiftLL(l.getLatLng(), off), l.options);
    else if (l instanceof L.Tooltip) return L.tooltip(l.options).setLatLng(shiftLL(l.getLatLng(), off)).setContent(l.getContent());
    if (!c) return null;
    var tt = l.getTooltip && l.getTooltip(); if (tt) c.bindTooltip(tt.getContent(), tt.options);
    if (l.listens && l.listens('click')) c.on('click', function (e) { l.fire('click', e); });   /* a copy acts like the original */
    return c;
  }
  function mirror() {
    gMirror.clearLayers();
    var b = map.getBounds(), W = b.getWest(), E2 = b.getEast(), n = 0;
    (A.groups || []).forEach(function (g) {
      if (!map.hasLayer(g)) return;
      g.eachLayer(function (l) {
        var r = (l instanceof L.LayerGroup) ? null : lngRange(l);
        [-720, -360, 360, 720].forEach(function (off) {
          if (r && (r[1] + off < W || r[0] + off > E2)) return;
          if (!r && !(l instanceof L.LayerGroup)) return;
          var c = cloneAt(l, off); if (c) { gMirror.addLayer(c); n++; }
        });
      });
    });
    return n;
  }
  window.ST_AFTER_MAP = function () { mirror(); };
  window.ST_MIRROR = mirror;
  var wrapping = false;
  map.on('moveend', function () {
    if (wrapping) return;
    var c = map.getCenter(), off = c.lng < HOME - 180 ? 360 : c.lng >= HOME + 180 ? -360 : 0;
    if (off) { wrapping = true; map.setView([c.lat, c.lng + off], map.getZoom(), { animate: false }); wrapping = false; }
    mirror();
  });
  map.on('overlayadd overlayremove layeradd', function (e) { if (e.layer && (A.groups || []).indexOf(e.layer) >= 0) mirror(); });

  /* ---------- start ---------- */
  var q = readHash();               /* before anything is written: only a link someone opened, not our own default */
  if ($('layers')) $('layers').open = false;   /* Layers starts closed so the map is clear; one click opens it */
  applyLayers(); decorateFleet(); decorateIntel();
  if (q.e && A.EVI[q.e]) { A.focusEvent(q.e, false); map.setView(A.EVI[q.e].center, 6); acted = true; writeHash(); }
  else if (q.v && V[q.v]) { A.focusVessel(q.v, null, false); var lp = V[q.v].pts[V[q.v].pts.length - 1]; if (lp) map.setView([lp.lat, lp.lon], 5); acted = true; writeHash(); }
  mirror();
  if (q.view && /^(gallery|timeline)$/.test(q.view)) A.setView(q.view);
  var notes = window.ST_NOTICES || [];
  if (notes.length) setTimeout(function () { A.toast(notes.join(' · ')); }, 600);
})();
