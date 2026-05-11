import re
from io import BytesIO
from datetime import datetime

import pandas as pd
import streamlit as st
import pdfplumber
from PIL import Image, ImageDraw, ImageFont


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


DATE_RE = re.compile(r"\d{2}-\d{2}-\d{4}")
ROOM_RE = re.compile(r"^\d{3,5}$")


def clean_name(value: str) -> str:
    value = value or ""
    value = value.replace("\ufffe", "-")
    value = value.replace("\n", " ")
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"^(ENBSL\d+\s*)+", "", value, flags=re.I).strip()
    return value


def parse_table_rows_with_lines(page):
    """Uses PDF column positions, so multi-line names stay in the same room row."""
    words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False)
    if not words:
        return []

    # Group words into visual text lines.
    lines = {}
    for w in words:
        top_key = round(float(w["top"]) / 3) * 3
        lines.setdefault(top_key, []).append(w)

    visual_lines = []
    for top in sorted(lines):
        ws = sorted(lines[top], key=lambda x: x["x0"])
        text = " ".join(w["text"] for w in ws)
        visual_lines.append({
            "top": top,
            "text": text,
            "words": ws,
            "name": " ".join(w["text"] for w in ws if w["x0"] < 180),
            "room": " ".join(w["text"] for w in ws if 180 <= w["x0"] < 280),
            "arrival": " ".join(w["text"] for w in ws if 280 <= w["x0"] < 430),
            "departure": " ".join(w["text"] for w in ws if 430 <= w["x0"] < 570),
            "guests": " ".join(w["text"] for w in ws if w["x0"] >= 570),
        })

    rows = []
    current_name_parts = []
    current_room = None
    current_guests = None
    current_arrival = ""
    current_departure = ""
    in_table = False

    for line in visual_lines:
        text = line["text"].strip()

        if "Guest Name" in text and "Room Number" in text:
            in_table = True
            continue

        if not in_table:
            continue

        if text.startswith("Totals") or text.startswith("Summary By"):
            break

        name_part = clean_name(line["name"])
        room_text = re.sub(r"\D", "", line["room"])
        guests_text = re.sub(r"\D", "", line["guests"])

        # If this line has a room number, it starts a new row.
        if room_text and ROOM_RE.match(room_text):
            if current_room and current_name_parts:
                rows.append({
                    "Room Number": current_room,
                    "Guest Name": clean_name(" ".join(current_name_parts)),
                    "Total Guests": int(current_guests or 1),
                    "Checked In": False,
                    "Check-in Time": "",
                })

            current_name_parts = [name_part] if name_part else []
            current_room = room_text
            current_guests = guests_text or "1"
            current_arrival = line["arrival"]
            current_departure = line["departure"]
        else:
            # Continuation line for the same guest name, e.g. THOMPSON or PORTERBROOK.
            if current_room and name_part and not DATE_RE.search(text):
                current_name_parts.append(name_part)

    if current_room and current_name_parts:
        rows.append({
            "Room Number": current_room,
            "Guest Name": clean_name(" ".join(current_name_parts)),
            "Total Guests": int(current_guests or 1),
            "Checked In": False,
            "Check-in Time": "",
        })

    return rows


@st.cache_data(show_spinner=False)
def parse_breakfast_pdf(file_bytes: bytes) -> pd.DataFrame:
    all_rows = []
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            all_rows.extend(parse_table_rows_with_lines(page))

    df = pd.DataFrame(all_rows)
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


def make_report_image(df: pd.DataFrame) -> bytes:
    checked = df[df["Checked In"]]
    not_checked = df[~df["Checked In"]]

    total_guests = int(df["Total Guests"].sum())
    checked_guests = int(checked["Total Guests"].sum())
    not_checked_guests = int(not_checked["Total Guests"].sum())

    width = 1200
    row_h = 34
    max_rows = min(len(not_checked), 40)
    height = 330 + max_rows * row_h

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 42)
        header_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
        body_font = ImageFont.truetype("DejaVuSans.ttf", 24)
        small_font = ImageFont.truetype("DejaVuSans.ttf", 20)
    except Exception:
        title_font = header_font = body_font = small_font = None

    y = 35
    draw.text((40, y), "Breakfast Check-in Report", fill="black", font=title_font)
    y += 70
    draw.text((40, y), f"Generated: {datetime.now().strftime('%d-%m-%Y %H:%M')}", fill="black", font=small_font)

    y += 55
    cards = [
        ("Total guests", total_guests),
        ("Guests checked in", checked_guests),
        ("Guests not checked in", not_checked_guests),
    ]
    x = 40
    for label, value in cards:
        draw.rounded_rectangle((x, y, x + 340, y + 105), radius=18, outline="#cbd5e1", width=2)
        draw.text((x + 22, y + 18), label, fill="#334155", font=small_font)
        draw.text((x + 22, y + 50), str(value), fill="black", font=header_font)
        x += 375

    y += 150
    draw.text((40, y), "Not checked in", fill="black", font=header_font)
    y += 45
    draw.text((40, y), "Room", fill="#334155", font=body_font)
    draw.text((170, y), "Guest Name", fill="#334155", font=body_font)
    draw.text((930, y), "Guests", fill="#334155", font=body_font)
    y += 35
    draw.line((40, y, 1120, y), fill="#cbd5e1", width=2)
    y += 12

    for _, row in not_checked.head(max_rows).iterrows():
        draw.text((40, y), str(row["Room Number"]), fill="black", font=small_font)
        draw.text((170, y), str(row["Guest Name"])[:60], fill="black", font=small_font)
        draw.text((930, y), str(int(row["Total Guests"])), fill="black", font=small_font)
        y += row_h

    if len(not_checked) > max_rows:
        y += 10
        draw.text((40, y), f"...and {len(not_checked) - max_rows} more rooms not checked in", fill="#334155", font=small_font)

    output = BytesIO()
    img.save(output, format="PNG")
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
    st.error("No guest rows were found. Check the PDF format.")
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
image_data = make_report_image(df)

if st.session_state.breakfast_ended:
    st.success("Breakfast ended. Download the final report below.")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "⬇️ Download final Excel report",
            data=excel_data,
            file_name=f"breakfast_checkin_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "⬇️ Download report image",
            data=image_data,
            file_name=f"breakfast_checkin_report_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
            mime="image/png",
            use_container_width=True,
        )

d1, d2, d3, d4 = st.columns([1, 1, 1, 1])
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
    st.download_button(
        "Download image report",
        data=image_data,
        file_name="breakfast_checkin_report.png",
        mime="image/png",
        use_container_width=True,
    )
with d4:
    st.button("Start new breakfast list", use_container_width=True, on_click=start_new_list)
