"""
XLSX → JPG pages → PDF pipeline.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


class ConversionError(RuntimeError):
    pass


def _find_soffice() -> str:
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/usr/local/bin/soffice",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise ConversionError(
        "LibreOffice not found. Add 'libreoffice' to packages.txt."
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


def _disable_recalculation(profile_dir: Path) -> None:
    user_dir = profile_dir / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "registrymodifications.xcu").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry">\n'
        '  <item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
        '<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>2</value></prop></item>\n'
        '  <item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
        '<prop oor:name="ODFRecalcMode" oor:op="fuse"><value>2</value></prop></item>\n'
        '</oor:items>\n',
        encoding="utf-8",
    )


def _xlsx_to_pdf_bytes(xlsx_bytes, filename, workdir, timeout=120):
    stem = Path(filename).stem or "workbook"
    suffix = Path(filename).suffix.lower() or ".xlsx"

    src = workdir / f"{stem}{suffix}"
    src.write_bytes(xlsx_bytes)

    out_dir = workdir / "pdf_out"
    out_dir.mkdir(exist_ok=True)

    profile_dir = workdir / "lo_profile"
    profile_dir.mkdir(exist_ok=True)
    _disable_recalculation(profile_dir)

    pdf_filter = (
        "pdf:calc_pdf_Export:"
        "{"
        '"SinglePageSheets":{"type":"boolean","value":"false"},'
        '"EmbedStandardFonts":{"type":"boolean","value":"true"}'
        "}"
    )

    cmd = [
        SOFFICE, "--headless", "--norestore", "--invisible",
        "--nologo", "--nolockcheck", "--nodefault", "--nofirststartwizard",
        f"-env:UserInstallation=file://{profile_dir}",
        "--convert-to", pdf_filter,
        "--outdir", str(out_dir),
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


def _pdf_to_jpgs(pdf_bytes, workdir, dpi=150, jpeg_quality=90):
    src = workdir / "intermediate.pdf"
    src.write_bytes(pdf_bytes)

    out_prefix = workdir / "page"
    cmd = [
        PDFTOPPM, "-jpeg", "-r", str(dpi),
        "-jpegopt", f"quality={jpeg_quality}",
        str(src), str(out_prefix),
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
        single = workdir / "page.jpg"
        if single.exists():
            pages = [single]
    if not pages:
        raise ConversionError("No JPG pages were produced.")

    return [p.read_bytes() for p in pages]


def _jpgs_to_pdf(jpg_bytes_list, dpi=150):
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
        images[0].save(
            out, format="PDF", save_all=True,
            append_images=images[1:],
            resolution=dpi, quality=90,
        )
        return out.getvalue()
    finally:
        for img in images:
            img.close()


def convert_xlsx_to_pdf_via_jpg(
    xlsx_bytes: bytes,
    filename: str,
    dpi: int = 150,
    jpeg_quality: int = 90,
    timeout: int = 120,
) -> tuple[bytes, list[bytes]]:
    with tempfile.TemporaryDirectory(prefix="xlsx2jpg2pdf_") as tmp:
        workdir = Path(tmp)
        intermediate_pdf = _xlsx_to_pdf_bytes(xlsx_bytes, filename, workdir, timeout)
        jpg_pages = _pdf_to_jpgs(intermediate_pdf, workdir, dpi, jpeg_quality)
        final_pdf = _jpgs_to_pdf(jpg_pages, dpi)
        return final_pdf, jpg_pages
