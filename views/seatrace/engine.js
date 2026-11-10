/* ===== SeaTrace engine: real AIS (Global Fishing Watch via vesseltracker-v2 export), ISA contract areas, WPI ports ===== */
var ENGINE = (function () {
  'use strict';
  var RAW = JSON.parse(document.getElementById('seatrace-data').textContent);
  var R = 6371.0088, D2R = Math.PI / 180, H = 3600e3, DAY = 24 * H;
  function hav(lat1, lon1, lat2, lon2) { var dLat = (lat2 - lat1) * D2R, dLon = (lon2 - lon1) * D2R; var a = Math.pow(Math.sin(dLat / 2), 2) + Math.cos(lat1 * D2R) * Math.cos(lat2 * D2R) * Math.pow(Math.sin(dLon / 2), 2); return 2 * R * Math.asin(Math.min(1, Math.sqrt(a))); }
  function bearing(lat1, lon1, lat2, lon2) { var y = Math.sin((lon2 - lon1) * D2R) * Math.cos(lat2 * D2R); var x = Math.cos(lat1 * D2R) * Math.sin(lat2 * D2R) - Math.sin(lat1 * D2R) * Math.cos(lat2 * D2R) * Math.cos((lon2 - lon1) * D2R); return (Math.atan2(y, x) / D2R + 360) % 360; }
  function offset(lat, lon, dxKm, dyKm) { return [lat + dyKm / 110.574, lon + dxKm / (111.32 * Math.cos(lat * D2R))]; }
  function clamp(x, lo, hi) { lo = lo === undefined ? 0 : lo; hi = hi === undefined ? 1 : hi; return Math.max(lo, Math.min(hi, x)); }
  function compass(deg) { var n = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']; return n[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16]; }
  function fmtDur(h) { return h < 48 ? Math.round(h) + ' h' : (h / 24).toFixed(1) + ' d'; }
  function f1(x) { return (Math.round(x * 10) / 10).toFixed(1); }

  var T_START = Date.parse(RAW.T0), AS_OF = T_START + RAW.AS_OF * H;
  function tm(h) { return T_START + h * H; }

  var PORTS = RAW.ports, PORT = {}; PORTS.forEach(function (p) { PORT[p.id] = p; });
  var ZONE_TYPES = {
    POLYMETALLIC_NODULE: { label: 'Polymetallic nodules', short: 'PMN', w: 0.9 },
    SEAFLOOR_MASSIVE_SULFIDE: { label: 'Polymetallic sulphides', short: 'PMS', w: 0.9 },
    COBALT_RICH_CRUST: { label: 'Cobalt-rich ferromanganese crusts', short: 'CFC', w: 0.9 },
    RARE_EARTH_MUD: { label: 'Rare-earth mud', short: 'REE', w: 1.0 }
  };
  var ZONES = RAW.zones.map(function (z) { return { id: z.id, name: z.contractor + ' (' + ZONE_TYPES[z.type].short + ')', type: z.type, contractor: z.contractor, sponsor: z.sponsor, km2: z.km2, rings: z.rings, label: z.label, jurisdiction: 'ISA exploration contract' }; });
  var ZONE = {}; ZONES.forEach(function (z) { ZONE[z.id] = z; });
  var ISO2NAME = {};
  var CLASS = {
    MINING: { label: 'Mining / production vessel', w: 1.0, station: 1 },
    DRILLING: { label: 'Deep-sea drilling vessel', w: 0.9, station: 1 },
    GEO: { label: 'Resource / geophysical survey vessel', w: 0.75, station: 1 },
    DEEP: { label: 'Deep-submergence support vessel', w: 0.75, station: 1 },
    SUPPORT: { label: 'Offshore construction / support vessel', w: 0.5, station: 1 },
    ENERGY: { label: 'Offshore oil & gas vessel', w: 0.35, station: 0.8 },
    RESEARCH: { label: 'Oceanographic research vessel', w: 0.5, station: 0.7 },
    GOV: { label: 'Government / coast guard vessel', w: 0.25, station: 0.3 },
    UNK: { label: 'Class not yet catalogued', w: 0.35, station: 0.3 }
  };
  var MODEL = {
    LAWNMOWER_SURVEY: { label: 'Lawnmower survey', short: 'SURVEY', status: 'SURVEYING' },
    STATIONKEEPING_OPERATION: { label: 'Stationkeeping operation', short: 'STATION', status: 'ON STATION' }
  };
  /* Survey Detector: reference events, watch items and the regression table come from the data when it has them */
  var X = RAW.extras || {};
  var REFERENCE = X.reference ? X.reference : {
    chikyu: {
      events: [
        { t: Date.parse('2026-01-12T00:00Z'), label: 'Departed Shimizu for Minamitorishima' },
        { t: Date.parse('2026-01-17T00:00Z'), label: 'Arrived at test site' },
        { t: Date.parse('2026-01-30T00:00Z'), label: 'Recovery operations began' },
        { t: Date.parse('2026-02-01T00:00Z'), label: 'First rare-earth mud retrieval confirmed' }
      ],
      notes: 'Reported depth about 5,600–6,000 m; work paused for bad weather. A full-scale test is planned for February 2027 at about 350 t of sediment per day.',
      gfw: {
        source: 'Global Fishing Watch v3 events API for vessel 10c55eed1 (MMSI 432522000), pulled 7 Nov 2026; position and bounding box from the loitering event record',
        events: [
          { t0: Date.parse('2025-12-26T02:43Z'), t1: Date.parse('2026-01-06T06:58Z'), kind: 'Port visit', label: 'Shimizu, Japan' },
          { t0: Date.parse('2026-01-09T04:07Z'), t1: Date.parse('2026-01-12T00:40Z'), kind: 'Port visit', label: 'Shimizu, Japan (departs 12 Jan 00:40 UTC)' },
          { t0: Date.parse('2026-01-12T07:56Z'), t1: Date.parse('2026-01-12T15:59Z'), kind: 'Loitering', label: '8 h, Japanese EEZ, shortly after departure' },
          { t0: Date.parse('2026-01-17T00:56Z'), t1: Date.parse('2026-02-08T17:59Z'), kind: 'Loitering', label: '22 d 17 h, Japanese EEZ, 7.22 km total movement, 0.01 kn average' },
          { t0: Date.parse('2026-02-14T04:47Z'), t1: Date.parse('2026-03-20T00:50Z'), kind: 'Port visit', label: 'Shimizu, Japan (arrives 14 Feb 04:47 UTC)' }
        ],
        site: { lat: 23.0581, lon: 154.2089, depth: -5568, mntKm: 140, t0: Date.parse('2026-01-17T00:56Z'), t1: Date.parse('2026-02-08T17:59Z'), km: 7.22, kn: 0.007, bbox: [154.20633, 23.05717, 154.21145, 23.05896] }
      },
      sources: [
        { title: 'Marine Technology News: Japan retrieves rare earth mud from deep seabed (2 Feb 2026)', url: 'https://www.marinetechnologynews.com/news/japan-retrieves-earth-seabed-658253' },
        { title: 'Science Japan / Kyodo: Japan collects rare earth mud from deep waters (12 Feb 2026)', url: 'https://sj.jst.go.jp/news/202602/n0212-01n.html' }
      ]
    }
  };
  var SC = X.stationCfg || { min_hours: 48, r95_km: 3, max_median_kn: 1, min_port_km: 60, min_depth_m: 0 };
  var STATION_RULE = 'at least ' + SC.min_hours + ' h within ' + SC.r95_km + ' km, median speed under ' + SC.max_median_kn + ' kn, more than ' + SC.min_port_km + ' km from any port' + (SC.min_depth_m ? ', in water deeper than ' + SC.min_depth_m + ' m' : '');
  var WATCH = X.watch ? X.watch : [{ id: 'W-CHIKYU-2027', vessel: 'chikyu', title: 'Planned full-scale rare-earth mud test', window: 'Feb 2027', basis: 'Public reporting (Feb 2026): full-scale test planned for Feb 2027, about 350 t/day.', expect: 'Watch for Chikyu leaving port for Minamitorishima, weeks of stationkeeping offshore of the island, and support traffic to the island facility.' }];

  var REGRESSION = X.regression ? X.regression : {
    source: 'synthetic_full_platform_test.csv · expected: synthetic_full_platform_expected_results.csv · results: app_data/ (load_full_platform_test_clean.py)',
    rows: [
      ['SYN001', 'Normal transit, no survey', 'No survey', 'No survey', true],
      ['SYN002', 'Completed PMN survey + same-port return', 'Survey + same-port return', 'Survey (8 lines, completed) + returned to Hilo', true],
      ['SYN003', 'Port call only, no survey', 'No survey', 'No survey', true],
      ['SYN004', 'Active PMN survey, no return yet', 'Active survey', 'Survey (7 lines, in progress at last fix)', true],
      ['SYN005', 'AIS transmission gap', 'AIS gap', 'AIS gap 8.5 h', true],
      ['SYN006', 'Completed survey + different port', 'Survey + different-port return', 'Survey (7 lines) + arrived San Carlos (not same port)', true],
      ['SYN007', 'Coordinated survey with SYN008', 'Survey + coordination', 'Survey (7 lines) + coordinated with SYN008 (16 km)', true],
      ['SYN008', 'Coordinated survey + same-port return', 'Survey + coordination + same-port', 'Survey (7 lines) + coordinated with SYN007 + same-port return', true],
      ['SYN009', 'Two survey episodes / revisit', 'Two survey areas (revisit)', 'After fix (6 Nov): two areas of 6 lines, second flagged as revisit. Before: one merged 12-line area', true],
      ['SYN010', 'Normal transit control', 'No survey', 'No survey', true]
    ],
    survey: { tp: 6, fp: 0, fn: 0, tn: 4 }, fixed: true
  };
  function comp(key, label, v, w, detail) { return { key: key, label: label, v: clamp(v), w: w, detail: detail }; }
  function scoreOf(c) { var sw = c.reduce(function (s, x) { return s + x.w; }, 0); return c.reduce(function (s, x) { return s + x.v * x.w; }, 0) / sw; }
  function confLabel(s) { return s >= 0.8 ? 'HIGH' : s >= 0.6 ? 'MODERATE' : 'LOW'; }
  function tierOf(s) { return s >= 0.7 ? 'P1' : s >= 0.5 ? 'P2' : s >= 0.35 ? 'P3' : 'P4'; }

  function build() {
    var vessels = RAW.vessels.filter(function (v) { return v.enc.length >= 8; }).map(function (r) {
      var P = [], t = 0, la = 0, lo = 0, e = r.enc;
      for (var i = 0; i < e.length; i += 4) { t += e[i]; la += e[i + 1]; lo += e[i + 2]; P.push({ t: T_START + t * 1800e3, lat: la / 100, lon: lo / 100, sog: e[i + 3] / 10, cog: 0 }); }
      for (var k = 1; k < P.length; k++) { var a = P[k - 1], b = P[k]; P[k].cog = (a.lat !== b.lat || a.lon !== b.lon) ? bearing(a.lat, a.lon, b.lat, b.lon) : a.cog; }
      if (P.length > 1) P[0].cog = P[1].cog;
      ISO2NAME[r.flag] = r.country;
      var v = { id: r.id, code: r.id.toUpperCase(), name: r.name.toUpperCase(), flag: r.flag, country: r.country, mmsi: r.mmsi, imo: r.imo, callsign: r.callsign, cls: r.cls, watch: r.watch, home: r.home, pts: P, nRaw: r.n_raw };
      var g = r.gfw || { ids: [], events: [] };
      v.gfw = { ids: g.ids, imo: g.imo, owner: g.owner, ownerFlag: g.ownerFlag, type: g.type, lengthM: g.lengthM, gt: g.gt, registry: g.registry, callsign: g.callsign,
        events: g.events.map(function (x) { var o = {}; for (var k in x) o[k] = x[k]; o.t0 = tm(x.t0); o.t1 = tm(x.t1); return o; }) };
      if (!v.imo && v.gfw.imo) v.imo = v.gfw.imo;
      v.calls = r.calls.map(function (c) { return { port: c.port, t0: tm(c.t0), t1: tm(c.t1), dwellH: c.t1 - c.t0, arrObserved: c.arrObserved, open: c.open }; });
      v.voyages = [];
      for (var q = 0; q < v.calls.length - 1; q++) v.voyages.push({ from: v.calls[q].port, to: v.calls[q + 1].port, t0: v.calls[q].t1, t1: v.calls[q + 1].t0 });
      var lc = v.calls[v.calls.length - 1];
      if (lc && !lc.open) v.voyages.push({ from: lc.port, to: null, t0: lc.t1, t1: P[P.length - 1].t, atSea: true });
      v.voyages.forEach(function (x) { x.days = (x.t1 - x.t0) / DAY; x.same = x.to !== null && x.from === x.to; });
      v.gaps = r.gaps.map(function (g) { return { t0: tm(g.t0), t1: tm(g.t1), hours: g.hours, km: g.km, kn: g.kn, a: g.a, b: g.b }; });
      v.segments = []; var s0 = 0;
      v.gaps.forEach(function (g) { var i = s0; while (i < P.length && P[i].t < g.t1) i++; if (i > s0) { v.segments.push([s0, i - 1]); s0 = i; } });
      v.segments.push([s0, P.length - 1]);
      v.segments = v.segments.reduce(function (out, sg) { var a = sg[0]; for (var k = sg[0] + 1; k <= sg[1]; k++) if (Math.abs(P[k].lon - P[k - 1].lon) > 90) { out.push([a, k - 1]); a = k; } out.push([a, sg[1]]); return out; }, []);
      v.last = P[P.length - 1]; v.stale = (AS_OF - v.last.t) > 3 * DAY;
      return v;
    });
    var byId = {}; vessels.forEach(function (v) { byId[v.id] = v; });
    var events = [];
    RAW.events.forEach(function (r) {
      var v = byId[r.vessel]; if (!v) return;
      var e = { rid: r.id, vessel: v.id, model: r.model, t0: tm(r.t0), t1: tm(r.t1), center: r.center, eez: r.eez, depth: r.depth, boundary: r.boundary, zone: (r.zone && ZONE[r.zone]) || null, nearZone: (r.nearZone && ZONE[r.nearZone]) || null, nearZoneKm: r.nearZoneKm, foreign: r.foreign, nearestPort: r.nearestPort, mntKm: r.mntKm };
      e.active = e.t1 >= AS_OF - 12 * H;
      if (r.L) {
        var L = r.L; L.lines.forEach(function (l) { l.t0 = tm(l.t0); l.t1 = tm(l.t1); }); e.L = L;
        e.conf = [
          comp('passes', 'Repeated passes', (L.n - 2) / 8, 0.2, L.n + ' survey lines'),
          comp('spacing', 'Spacing regularity', 1 - L.spacingCV / 0.5, 0.2, f1(L.spacing) + ' km median, CV ' + L.spacingCV.toFixed(2)),
          comp('reversal', 'Reversal consistency', 1 - L.dev / 20, 0.15, 'mean ' + f1(L.dev) + '° off 180°'),
          comp('overlap', 'Line overlap', L.overlap, 0.15, Math.round(L.overlap * 100) + '% mean overlap'),
          comp('progress', 'Progressive coverage', L.progression, 0.1, Math.round(L.progression * 100) + '% of steps advance'),
          comp('newtrack', 'New ground each pass', L.newTrack, 0.1, Math.round(L.newTrack * 100) + '% new track'),
          comp('speed', 'Survey speed band', L.speed >= 2 && L.speed <= 8 ? 1 : 0.5, 0.1, f1(L.speed) + ' kn median')
        ];
        e.confScore = L.score; e.confSource = 'survey_pattern_detector.py score';
      } else {
        var S = r.S; S.excursions = []; e.S = S;
        e.conf = [
          comp('dwell', 'Extended dwell', (S.onHours - 24) / (7 * 24), 0.3, fmtDur(S.onHours) + ' on station'),
          comp('radius', 'Tight radius', 1 - (S.r95 - 1.0) / 2.5, 0.25, (S.r95 * 1000).toFixed(0) + ' m (95%), ' + S.cells + ' grid cells'),
          comp('speed', 'Near-zero speed', 1 - (S.medSog - 0.2) / 1, 0.25, 'median ' + S.medSog.toFixed(1) + ' kn'),
          comp('disp', 'Low net displacement', 1 - S.net / 3, 0.1, (S.net * 1000).toFixed(0) + ' m start-to-end'),
          comp('cls', 'Vessel class fits station work', CLASS[v.cls].station, 0.1, CLASS[v.cls].label),
          comp('gfw', 'Independent GFW loitering event', r.gfwMatch ? (r.gfwMatch.overlap >= 0.5 ? 1 : 0.7) : 0.2, 0.15, r.gfwMatch ? 'GFW loitering ' + fmtDur(r.gfwMatch.hours) + ', ' + Math.round(r.gfwMatch.overlap * 100) + '% overlap, ' + f1(r.gfwMatch.km) + ' km away' : 'No matching GFW loitering event')
        ];
        e.gfw = r.gfwMatch ? { overlap: r.gfwMatch.overlap, km: r.gfwMatch.km, hours: r.gfwMatch.hours, distKm: r.gfwMatch.distKm, kn: r.gfwMatch.kn, t0: tm(r.gfwMatch.t0), t1: tm(r.gfwMatch.t1) } : null;
        e.confScore = scoreOf(e.conf); e.confSource = 'SeaTrace stationkeeping model';
      }
      e.confLabel = confLabel(e.confScore);
      e.gaps = v.gaps.filter(function (g) { return g.t1 >= e.t0 - 7 * DAY && g.t0 <= e.t1; });
      e.voyage = v.voyages.filter(function (vy) { return vy.t0 <= e.t0 && vy.t1 >= e.t0; })[0] || null;
      events.push(e);
    });
    events.sort(function (a, b) { return a.t0 - b.t0; });
    var cnt = {}; events.forEach(function (e) { var c = byId[e.vessel].code; cnt[c] = (cnt[c] || 0) + 1; e.id = e.rid || ('E-' + c + '-' + String(cnt[c]).padStart(2, '0')); });   /* Survey Detector: stable ids from the data */
    events.forEach(function (e) {
      e.coord = events.filter(function (o) {
        if (o.vessel === e.vessel) return false;
        var ov = Math.min(e.t1, o.t1) - Math.max(e.t0, o.t0);
        return ov > 12 * H && hav(e.center[0], e.center[1], o.center[0], o.center[1]) < 80;
      }).map(function (o) { return { id: o.id, vessel: o.vessel, km: hav(e.center[0], e.center[1], o.center[0], o.center[1]), overlapH: (Math.min(e.t1, o.t1) - Math.max(e.t0, o.t0)) / H }; });
      e.revisits = events.filter(function (o) { return o.vessel === e.vessel && o.id !== e.id && Math.abs(o.t0 - e.t0) > 7 * DAY && hav(e.center[0], e.center[1], o.center[0], o.center[1]) < 150; }).map(function (o) { return o.id; });
      e.otherVisits = events.filter(function (o) { return o.vessel !== e.vessel && Math.abs(o.t0 - e.t0) > 7 * DAY && hav(e.center[0], e.center[1], o.center[0], o.center[1]) < 50; }).map(function (o) { return o.id; });
      e.sameZoneOps = events.filter(function (o) { return o.vessel === e.vessel && o.id !== e.id && Math.abs(o.t0 - e.t0) <= 7 * DAY && hav(e.center[0], e.center[1], o.center[0], o.center[1]) < 150; }).map(function (o) { return o.id; });
    });
    events.forEach(function (e) {
      var v = byId[e.vessel], z = e.zone, fRes, resD;
      if (z) { fRes = ZONE_TYPES[z.type].w; resD = 'Inside ISA contract area: ' + z.contractor + ' (' + ZONE_TYPES[z.type].label + ')'; }
      else if (e.mntKm < 300) { fRes = 0.8; resD = Math.round(e.mntKm) + ' km from Minamitorishima (rare-earth mud test area)'; }
      else if (e.nearZone && e.nearZoneKm != null && e.nearZoneKm < 300) {   /* Survey Detector: no ISA areas → no zone */ fRes = 0.5 * ZONE_TYPES[e.nearZone.type].w; resD = Math.round(e.nearZoneKm) + ' km from ISA area ' + e.nearZone.contractor; }
      else { fRes = 0.1; resD = 'No ISA area or rare-earth site within 300 km'; }
      var fStr, strD, ez = e.eez, bd = e.boundary;
      if (ez && ez.sov.indexOf(v.country) < 0) { fStr = 1; strD = 'Inside foreign EEZ: ' + ez.name; }
      else if (ez && ez.type !== '200NM') { fStr = 0.75; strD = 'Inside ' + ez.name; }
      else if (ez && bd && bd.km < 50) { fStr = 0.6; strD = 'Own EEZ, ' + Math.round(bd.km) + ' km from ' + bd.name + ' (' + bd.type.toLowerCase() + ')'; }
      else if (ez) { fStr = 0.15; strD = 'Inside own-flag EEZ (' + ez.name + ')'; }
      else if (z && z.sponsor && z.sponsor !== v.country) { fStr = 0.8; strD = 'High seas, in an area sponsored by ' + z.sponsor; }
      else if (bd && bd.km < 50) { fStr = 0.6; strD = 'High seas, ' + Math.round(bd.km) + ' km from ' + bd.name; }
      else { fStr = 0.4; strD = 'High seas (outside all EEZs)'; }
      var dp = e.depth, fDep, depD;
      if (dp === null || dp === undefined) { fDep = 0.5; depD = 'Depth unknown'; }
      else if (dp >= 0) { fDep = 0.05; depD = 'GEBCO cell is land or intertidal (' + dp + ' m)'; }
      else if (dp <= -1000) { fDep = 1; depD = Math.round(-dp).toLocaleString() + ' m water depth'; }
      else if (dp <= -200) { fDep = 0.6; depD = Math.round(-dp).toLocaleString() + ' m water depth (slope)'; }
      else { fDep = 0.15; depD = Math.round(-dp) + ' m water depth (shelf)'; }
      var fPat, patD;
      if (e.revisits.length) { fPat = 1; patD = 'Repeat visit: ' + (e.revisits.length + 1) + ' operations at this site'; }
      else if (e.otherVisits.length) { fPat = 0.8; patD = 'Other vessels worked this site at other times (' + e.otherVisits.length + ')'; }
      else if (e.sameZoneOps.length) { fPat = 0.6; patD = 'Several operations here on one voyage'; }
      else if (e.voyage && e.voyage.same) { fPat = 0.4; patD = 'Single cycle with same-port return'; }
      else { fPat = 0.3; patD = 'Single operation'; }
      var fCo = e.coord.length ? 1 : 0, coD = e.coord.length ? e.coord.map(function (k) { return byId[k.vessel].name + ' within ' + Math.round(k.km) + ' km'; }).join('; ') : 'No other vessel operating nearby at the same time';
      var fDark = e.gaps.length ? 1 : 0, darkD = e.gaps.length ? e.gaps.map(function (g) { return fmtDur(g.hours) + ' AIS gap'; }).join(', ') : 'Continuous AIS';
      var age = (AS_OF - e.t1) / DAY, fRec = e.active ? 1 : age < 14 ? 0.8 : age < 45 ? 0.6 : age < 120 ? 0.3 : 0.1, recD = e.active ? 'Active at last report' : 'Ended ' + Math.round(age) + ' days before latest data';
      e.pri = [
        comp('resource', 'Resource context', fRes, 0.22, resD),
        comp('capability', 'Vessel class', CLASS[v.cls].w, 0.22, CLASS[v.cls].label + (v.gfw.owner ? ' · registry owner ' + v.gfw.owner : ' (inferred)')),
        comp('strategic', 'EEZ / jurisdiction', fStr, 0.16, strD),
        comp('depth', 'Water depth', fDep, 0.1, depD),
        comp('pattern', 'Pattern of life', fPat, 0.1, patD),
        comp('coord', 'Multi-vessel activity', fCo, 0.08, coD),
        comp('dark', 'AIS gaps', fDark, 0.06, darkD),
        comp('recency', 'Recency', fRec, 0.06, recD)
      ];
      e.priScore = Math.round(scoreOf(e.pri) * 100) / 100; e.tier = tierOf(e.priScore);
      e.status = e.active ? 'ACTIVE' : 'COMPLETED';
      e.anchorage = !!(e.S && e.depth !== null && e.depth > -200 && e.S.portKm < 150);
      e.why = explain(e, v, byId);
    });
    events.sort(function (a, b) { return b.priScore - a.priScore || b.confScore - a.confScore; });
    var screened = RAW.screened.map(function (s) { return { vessel: s.vessel, t0: tm(s.t0), t1: tm(s.t1), reason: s.reason, center: s.center, n: s.n }; }).filter(function (s) { return byId[s.vessel]; });
    vessels.forEach(function (v) {
      v.events = events.filter(function (e) { return e.vessel === v.id; });
      v.top = v.events.slice().sort(function (a, b) { return b.priScore - a.priScore; })[0] || null;
      v.activeEv = v.events.filter(function (e) { return e.active; })[0] || null;
      v.screened = screened.filter(function (s) { return s.vessel === v.id; });
      var lastCall = v.calls[v.calls.length - 1];
      v.inPort = lastCall && lastCall.open ? PORT[lastCall.port] : null;
      v.sameReturns = v.voyages.filter(function (x) { return x.same && v.events.some(function (e) { return e.t0 >= x.t0 && e.t0 <= x.t1; }); }).length;
      v.status = v.activeEv ? MODEL[v.activeEv.model].status : v.inPort ? 'IN PORT' : (v.last.sog > 3 ? 'UNDERWAY' : 'SLOW / STOPPED');
    });
    var days = Math.ceil((AS_OF - T_START) / DAY) + 1, hist = new Array(days).fill(0);
    events.forEach(function (e) { for (var d = Math.floor((e.t0 - T_START) / DAY); d <= Math.floor((e.t1 - T_START) / DAY); d++) if (d >= 0 && d < days) hist[d]++; });
    var stats = { positionsRaw: RAW.meta.positions_raw, positions: vessels.reduce(function (s, v) { return s + v.pts.length; }, 0), vessels: vessels.length, events: events.length, surveys: events.filter(function (e) { return e.L; }).length, stations: events.filter(function (e) { return e.S; }).length, screened: screened.length, calls: vessels.reduce(function (s, v) { return s + v.calls.length; }, 0), voyages: vessels.reduce(function (s, v) { return s + v.voyages.length; }, 0), gaps: vessels.reduce(function (s, v) { return s + v.gaps.length; }, 0), sameReturns: vessels.reduce(function (s, v) { return s + v.sameReturns; }, 0), coord: events.filter(function (e) { return e.coord.length; }).length, surveyLines: events.reduce(function (s, e) { return s + (e.L ? e.L.lines.length : 0); }, 0), zones: ZONES.length, ports: PORTS.length };
    stats.gfwEvents = vessels.reduce(function (s, v) { return s + v.gfw.events.length; }, 0); stats.registry = vessels.filter(function (v) { return v.gfw.owner; }).length;
    return { vessels: vessels, byId: byId, events: events, screened: screened, hist: hist, stats: stats, ree: RAW.ree, hotspots: RAW.hotspots, eezLines: RAW.eezLines, gfwVal: RAW.gfwVal };
  }
  function explain(e, v, byId) {
    var parts = [];
    if (e.L) { var L = e.L; parts.push(L.n + ' parallel survey passes', f1(L.spacing) + ' km spacing (CV ' + L.spacingCV.toFixed(2) + ')', 'reversals within ' + Math.max(1, Math.round(L.dev)) + '° of 180°', Math.round(L.overlap * 100) + '% line overlap', f1(L.speed) + ' kn survey speed', Math.round(L.offshore) + ' km offshore'); }
    if (e.S) { var S = e.S; parts.push(fmtDur(S.onHours) + ' within ' + (S.r95 * 1000).toFixed(0) + ' m (95%)', 'median ' + S.medSog.toFixed(1) + ' kn', Math.round(S.portKm) + ' km from the nearest port'); }
    if (e.S && e.gfw) parts.push('confirmed by a GFW loitering event (' + fmtDur(e.gfw.hours) + ')');
    if (e.zone) parts.push('inside ISA ' + ZONE_TYPES[e.zone.type].short + ' contract area of ' + e.zone.contractor);
    else if (e.mntKm < 300) parts.push(Math.round(e.mntKm) + ' km from Minamitorishima (rare-earth mud)');
    if (e.eez && e.eez.sov.indexOf(v.country) < 0) parts.push('inside ' + e.eez.name);
    else if (e.eez && e.eez.type !== '200NM') parts.push('inside ' + e.eez.name);
    else if (!e.eez) parts.push('high seas, outside all EEZs');
    if (e.boundary && e.boundary.km < 50) parts.push(Math.round(e.boundary.km) + ' km from ' + e.boundary.name + ' (' + e.boundary.type.toLowerCase() + ')');
    if (e.depth !== null && e.depth !== undefined) parts.push(e.depth < 0 ? Math.round(-e.depth).toLocaleString() + ' m water depth' : 'GEBCO cell on land/intertidal');
    if (e.anchorage) parts.push('shallow and near port: may be anchoring');
    e.coord.forEach(function (k) { parts.push(byId[k.vessel].name + ' operating ' + Math.round(k.km) + ' km away at the same time'); });
    if (e.gaps.length) parts.push(fmtDur(e.gaps[0].hours) + ' AIS gap');
    if (e.revisits.length) parts.push('repeat visit to this site');
    if (e.otherVisits.length) parts.push(e.otherVisits.length + ' other vessel operation' + (e.otherVisits.length > 1 ? 's' : '') + ' at this site');
    if (e.voyage && e.voyage.same) parts.push('returned to ' + PORT[e.voyage.from].name);
    return parts;
  }
  return { EXTRAS: X, STATION_RULE: STATION_RULE, build: build, PORTS: PORTS, PORT: PORT, ZONES: ZONES, ZONE_TYPES: ZONE_TYPES, COUNTRY: ISO2NAME, CLASS: CLASS, MODEL: MODEL, REFERENCE: REFERENCE, WATCH: WATCH, REGRESSION: REGRESSION, AS_OF: AS_OF, T_START: T_START, H: H, DAY: DAY, hav: hav, offset: offset, fmtDur: fmtDur, compass: compass };
})();
