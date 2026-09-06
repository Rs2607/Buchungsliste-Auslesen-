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
    Du bist ein Experte für Air Cargo Handling am Flughafen Wien (ULD Processing).
    Analysiere das Bild dieser Buchungsliste / Cargo Manifest extrem genau.

    ANWEISUNG ZUR EXTRAKTION:
    - Scanne die Buchungsliste nach Flugnummer (z.B. KE538), Destination (z.B. MXP) und allen ULDs.
    - Scanne in der Spalte "Flugdetails & Aufbau" JEDE EINZELNE ZEILE auf ULD-Nummern (z.B. PMC80397R7, PMC58968R7, PMC17665R9, PMC70204R7).
    - Verknüpfe jede ULD-Nummer mit der AWB-Nummer, Stückzahl, Gewicht und Special-Cargo-Codes.

    Extrahiere alle Daten und antworte STRENG im folgenden JSON-Format (kein Fließtext, kein Markdown-Codeblock):
    {
      "flight": "KE538",
      "dest": "MXP",
      "raw_records": [
        {
          "uld_id": "PMC80397R7",
          "awb": "180-54275970",
          "pcs": "6",
          "weight": "2639",
          "contour": "SCA",
          "special": "EAW, ECC"
        }
      ]
    }

    Regeln:
    1. Bereinige Konturbezeichnungen (z.B. aus "SCA/P6/K3535" wird "SCA").
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

    with st.spinner("Gemini liest die Daten aus..."):
        try:
            raw_data = analyze_booking_list_with_ai(input_bytes)
            flight_no = raw_data.get("flight", "-")
            dest_code = raw_data.get("dest", "-")
            raw_records = raw_data.get("raw_records", [])
            ulds = consolidate_ulds(raw_records)
            st.success(f"Analyse erfolgreich! Gefundene ULDs: {len(ulds)}")
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
            body, html {
                font-family: Helvetica, Arial, sans-serif;
                font-size: 8.5pt;
                color: #000000;
                margin: 0;
                padding: 0;
            }
            .page-container {
                page-break-after: always;
            }
            .main-table {
                width: 100%;
                border-collapse: collapse;
            }
            .main-table td, .main-table th {
                border: 1px solid #000000;
                padding: 4px 6px;
                vertical-align: middle;
            }
            .center { text-align: center; }
            .right { text-align: right; }
            .bold { font-weight: bold; }
            .header-bg { background-color: #f0f0f0; font-weight: bold; text-align: center; }
            .check-box { width: 13px; height: 13px; border: 1px solid #000; display: inline-block; }
            .small-text { font-size: 7pt; }
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
                <tr style="height: 28px;">
                    <td colspan="3" style="font-size: 11pt; font-weight: bold; padding-left: 10px;">{a['awb']}</td>
                    <td colspan="1" class="center" style="font-size: 11pt; font-weight: bold;">{a['pcs']}</td>
                    <td colspan="2" class="center" style="font-size: 10pt;">{a['special']}</td>
                </tr>
                """
            
            # Formular auf genau 8 AWB-Zeilen aufspannen
            empty_rows = max(0, 8 - len(awb_list))
            for _ in range(empty_rows):
                awb_rows += """
                <tr style="height: 28px;">
                    <td colspan="3">&nbsp;</td>
                    <td colspan="1">&nbsp;</td>
                    <td colspan="2">&nbsp;</td>
                </tr>
                """

            page_html = f"""
            <div class="page-container">
                <table class="main-table">
                    <!-- HEADER -->
                    <tr>
                        <td colspan="4" style="padding: 8px;">
                            <span style="font-size: 16pt; font-weight: bold;">ULD - Statement</span> 
                            <span style="font-size: 10pt; font-weight: bold;">Cargo - Handling</span><br><br>
                            <span style="font-size: 11pt;"><b>Flug:</b> {flight_no} &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <b>Dest.:</b> {dest_code}</span>
                        </td>
                        <td colspan="2" class="right" style="padding: 8px;">
                            <span style="font-size: 22pt; font-weight: bold;">VIE</span><br>
                            <span style="font-size: 9pt;">Vienna Airport</span>
                        </td>
                    </tr>

                    <!-- ULD NUMBER -->
                    <tr>
                        <td colspan="6" style="padding: 8px;">
                            <span style="font-size: 9pt;">ULD - Number</span><br>
                            <span style="font-size: 14pt; font-weight: bold;">Paletten / Container: {uld_id}</span>
                        </td>
                    </tr>

                    <!-- AWB HEADERS -->
                    <tr class="header-bg" style="height: 24px;">
                        <td colspan="3" style="width: 50%;">Air Waybill</td>
                        <td colspan="1" style="width: 15%;">Pcs<br><span class="small-text">Stück</span></td>
                        <td colspan="2" style="width: 35%;">Special-Cargo</td>
                    </tr>

                    <!-- AWB ROWS -->
                    {awb_rows}

                    <!-- KONTUR & MATERIALIEN -->
                    <tr>
                        <td colspan="6" style="font-size: 11pt; font-weight: bold; padding: 6px;">KONTUR: {contour}</td>
                    </tr>
                    <tr style="height: 22px;">
                        <td colspan="1" style="width: 25%;">Stricke:</td>
                        <td colspan="2" style="width: 25%;">Gurten:</td>
                        <td colspan="2" style="width: 25%;">EURO - Pal.:</td>
                        <td colspan="1" style="width: 25%;">Verzurrösen:</td>
                    </tr>
                    <tr style="height: 22px;">
                        <td colspan="1">Bretter 1,30m:</td>
                        <td colspan="2">Bretter 2,00m:</td>
                        <td colspan="2">Bretter 2,20m:</td>
                        <td colspan="1">Bretter 2,90m:</td>
                    </tr>

                    <!-- DAMAGE / HEIGHT CHECK -->
                    <tr>
                        <td colspan="3" style="padding: 10px 6px;">
                            <b>ULD CHECKED FOR DAMAGES</b><br>
                            <span class="small-text">Check and ensure airworthiness of BUP/TRU</span><br><br>
                            <b>OK</b> <span class="check-box"></span> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <b>NOT OK</b> <span class="check-box"></span>
                        </td>
                        <td colspan="3" style="padding: 10px 6px;">
                            <b>HEIGHT CHECK PERFORMED</b><br><br><br>
                            <b>OK</b> <span class="check-box"></span> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <b>NOT OK</b> <span class="check-box"></span>
                        </td>
                    </tr>

                    <!-- LAGERPLATZ GRID -->
                    <tr style="height: 22px;">
                        <td rowspan="2" colspan="1" style="font-weight: bold; font-size: 9.5pt;">Lagerplatz</td>
                        <td colspan="1">Perisha 1</td>
                        <td colspan="1">2</td>
                        <td colspan="1">3</td>
                        <td colspan="1">4</td>
                        <td colspan="1">5</td>
                    </tr>
                    <tr style="height: 22px;">
                        <td colspan="1">fache Seite</td>
                        <td colspan="1">&nbsp;</td>
                        <td colspan="1">&nbsp;</td>
                        <td colspan="1">&nbsp;</td>
                        <td colspan="1">&nbsp;</td>
                    </tr>
                    <tr style="height: 22px;">
                        <td colspan="3">Fremdhandling Vorhaltefläche</td>
                        <td colspan="3">Stückgut Vorhaltefläche</td>
                    </tr>
                    <tr style="height: 22px;">
                        <td colspan="3">LCAG Vorhaltefläche</td>
                        <td colspan="3">Stückgut Warehouse</td>
                    </tr>
                    <tr style="height: 22px;">
                        <td colspan="3">LCAG Warehouse</td>
                        <td colspan="3">Trucking Vorhaltefläche</td>
                    </tr>
                    <tr style="height: 22px;">
                        <td colspan="3">Breakdown</td>
                        <td colspan="3">Disponent Büro</td>
                    </tr>
                    <tr style="height: 26px;">
                        <td colspan="6">Sonstiger Lagerplatz:</td>
                    </tr>

                    <!-- BRUTTOGEWICHT -->
                    <tr>
                        <td colspan="6" style="font-size: 12pt; font-weight: bold; padding: 8px;">
                            Grossweight / Bruttogewicht: {weight} kg
                        </td>
                    </tr>

                    <!-- UNTERSCHRIFTEN -->
                    <tr>
                        <td colspan="3" style="padding: 10px; height: 50px; vertical-align: top;">
                            Name / PersNr.:<br><br><br>
                            <b>Unterschrift DG:</b>
                        </td>
                        <td colspan="3" style="padding: 10px; height: 50px; vertical-align: top;">
                            Name / PersNr.:<br><br><br>
                            <b>Unterschrift MA:</b>
                        </td>
                    </tr>
                </table>
                <div class="small-text right" style="margin-top: 4px;">Form 752z/25 vie</div>
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
