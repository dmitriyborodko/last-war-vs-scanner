from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from vsparser.export import csv_bytes, results_frame, xlsx_bytes  # noqa: E402
from vsparser.pipeline import process_video  # noqa: E402
from vsparser.roster import load_roster, remember_names, save_member_list  # noqa: E402


st.set_page_config(page_title="Last War VS Parser", layout="wide")
st.title("Last War VS Ranking Parser")
st.caption("Local-only processing. Recordings and extracted data remain on this PC.")

video_text = st.text_input("MP4 path", placeholder=str(ROOT / "recording.mp4"))
output_text = st.text_input("Output folder", str(ROOT / "output"))
roster_text = st.text_input("Local teammate roster", str(ROOT / "data" / "member_roster.json"))

if st.button("Alliance Members"):
    st.session_state["show_member_editor"] = True
if st.session_state.get("show_member_editor"):
    roster_path = Path(roster_text)
    try:
        saved_members = "\n".join(load_roster(roster_path))
    except (OSError, ValueError, TypeError) as error:
        st.error(f"Could not open members: {error}")
        saved_members = ""
    members_text = st.text_area(
        "One alliance member per line",
        value=saved_members,
        height=240,
        help="Paste a column from Google Sheets. Edit the lines to add, rename, or remove members.",
    )
    if st.button("Save Members", type="primary"):
        try:
            members = save_member_list(roster_path, members_text)
            st.success(f"Saved {len(members)} alliance member(s).")
        except (OSError, ValueError, TypeError) as error:
            st.error(f"Could not save members: {error}")

if st.button("Process recording", type="primary"):
    progress_bar = st.progress(0, "Opening video")

    def update(current: int, total: int, message: str) -> None:
        progress_bar.progress(current / total, message)

    try:
        with st.spinner("Selecting frames and running offline OCR..."):
            results = process_video(Path(video_text), Path(output_text), Path(roster_text), update)
        st.session_state["results"] = results_frame(results)
        progress_bar.progress(1.0, "Complete")
    except Exception as error:
        st.error(str(error))

if "results" in st.session_state:
    st.subheader("Review")
    st.write("Correct cells directly. Clear **Keep** to remove a row from exports.")
    editable = st.session_state["results"].copy()
    if "Keep" not in editable:
        editable.insert(0, "Keep", True)
    edited = st.data_editor(
        editable,
        hide_index=True,
        use_container_width=True,
        disabled=["confidence", "raw_rank", "raw_name", "raw_points", "timestamps", "source_frames", "observation_count"],
        column_config={
            "Keep": st.column_config.CheckboxColumn(default=True),
            "review": st.column_config.CheckboxColumn(),
            "confidence": st.column_config.NumberColumn(format="%.3f"),
        },
    )
    validated = edited.loc[edited["Keep"]].drop(columns=["Keep"])
    if st.button("Remember reviewed teammate names"):
        remember_names(Path(roster_text), validated.to_dict(orient="records"))
        st.success(f"Saved names and OCR aliases locally to {roster_text}")
    st.download_button("Export reviewed CSV", csv_bytes(validated), "vs_rankings_reviewed.csv", "text/csv")
    st.download_button(
        "Export reviewed Excel", xlsx_bytes(validated), "vs_rankings_reviewed.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    source_options = sorted({path for value in validated["source_frames"] for path in str(value).split("; ") if path})
    if source_options:
        st.subheader("Source verification")
        selected_source = st.selectbox("Frame", source_options)
        st.image(selected_source, caption=selected_source)
