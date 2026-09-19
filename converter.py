"""
LibreOffice-based XLSX → PDF conversion engine.
Designed for Streamlit Community Cloud (headless, sandboxed).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


class ConversionError(RuntimeError):
    pass


def _find_soffice() -> str:
    """Locate the LibreOffice binary across common install paths."""
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/usr/local/bin/soffice",
        "/opt/libreoffice/program/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise ConversionError(
        "LibreOffice not found. On Streamlit Cloud, add 'libreoffice' to "
        "packages.txt. Locally, install LibreOffice."
    )


SOFFICE = _find_soffice()


def convert_xlsx_to_pdf(
    input_bytes: bytes,
    original_filename: str,
    timeout: int = 120,
) -> bytes:
    """
    Convert in-memory XLSX bytes → in-memory PDF bytes.

    Uses an isolated LibreOffice profile per call so concurrent
    Streamlit sessions never collide on the user profile lock.
    """
    stem = Path(original_filename).stem or "workbook"
    suffix = Path(original_filename).suffix.lower() or ".xlsx"

    with tempfile.TemporaryDirectory(prefix="xlsx2pdf_") as workdir:
        workdir = Path(workdir)
        src = workdir / f"{stem}{suffix}"
        src.write_bytes(input_bytes)

        out_dir = workdir / "out"
        out_dir.mkdir()

        profile_dir = workdir / "profile"
        profile_dir.mkdir()

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
            "pdf:calc_pdf_Export",
            "--outdir",
            str(out_dir),
            str(src),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise ConversionError(
                f"Conversion timed out after {timeout}s. "
                "The file may be too large or contain slow formulas."
            ) from e

        produced = out_dir / f"{stem}.pdf"
        if result.returncode != 0 or not produced.exists():
            err = (result.stderr or result.stdout or "").strip()
            raise ConversionError(
                f"LibreOffice failed (exit {result.returncode}). {err[:400]}"
            )

        return produced.read_bytes()
