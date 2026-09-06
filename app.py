import io
import json
import re
from collections import defaultdict
import streamlit as st
from PIL import Image
import cv2
import numpy as np
import pytesseract
import easyocr
import google.generativeai as genai
from xhtml2pdf import pisa

# Konfiguration
st.set_page_config(page_title="ULD Statement Generator", page_icon="📦", layout="centered")

st.title("📦 Multi-Engine ULD Statement Generator")
st.write("Bildverarbeitung (OpenCV), Tesseract, EasyOCR & Gemini KI in Kombination.")

st.sidebar.header("Einstellungen")
api_key = st.sidebar.text_input("Gemini API Key (Empfohlen)", type="password")
use_easyocr = st.sidebar.checkbox("EasyOCR aktivieren", value=True)
use_tesseract = st.sidebar.checkbox("Tesseract OCR aktivieren", value=True)
enable_preprocess = st.sidebar.checkbox("Bildoptimierung (OpenCV) aktivieren", value=True)

@st.cache_resource
def load_easyocr_reader():
    return easyocr.Reader(['en', 'de'], gpu=False)

# BAUSTEIN 1: Automatische Bildoptimierung per OpenCV
def preprocess_image(pil_img):
    img_np = np.array(pil_img)
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharpened = cv2.filter2D(enhanced, -1, kernel)
    return Image.fromarray(sharpened), sharpened

uploaded_file = st.file_uploader("Foto der Buchungsliste hochladen", type=["jpg", "jpeg", "png"], key="uploader_input")

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    image.thumbnail((2000, 2000))
    
    if enable_preprocess:
        proc_pil, proc_np = preprocess_image(image)
        st.image(image, caption="Hochgeladene Buchungsliste (Optimiert)", use_container_width=True)
    else:
        proc_pil = image
        proc_np = np.array(image)
        st.image(image, caption="Hochgeladene Buchungsliste", use_container_width=True)

    combined_ocr_text = ""

    with st.spinner("Lese Text mit ausgewählten OCR-Engines aus..."):
        tesseract_text = ""
        if use_tesseract:
            try:
                tesseract_text = pytesseract.image_to_string(proc_pil, config='--oem 3 --psm 6')
            except Exception as e:
                tesseract_text = f"Tesseract Fehler: {e}"

        easyocr_text = ""
        if use_easyocr:
            try:
                reader = load_easyocr_reader()
                results = reader.readtext(proc_np, detail=0)
                easyocr_text = "\n".join(results)
            except Exception as e:
                easyocr_text = f"EasyOCR Fehler: {e}"

        combined_ocr_text = f"--- TESSERACT OCR ---\n{tesseract_text}\n\n--- EASYOCR ---\n{easyocr_text}"

    extracted_ulds = []

    # BAUSTEIN 2: KI-Verarbeitung & Strukturierung
    if api_key:
        with st.spinner("KI vergleicht OCR-Ergebnisse und strukturiert die Daten..."):
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-flash')

                prompt = f"""
                Du bist ein Experte für Luftfracht. Vor dir liegt ein Foto einer Buchungsliste sowie der extrahierte Text zweier OCR-Engines.
                
                Extrahierter OCR-Text:
                {combined_ocr_text}

                Aufgabe:
                Analysiere das Foto und den OCR-Text. Extrahiere alle ULD-Nummern (PMC, PLA, AKE etc.), Air Waybills (AWBs), Stückzahlen und Gewichte.
                Füge gleiche ULD-Nummern zusammen. Die Konturen bestehen meist nur aus 2-3 Buchstaben (z.B. SCA, LD6, LDP, LDG) - lasse Zusatzbezeichnungen wie -T(2) weg.
                
                Gib NUR ein gültiges JSON-Array zurück (ohne Markdown-Backticks):
                [
                    {{"uld": "PMC01886R7", "awb": "180-54666065", "pcs": "1", "weight": "1580", "contour": "SCA"}}
                ]
                """

                response = model.generate_content([prompt, image])
                clean_json_str = response.text.replace("```json", "").replace("```", "").strip()
                extracted_ulds = json.loads(clean_json_str)
            except Exception as e:
                st.error(f"KI-Fehler: {e}")

    json_text_input = st.text_area(
        "Erkannte ULD-Daten (JSON-Format):", 
        value=json.dumps(extracted_ulds, indent=2) if extracted_ulds else "[]", 
        height=200,
        key="json_editor"
    )

    # BAUSTEIN 3: RegEx-Filterung, Bereinigung & Deduplizierung
    try:
        parsed_data = json.loads(json_text_input)
        grouped_ulds = defaultdict(lambda: {'awbs': [], 'weight': '0', 'contour': '-'})

        uld_regex = re.compile(r'\b([A-Z]{3}\d{5}[A-Z0-9]{2})\b')

        for entry in parsed_data:
            raw_uld = entry.get("uld", "").strip().upper()
            uld_match = uld_regex.search(raw_uld)
            uld_id = uld_match.group(1) if uld_match else raw_uld

            if uld_id:
                # Kontur bereinigen (nur 2-3 Buchstaben behalten)
                raw_contour = entry.get("contour", "-").strip()
                clean_contour = re.sub(r'[\(\)\-T0-9]', '', raw_contour)
                grouped_ulds[uld_id]['contour'] = clean_contour if clean_contour else "-"

                if entry.get("weight") and entry.get("weight") != "0":
                    grouped_ulds[uld_id]['weight'] = entry.get("weight")
                
                grouped_ulds[uld_id]['awbs'].append({
                    'awb': entry.get("awb", "-"),
                    'pcs': str(entry.get("pcs", "1")),
                    'special': entry.get("special", "-")
                })

        if grouped_ulds:
            st.success(f"Erfolgreich {len(grouped_ulds)} ULD(s) aufbereitet.")

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
            for uld_id, item in grouped_ulds.items():
                awb_rows = ""
                for a in item['awbs']:
                    awb_rows += f"""
                    <tr>
                        <td style="height: 18.5px; font-size: 9pt;">{a['awb']}</td>
                        <td class="center" style="font-size: 9pt;">{a['pcs']}</td>
                        <td class="center" style="font-size: 8pt;">{a['special']}</td>
                    </tr>
                    """
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
                            <td style="padding: 7px;"><b>ULD - Number:</b> {uld_id}</td>
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
                        <tbody>{awb_rows}</tbody>
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

            pdf_buffer = io.BytesIO()
            pisa.CreatePDF(full_html, dest=pdf_buffer)
            pdf_bytes = pdf_buffer.getvalue()

            st.download_button(
                label="📄 Fertiges ULD-Statement PDF herunterladen",
                data=pdf_bytes,
                file_name="ULD_Statements_Export.pdf",
                mime="application/pdf",
                key="pdf_download_btn"
            )
    except Exception as json_err:
        st.warning(f"Fehler bei der Datenverarbeitung: {json_err}")
