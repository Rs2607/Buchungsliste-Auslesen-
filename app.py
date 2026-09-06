import io
import re
from collections import defaultdict
import streamlit as st
from PIL import Image
import pytesseract
from weasyprint import HTML

# Konfiguration der Seite
st.set_page_config(page_title="ULD Statement Generator", page_icon="📦", layout="centered")

st.title("📦 ULD Statement Generator")
st.write("Lade ein Foto der Buchungsliste hoch, um automatisch PDF-Statements zu generieren.")

# 1. Foto-Upload / Kamera-Input
uploaded_file = st.file_uploader("Foto der Buchungsliste hochladen", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # Bild anzeigen
    image = Image.open(uploaded_file)
    st.image(image, caption="Hochgeladene Buchungsliste", use_column_width=True)

    with st.spinner("Lese Text aus dem Foto (OCR)..."):
        # Texterkennung per Tesseract-OCR
        extracted_text = pytesseract.image_to_string(image)

    # Optional: Erkannten Text anzeigen zur Kontrolle
    with st.expander("Erkannten Text anzeigen / bearbeiten"):
        text_input = st.text_area("OCR-Ergebnis", value=extracted_text, height=150)

    # Parse-Logik für ULDs und AWBs
    # Suchmuster für Standard-ULDs (PMC, PLA, AKE, AKH, etc.)
    uld_pattern = re.compile(r'\b([A-Z]{3}\d{5}[A-Z0-9]{2})\b')
    awb_pattern = re.compile(r'\b(\d{3}[\s-]?\d{8})\b')

    # Struktur zur Speicherung: uld_dict[uld_id] = {'awbs': [], 'weight': '0', 'contour': 'SCA'}
    ulds = defaultdict(lambda: {'awbs': [], 'weight': '0', 'contour': '-'})

    # Verarbeitung der Textzeilen
    lines = text_input.split('\n')
    current_uld = None

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        # Prüfen, ob ULD in der Zeile vorkommt
        uld_match = uld_pattern.search(line_clean)
        if uld_match:
            current_uld = uld_match.group(1)

        # Prüfen, ob AWB in der Zeile vorkommt
        awb_match = awb_pattern.search(line_clean)
        if awb_match and current_uld:
            awb_no = awb_match.group(1)
            # Einfaches Auslesen von Stückzahl / Sondermeldungen falls vorhanden
            ulds[current_uld]['awbs'].append({
                'awb': awb_no,
                'pcs': '1', # Standardwert, falls nicht im OCR erkannt
                'special': '-'
            })

    if ulds:
        st.success(f"Gefundene ULDs: {len(ulds)}")
        
        # 2. Generierung des HTML/PDF Layouts
        css_style = """
        <style>
            @page { size: A4 portrait; margin: 4mm 5mm; }
            body { font-family: Arial, sans-serif; font-size: 10pt; color: #000; }
            .container { width: 100%; height: 100%; page-break-after: always; }
            table { width: 100%; border-collapse: collapse; table-layout: fixed; }
            th, td { border: 1px solid #000; padding: 4px 6px; vertical-align: middle; }
            .title-area { font-size: 22pt; font-weight: bold; }
            .center { text-align: center; }
        </style>
        """

        html_pages = []
        for uld_id, item in ulds.items():
            awb_rows = ""
            for a in item['awbs']:
                awb_rows += f"""
                <tr>
                    <td style="height: 18.5px; font-size: 9pt;">{a['awb']}</td>
                    <td class="center" style="font-size: 9pt;">{a['pcs']}</td>
                    <td class="center" style="font-size: 8pt;">{a['special']}</td>
                </tr>
                """
            # Auffüllen leerer Zeilen
            for _ in range(max(0, 32 - len(item['awbs']))):
                awb_rows += '<tr><td style="height: 18.5px;"></td><td></td><td></td></tr>'

            page_html = f"""
            <div class="container">
                <table style="margin-bottom: 3px;">
                    <tr>
                        <td style="width: 58%; padding: 7px;">
                            <span class="title-area">ULD - Statement</span> <b>Cargo - Handling</b>
                        </td>
                        <td style="width: 42%; text-align: right; font-size: 20pt; font-weight: bold;">
                            VIE <span style="font-size: 9pt; display: block;">Vienna Airport</span>
                        </td>
                    </tr>
                </table>
                <table style="margin-bottom: 3px;">
                    <tr>
                        <td style="padding: 7px;">
                            <b>ULD - Number:</b> {uld_id}
                        </td>
                    </tr>
                </table>
                <table style="margin-bottom: 3px;">
                    <thead>
                        <tr style="background-color: #f0f0f0;">
                            <th>Air Waybill</th>
                            <th style="width: 60px;">Pcs</th>
                            <th style="width: 90px;">Special-Cargo</th>
                        </tr>
                    </thead>
                    <tbody>
                        {awb_rows}
                    </tbody>
                </table>
                <table>
                    <tr>
                        <td><b>KONTUR:</b> {item['contour']}</td>
                        <td><b>Bruttogewicht:</b> {item['weight']} kg</td>
                    </tr>
                </table>
            </div>
            """
            html_pages.append(page_html)

        full_html = f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{css_style}</head><body>{''.join(html_pages)}</body></html>"

        # PDF per WeasyPrint erzeugen
        pdf_bytes = HTML(string=full_html).write_pdf()

        # Download-Button anzeigen
        st.download_button(
            label="📄 Fertiges ULD-Statement PDF herunterladen",
            data=pdf_bytes,
            file_name="ULD_Statements_Export.pdf",
            mime="application/pdf"
        )
    else:
        st.warning("Keine gültigen ULD-Nummern oder AWBs im Bild erkannt. Bitte passe den Text im Feld manuell an.")
