"""
XLSX → JPG pages → PDF pipeline.
Each Excel sheet is rendered as an image, then wrapped in a PDF.
This freezes the visual output — no formula recalculation, no font issues.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image


class ConversionError(RuntimeError):
    pass


# ------------------------------------------------------------------ #
# Binary discovery
# ------------------------------------------------------------------ #
def _find_soffice() -> str:
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise ConversionError(
        "LibreOffice not found. Add 'libreoffice' to packages.txt on Streamlit Cloud."
    )


def _find_pdftoppm() -> str:
    p = shutil.which("pdftoppm")
    if not p:
        raise ConversionError(
            "pdftoppm not found. Add 'poppler-utils' to packages.txt."
        )
    return p


SOFFICE = _find_soffice()
PDFTOPPM = _find_pdftoppm()


# ------------------------------------------------------------------ #
# Step 1: XLSX → intermediate PDF (LibreOffice headless)
# ------------------------------------------------------------------ #
def _disable_recalculation(profile_dir: Path) -> None:
    """Tell LibreOffice to trust the cached formula values in the file."""
    user_dir = profile_dir / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "registrymodifications.xcu").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry">\n'
        '  <item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
        '<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>2</value></prop></item>\n'
        '  <item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
        '<prop oor:name="ODFRecalcMode" oor:op="fuse"><value>2</value></prop></item>\n'
        '  <item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
        '<prop oor:name="HardRecalcState" oor:op="fuse"><value>2</value></prop></item>\n'
        '</oor:items>\n',
        encoding="utf-8",
    )


def _xlsx_to_pdf_bytes(
    xlsx_bytes: bytes,
    filename: str,
    workdir: Path,
    timeout: int = 120,
) -> bytes:
    stem = Path(filename).stem or "workbook"
    suffix = Path(filename).suffix.lower() or ".xlsx"

    src = workdir / f"{stem}{suffix}"
    src.write_bytes(xlsx_bytes)

    out_dir = workdir / "pdf_out"
    out_dir.mkdir(exist_ok=True)

    profile_dir = workdir / "lo_profile"
    profile_dir.mkdir(exist_ok=True)
    _disable_recalculation(profile_dir)

    # Filter options: one sheet per page, no forced scaling surprises
    pdf_filter = (
        "pdf:calc_pdf_Export:"
        "{"
        '"SinglePageSheets":{"type":"boolean","value":"false"},'
        '"EmbedStandardFonts":{"type":"boolean","value":"true"},'
        '"SelectPdfVersion":{"type":"long","value":"0"},'
        '"UseTaggedPDF":{"type":"boolean","value":"true"}'
        "}"
    )

    cmd = [
        SOFFICE,
        "--headless",
        "--norestore",
        "--invisible",
        "--nologo",
        "--nolockcheck",
        "--nodefault",
        "--nofirststartwizard",
        f"-env:UserInstallation=file://{profile_dir}",
        "--convert-to",
        pdf_filter,
        "--outdir",
        str(out_dir),
        str(src),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as e:
        raise ConversionError(f"LibreOffice timed out after {timeout}s.") from e

    produced = out_dir / f"{stem}.pdf"
    if result.returncode != 0 or not produced.exists():
        err = (result.stderr or result.stdout or "").strip()
        raise ConversionError(f"LibreOffice failed: {err[:400]}")

    return produced.read_bytes()


# ------------------------------------------------------------------ #
# Step 2: PDF → JPG images (pdftoppm)
# ------------------------------------------------------------------ #
def _pdf_to_jpgs(
    pdf_bytes: bytes,
    workdir: Path,
    dpi: int = 150,
    jpeg_quality: int = 90,
) -> list[bytes]:
    src = workdir / "intermediate.pdf"
    src.write_bytes(pdf_bytes)

    out_prefix = workdir / "page"
    cmd = [
        PDFTOPPM,
        "-jpeg",
        "-r", str(dpi),
        "-jpegopt", f"quality={jpeg_quality}",
        str(src),
        str(out_prefix),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, check=False
        )
    except subprocess.TimeoutExpired as e:
        raise ConversionError("pdftoppm timed out.") from e

    if result.returncode != 0:
        raise ConversionError(f"pdftoppm failed: {result.stderr[:400]}")

    pages = sorted(workdir.glob("page-*.jpg"))
    if not pages:
        # Single-page PDFs sometimes produce "page.jpg" without a number
        single = workdir / "page.jpg"
        if single.exists():
            pages = [single]

    if not pages:
        raise ConversionError("No JPG pages were produced.")

    return [p.read_bytes() for p in pages]


# ------------------------------------------------------------------ #
# Step 3: JPGs → final PDF (Pillow)
# ------------------------------------------------------------------ #
def _jpgs_to_pdf(
    jpg_bytes_list: list[bytes],
    dpi: int = 150,
) -> bytes:
    images = []
    try:
        for jpg_bytes in jpg_bytes_list:
            img = Image.open(io.BytesIO(jpg_bytes))
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            images.append(img)

        if not images:
            raise ConversionError("No images to assemble.")

        out = io.BytesIO()
        # resolution= sets the PDF's DPI metadata so pages print at the
        # correct physical size.
        images[0].save(
            out,
            format="PDF",
            save_all=True,
            append_images=images[1:],
            resolution=dpi,
            quality=90,
        )
        return out.getvalue()
    finally:
        for img in images:
            img.close()


# ------------------------------------------------------------------ #
# Public API
# ------------------------------------------------------------------ #
def convert_xlsx_to_pdf_via_jpg(
    xlsx_bytes: bytes,
    filename: str,
    dpi: int = 150,
    jpeg_quality: int = 90,
    timeout: int = 120,
) -> tuple[bytes, list[bytes]]:
    """
    Full pipeline: XLSX → PDF → JPGs → PDF.

    Returns:
        (final_pdf_bytes, list_of_jpg_page_bytes)
    """
    with tempfile.TemporaryDirectory(prefix="xlsx2jpg2pdf_") as tmp:
        workdir = Path(tmp)

        # Step 1
        intermediate_pdf = _xlsx_to_pdf_bytes(
            xlsx_bytes, filename, workdir, timeout=timeout
        )

        # Step 2
        jpg_pages = _pdf_to_jpgs(
            intermediate_pdf, workdir, dpi=dpi, jpeg_quality=jpeg_quality
        )

        # Step 3
        final_pdf = _jpgs_to_pdf(jpg_pages, dpi=dpi)

        return final_pdf, jpg_pages
