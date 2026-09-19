"""
Streamlit XLSX → PDF Converter
Powered by LibreOffice headless mode.
"""
from __future__ import annotations

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st

from converter import ConversionError, convert_xlsx_to_pdf

# ------------------------------------------------------------------ #
# Page config
# ------------------------------------------------------------------ #
st.set_page_config(
    page_title="XLSX → PDF Converter",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------ #
# Session state
# ------------------------------------------------------------------ #
if "results" not in st.session_state:
    st.session_state.results = {}   # name -> bytes (success)
if "errors" not in st.session_state:
    st.session_state.errors = {}    # name -> error message

# ------------------------------------------------------------------ #
# Sidebar
# ------------------------------------------------------------------ #
with st.sidebar:
    st.header("⚙️ Settings")
    max_workers = st.slider(
        "Parallel conversions",
        min_value=1,
        max_value=4,
        value=2,
        help="Higher = faster for many files, but heavier on CPU.",
    )
    timeout = st.slider(
        "Timeout per file (seconds)",
        min_value=30,
        max_value=300,
        value=120,
        step=30,
    )
    st.divider()
    st.caption(
        "Conversion is done by **LibreOffice** in headless mode — "
        "charts, conditional formatting, and formulas are preserved."
    )

# ------------------------------------------------------------------ #
# Header
# ------------------------------------------------------------------ #
st.title("📄 XLSX → PDF Converter")
st.write(
    "Upload one or more Excel files and download them as PDFs. "
    "Formatting, charts, and formulas are preserved."
)

# ------------------------------------------------------------------ #
# Uploader
# ------------------------------------------------------------------ #
uploaded_files = st.file_uploader(
    "Drop your Excel files here",
    type=["xlsx", "xlsm", "xls"],
    accept_multiple_files=True,
    help="Supported: .xlsx, .xlsm, .xls",
)

# ------------------------------------------------------------------ #
# Convert button
# ------------------------------------------------------------------ #
if uploaded_files:
    st.success(f"Loaded {len(uploaded_files)} file(s).")

    if st.button("🚀 Convert to PDF", type="primary", use_container_width=True):
        st.session_state.results = {}
        st.session_state.errors = {}

        progress = st.progress(0, text="Starting…")
        status = st.empty()

        total = len(uploaded_files)
        completed = 0

        # Read everything into memory once
        payloads = []
        for uf in uploaded_files:
            try:
                data = uf.getvalue()
                payloads.append((uf.name, data))
            except Exception as e:
                st.session_state.errors[uf.name] = f"Read error: {e}"

        def _job(item):
            name, data = item
            return name, convert_xlsx_to_pdf(data, name, timeout=timeout)

        # LibreOffice is CPU-heavy; keep threads modest
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_job, p): p[0] for p in payloads}
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    _, pdf_bytes = fut.result()
                    st.session_state.results[name] = pdf_bytes
                except ConversionError as e:
                    st.session_state.errors[name] = str(e)
                except Exception as e:
                    st.session_state.errors[name] = f"Unexpected error: {e}"
                completed += 1
                progress.progress(
                    completed / total,
                    text=f"Converted {completed}/{total} — {name}",
                )

        progress.empty()
        status.empty()
        st.rerun()

# ------------------------------------------------------------------ #
# Results
# ------------------------------------------------------------------ #
if st.session_state.results or st.session_state.errors:
    st.divider()
    st.subheader("📊 Results")

    ok_count = len(st.session_state.results)
    err_count = len(st.session_state.errors)
    c1, c2 = st.columns(2)
    c1.metric("✅ Converted", ok_count)
    c2.metric("❌ Failed", err_count)

    # ----- Successes ----- #
    if st.session_state.results:
        st.markdown("### ✅ Successful conversions")

        for name, pdf_bytes in st.session_state.results.items():
            pdf_name = f"{name.rsplit('.', 1)[0]}.pdf"
            col1, col2 = st.columns([4, 1])
            with col1:
                st.write(f"**{name}** → `{pdf_name}` ({len(pdf_bytes)/1024:.1f} KB)")
            with col2:
                st.download_button(
                    "⬇️ PDF",
                    data=pdf_bytes,
                    file_name=pdf_name,
                    mime="application/pdf",
                    key=f"dl_{name}",
                    use_container_width=True,
                )

        # ----- Bulk ZIP download ----- #
        if ok_count > 1:
            st.markdown("### 📦 Download all")
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, pdf_bytes in st.session_state.results.items():
                    pdf_name = f"{name.rsplit('.', 1)[0]}.pdf"
                    zf.writestr(pdf_name, pdf_bytes)
            zip_buffer.seek(0)

            st.download_button(
                f"⬇️ Download all {ok_count} PDFs as ZIP",
                data=zip_buffer.getvalue(),
                file_name="converted_pdfs.zip",
                mime="application/zip",
                use_container_width=True,
                type="primary",
            )

    # ----- Errors ----- #
    if st.session_state.errors:
        st.markdown("### ❌ Failed conversions")
        with st.expander("Show errors", expanded=True):
            for name, err in st.session_state.errors.items():
                st.error(f"**{name}** — {err}")

    # ----- Clear ----- #
    if st.button("🗑️ Clear results"):
        st.session_state.results = {}
        st.session_state.errors = {}
        st.rerun()

# ------------------------------------------------------------------ #
# Footer
# ------------------------------------------------------------------ #
st.divider()
st.caption(
    "Built with Streamlit + LibreOffice · "
    "Files are processed in an isolated temp directory and deleted immediately."
)
