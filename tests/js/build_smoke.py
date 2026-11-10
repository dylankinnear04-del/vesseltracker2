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

RECORDER = """<script>window.__errors=[];window.addEventListener('error',function(e){window.__errors.push(String(e.message)+' @'+(e.lineno||''));});
window.addEventListener('unhandledrejection',function(e){window.__errors.push('promise: '+String(e.reason));});</script>"""
DRIVER = """<script>
(function(){
  function $(id){return document.getElementById(id);}
  function click(id){var el=$(id); if(el) el.click();}
  var out={errors:window.__errors,steps:0,events:0,vessels:0};
  try{
    var raw=JSON.parse(document.getElementById('seatrace-data').textContent); out.events=raw.events.length; out.vessels=raw.vessels.length;
    click('btn-brief');
    for(var i=0;i<40;i++){ var b=$('brief'); if(!b||!b.innerHTML||!$('b-next')) break; out.steps++; click('b-next'); }
    ['vw-gallery','vw-timeline','vw-map','tab-alerts','tab-fleet'].forEach(click);
    click('btn-valid'); document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));
    click('btn-method'); document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));
    click('play'); click('play'); click('season'); click('live');
  }catch(e){window.__errors.push('driver: '+e.message);}
  setTimeout(function(){ out.ok=window.__errors.length===0; document.title=JSON.stringify(out); },1500);
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
