"""The SeaTrace console files and the page that shows them."""
import pytest

from tests import seatrace_ref as ref

needs_original = pytest.mark.skipif(not ref.available(), reason="SeaTrace.html not in ~/Downloads")


@needs_original
def test_markup_and_styles_unchanged():
    """SeaTrace's markup and CSS (everything before its data) are untouched, apart from the two text slots.
    The engine and UI scripts carry small, committed changes (git log views/seatrace/)."""
    from webapp import console
    page = console.assemble(ref.blob(), raw=True)
    cut = '<script type="application/json" id="seatrace-data">'
    assert page.split(cut)[0] == ref.original().split(cut)[0]


def test_assemble_escapes_script_end():
    from webapp.console import assemble
    html = assemble('{"name": "</script><b>x"}')
    data = html.split('id="seatrace-data">', 1)[1].split("</script>", 1)[0]
    assert "\\u003c/script>" in data and "{{" not in html


def test_console_files_reread_after_a_change(tmp_path, monkeypatch):
    """A deploy that changes ui.js must show up without restarting the server (no stale in-memory copy)."""
    import os
    import shutil
    from webapp import console
    for f in ("console.html", "engine.js", "ui.js", "addons.js"):
        shutil.copy(console.DIR / f, tmp_path / f)
    monkeypatch.setattr(console, "DIR", tmp_path)
    assert "MARKER-OLD" not in console.assemble('{"events":[],"vessels":[]}')
    ui = tmp_path / "ui.js"
    ui.write_text(ui.read_text() + "\n/* MARKER-NEW */\n")
    st = ui.stat()
    os.utime(ui, (st.st_atime, st.st_mtime + 5))
    assert "MARKER-NEW" in console.assemble('{"events":[],"vessels":[]}')
