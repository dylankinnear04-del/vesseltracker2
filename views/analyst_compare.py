"""Analyst > Validation: how well the detectors do, on labelled test data and against independent evidence."""
import pandas as pd
import streamlit as st

import models
from webapp import data, state, ui

ui.page_header("Compare models", "Run several detection models side by side and score them against known answers, "
               "and see how the detections compare with independent evidence.", eyebrow="Analyst")

BENCH = data.HERE / "benchmarks"
SOURCES = {f"Benchmark: {p.stem.replace('_', ' ')} (with labels)": p for p in sorted(BENCH.glob("*.csv"))
           if not p.stem.endswith("_labels") and (BENCH / f"{p.stem}_labels.csv").exists()}
OPTIONS = list(SOURCES) + ["Mining ships, last 6 months"] + (["Your uploaded files"] if st.session_state.get("upload_groups") else [])

st.markdown("### Compare models")
src = st.selectbox("Data", OPTIONS, key="val-data")
MODELS = models.available()
picked = st.multiselect("Models to compare", list(MODELS), default=list(MODELS), format_func=models.label, key="val-models")
labels_upload = st.file_uploader("Labels (optional): CSV with columns vessel, is_survey (1 or 0), e.g. the Alert "
                                 "queue's 'Download as labels'.", type=["csv"], key="val-labels")
if st.button("Run comparison", disabled=not picked):
    truth, ident = None, ()
    if src in SOURCES:
        f = SOURCES[src]
        groups = ((f.stem, ((f.name, f.read_bytes()),)),)
        lab = pd.read_csv(BENCH / f"{f.stem}_labels.csv", dtype={"vessel": str})
        truth = dict(zip(lab["vessel"].astype(str), lab["is_survey"].astype(int)))
    elif src == "Your uploaded files":
        groups = st.session_state["upload_groups"]
    else:
        groups, ident, _ = data.build_groups(data.select_ships(data.library(), "mining"), "6m")
    if labels_upload is not None:
        truth, problem = data.parse_labels(labels_upload.getvalue())
        if problem:
            st.error(problem)
            st.stop()
    summary, per_vessel = [], {}
    for key in picked:
        with st.spinner(f"Running {models.label(key)}..."):
            r = data.analyse(groups, {**state.settings(), "model": key}, ident)
        V, B = r["tables"]["vessels"], r["tables"]["survey_blocks"]
        found = dict(zip(V["vessel"].astype(str), V["survey_status"] != "No survey pattern"))
        per_vessel[models.label(key)] = found
        row = {"model": models.label(key), "vessels flagged": sum(found.values()),
               "survey areas": len(r["tables"]["survey_areas"]), "survey blocks": len(B),
               "mean block score": round(float(B["score"].mean()), 3) if len(B) else None,
               "seconds": round(r["seconds"], 2), "true positives": None, "false alarms": None, "missed": None,
               "precision": None, "recall": None}
        if truth:
            t = {v: truth[v] for v in found if v in truth}
            tp = sum(found[v] and x for v, x in t.items())
            fp = sum(found[v] and not x for v, x in t.items())
            fn = sum(not found[v] and x for v, x in t.items())
            row.update({"true positives": tp, "false alarms": fp, "missed": fn,
                        "precision": round(tp / (tp + fp), 2) if tp + fp else None,
                        "recall": round(tp / (tp + fn), 2) if tp + fn else None})
        summary.append(row)
    st.session_state["comparison"] = (summary, per_vessel, truth)
if "comparison" in st.session_state:
    summary, per_vessel, truth = st.session_state["comparison"]
    st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch")
    st.caption("precision = share of flagged ships that really are surveying; recall = share of real surveys "
               "that were flagged. seconds is the first, uncached run.")
    grid = pd.DataFrame(per_vessel).replace({True: "survey", False: ""})
    if truth:
        grid.insert(0, "truth", [("survey" if truth.get(v) else "") if v in truth else "?" for v in grid.index])
    grid.index.name = "vessel"
    with st.expander("Per ship"):
        st.dataframe(grid.reset_index(), hide_index=True, width="stretch")

st.info("Precision on the real detections comes from your reviews: mark detections in SeaTrace's Alert queue, "
        "then open SeaTrace ▸ Validation. 'Download as labels' there gives a labels file for this page.")
ui.footer()
