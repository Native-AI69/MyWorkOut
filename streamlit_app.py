from __future__ import annotations

import os
from datetime import date
import pandas as pd
import streamlit as st
import plotly.express as px

PROGRAM_PATH = "program.csv"
LOG_PATH = "workouts_log.csv"

# ----------------- Program -----------------
@st.cache_data
def load_program() -> pd.DataFrame:
    """
    Loads program.csv robustly.

    Common cause of ParserError: a comma inside a field that is not quoted.
    This loader uses the python engine (more tolerant) and shows a helpful
    message if parsing fails.
    """
    try:
        df = pd.read_csv(
            PROGRAM_PATH,
            engine="python",
            sep=",",
            quotechar='"',
            encoding="utf-8-sig",
        )
    except Exception as e:
        # Show the first ~50 lines of the file to diagnose formatting.
        preview = ""
        try:
            with open(PROGRAM_PATH, "r", encoding="utf-8-sig", errors="replace") as f:
                preview = "".join([next(f) for _ in range(50)])
        except Exception:
            preview = "(Could not read program.csv preview.)"

        st.error("Could not parse program.csv. This is usually caused by an extra comma in a field that isn't quoted.")
        st.code(preview, language="text")
        st.stop()

    required = {
        "day","group","exercise_id","exercise_name","equipment",
        "sets_prescribed","reps_prescribed","load_target","load_unit"
    }
    missing = required - set(df.columns)
    if missing:
        st.error(f"program.csv is missing required columns: {sorted(missing)}")
        st.dataframe(df.head(20), use_container_width=True)
        st.stop()

    # Normalize types
    df["sets_prescribed"] = pd.to_numeric(df["sets_prescribed"], errors="coerce").fillna(0).astype(int)
    df["day"] = df["day"].astype(str).str.strip()
    return df

# ----------------- Log (CSV) -----------------
def ensure_log_exists() -> None:
    if not os.path.exists(LOG_PATH):
        cols = [
            "workout_date","week","day","group","exercise_id","exercise_name","equipment",
            "sets_prescribed","reps_prescribed","load_target","load_unit",
            "sets_completed","reps_by_set","load_used","load_used_unit",
            "rir_last_set","form","pain","set_quality","barbell_same_weight",
            "compliance","reasons","notes"
        ]
        pd.DataFrame(columns=cols).to_csv(LOG_PATH, index=False)

def read_log() -> pd.DataFrame:
    ensure_log_exists()
    return pd.read_csv(LOG_PATH)

def append_log(row: dict) -> None:
    ensure_log_exists()
    pd.DataFrame([row]).to_csv(LOG_PATH, mode="a", header=False, index=False)

# ----------------- Rules -----------------
def parse_reps(reps_text: str) -> list[int]:
    parts = [p.strip() for p in str(reps_text).split(",") if p.strip()]
    return [int(p) for p in parts]

def reps_meet_prescription(sets_prescribed: int, reps_prescribed: str, reps_by_set: str) -> tuple[bool, str]:
    try:
        reps_list = parse_reps(reps_by_set)[:sets_prescribed]
        if len(reps_list) < sets_prescribed:
            return False, "Fewer sets logged than prescribed"

        reps_prescribed = str(reps_prescribed).strip()
        if "-" in reps_prescribed:
            lo, _hi = reps_prescribed.split("-")
            lo = int(lo.strip())
            if any(r < lo for r in reps_list):
                return False, "Some sets below minimum rep target"
            return True, ""
        else:
            target = int(reps_prescribed)
            if any(r < target for r in reps_list):
                return False, "Some sets below prescribed reps"
            return True, ""
    except Exception:
        return False, "Could not parse reps_by_set"

def compliance_check(
    equipment: str,
    sets_prescribed: int,
    reps_prescribed: str,
    reps_by_set: str,
    pain: str,
    form: str,
    set_quality: str,
    barbell_same_weight: bool
) -> tuple[str, list[str]]:
    reasons: list[str] = []

    # Hard stops
    if pain in ["Moderate", "Severe"]:
        return "FAIL", ["Pain is Moderate/Severe"]
    if equipment.lower() == "barbell" and not barbell_same_weight:
        return "FAIL", ["Barbell working weight changed across sets"]
    if str(set_quality).startswith("Red"):
        return "FAIL", ["Set quality marked Red"]

    # Warnings
    if form == "Bad":
        reasons.append("Form marked Bad")
    if str(set_quality).startswith("Yellow"):
        reasons.append("Set quality marked Yellow")

    ok_reps, rep_reason = reps_meet_prescription(sets_prescribed, reps_prescribed, reps_by_set)
    if not ok_reps:
        reasons.append(rep_reason)

    if reasons:
        return "WARN", reasons
    return "PASS", reasons

# ----------------- UI -----------------
def main():
    st.set_page_config(page_title="Strength Program Tracker", layout="wide")
    program = load_program()
    ensure_log_exists()

    st.title("Strength Program Tracker")
    st.caption("Week selector is for logging. The plan stays fixed, you track compliance and progress.")

    tab1, tab2 = st.tabs(["Log Workout", "Dashboard"])

    with tab1:
        st.subheader("Log a workout")

        colA, colB, colC = st.columns(3)
        with colA:
            workout_date = st.date_input("Workout date", value=date.today())
        with colB:
            week = st.selectbox("Week", options=list(range(1, 9)))
        with colC:
            day = st.selectbox("Day", options=sorted(program["day"].unique()))

        day_plan = program[program["day"] == day].copy()

        st.markdown("### Planned session")
        st.dataframe(
            day_plan[["group","exercise_name","equipment","sets_prescribed","reps_prescribed","load_target","load_unit"]],
            use_container_width=True
        )

        st.markdown("### Enter results (save each exercise)")
        for _, ex in day_plan.iterrows():
            ex_id = ex["exercise_id"]
            with st.expander(f"{ex['exercise_name']} ({ex['equipment']})", expanded=True):
                sets_completed = st.number_input(
                    "Sets completed",
                    min_value=0, max_value=20,
                    value=int(ex["sets_prescribed"]),
                    key=f"sets_{ex_id}"
                )

                reps_by_set = st.text_input(
                    "Reps by set (comma-separated, e.g., 5,5,5,5,5)",
                    value="",
                    key=f"reps_{ex_id}"
                )

                load_used = st.number_input(
                    "Load used (number)",
                    min_value=0.0,
                    value=0.0,
                    step=5.0,
                    key=f"load_{ex_id}"
                )

                load_used_unit = st.selectbox(
                    "Load unit (what you logged)",
                    options=["plates only", "lb", "lbs each"],
                    index=0,
                    key=f"unit_{ex_id}"
                )

                rir_last_set = st.selectbox(
                    "RIR on last set",
                    options=[0,1,2,3,4,5],
                    index=2,
                    key=f"rir_{ex_id}"
                )

                form = st.selectbox(
                    "Form",
                    options=["Good","OK","Bad"],
                    index=0,
                    key=f"form_{ex_id}"
                )

                pain = st.selectbox(
                    "Pain",
                    options=["None","Mild","Moderate","Severe"],
                    index=0,
                    key=f"pain_{ex_id}"
                )

                set_quality = st.selectbox(
                    "Set quality (overall)",
                    options=["Green (clean)", "Yellow (slowed)", "Red (missed/ugly)"],
                    index=0,
                    key=f"qual_{ex_id}"
                )

                barbell_same_weight = True
                if str(ex["equipment"]).lower() == "barbell":
                    barbell_same_weight = st.checkbox(
                        "Barbell rule: same working weight across all work sets",
                        value=True,
                        key=f"same_{ex_id}"
                    )

                notes = st.text_area("Notes (optional)", value="", key=f"notes_{ex_id}")

                if st.button("Save this exercise", key=f"save_{ex_id}"):
                    compliance, reasons = compliance_check(
                        equipment=str(ex["equipment"]),
                        sets_prescribed=int(ex["sets_prescribed"]),
                        reps_prescribed=str(ex["reps_prescribed"]),
                        reps_by_set=reps_by_set,
                        pain=pain,
                        form=form,
                        set_quality=set_quality,
                        barbell_same_weight=barbell_same_weight
                    )

                    row = dict(
                        workout_date=str(workout_date),
                        week=int(week),
                        day=str(day),
                        group=str(ex["group"]),
                        exercise_id=str(ex_id),
                        exercise_name=str(ex["exercise_name"]),
                        equipment=str(ex["equipment"]),
                        sets_prescribed=int(ex["sets_prescribed"]),
                        reps_prescribed=str(ex["reps_prescribed"]),
                        load_target=str(ex["load_target"]),
                        load_unit=str(ex["load_unit"]),
                        sets_completed=int(sets_completed),
                        reps_by_set=str(reps_by_set),
                        load_used=float(load_used),
                        load_used_unit=str(load_used_unit),
                        rir_last_set=int(rir_last_set),
                        form=str(form),
                        pain=str(pain),
                        set_quality=str(set_quality),
                        barbell_same_weight=1 if barbell_same_weight else 0,
                        compliance=str(compliance),
                        reasons="; ".join(reasons),
                        notes=str(notes)
                    )
                    append_log(row)
                    st.success(f"Saved. Compliance: {compliance}" + (f" | {row['reasons']}" if row["reasons"] else ""))

        st.divider()
        st.markdown("### Download your log")
        log_df = read_log()
        st.download_button(
            label="Download workouts_log.csv",
            data=log_df.to_csv(index=False).encode("utf-8"),
            file_name="workouts_log.csv",
            mime="text/csv"
        )

    with tab2:
        st.subheader("Dashboard")
        log = read_log()
        if log.empty:
            st.info("No entries yet. Log your first workout.")
            return

        log["workout_date"] = pd.to_datetime(log["workout_date"], errors="coerce")

        col1, col2, col3 = st.columns(3)
        with col1:
            exercise = st.selectbox("Exercise", options=sorted(log["exercise_name"].dropna().unique()))
        with col2:
            view_metric = st.selectbox("Metric", options=["Load Used", "Compliance"])
        with col3:
            week_filter = st.multiselect(
                "Weeks",
                options=sorted(log["week"].dropna().unique()),
                default=sorted(log["week"].dropna().unique())
            )

        dfe = log[(log["exercise_name"] == exercise) & (log["week"].isin(week_filter))].copy()
        dfe = dfe.sort_values("workout_date")

        if view_metric == "Load Used":
            fig = px.line(dfe, x="workout_date", y="load_used", markers=True, title=f"{exercise}: Load Used")
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("### Recent entries")
        st.dataframe(
            dfe[["workout_date","week","day","load_used","load_used_unit","reps_by_set","rir_last_set","form","pain","set_quality","compliance","reasons","notes"]],
            use_container_width=True
        )

        st.markdown("### Compliance counts")
        counts = dfe["compliance"].value_counts().reset_index()
        counts.columns = ["compliance","count"]
        fig2 = px.bar(counts, x="compliance", y="count", title="Compliance counts")
        st.plotly_chart(fig2, use_container_width=True)

if __name__ == "__main__":
    main()
