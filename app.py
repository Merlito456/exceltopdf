"""
Streamlit: XLSX → JPG pages → PDF
"""
from __future__ import annotations

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st
from PIL import Image

from converter import ConversionError, convert_xlsx_to_pdf_via_jpg

# ------------------------------------------------------------------ #
# Page config
# ------------------------------------------------------------------ #
st.set_page_config(
    page_title="Excel → JPG → PDF",
    page_icon="🖼️",
    layout="centered",
)

# ------------------------------------------------------------------ #
# Session state
# ------------------------------------------------------------------ #
if "step" not in st.session_state:
    st.session_state.step = "upload"           # upload | converting | download
if "results" not in st.session_state:
    st.session_state.results = {}              # name -> {"pdf": bytes, "jpgs": [bytes]}
if "errors" not in st.session_state:
    st.session_state.errors = {}

# ------------------------------------------------------------------ #
# Sidebar: output quality knobs
# ------------------------------------------------------------------ #
with st.sidebar:
    st.header("🖼️ Image settings")
    dpi = st.select_slider(
        "Resolution (DPI)",
        options=[72, 100, 150, 200, 300],
        value=150,
        help="Higher = sharper images, larger files. 150 DPI is print-quality.",
    )
    jpeg_quality = st.slider(
        "JPEG quality",
        min_value=50,
        max_value=100,
        value=90,
        step=5,
        help="Higher = better visuals, larger files.",
    )
    timeout = st.slider(
        "Timeout per file (seconds)",
        min_value=30, max_value=300, value=120, step=30,
    )
    st.divider()
    st.caption(
        "**Pipeline:** XLSX → PDF → JPG per page → final PDF. "
        "Rasterizing freezes layout so charts, images, and fonts "
        "render exactly as Excel shows them."
    )

# ------------------------------------------------------------------ #
# Header
# ------------------------------------------------------------------ #
st.title("🖼️ Excel → JPG → PDF")
st.write(
    "Upload Excel files. Each sheet is rendered as a JPG image, then "
    "wrapped in a PDF — perfect for template-style reports where "
    "layout matters more than selectable text."
)

# ================================================================== #
# STEP 1: UPLOAD
# ================================================================== #
if st.session_state.step == "upload":
    uploaded = st.file_uploader(
        "Drag and drop Excel files here",
        type=["xlsx", "xlsm", "xls"],
        accept_multiple_files=True,
    )

    if uploaded:
        total_mb = sum(f.size for f in uploaded) / (1024 * 1024)
        st.info(f"{len(uploaded)} file(s) • {total_mb:.1f} MB total")

        if st.button("🚀 Convert", type="primary", use_container_width=True):
            st.session_state.step = "converting"
            st.session_state._payloads = [(f.name, f.getvalue()) for f in uploaded]
            st.rerun()

# ================================================================== #
# STEP 2: CONVERTING
# ================================================================== #
elif st.session_state.step == "converting":
    payloads = st.session_state.get("_payloads", [])
    total = len(payloads)

    progress = st.progress(0.0, text="Starting…")
    detail = st.empty()

    def _job(item):
        name, data = item
        pdf_bytes, jpgs = convert_xlsx_to_pdf_via_jpg(
            data, name, dpi=dpi, jpeg_quality=jpeg_quality, timeout=timeout
        )
        return name, {"pdf": pdf_bytes, "jpgs": jpgs}

    results = {}
    errors = {}

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(_job, p): p[0] for p in payloads}
        for i, fut in enumerate(as_completed(futures), 1):
            name = futures[fut]
            detail.write(f"Processing **{name}**…")
            try:
                _, payload = fut.result()
                results[name] = payload
            except ConversionError as e:
                errors[name] = str(e)
            except Exception as e:
                errors[name] = f"Unexpected error: {e}"
            progress.progress(i / total, text=f"Converted {i}/{total}")

    st.session_state.results = results
    st.session_state.errors = errors
    st.session_state.step = "download"
    st.rerun()

# ================================================================== #
# STEP 3: DOWNLOAD
# ================================================================== #
elif st.session_state.step == "download":
    results = st.session_state.results
    errors = st.session_state.errors

    st.subheader(f"✅ {len(results)} file(s) converted")
    if errors:
        with st.expander(f"⚠️ {len(errors)} failed", expanded=True):
            for name, err in errors.items():
                st.error(f"**{name}** — {err}")

    # ----- Per-file display + downloads ----- #
    for name, payload in results.items():
        stem = name.rsplit(".", 1)[0]
        pdf_bytes = payload["pdf"]
        jpgs = payload["jpgs"]

        with st.expander(
            f"📄 **{stem}.pdf** — {len(jpgs)} page(s) · {len(pdf_bytes)/1024:.0f} KB",
            expanded=False,
        ):
            # Preview thumbnails
            st.caption("Page previews")
            cols = st.columns(min(len(jpgs), 4))
            for idx, jpg_bytes in enumerate(jpgs):
                with cols[idx % len(cols)]:
                    st.image(
                        Image.open(io.BytesIO(jpg_bytes)),
                        caption=f"Page {idx + 1}",
                        use_container_width=True,
                    )

            # Download buttons
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "⬇️ Download PDF",
                    data=pdf_bytes,
                    file_name=f"{stem}.pdf",
                    mime="application/pdf",
                    key=f"pdf_{name}",
                    use_container_width=True,
                    type="primary",
                )
            with c2:
                # Bundle that file's JPGs into a zip
                zbuf = io.BytesIO()
                with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for i, jpg_bytes in enumerate(jpgs, 1):
                        zf.writestr(f"{stem}_page_{i}.jpg", jpg_bytes)
                st.download_button(
                    f"⬇️ Download {len(jpgs)} JPG(s)",
                    data=zbuf.getvalue(),
                    file_name=f"{stem}_jpgs.zip",
                    mime="application/zip",
                    key=f"jpg_{name}",
                    use_container_width=True,
                )

    # ----- Bulk ZIP ----- #
    if len(results) > 1:
        st.divider()
        st.markdown("### 📦 Download everything")

        c1, c2 = st.columns(2)

        # All PDFs
        pdf_zip = io.BytesIO()
        with zipfile.ZipFile(pdf_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, payload in results.items():
                zf.writestr(f"{name.rsplit('.', 1)[0]}.pdf", payload["pdf"])
        with c1:
            st.download_button(
                f"📦 All PDFs ({len(results)})",
                data=pdf_zip.getvalue(),
                file_name="all_pdfs.zip",
                mime="application/zip",
                use_container_width=True,
                type="primary",
            )

        # All JPGs
        jpg_zip = io.BytesIO()
        with zipfile.ZipFile(jpg_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, payload in results.items():
                stem = name.rsplit(".", 1)[0]
                for i, jpg_bytes in enumerate(payload["jpgs"], 1):
                    zf.writestr(f"{stem}_page_{i}.jpg", jpg_bytes)
        with c2:
            st.download_button(
                f"🖼️ All JPGs ({sum(len(p['jpgs']) for p in results.values())})",
                data=jpg_zip.getvalue(),
                file_name="all_jpgs.zip",
                mime="application/zip",
                use_container_width=True,
            )

    # ----- Reset ----- #
    if st.button("🔄 Convert more files"):
        st.session_state.step = "upload"
        st.session_state.results = {}
        st.session_state.errors = {}
        st.session_state.pop("_payloads", None)
        st.rerun()

# ------------------------------------------------------------------ #
# Footer
# ------------------------------------------------------------------ #
st.divider()
st.caption(
    "Pipeline: **XLSX → PDF → JPG → PDF**. "
    "Every page is rasterized, so the final PDF looks exactly like "
    "the source — no font substitutions, no broken formulas."
)
