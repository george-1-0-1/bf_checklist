import re
from io import BytesIO
from datetime import datetime

import pandas as pd
import streamlit as st
import pdfplumber


st.set_page_config(
    page_title="Breakfast Check-in",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="collapsed",
)


CUSTOM_CSS = """
<style>
:root {
    --app-card-bg: color-mix(in srgb, var(--background-color) 92%, var(--text-color) 8%);
    --app-border: color-mix(in srgb, var(--text-color) 18%, transparent);
    --app-muted: color-mix(in srgb, var(--text-color) 68%, transparent);
    --app-shadow: rgba(0,0,0,0.10);
    --app-ok-bg: color-mix(in srgb, #22c55e 22%, var(--background-color) 78%);
    --app-ok-text: color-mix(in srgb, #22c55e 70%, var(--text-color) 30%);
    --app-wait-bg: color-mix(in srgb, #f59e0b 24%, var(--background-color) 76%);
    --app-wait-text: color-mix(in srgb, #f59e0b 70%, var(--text-color) 30%);
}
.block-container {
    max-width: 1500px;
    padding-top: 2.4rem;
    padding-left: 1.5rem;
    padding-right: 1.5rem;
}
.main-title {
    font-size: 2.15rem;
    font-weight: 800;
    margin-top: 0.8rem;
    margin-bottom: 0.25rem;
    color: var(--text-color);
}
.small-muted {
    color: var(--app-muted);
    font-size: 0.95rem;
    margin-bottom: 0.8rem;
}
.card {
    border: 1px solid var(--app-border);
    border-radius: 18px;
    padding: 18px 20px;
    background: var(--app-card-bg);
    box-shadow: 0 2px 10px var(--app-shadow);
    margin-bottom: 14px;
    color: var(--text-color);
}
.guest-name {
    font-size: 1.55rem;
    font-weight: 800;
    margin-bottom: 0.2rem;
    color: var(--text-color);
}
.room-number {
    font-size: 1.05rem;
    color: var(--app-muted);
    font-weight: 600;
}
.status-ok {
    display: inline-block;
    padding: 7px 11px;
    border-radius: 999px;
    background: var(--app-ok-bg);
    color: var(--app-ok-text);
    font-weight: 700;
}
.status-waiting {
    display: inline-block;
    padding: 7px 11px;
    border-radius: 999px;
    background: var(--app-wait-bg);
    color: var(--app-wait-text);
    font-weight: 700;
}
div[data-testid="stMetric"] {
    background: var(--app-card-bg);
    border: 1px solid var(--app-border);
    padding: 12px 14px;
    border-radius: 16px;
    box-shadow: 0 1px 8px var(--app-shadow);
}
[data-testid="stDataFrame"] {
    border-radius: 14px;
}
@media (max-width: 900px) {
    .block-container {
        padding-top: 1.8rem;
        padding-left: 0.7rem;
        padding-right: 0.7rem;
    }
    .main-title {
        font-size: 1.8rem;
        margin-top: 0.5rem;
    }
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def clean_cell(value: str) -> str:
    value = value or ""
    value = value.replace("\ufffe", "-")
    value = value.replace("\n", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value


@st.cache_data(show_spinner=False)
def parse_breakfast_pdf(file_bytes: bytes) -> pd.DataFrame:
    rows = []

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()

            for table in tables:
                for raw_row in table:
                    if not raw_row or len(raw_row) < 5:
                        continue

                    name = clean_cell(raw_row[0])
                    room = clean_cell(raw_row[1])
                    guests = clean_cell(raw_row[4])

                    # This prevents report header text such as "Report Run Date"
                    # being treated as a guest name.
                    if not re.fullmatch(r"\d{3,5}", room):
                        continue

                    if not re.fullmatch(r"\d+", guests):
                        continue

                    if not name or name.lower() == "guest name":
                        continue

                    rows.append({
                        "Room Number": room,
                        "Guest Name": name,
                        "Total Guests": int(guests),
                        "Checked In": False,
                        "Check-in Time": "",
                    })

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["Room Number"], keep="first")
    return df.sort_values("Room Number").reset_index(drop=True)


def make_excel_report(df: pd.DataFrame) -> bytes:
    output = BytesIO()

    checked = df[df["Checked In"]].copy()
    not_checked = df[~df["Checked In"]].copy()

    summary = pd.DataFrame({
        "Metric": ["Total guests", "Guests checked in", "Guests not checked in"],
        "Value": [
            int(df["Total Guests"].sum()),
            int(checked["Total Guests"].sum()),
            int(not_checked["Total Guests"].sum()),
        ],
    })

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="Summary")
        checked.to_excel(writer, index=False, sheet_name="Checked In")
        not_checked.to_excel(writer, index=False, sheet_name="Not Checked In")
        df.to_excel(writer, index=False, sheet_name="Full List")

        for sheet in writer.sheets.values():
            for column_cells in sheet.columns:
                max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
                sheet.column_dimensions[column_cells[0].column_letter].width = min(max_length + 3, 45)

    return output.getvalue()


def check_in_room(room_number: str):
    df = st.session_state.guest_df
    matches = df.index[df["Room Number"] == room_number].tolist()

    if not matches:
        return

    idx = matches[0]
    if not bool(df.loc[idx, "Checked In"]):
        st.session_state.guest_df.loc[idx, "Checked In"] = True
        st.session_state.guest_df.loc[idx, "Check-in Time"] = datetime.now().strftime("%H:%M:%S")

    st.session_state.last_checked_room = room_number
    st.session_state.selected_room = ""
    st.session_state.search_key += 1


def undo_room(room_number: str):
    df = st.session_state.guest_df
    matches = df.index[df["Room Number"] == room_number].tolist()

    if not matches:
        return

    idx = matches[0]
    st.session_state.guest_df.loc[idx, "Checked In"] = False
    st.session_state.guest_df.loc[idx, "Check-in Time"] = ""
    st.session_state.selected_room = room_number


def start_new_list():
    st.session_state.guest_df = None
    st.session_state.selected_room = ""
    st.session_state.last_checked_room = ""
    st.session_state.search_key += 1
    st.session_state.breakfast_ended = False


for key, default in {
    "guest_df": None,
    "selected_room": "",
    "last_checked_room": "",
    "search_key": 0,
    "breakfast_ended": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


st.markdown('<div class="main-title">🍳 Breakfast Check-in</div>', unsafe_allow_html=True)
st.markdown('<div class="small-muted">Upload the PDF once, search by room number, check guests in, then view or download the report.</div>', unsafe_allow_html=True)

uploaded_pdf = st.file_uploader("Upload breakfast PDF", type=["pdf"], label_visibility="collapsed")

if uploaded_pdf is not None and st.session_state.guest_df is None:
    with st.spinner("Reading breakfast list..."):
        st.session_state.guest_df = parse_breakfast_pdf(uploaded_pdf.getvalue())

if st.session_state.guest_df is None:
    st.info("Upload the breakfast PDF to start.")
    st.stop()

df = st.session_state.guest_df

if df.empty:
    st.error("No guest rows were found. This PDF format may be different from the breakfast report format.")
    st.stop()

total_rooms = len(df)
checked_rooms = int(df["Checked In"].sum())
remaining_rooms = total_rooms - checked_rooms

total_guests = int(df["Total Guests"].sum())
checked_guests = int(df.loc[df["Checked In"], "Total Guests"].sum())
remaining_guests = total_guests - checked_guests

m1, m2, m3, m4 = st.columns(4)
m1.metric("Guests checked in", f"{checked_guests}/{total_guests}")
m2.metric("Rooms checked in", f"{checked_rooms}/{total_rooms}")
m3.metric("Guests remaining", remaining_guests)
m4.metric("Rooms remaining", remaining_rooms)

if st.session_state.last_checked_room:
    st.success(f"Last checked in: room {st.session_state.last_checked_room}")

left, right = st.columns([0.95, 1.35], gap="large")

with left:
    st.markdown("### Search and check in")

    with st.form(key=f"room_form_{st.session_state.search_key}", clear_on_submit=True):
        room_input = st.text_input(
            "Enter room number",
            placeholder="Example: 106",
            label_visibility="visible",
        )
        submitted = st.form_submit_button("Find room", type="primary", use_container_width=True)

    if submitted:
        st.session_state.selected_room = room_input.strip()

    selected_room = st.session_state.selected_room.strip()

    if not selected_room:
        st.markdown(
            """
            <div class="card">
                <b>Ready for next guest.</b><br>
                Type a room number and press <b>Find room</b>.
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        result = df[df["Room Number"] == selected_room]

        if result.empty:
            st.warning(f"Room {selected_room} was not found.")
        else:
            row = result.iloc[0]
            checked_status = bool(row["Checked In"])
            status_html = (
                '<span class="status-ok">Already checked in</span>'
                if checked_status
                else '<span class="status-waiting">Not checked in yet</span>'
            )

            st.markdown(
                f"""
                <div class="card">
                    <div class="room-number">Room {row['Room Number']}</div>
                    <div class="guest-name">{row['Guest Name']}</div>
                    <p><b>Total guests:</b> {int(row['Total Guests'])}</p>
                    <p><b>Status:</b> {status_html}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if not checked_status:
                st.button(
                    "✅ Check in",
                    type="primary",
                    use_container_width=True,
                    on_click=check_in_room,
                    args=(str(row["Room Number"]),),
                )
            else:
                st.button(
                    "Undo check-in",
                    use_container_width=True,
                    on_click=undo_room,
                    args=(str(row["Room Number"]),),
                )

with right:
    st.markdown("### Live breakfast list")

    view_choice = st.radio(
        "Filter list",
        ["All", "Checked in", "Not checked in"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if view_choice == "Checked in":
        list_df = df[df["Checked In"]]
    elif view_choice == "Not checked in":
        list_df = df[~df["Checked In"]]
    else:
        list_df = df

    show_df = list_df[["Room Number", "Guest Name", "Total Guests", "Checked In", "Check-in Time"]].copy()
    show_df["Checked In"] = show_df["Checked In"].map({True: "✅", False: ""})

    st.dataframe(
        show_df,
        use_container_width=True,
        hide_index=True,
        height=430,
    )

st.divider()

st.markdown("## End of breakfast report")

summary_df = pd.DataFrame({
    "Metric": ["Total guests", "Guests checked in", "Guests not checked in"],
    "Value": [total_guests, checked_guests, remaining_guests],
})

r1, r2 = st.columns([0.7, 1.3], gap="large")

with r1:
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
    if st.button("End breakfast", type="primary", use_container_width=True):
        st.session_state.breakfast_ended = True

with r2:
    checked_report = df[df["Checked In"]][["Room Number", "Guest Name", "Total Guests", "Check-in Time"]]
    not_checked_report = df[~df["Checked In"]][["Room Number", "Guest Name", "Total Guests"]]

    tab1, tab2 = st.tabs(["Checked in", "Not checked in"])
    with tab1:
        st.dataframe(checked_report, use_container_width=True, hide_index=True, height=260)
    with tab2:
        st.dataframe(not_checked_report, use_container_width=True, hide_index=True, height=260)

excel_data = make_excel_report(df)
csv_data = df.to_csv(index=False).encode("utf-8")

if st.session_state.breakfast_ended:
    st.success("Breakfast ended. Download the final Excel report below.")
    st.download_button(
        "⬇️ Download final Excel report",
        data=excel_data,
        file_name=f"breakfast_checkin_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )

d1, d2, d3 = st.columns([1, 1, 1])
with d1:
    st.download_button(
        "Download Excel report",
        data=excel_data,
        file_name="breakfast_checkin_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
with d2:
    st.download_button(
        "Download CSV report",
        data=csv_data,
        file_name="breakfast_checkin_report.csv",
        mime="text/csv",
        use_container_width=True,
    )
with d3:
    st.button("Start new breakfast list", use_container_width=True, on_click=start_new_list)
