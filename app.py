import io
import json
import re
import time
import streamlit as st
from PIL import Image
from google import genai
from google.genai.errors import APIError
from xhtml2pdf import pisa

# Page Configuration
st.set_page_config(page_title="ULD Statement Generator AI", page_icon="📦", layout="centered")

st.title("📦 ULD Statement Generator (AI)")
st.write("Foto der Buchungsliste hochladen – Gemini liest die ULDs und AWBs automatisch aus.")

# API Key check from Streamlit Secrets
if "GEMINI_API_KEY" in st.secrets:
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("Kein GEMINI_API_KEY in den Streamlit Secrets gefunden!")
    st.stop()

def analyze_booking_list_with_ai(image_bytes):
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((1600, 1600))
    
    prompt = """
    Du bist ein Experte für Air Cargo Handling am Flughafen (ULD Processing).
    Analysiere das Bild dieser Buchungsliste / Cargo Manifest.

    Extrahiere alle Daten und antworte STRENG im folgenden JSON-Format (kein Fließtext, kein Markdown-Codeblock):
    {
      "ulds": [
        {
          "uld_id": "PMC01886R7",
          "contour": "SCA",
          "weight": "1580",
          "awbs": [
            {
              "awb": "180-54666065",
              "pcs": "1",
              "special": "-"
            }
          ]
        }
      ]
    }

    Regeln:
    1. Identifiziere ULDs (z. B. PMC, PLA, AKE, AKH) und erstelle für jeden ULD einen Eintrag.
    2. Wenn ein ULD mehrere AWBs enthält, ordne alle AWBs diesem ULD zu.
    3. Bereinige Konturbezeichnungen (z. B. "SCA-T(2)" -> "SCA").
    4. Gib ausschließlich valides JSON zurück.
    """
    
    # Gültige Modellnamen in der aktuellen Google GenAI SDK
    models_to_try = ["gemini-2.0-flash-lite", "gemini-2.0-flash"]
    
    response = None
    last_exception = None

    for model_name in models_to_try:
        # Bis zu 2 Versuche bei temporärer Überlastung
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[img, prompt]
                )
                if response and response.text:
                    break
            except APIError as e:
                last_exception = e
                # Bei Überlastung (503) kurz warten und wiederholen
                if getattr(e, 'code', None) == 503 or "503" in str(e):
                    time.sleep(2)
                    continue
                else:
                    break
            except Exception as e:
                last_exception = e
                break
        
        if response and response.text:
            break

    if not response or not response.text:
        raise RuntimeError(f"Anfrage konnte nicht verarbeitet werden: {last_exception}")

    raw_text = response.text.strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:-3].strip()
    elif raw_text.startswith("```"):
        raw_text = raw_text[3:-3].strip()
        
    return json.loads(raw_text)

# File Uploader Widget
uploaded_file = st.file_uploader(
    "Foto der Buchungsliste hochladen", 
    type=["jpg", "jpeg", "png"],
    key="uploader_input"
)

if uploaded_file is not None:
    input_bytes = uploaded_file.read()
    image = Image.open(io.BytesIO(input_bytes))
    
    st.image(image, caption="Hochgeladene Buchungsliste", use_container_width=True)

    with st.spinner("Gemini liest die Daten aus..."):
        try:
            data = analyze_booking_list_with_ai(input_bytes)
            ulds = data.get("ulds", [])
            st.success(f"Analyse erfolgreich! Gefundene ULDs: {len(ulds)}")
        except Exception as e:
            st.error(f"Fehler bei der KI-Analyse: {e}")
            st.stop()

    if ulds:
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
        for item in ulds:
            uld_id = item.get("uld_id", "-")
            contour = item.get("contour", "-")
            weight = item.get("weight", "0")
            awb_list = item.get("awbs", [])

            awb_rows = ""
            for a in awb_list:
                awb_rows += f"""
                <tr>
                    <td style="height: 18.5px; font-size: 9pt;">{a.get('awb', '')}</td>
                    <td class="center" style="font-size: 9pt;">{a.get('pcs', '')}</td>
                    <td class="center" style="font-size: 8pt;">{a.get('special', '-')}</td>
                </tr>
                """
            for _ in range(max(0, 32 - len(awb_list))):
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
                        <td><b>KONTUR:</b> {contour}</td>
                        <td><b>Bruttogewicht:</b> {weight} kg</td>
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
