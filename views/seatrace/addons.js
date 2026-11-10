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
    '.stx-watch{opacity:.55}.stx-watch .vrow{cursor:default}.stx-link{display:flex;gap:6px}';
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
  var EXTRA_LAYERS = [['routes', 'Port routes (selected survey)', 'dash:#5cc8ff'], ['pred', 'Predicted next lines', 'dash:#ff7ec3'],
                      ['regions', 'Seabed resource regions', 'linear-gradient(90deg,#1e88e5,#d81b60)']];
  (function layers() {
    var at = A.LAYERS.findIndex(function (l) { return l[0] === 'grat'; });
    A.LAYERS.splice(at < 0 ? A.LAYERS.length : at, 0, EXTRA_LAYERS[0], EXTRA_LAYERS[1], EXTRA_LAYERS[2]);
    S.layers.routes = true; S.layers.pred = true; S.layers.regions = false;
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
    [[gRoutes, 'routes'], [gPred, 'pred'], [gRegions, 'regions']].forEach(function (x) {
      if (S.layers[x[1]]) { if (!map.hasLayer(x[0])) x[0].addTo(map); } else map.removeLayer(x[0]);
    });
  }
  document.addEventListener('click', function (e) {
    var t = e.target; if (!t || !t.getAttribute) return;
    var k = t.getAttribute('data-layer');
    if (k === 'routes' || k === 'pred' || k === 'regions') setTimeout(applyLayers, 0);
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
    drawRoutes(); writeHash();
    busy = false;
  }
  new MutationObserver(function () { decorateIntel(); }).observe($('intel'), { childList: true });
  document.addEventListener('click', function (e) {
    if (e.target && e.target.id === 'stx-copylink') { try { A.copy(window.top.location.href, 'Link'); } catch (err) { A.copy(location.href, 'Link'); } }
  });

  /* ---------- shareable links: #v=ship&e=detection&view=… in the page address ---------- */
  function writeHash() {
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

  /* ---------- start ---------- */
  applyLayers(); decorateFleet(); decorateIntel();
  var q = readHash();
  if (q.e && A.EVI[q.e]) A.focusEvent(q.e, true); else if (q.v && V[q.v]) A.focusVessel(q.v, null, true);
  if (q.view && /^(gallery|timeline)$/.test(q.view)) A.setView(q.view);
  var notes = window.ST_NOTICES || [];
  if (notes.length) setTimeout(function () { A.toast(notes.join(' · ')); }, 600);
})();
