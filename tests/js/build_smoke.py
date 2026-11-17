"""
Build SeaTrace smoke-test pages: the real console on several data sets, with an error recorder first and a
driver last that presses every control (briefing to the end, views, sheets, play, season) and writes the
result into the page title as JSON: {"ok": bool, "errors": [...], "steps": n, "events": n, "vessels": n}.

    python tests/js/build_smoke.py OUT_DIR      # then open each OUT_DIR/*.html in a browser
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from webapp import console, data, seatrace_export as sx   # noqa: E402

RECORDER = """<script>window.__hash0=(function(){try{return window.top.location.hash}catch(e){return location.hash}})();window.__errors=[];window.addEventListener('error',function(e){window.__errors.push(String(e.message)+' @'+(e.lineno||''));});
window.addEventListener('unhandledrejection',function(e){window.__errors.push('promise: '+String(e.reason));});</script>"""
DRIVER = """<script>
(function(){
  function $(id){return document.getElementById(id);}
  function click(id){var el=$(id); if(el) el.click();}
  var out={errors:window.__errors,steps:0,events:0,vessels:0};
  setTimeout(function(){   /* let start-up animations (a restored link's fly-to) finish first */
  try{
    var M=window.SEATRACE&&window.SEATRACE.map;
    out.layersOpen=!!($('layers')&&$('layers').open); if(out.layersOpen) window.__errors.push('Layers panel open at start (covers the map)');
    if(M){ out.startZoom=M.getZoom(); out.hashAtStart=(function(){try{return window.top.location.hash}catch(e){return location.hash}})();
      M.setView([10,-170],3,{animate:false}); M.fire('moveend');                    /* pan west past the old -150 lock */
      var lng=M.getCenter().lng; out.panOk=Math.abs((((lng+170)%360)+360)%360)<1;  /* same place on the globe, not pulled back */
      out.mirror=window.ST_MIRROR?window.ST_MIRROR():-1;                             /* ships/tracks repeated where needed */
      M.setView([0,140],2,{animate:false}); M.fire('moveend'); }
    out.hash0=window.__hash0||''; out.link=/(^|[#&])e=/.test(out.hash0);
    if(!(out.startZoom<=(out.link?6:4))) window.__errors.push('starts zoomed in: '+out.startZoom);
    if(!out.link && /e=/.test(out.hashAtStart)) window.__errors.push('default selection written to the URL before any click: '+location.hash);
    if(!out.panOk) window.__errors.push('pan west blocked');
    if(!(out.mirror>0)) window.__errors.push('no world copies of ships/tracks: '+out.mirror);
    var raw=JSON.parse(document.getElementById('seatrace-data').textContent); out.events=raw.events.length; out.vessels=raw.vessels.length;
    /* seamounts and ridges: raise resource context only in water deeper than 200 m and never over an ISA contract value */
    var EV=(window.SEATRACE&&window.SEATRACE.D.events)||[], res=function(e){return e.pri.filter(function(c){return c.key==='resource';})[0];};
    var onSf=EV.filter(function(e){return e.seafloor&&e.seafloor.kind&&e.depth!=null&&e.depth<-200&&!e.zone;});
    out.seafloorEvents=onSf.length;
    out.rawSeafloor=raw.events.filter(function(r){return r.seafloor&&r.seafloor.kind&&r.depth!=null&&r.depth<-200&&!r.zone;}).length;
    if(out.rawSeafloor!==out.seafloorEvents) window.__errors.push('seafloor not carried into the engine: '+out.seafloorEvents+' of '+out.rawSeafloor);
    out.seamountOk=onSf.every(function(e){var c=res(e);return c.v>=0.6&&/seamount|ridge/i.test(c.detail);});
    out.shallowOk=EV.filter(function(e){return !(e.depth!=null&&e.depth<-200);}).every(function(e){return !/seamount|ridge/i.test(res(e).detail);});
    out.zoneOk=EV.filter(function(e){return e.zone;}).every(function(e){return Math.abs(res(e).v-ENGINE.ZONE_TYPES[e.zone.type].w)<1e-9;});
    if(!out.seamountOk) window.__errors.push('seamount detection not scored as one');
    if(!out.shallowOk) window.__errors.push('seamount rule applied in shallow water');
    if(!out.zoneOk) window.__errors.push('ISA contract value changed by the seafloor rule');
    /* Seafloor (GEBCO) layer: listed, off at start, toggles a WMS layer from wms.gebco.net */
    if(M){ var sfb=document.querySelector('[data-layer="seafloor"]'), wms=function(){var n=0;M.eachLayer(function(l){if(l._url&&/wms\\.gebco\\.net/.test(l._url))n++;});return n;};
      var off0=wms()===0; if(sfb) sfb.click();
      setTimeout(function(){ var on1=wms()===1, b2=document.querySelector('[data-layer="seafloor"]'); if(b2) b2.click();
        setTimeout(function(){ var off2=wms()===0; out.seafloorLayer=!!sfb&&off0&&on1&&off2;
          if(!out.seafloorLayer) window.__errors.push('seafloor layer: '+[!!sfb,off0,on1,off2].join(',')); },60); },60); }
    click('btn-brief');
    for(var i=0;i<40;i++){ var b=$('brief'); if(!b||!b.innerHTML||!$('b-next')) break; out.steps++; click('b-next'); }
    ['vw-gallery','vw-timeline','vw-map','tab-alerts','tab-fleet'].forEach(click);
    click('btn-valid'); document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));
    click('btn-method'); document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));
    click('play'); click('play'); click('season'); click('live');
    click('tab-entities'); var r0=document.querySelector('.stx-ent'); if(r0){ r0.click(); var b0=r0.querySelector('[data-vid]'); if(b0) b0.click(); }
    click('tab-fleet');
    var A=window.SEATRACE; if(A && A.D.events.length){ A.focusEvent(A.D.events[0].id, false); }
    /* SEAMOUNT / RIDGE tags: one per listed alert on a seamount or ridge, and in the detection panel header */
    if(A){ click('tab-alerts'); var listed=[].slice.call(document.querySelectorAll('.alert[data-ev]')).map(function(b){return b.getAttribute('data-ev');});
      var want=listed.filter(function(id){var e=A.D.events.filter(function(x){return x.id===id;})[0];return e&&ENGINE.seafloorOn(e);});
      var got=document.querySelectorAll('.alert .sftag').length, sfe=want.length?A.D.events.filter(function(x){return x.id===want[0];})[0]:null, head=true;
      if(sfe){ A.focusEvent(sfe.id,false); var t=document.querySelector('.evhead .sftag'); head=!!t&&t.title===ENGINE.seafloorText(sfe.seafloor); }
      out.tagOk=got===want.length&&head; if(!out.tagOk) window.__errors.push('seafloor tags: '+got+' of '+want.length+', header '+head); click('tab-fleet'); }
    out.entities=document.querySelectorAll('.stx-ent').length;
  }catch(e){window.__errors.push('driver: '+e.message);}
  setTimeout(function(){ out.supply=!!document.querySelector('.stx-supply'); out.ok=window.__errors.length===0; document.title=JSON.stringify(out); },1500);
  },1200);
})();
</script>"""


def strip_zones(b: dict) -> dict:
    """ISA contract polygons never go to disk: drop them (and so the events' zone references)."""
    b["zones"] = []
    for e in b.get("events", []):
        e["zone"] = e["nearZone"] = None
    return b


def page(blob_json: str, banner: str = console.ORIGINAL_BANNER, subtitle: str = console.ORIGINAL_SUBTITLE) -> str:
    html = console.assemble(blob_json, banner=banner, subtitle=subtitle)
    html = html.replace("<head>", "<head>" + RECORDER, 1)
    return html.replace("</body>", DRIVER + "</body>", 1)


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    orig = Path.home() / "Downloads" / "SeaTrace.html"
    if orig.exists():
        b = json.loads(console.reference_blob())
        strip_zones(b)
        (out / "original_data.html").write_text(page(sx.to_json(b)))
    for group, window in (("mining", "6m"), ("all", "6m"), ("china", "30d"), ("all", "all")):
        p = data.public_payload(group, window)
        if p is None:
            (out / f"{group}_{window}.html").write_text("<title>{\"ok\": true, \"empty\": true}</title>")
            continue
        b = json.loads(p[0])
        strip_zones(b)
        (out / f"{group}_{window}.html").write_text(page(sx.to_json(b), p[1], p[2]))
        if (group, window) == ("mining", "6m"):
            b["events"], b["screened"] = [], []                      # a season with nothing found
            (out / "no_detections.html").write_text(page(sx.to_json(b), p[1], p[2]))
    print("\n".join(sorted(x.name for x in out.glob("*.html"))))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
