"""
What the visitor is looking at, kept in the web address so every view can be shared and survives
a refresh, plus this visitor's own detection settings (Analyst > Detection settings).
"""
from __future__ import annotations

from typing import Iterable

import streamlit as st

from webapp import data


def param(name: str, allowed: Iterable[str] | None, default: str) -> str:
    """A text parameter from the URL; missing or not one of `allowed` -> default."""
    value = st.query_params.get(name)
    if value is None or value == "":
        return default
    if allowed is not None and value not in set(allowed):
        return default
    return value


def int_param(name: str, default: int | None = None) -> int | None:
    """A whole-number parameter from the URL; missing or not a number -> default."""
    try:
        return int(st.query_params.get(name))
    except (TypeError, ValueError):
        return default


def set_params(**kw: str | int | None) -> None:
    """Write parameters into the URL; None removes one."""
    for name, value in kw.items():
        if value is None:
            if name in st.query_params:
                del st.query_params[name]
        else:
            st.query_params[name] = str(value)


def settings() -> dict:
    """This visitor's detection settings (the defaults until they change something)."""
    if "settings" not in st.session_state:
        st.session_state["settings"] = data.default_settings()
    return st.session_state["settings"]


def station_settings() -> dict:
    """This visitor's stationkeeping thresholds (stationkeeping.StationConfig fields)."""
    if "station_settings" not in st.session_state:
        st.session_state["station_settings"] = data.default_station_settings()
    return st.session_state["station_settings"]


def is_custom() -> bool:
    """True while any detection or station setting differs from the default."""
    return (("settings" in st.session_state and st.session_state["settings"] != data.default_settings())
            or ("station_settings" in st.session_state
                and st.session_state["station_settings"] != data.default_station_settings()))


def reset_settings() -> None:
    st.session_state["settings"] = data.default_settings()
    st.session_state["station_settings"] = data.default_station_settings()
    for k in [k for k in st.session_state if str(k).startswith(("cfg_", "stn_"))]:
        del st.session_state[k]


def results_settings() -> dict | None:
    """Settings to pass to data.public_results: None (shared defaults) unless customised."""
    return dict(settings()) if is_custom() else None


def results_station() -> dict | None:
    return dict(station_settings()) if is_custom() else None
