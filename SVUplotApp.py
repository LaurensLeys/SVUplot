import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import plotly.graph_objects as go
import io
from PIL import Image
from pandas.errors import EmptyDataError

st.set_page_config(layout="wide", page_title="Rheavita Signal Viewer")

# Logo
logo = Image.open("Rheavita_logo.png")
st.image(logo, width=200)

st.title("📈 Rheavita Signal Viewer (Multi-file Comparison)")

# Upload multiple CSV files
uploaded_files = st.file_uploader(
    "Upload one or more semicolon-separated CSV files",
    type=["csv"],
    accept_multiple_files=True
)

@st.cache_data
def load_data(file_bytes, file_name):
    if not file_bytes or len(file_bytes) == 0:
        raise ValueError(f"{file_name} is empty.")

    try:
        df = pd.read_csv(io.BytesIO(file_bytes), sep=";")
    except EmptyDataError:
        raise ValueError(f"{file_name} contains no readable CSV data.")
    except Exception as e:
        raise ValueError(f"Could not read {file_name}: {e}")

    required_cols = {"Timestamp", "Name", "Value"}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise ValueError(
            f"{file_name} is missing required column(s): {', '.join(sorted(missing_cols))}"
        )

    if df.empty:
        raise ValueError(f"{file_name} has headers but no data rows.")

    return df

def process_time(df_subset, ref_time, offset=0.0):
    return [
        ((datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f") - ref_time).total_seconds() / 3600) + offset
        for ts in df_subset["Timestamp"]
    ]

if uploaded_files:
    st.success(f"✅ {len(uploaded_files)} file(s) uploaded.")

    all_data = []
    valid_files = []

    # Read all files once into bytes, then parse safely
    for file in uploaded_files:
        try:
            file_bytes = file.getvalue()
            df = load_data(file_bytes, file.name)
            valid_files.append((file.name, df))
        except ValueError as e:
            st.warning(str(e))

    if not valid_files:
        st.error("No valid CSV files could be loaded.")
        st.stop()

    all_data = []

    # Display signal options from first valid file
    first_df = valid_files[0][1]
    available_signals = first_df["Name"].dropna().unique().tolist()

    with st.sidebar:
        st.markdown("### 🔧 Global Plot Settings")
        x_min = st.slider("X Min (hours)", 0.0, 4.0, 0.0, 0.05)
        x_max = st.slider("X Max (hours)", 0.0, 4.0, 4.0, 0.05)
        selected_signals = st.multiselect(
            "Select signals to plot",
            options=available_signals,
            default=["Vial temperature"] if "Vial temperature" in available_signals else available_signals[:1]
        )
        filename = st.text_input("Export filename (no extension)", value="rheavita_signals")

    file_offsets = {}
    for i, (file_name, df) in enumerate(valid_files):
        with st.sidebar:
            offset = st.slider(f"⏱ Offset for File {i+1} ({file_name})", -2.0, 2.0, 0.0, 0.01)
            file_offsets[file_name] = offset

        try:
            ref_time = datetime.strptime(df["Timestamp"].iloc[0], "%Y-%m-%d %H:%M:%S.%f")
        except Exception:
            st.warning(f"{file_name}: first Timestamp is not in expected format '%Y-%m-%d %H:%M:%S.%f'")
            continue

        all_data.append((file_name, df, ref_time))

    if not all_data:
        st.error("No files contained usable timestamp data.")
        st.stop()

    # Prepare plots per signal
    plots = {signal: go.Figure() for signal in selected_signals}

    for file_name, df, ref_time in all_data:
        offset = file_offsets[file_name]
        for signal in selected_signals:
            df_signal = df[df["Name"].astype(str).str.contains(signal, na=False)].copy()
            if df_signal.empty:
                continue

            try:
                df_signal["Time (hours)"] = process_time(df_signal, ref_time, offset)
            except Exception:
                st.warning(f"Could not process timestamps for signal '{signal}' in {file_name}")
                continue

            df_signal = df_signal[
                (df_signal["Time (hours)"] >= x_min) & (df_signal["Time (hours)"] <= x_max)
            ]

            if not df_signal.empty:
                plots[signal].add_trace(go.Scatter(
                    x=df_signal["Time (hours)"],
                    y=df_signal["Value"],
                    mode="lines",
                    name=f"{signal} ({file_name})"
                ))

    # Display plots
    for signal, fig in plots.items():
        fig.update_layout(
            title=signal,
            xaxis_title="Time (hours)",
            yaxis_title="Vial Temperature (K)",
            template="plotly_dark",
            height=300,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Export button
    export_btn = st.button("📤 Export selected signals to Excel")

    if export_btn:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            for signal in selected_signals:
                signal_df = pd.DataFrame()

                for file_name, df, ref_time in all_data:
                    offset = file_offsets[file_name]
                    df_signal = df[df["Name"].astype(str).str.contains(signal, na=False)].copy()
                    if df_signal.empty:
                        continue

                    try:
                        df_signal["Time (hours)"] = process_time(df_signal, ref_time, offset)
                    except Exception:
                        continue

                    df_signal = df_signal[
                        (df_signal["Time (hours)"] >= x_min) & (df_signal["Time (hours)"] <= x_max)
                    ]

                    if not df_signal.empty:
                        safe_name = file_name.rsplit(".", 1)[0][:10]
                        time_col = f"Time_{safe_name}"
                        value_col = f"Value_{safe_name}"
                        partial = df_signal[["Time (hours)", "Value"]].copy()
                        partial.columns = [time_col, value_col]

                        if signal_df.empty:
                            signal_df = partial.reset_index(drop=True)
                        else:
                            signal_df = pd.concat(
                                [signal_df.reset_index(drop=True), partial.reset_index(drop=True)],
                                axis=1
                            )

                if not signal_df.empty:
                    sheet_name = signal[:31] if signal else "Sheet1"
                    signal_df.to_excel(writer, sheet_name=sheet_name, index=False)

        output.seek(0)

        st.download_button(
            label="📥 Download Excel file",
            data=output.getvalue(),
            file_name=f"{filename}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

else:
    st.info("Upload one or more CSV files to get started.")
