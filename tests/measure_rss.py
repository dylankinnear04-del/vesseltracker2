"""Peak memory (MB) of a page path under AppTest. Usage: python tests/measure_rss.py old|new"""
import resource, sys
from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
mode = sys.argv[1]
if mode == "default":
    # the default SeaTrace page only (mining ships, 6 months): compare with the old app's mining quick pick
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=900)
    at.run()
    print("exceptions:", [e.value for e in at.exception][:3])
    print("peak_rss_mb", round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6))
    sys.exit(0)
if mode == "old":
    # the pre-revamp app must run from the project root (it finds library/ next to itself)
    at = AppTest.from_file(str(ROOT / "_pre_revamp_app.py"), default_timeout=900)
    at.run()
    [b for b in at.button if b.label == "Mining ships"][0].click().run()
else:
    # SeaTrace (mining, 6 months: the default page), then all ships, then an Analyst page
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=900)
    at.run()
    at.query_params["group"] = "all"
    at.run()
    at.switch_page("views/analyst_data.py").run()
print("exceptions:", [e.value for e in at.exception][:3])
print("peak_rss_mb", round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6))
