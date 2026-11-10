"""Analyst > Detection settings: the model, its thresholds, station thresholds and port matching (this visitor only)."""
import streamlit as st

import models
import port_intel
import stationkeeping
from webapp import data, state, ui

ui.page_header("Detection settings", "Change how surveys and stations are found. Your changes apply to every page, "
               "for you only, until you reset them; everyone else keeps the defaults.", eyebrow="Analyst")
s, stn = state.settings(), state.station_settings()
defaults, stn_defaults = data.default_settings(), data.default_station_settings()
if st.button("Reset everything to the defaults", disabled=not state.is_custom()):
    state.reset_settings()
    st.rerun()

st.markdown("### Detection model")
MODELS = models.available()
keys = list(MODELS)
s["model"] = st.selectbox("Detection model", keys, index=keys.index(s["model"]) if s["model"] in keys else 0,
                          format_func=models.label, key="cfg_model",
                          help="Each file in the models/ folder is one model. Copy models/_template.py to add yours.")
st.caption(getattr(MODELS[s["model"]], "DESCRIPTION", ""))
for bad, why in models.errors().items():
    st.warning(f"models/{bad}.py could not be loaded: {why}")


def number(store: dict, name: str, default, help_text: str, key: str) -> None:
    label = name.replace("_", " ").replace(" kn", " (kn)").replace(" km", " (km)").replace(" deg", " (°)")
    if isinstance(default, int) and not isinstance(default, bool):
        store[name] = int(st.number_input(label, value=int(store.get(name, default)), min_value=0, step=1,
                                          help=help_text, key=key))
    else:
        store[name] = float(st.number_input(label, value=float(store.get(name, default)), min_value=0.0,
                                            format="%g", help=help_text, key=key))


st.markdown("### Lawnmower survey thresholds")
st.caption("You don't need to change these: the defaults suit most survey ships.")
for group, items in data.SETTINGS.items():
    with st.expander(group):
        for name, help_text in items.items():
            number(s, name, defaults[name], help_text, f"cfg_{name}")

st.markdown("### Station thresholds")
with st.expander("Holding one spot over deep water"):
    for name, help_text in stationkeeping.STATION_HELP.items():
        number(stn, name, stn_defaults[name], help_text, f"stn_{name}")

st.markdown("### Port matching")
modes = ["Each vessel's flag state", "One country for every vessel", "Nobody"]
current = 0 if s["port_country"] == "flag" else 2 if s["port_country"] == "none" else 1
mode = st.radio("Also list the nearest ports of", modes, index=current, key="cfg_port_mode",
                help="Matches each survey to ports of a country: its vessel's flag state (Chinese ships to "
                     "Chinese ports...), or one country you pick for every vessel.")
if mode == modes[1]:
    countries = port_intel.port_countries()
    pick = s["port_country"] if s["port_country"] in countries else ("China" if "China" in countries else countries[0])
    s["port_country"] = st.selectbox("Country", countries, index=countries.index(pick), key="cfg_port_country")
else:
    s["port_country"] = "flag" if mode == modes[0] else "none"

if state.is_custom():
    st.info("Custom settings are active: every page now shows results from your settings (the first page you "
            "open will take a minute to recompute).")
ui.footer("See the results in SeaTrace", "views/console.py")
