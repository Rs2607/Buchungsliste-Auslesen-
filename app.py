import io
import json
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

    Lies jede Zeile der Tabelle aus und ordne die AWB-Nummern den jeweiligen ULDs zu.

    Extrahiere alle Daten und antworte STRENG im folgenden JSON-Format (kein Fließtext, kein Markdown-Codeblock):
    {
      "ulds": [
        {
          "uld_id": "PMC58968R7",
          "contour": "SCA",
          "weight": "1876",
          "awbs": [
            {
              "awb": "180-63061655",
              "pcs": "10",
              "special": "EAW,ECC,GCP"
            }
          ]
        }
      ]
    }

    Regeln:
    1. Erfasse jeden AWB und die zugehörige ULD-Nummer.
    2. Bereinige Konturbezeichnungen (z. B. aus "SCA/P2/K2205" wird "SCA").
    3. Gib ausschließlich valides JSON zurück.
    """
    
    models_to_try = ["gemini-3.5-flash-lite", "gemini-3.6-flash"]
    response = None
    last_exception = None

    for model_name in models_to_try:
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
                if getattr(e, 'code', None) == 503 or "503" in str(e):
                    time.sleep(1.5)
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

def consolidate_ulds(raw_ulds):
    """Führt doppelte ULD-Nummern garantiert in Python zusammen."""
    consolidated = {}
    for item in raw_ulds:
        uld_id = str(item.get("uld_id") or "-").strip()
        contour = str(item.get("contour") or "-").strip()
        weight = str(item.get("weight") or "0").strip()
        awb_list = item.get("awbs") if isinstance(item.get("awbs"), list) else []

        if uld_id not in consolidated:
            consolidated[uld_id] = {
                "uld_id": uld_id,
                "contour": contour,
                "weight": weight,
                "awbs": []
            }
        
        for a in awb_list:
            if isinstance(a, dict):
                consolidated[uld_id]["awbs"].append({
                    "awb": str(a.get('awb') or '').strip(),
                    "pcs": str(a.get('pcs') or '1').strip(),
                    "special": str(a.get('special') or '-').strip()
                })
    return list(consolidated.values())

uploaded_file = st.file_uploader(
    "Foto der Buchungsliste hochladen", 
    type=["jpg", "jpeg", "png"],
    key="uploader_input"
)

if uploaded_file is not None:
    input_bytes = uploaded_file.read()
    image = Image.open(io.BytesIO(input_bytes))
    
    st.image(image, caption="Hochgeladene Buchungsliste", use_container_width=True)

    with st.spinner("Gemini liest und konsolidiert die ULDs..."):
        try:
            raw_data = analyze_booking_list_with_ai(input_bytes)
            raw_ulds = raw_data.get("ulds", [])
            ulds = consolidate_ulds(raw_ulds)
            st.success(f"Analyse erfolgreich! Eindeutige ULDs: {len(ulds)}")
        except Exception as e:
            st.error(f"Fehler bei der KI-Analyse: {e}")
            st.stop()

    if ulds:
        css_style = """
        <style>
            @page {
                size: A4 portrait;
                margin: 8mm;
            }
            body {
                font-family: Helvetica, Arial, sans-serif;
                font-size: 10pt;
                color: #000000;
            }
            .page-container {
                page-break-after: always;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 8px;
            }
            th, td {
                border: 1px solid #000000;
                padding: 5px;
                vertical-align: middle;
            }
            th {
                background-color: #e0e0e0;
                font-weight: bold;
                text-align: center;
            }
            .header-table td {
                border: 1px solid #000000;
                padding: 8px;
            }
            .title {
                font-size: 18pt;
                font-weight: bold;
            }
            .airport {
                font-size: 16pt;
                font-weight: bold;
                text-align: right;
            }
            .center {
                text-align: center;
            }
        </style>
        """

        html_pages = []
        for item in ulds:
            uld_id = item["uld_id"]
            contour = item["contour"]
            weight = item["weight"]
            awb_list = item["awbs"]

            awb_rows = ""
            for a in awb_list:
                awb_rows += f"""
                <tr>
                    <td style="width: 50%; font-size: 10pt;">{a['awb']}</td>
                    <td class="center" style="width: 15%; font-size: 10pt;">{a['pcs']}</td>
                    <td class="center" style="width: 35%; font-size: 9pt;">{a['special']}</td>
                </tr>
                """
            
            # Auffüllen leerer Tabellenzeilen für saubere Optik
            empty_rows_needed = max(0, 18 - len(awb_list))
            for _ in range(empty_rows_needed):
                awb_rows += """
                <tr>
                    <td style="height: 20px;"></td>
                    <td></td>
                    <td></td>
                </tr>
                """

            page_html = f"""
            <div class="page-container">
                <table class="header-table">
                    <tr>
                        <td style="width: 65%;">
                            <span class="title">ULD - Statement</span><br>
                            <span style="font-size: 10pt;">Cargo - Handling</span>
                        </td>
                        <td style="width: 35%;" class="airport">
                            VIE<br>
                            <span style="font-size: 8pt; font-weight: normal;">Vienna Airport</span>
                        </td>
                    </tr>
                </table>

                <table>
                    <tr>
                        <td style="padding: 8px; font-size: 12pt;">
                            <b>ULD - Number:</b> {uld_id}
                        </td>
                    </tr>
                </table>

                <table>
                    <thead>
                        <tr>
                            <th style="width: 50%;">Air Waybill</th>
                            <th style="width: 15%;">Pcs</th>
                            <th style="width: 35%;">Special-Cargo</th>
                        </tr>
                    </thead>
                    <tbody>
                        {awb_rows}
                    </tbody>
                </table>

                <table>
                    <tr>
                        <td style="width: 50%; padding: 8px;"><b>KONTUR:</b> {contour}</td>
                        <td style="width: 50%; padding: 8px;"><b>Bruttogewicht:</b> {weight} kg</td>
                    </tr>
                </table>
            </div>
            """
            html_pages.append(page_html)

        full_html = f"<!DOCTYPE html><html><head><meta charset='UTF-8'>{css_style}</head><body>{''.join(html_pages)}</body></html>"

        try:
            pdf_buffer = io.BytesIO()
            pisa_status = pisa.CreatePDF(full_html, dest=pdf_buffer)
            
            if not pisa_status.err:
                pdf_bytes = pdf_buffer.getvalue()
                st.download_button(
                    label="📄 Fertiges ULD-Statement PDF herunterladen",
                    data=pdf_bytes,
                    file_name="ULD_Statements_Export.pdf",
                    mime="application/pdf",
                    key="pdf_download_btn"
                )
            else:
                st.error("Fehler beim Erstellen des PDFs (Layout-Problem).")
        except Exception as e:
            st.error(f"Fehler bei der Erstellung der PDF-Datei: {e}")
