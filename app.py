import re
from io import BytesIO
from datetime import datetime

import pandas as pd
import streamlit as st
import pdfplumber


st.set_page_config(
    page_title="Breakfast Check-in",
    page_icon="🍳",
    layout="centered"
)


ROOM_ROW_WITH_NAME = re.compile(
    r"^(?P<name>.*?)\s+(?P<room>\d{3,5})\s+"
    r"(?P<arr>\d{2}-\d{2}-\d{4})\s+"
    r"(?P<dep>\d{2}-\d{2}-\d{4})\s+"
    r"(?P<guests>\d+)$"
)

ROOM_ROW_NO_NAME = re.compile(
    r"^(?P<room>\d{3,5})\s+"
    r"(?P<arr>\d{2}-\d{2}-\d{4})\s+"
    r"(?P<dep>\d{2}-\d{2}-\d{4})\s+"
    r"(?P<guests>\d+)$"
)

IGNORE_STARTS = (
    "Guest Name",
    "Breakfast And Packages",
    "Bristol Grand Hotel",
    "Date Range",
    "Report Run",
    "User:",
    "Summary By",
    "Date Day",
    "Package",
    "Totals",
)


def clean_name(name: str) -> str:
    name = name.replace("\ufffe", "-")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def should_ignore(line: str) -> bool:
    line = line.strip()
    if not line:
        return True
    return any(line.startswith(x) for x in IGNORE_STARTS)


def parse_breakfast_pdf(file) -> pd.DataFrame:
    rows = []
    name_buffer = []

    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if should_ignore(line):
                    continue

                match = ROOM_ROW_WITH_NAME.match(line)
                if match:
                    inline_name = match.group("name").strip()
                    full_name = clean_name(" ".join(name_buffer + [inline_name]))
                    rows.append({
                        "Room Number": str(match.group("room")),
                        "Guest Name": full_name,
                        "Arrival Date": match.group("arr"),
                        "Departure Date": match.group("dep"),
                        "Total Guests": int(match.group("guests")),
                    })
                    name_buffer = []
                    continue

                match = ROOM_ROW_NO_NAME.match(line)
                if match and name_buffer:
                    full_name = clean_name(" ".join(name_buffer))
                    rows.append({
                        "Room Number": str(match.group("room")),
                        "Guest Name": full_name,
                        "Arrival Date": match.group("arr"),
                        "Departure Date": match.group("dep"),
                        "Total Guests": int(match.group("guests")),
                    })
                    name_buffer = []
                    continue

                # Likely part of a multi-line guest name.
                if not re.search(r"\d{2}-\d{2}-\d{4}", line):
                    name_buffer.append(line)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    df = df.drop_duplicates(subset=["Room Number"], keep="first")
    df["Checked In"] = False
    df["Check-in Time"] = ""
    return df.sort_values("Room Number").reset_index(drop=True)


def make_excel_report(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        checked = df[df["Checked In"]].copy()
        not_checked = df[~df["Checked In"]].copy()

        summary = pd.DataFrame({
            "Metric": [
                "Total rooms",
                "Rooms checked in",
                "Rooms not checked in",
                "Total guests",
                "Guests checked in",
                "Guests not checked in",
            ],
            "Value": [
                len(df),
                len(checked),
                len(not_checked),
                int(df["Total Guests"].sum()),
                int(checked["Total Guests"].sum()),
                int(not_checked["Total Guests"].sum()),
            ]
        })

        summary.to_excel(writer, index=False, sheet_name="Summary")
        checked.to_excel(writer, index=False, sheet_name="Checked In")
        not_checked.to_excel(writer, index=False, sheet_name="Not Checked In")
        df.to_excel(writer, index=False, sheet_name="Full List")

    return output.getvalue()


def reset_search_box():
    st.session_state.room_search = ""


if "guest_df" not in st.session_state:
    st.session_state.guest_df = None

if "last_checked_room" not in st.session_state:
    st.session_state.last_checked_room = ""


st.title("🍳 Breakfast Check-in")
st.caption("Upload the breakfast PDF once, then search rooms and mark guests as checked in.")

uploaded_pdf = st.file_uploader("Upload breakfast PDF", type=["pdf"])

if uploaded_pdf is not None and st.session_state.guest_df is None:
    with st.spinner("Reading breakfast list..."):
        st.session_state.guest_df = parse_breakfast_pdf(uploaded_pdf)

if st.session_state.guest_df is None:
    st.info("Upload the PDF to start.")
    st.stop()

df = st.session_state.guest_df

if df.empty:
    st.error("No guest rows were found. Try another PDF or check the format.")
    st.stop()

total_rooms = len(df)
checked_rooms = int(df["Checked In"].sum())
total_guests = int(df["Total Guests"].sum())
checked_guests = int(df.loc[df["Checked In"], "Total Guests"].sum())

a, b, c = st.columns(3)
a.metric("Rooms checked", f"{checked_rooms}/{total_rooms}")
b.metric("Guests checked", f"{checked_guests}/{total_guests}")
c.metric("Remaining rooms", total_rooms - checked_rooms)

st.divider()

room = st.text_input(
    "Enter room number",
    key="room_search",
    placeholder="Example: 106",
)

room = room.strip()

if room:
    result = df[df["Room Number"] == room]

    if result.empty:
        st.warning(f"Room {room} was not found in this breakfast list.")
    else:
        row = result.iloc[0]
        idx = result.index[0]

        status = "✅ Already checked in" if row["Checked In"] else "Not checked in yet"

        st.subheader(f"Room {row['Room Number']}")
        st.write(f"**Guest name:** {row['Guest Name']}")
        st.write(f"**Total guests:** {row['Total Guests']}")
        st.write(f"**Arrival:** {row['Arrival Date']}")
        st.write(f"**Departure:** {row['Departure Date']}")
        st.write(f"**Status:** {status}")

        if not row["Checked In"]:
            if st.button("✅ Check in this room", type="primary"):
                now = datetime.now().strftime("%H:%M:%S")
                st.session_state.guest_df.loc[idx, "Checked In"] = True
                st.session_state.guest_df.loc[idx, "Check-in Time"] = now
                st.session_state.last_checked_room = room
                reset_search_box()
                st.rerun()
        else:
            if st.button("Undo check-in"):
                st.session_state.guest_df.loc[idx, "Checked In"] = False
                st.session_state.guest_df.loc[idx, "Check-in Time"] = ""
                reset_search_box()
                st.rerun()

if st.session_state.last_checked_room:
    st.success(f"Last checked in: room {st.session_state.last_checked_room}")

st.divider()

with st.expander("View full list"):
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

st.subheader("End of breakfast report")

checked = df[df["Checked In"]]
not_checked = df[~df["Checked In"]]

st.write(f"**Checked-in rooms:** {len(checked)}")
st.write(f"**Not checked-in rooms:** {len(not_checked)}")
st.write(f"**Checked-in guests:** {int(checked['Total Guests'].sum())}")
st.write(f"**Not checked-in guests:** {int(not_checked['Total Guests'].sum())}")

csv_data = df.to_csv(index=False).encode("utf-8")
excel_data = make_excel_report(df)

st.download_button(
    "Download CSV report",
    data=csv_data,
    file_name="breakfast_checkin_report.csv",
    mime="text/csv"
)

st.download_button(
    "Download Excel report",
    data=excel_data,
    file_name="breakfast_checkin_report.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

st.divider()

if st.button("Start new breakfast list"):
    st.session_state.guest_df = None
    st.session_state.last_checked_room = ""
    reset_search_box()
    st.rerun()
