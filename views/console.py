"""SeaTrace: the console, full window, on the live Survey Detector data."""
import streamlit as st

from webapp import console, data, state

st.html("""<style>
header[data-testid="stHeader"], [data-testid="stToolbar"], footer { display: none !important; }
.block-container, [data-testid="stMainBlockContainer"] { padding: 0 !important; max-width: 100% !important; }
[data-testid="stMain"] iframe { height: 100vh !important; width: 100% !important; border: 0; display: block; }
[data-testid="stAppViewContainer"], .stApp { background: #07121a; }
.seatrace-wait { color: #a1b5c3; font: 14px 'IBM Plex Sans', sans-serif; padding: 40vh 0 0; text-align: center; }
.seatrace-wait b { color: #dde8ef; } .seatrace-err { color: #ff5f56; }
</style>""")

group = state.param("group", data.GROUPS, "mining")
window = state.param("time", data.WINDOWS, "6m")
wait = st.empty()
wait.markdown('<div class="seatrace-wait"><b>SeaTrace</b><br>Loading ships and detections…</div>',
              unsafe_allow_html=True)
notices = []
if state.is_custom():
    notices.append("Custom detection settings active (Analyst ▸ Detection settings)")
late = console.track_notice(data.last_updated(data.library()))
if late:
    notices.append(late)
try:
    if st.query_params.get("source") == "upload" and st.session_state.get("upload_payload"):
        payload = st.session_state["upload_payload"]
        notices.insert(0, "Showing your uploaded files (Analyst ▸ Upload); remove ?source=upload to go back")
    else:
        payload = data.public_payload(group, window, state.results_settings(), state.results_station())
except Exception as exc:          # never a blank page
    wait.markdown(f'<div class="seatrace-wait seatrace-err">Could not build the console data: {type(exc).__name__}: '
                  f'{str(exc)[:300]}</div>', unsafe_allow_html=True)
    st.stop()
wait.empty()
if payload is None:
    st.markdown('<div class="seatrace-wait">No ship in this group has positions in that period. '
                '<a href="?group=all&time=1y" target="_top">Show all ships, last year</a></div>', unsafe_allow_html=True)
    st.stop()
blob, banner, subtitle = payload
if data.isa_zones() is None:
    notices.append("ISA contract areas unavailable right now: priorities use approximate resource regions")
if '"events":[]' in blob:
    notices.append("No detections in this season: try a longer season")
st.iframe(console.assemble(blob, banner=banner, subtitle=subtitle, notices=tuple(notices)), height=900)
