"""SeaTrace's original file (the user's ~/Downloads copy) as the reference for look and data format.
Its data blob embeds ISA contract polygons, so it is read from there and never stored in the repo."""
from functools import lru_cache
from pathlib import Path

ORIGINAL = Path.home() / "Downloads" / "SeaTrace.html"
HERE = Path(__file__).resolve().parents[1] / "views" / "seatrace"
PRE, SUF = '<script type="application/json" id="seatrace-data">', "</script>"


def available() -> bool:
    return ORIGINAL.exists()


@lru_cache(maxsize=1)
def original() -> str:
    return ORIGINAL.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def blob() -> str:
    line = next(l for l in original().split("\n") if l.startswith(PRE))
    return line[len(PRE):-len(SUF)]
