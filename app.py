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
    Analysiere das Bild dieser Buchungsliste / Cargo Manifest extrem genau.

    ANWEISUNG ZUR DOKUMENTEN-EXTRAKTION:
    - Scanne in der Spalte "Flugdetails & Aufbau" JEDE EINZELNE ZEILE auf ULD-Nummern (z.B. PMC80397R7, PMC58968R7, PMC17665R9, PMC70204R7, PMC01424R7, PMC60998R7).
    - Oft stehen in EINER Tabellenzeile der Buchungsliste zwei ULDs untereinander. Du musst BEIDE ULDs erfassen!
    - Verknüpfe jede gefundene ULD-Nummer mit der AWB-Nummer der jeweiligen Tabellenzeile.

    Extrahiere alle Daten und antworte STRENG im folgenden JSON-Format (kein Fließtext, kein Markdown-Codeblock):
    {
      "raw_records": [
        {
          "uld_id": "PMC80397R7",
          "awb": "180-54275970",
          "pcs": "6",
          "weight": "2639",
          "contour": "SCA",
          "special": "EAW,ECC"
        }
      ]
    }

    Regeln:
    1. Bereinige Konturbezeichnungen (z.B. aus "SCA/P6/K3535" wird "SCA", aus "PWG/P137/K1730" wird "PWG").
    2. Ignoriere Hinweistexte wie "ULD STACKS: ...".
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

def consolidate_ulds(raw_records):
    """Gruppiert alle AWBs nach ULD-ID auf Python-Ebene."""
    consolidated = {}
    for item in raw_records:
        uld_id = str(item.get("uld_id") or "-").strip()
        if not uld_id or uld_id == "-":
            continue

        contour = str(item.get("contour") or "-").strip()
        weight = str(item.get("weight") or "0").strip()
        awb = str(item.get("awb") or "-").strip()
        pcs = str(item.get("pcs") or "1").strip()
        special = str(item.get("special") or "-").strip()

        if uld_id not in consolidated:
            consolidated[uld_id] = {
                "uld_id": uld_id,
                "contour": contour,
                "weight": weight,
                "awbs": []
            }
        
        existing_awbs = [a["awb"] for a in consolidated[uld_id]["awbs"]]
        if awb not in existing_awbs:
            consolidated[uld_id]["awbs"].append({
                "awb": awb,
                "pcs": pcs,
                "special": special
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
            raw_records = raw_data.get("raw_records", [])
            ulds = consolidate_ulds(raw_records)
            st.success(f"Analyse erfolgreich! Eindeutige ULDs: {len(ulds)}")
        except Exception as e:
            st.error(f"Fehler bei der KI-Analyse: {e}")
            st.stop()

    if ulds:
        css_style = """
        <style>
            @page {
                size: A4 portrait;
                margin: 6mm;
            }
            body {
                font-family: Helvetica, Arial, sans-serif;
                font-size: 9pt;
                color: #000000;
            }
            .page-container {
                page-break-after: always;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 6px;
            }
            th, td {
                border: 1px solid #000000;
                padding: 4px;
                vertical-align: middle;
            }
            th {
                background-color: #e0e0e0;
                font-weight: bold;
                text-align: center;
            }
            .title-box {
                font-size: 16pt;
                font-weight: bold;
            }
            .airport-box {
                font-size: 14pt;
                font-weight: bold;
                text-align: right;
            }
            .center {
                text-align: center;
            }
            .data-row {
                height: 18px;
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
                <tr class="data-row">
                    <td style="width: 50%; font-size: 9.5pt;">{a['awb']}</td>
                    <td class="center" style="width: 15%; font-size: 9.5pt;">{a['pcs']}</td>
                    <td class="center" style="width: 35%; font-size: 8.5pt;">{a['special']}</td>
                </tr>
                """
            
            # Exakt 15 Datenzeilen insgesamt pro Seite, damit nichts auf Seite 2 rutscht
            empty_rows_needed = max(0, 15 - len(awb_list))
            for _ in range(empty_rows_needed):
                awb_rows += """
                <tr class="data-row">
                    <td>&nbsp;</td>
                    <td>&nbsp;</td>
                    <td>&nbsp;</td>
                </tr>
                """

            page_html = f"""
            <div class="page-container">
                <table>
                    <tr>
                        <td style="width: 65%; padding: 6px;">
                            <span class="title-box">ULD - Statement</span><br>
                            <span style="font-size: 9pt;">Cargo - Handling</span>
                        </td>
                        <td style="width: 35%; padding: 6px;" class="airport-box">
                            VIE<br>
                            <span style="font-size: 8pt; font-weight: normal;">Vienna Airport</span>
                        </td>
                    </tr>
                </table>

                <table>
                    <tr>
                        <td style="padding: 6px; font-size: 11pt;">
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
                        <td style="width: 50%; padding: 6px;"><b>KONTUR:</b> {contour}</td>
                        <td style="width: 50%; padding: 6px;"><b>Bruttogewicht:</b> {weight} kg</td>
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
