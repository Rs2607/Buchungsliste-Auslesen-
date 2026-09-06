import io
import json
import re
from collections import defaultdict
import streamlit as st
from PIL import Image
import pytesseract
import easyocr
import numpy as np
import google.generativeai as genai
from xhtml2pdf import pisa

# Konfiguration der Seite
st.set_page_config(page_title="ULD Statement Generator", page_icon="📦", layout="centered")

st.title("📦 Multi-Engine ULD Statement Generator")
st.write("Verarbeitet Buchungslisten mit Tesseract, EasyOCR & Gemini KI für maximale Erkennungsgenauigkeit.")

# Sidebar für Einstellungen & API-Key
st.sidebar.header("Einstellungen")
api_key = st.sidebar.text_input("Gemini API Key (Empfohlen)", type="password", help="Trage hier deinen API-Key ein.")
use_easyocr = st.sidebar.checkbox("EasyOCR aktivieren", value=True)
use_tesseract = st.sidebar.checkbox("Tesseract OCR aktivieren", value=True)

@st.cache_resource
def load_easyocr_reader():
    return easyocr.Reader(['en', 'de'], gpu=False)

uploaded_file = st.file_uploader("Foto der Buchungsliste hochladen", type=["jpg", "jpeg", "png"], key="uploader_input")

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    # Bild verkleinern, um RAM-Grenzwerte bei großen Smartphone-Fotos zu wahren
    image.thumbnail((2000, 2000))
    st.image(image, caption="Hochgeladene Buchungsliste", use_container_width=True)

    combined_ocr_text = ""

    with st.spinner("Lese Text mit ausgewählten OCR-Engines aus..."):
        # 1. Tesseract OCR
        tesseract_text = ""
        if use_tesseract:
            try:
                tesseract_text = pytesseract.image_to_string(image, config='--oem 3 --psm 6')
            except Exception as e:
                tesseract_text = f"Tesseract Fehler: {e}"

        # 2. EasyOCR
        easyocr_text = ""
        if use_easyocr:
            try:
                reader = load_easyocr_reader()
                img_np = np.array(image)
                results = reader.readtext(img_np, detail=0)
                easyocr_text = "\n".join(results)
            except Exception as e:
                easyocr_text = f"EasyOCR Fehler: {e}"

        combined_ocr_text = f"--- TESSERACT OCR ---\n{tesseract_text}\n\n--- EASYOCR ---\n{easyocr_text}"

    extracted_ulds = []

    # 3. KI-Auswertung (Gemini)
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
                clean_json_str = response.text.replace("```json", "").replace("
