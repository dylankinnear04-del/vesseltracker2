"""
Build the SeaTrace console's data for every ship group and season ahead of time (prebuilt/*.json.gz), so the
website shows it at once instead of running the detector (about a minute and 1.4 GB) for the first visitor.
The weekly GFW update and every push to main run this; to run it by hand:

    python scripts/build_console_data.py              # every group and season
    python scripts/build_console_data.py mining:6m    # just some

A file is only used while it matches the ship data and detector code (a fingerprint is stored in it); otherwise
the site builds the data itself, as before. ISA contract polygons are never written: they are added live.
"""
import gc
import logging
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
logging.getLogger("streamlit").setLevel(logging.ERROR)

from webapp import data   # noqa: E402

wanted = [a.split(":") for a in sys.argv[1:]] or [(g, w) for g in data.GROUPS for w in data.WINDOWS]
print(f"fingerprint {data.inputs_stamp()}, ISA areas {'available' if data.isa_zones() is not None else 'UNAVAILABLE'}")
for group, window in wanted:
    t = time.time()
    path = data.write_prebuilt(group, window)
    gc.collect()
    print(f"{path.relative_to(ROOT)}: {path.stat().st_size / 1e6:.1f} MB in {time.time() - t:.0f} s", flush=True)
