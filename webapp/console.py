"""
The SeaTrace console: its files (views/seatrace/, copied from the SeaTrace prototype) put back together
around a data blob, ready to show in an iframe.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parents[1] / "views" / "seatrace"


@lru_cache(maxsize=1)
def _parts() -> tuple[str, str, str]:
    return tuple((DIR / f).read_text(encoding="utf-8") for f in ("console.html", "engine.js", "ui.js"))


ORIGINAL_BANNER = ("Unclassified · real AIS: Global Fishing Watch, 1 May – 29 Oct 2026 · GFW events &amp; registry "
                   "Jan – Nov 2026 · ISA contract areas · Marine Regions EEZs · research prototype")
ORIGINAL_SUBTITLE = "Deep-sea mineral activity intelligence · JMU capstone prototype"


def _addons() -> str:
    return (DIR / "addons.js").read_text(encoding="utf-8")


def assemble(blob: str, raw: bool = False, banner: str = ORIGINAL_BANNER, subtitle: str = ORIGINAL_SUBTITLE,
             notices: tuple = ()) -> str:
    """
    The full console page around a JSON blob. raw=True inserts it as given (the parity test).
    banner / subtitle: HTML-safe text for the header (default: SeaTrace's original).
    """
    shell, engine, ui = _parts()
    addons = "" if raw else "window.ST_NOTICES = " + json.dumps(list(notices)).replace("<", "\\u003c") + ";\n" + _addons()
    shell = shell.replace("{{BANNER}}", banner, 1).replace("{{SUBTITLE}}", subtitle, 1).replace("{{ADDONS}}", addons, 1)
    if not raw:
        blob = blob.replace("<", "\\u003c")     # nothing inside the data can close its <script> tag or open a comment
    # one replacement each, in an order where inserted text cannot contain a later marker
    return shell.replace("{{ENGINE}}", engine, 1).replace("{{UI}}", ui, 1).replace("{{DATA}}", blob, 1)


def reference_blob() -> str:
    """SeaTrace's original data, from the user's Downloads copy (temporary, Task 0 only)."""
    pre = '<script type="application/json" id="seatrace-data">'
    src = (Path.home() / "Downloads" / "SeaTrace.html").read_text(encoding="utf-8")
    line = next(l for l in src.split("\n") if l.startswith(pre))
    return line[len(pre):-len("</script>")]
