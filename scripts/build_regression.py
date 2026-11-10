"""
Rebuild benchmarks/regression_results.json: the default detection model on the labelled benchmarks, shown in
SeaTrace's Validation sheet. Run after changing the detector, models/ or benchmarks/ (a test checks it is current):

    python scripts/build_regression.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from webapp import seatrace_export as sx   # noqa: E402

out = sx.compute_regression()
sx.REGRESSION_FILE.write_text(json.dumps(out, indent=1))
print(f"wrote {sx.REGRESSION_FILE.relative_to(ROOT)}: {len(out['rows'])} ships, {out['survey']}")
