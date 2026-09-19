# XLSX → PDF Converter (Streamlit)

Convert Excel workbooks to PDFs using LibreOffice headless mode.
Charts, formulas, conditional formatting, and pivot tables are preserved.

## Run locally

Install LibreOffice first:
- **Ubuntu/Debian:** `sudo apt install libreoffice-calc`
- **macOS:** `brew install --cask libreoffice`
- **Windows:** https://www.libreoffice.org/download/

Then:
```bash
pip install -r requirements.txt
streamlit run app.py
