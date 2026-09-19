# XLSX → JPG → PDF Converter (Streamlit)

Three-stage pipeline that guarantees pixel-perfect output:

1. **XLSX → PDF** via LibreOffice headless
2. **PDF → JPG** via `pdftoppm` (one JPG per page)
3. **JPGs → PDF** via Pillow (single multi-page PDF)

The rasterization step **freezes the visual output**, which means
formulas, charts, fonts, and layout render exactly as Excel shows
them — critical for template-style reports like Huawei TSSR.

## Features

- Multi-file upload (.xlsx / .xlsm / .xls)
- Adjustable DPI (72–300) and JPEG quality (50–100)
- Page previews in the browser before download
- Download PDFs individually, as JPGs, or all as ZIP
- In-memory processing — nothing persisted

## Deploy on Streamlit Community Cloud

1. Push this folder to GitHub.
2. Create the app at https://share.streamlit.io → point to `app.py`.
3. Streamlit installs `libreoffice` and `poppler-utils` from `packages.txt`.
