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
    - Scanne die Buchungsliste nach Flugnummer (z.B. KE538) und Destination (z.B. MXP).
    - Scanne in der Spalte "Flugdetails & Aufbau" JEDE EINZELNE ZEILE auf ULD-Nummern (z.B. PMC80397R7, PMC58968R7).
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
            flight_no = raw_data.get("flight", "")
            dest_code = raw_data.get("dest", "")
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
                margin: 5mm;
            }
            body, html {
                font-family: Helvetica, Arial, sans-serif;
                font-size: 7.5pt;
                color: #000000;
                margin: 0;
                padding: 0;
            }
            .page-container {
                page-break-after: always;
            }
            table {
                width: 100%;
                border-collapse: collapse;
            }
            td, th {
                border: 1px solid #000000;
                padding: 2px 4px;
                vertical-align: middle;
            }
            .center { text-align: center; }
            .right { text-align: right; }
            .bold { font-weight: bold; }
            .header-bg { background-color: #e0e0e0; font-weight: bold; text-align: center; }
            .check-box { width: 11px; height: 11px; border: 1px solid #000; display: inline-block; }
            .small-text { font-size: 6pt; }
            
            /* SVG Kontur-Skizze im echten Formularstil */
            .contour-sketch {
                width: 70px;
                height: 90px;
                margin: 0 auto;
                display: block;
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
                <tr style="height: 18px;">
                    <td style="width: 58%; font-size: 9pt; font-weight: bold;">{a['awb']}</td>
                    <td class="center" style="width: 17%; font-size: 9pt; font-weight: bold;">{a['pcs']}</td>
                    <td class="center" style="width: 25%; font-size: 8pt;">{a['special']}</td>
                </tr>
                """
            
            # Formular auf genau 20 AWB-Zeilen aufspannen (Exakte Ausrichtung an der Vorlage)
            empty_rows = max(0, 20 - len(awb_list))
            for _ in range(empty_rows):
                awb_rows += """
                <tr style="height: 18px;">
                    <td>&nbsp;</td>
                    <td>&nbsp;</td>
                    <td>&nbsp;</td>
                </tr>
                """

            page_html = f"""
            <div class="page-container">
                <!-- OBERER HEADER BLOCK -->
                <table style="margin-bottom: 0px;">
                    <tr>
                        <td style="width: 60%; vertical-align: top; padding: 4px;">
                            <span style="font-size: 14pt; font-weight: bold;">ULD - Statement</span> 
                            <span style="font-size: 8pt; font-weight: bold;">Cargo - Handling</span><br><br>
                            Flug: ___________________ &nbsp;&nbsp;&nbsp;&nbsp; Dest.: ___________________
                        </td>
                        <td style="width: 40%; vertical-align: top; text-align: right; padding: 4px;">
                            <span style="font-size: 18pt; font-weight: bold;">VIE</span><br>
                            <span style="font-size: 8pt;">Vienna Airport</span>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 4px;">
                            <span style="font-size: 8pt;">ULD - Number</span><br>
                            <span style="font-size: 9pt;">Paletten / Container: <b>{uld_id}</b></span>
                        </td>
                        <td style="padding: 2px; font-size: 6.5pt;">
                            <table style="border: none; width: 100%;">
                                <tr><td style="border: none; padding: 1px;" colspan="2">ULD CHECKED FOR DAMAGES</td></tr>
                                <tr><td style="border: none; padding: 1px;" colspan="2">HEIGHT CHECK PERFORMED</td></tr>
                                <tr><td style="border: none; padding: 1px;" colspan="2"><span class="small-text">Check and ensure airworthiness of BUP/TRU</span></td></tr>
                                <tr>
                                    <td class="center" style="border: 1px solid #000; width: 50%;">OK</td>
                                    <td class="center" style="border: 1px solid #000; width: 50%;">NOT OK</td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>

                <!-- MITTELTEIL: ZWEISPALTTIGES RASTER -->
                <table style="margin-top: -1px;">
                    <tr>
                        <!-- LINKE SPALTE: AWB TABELLE (60% BREITE) -->
                        <td style="width: 60%; vertical-align: top; padding: 0px; border: none;">
                            <table style="width: 100%;">
                                <tr class="header-bg" style="height: 22px;">
                                    <td style="width: 58%;">Air Waybill</td>
                                    <td style="width: 17%;">Pcs<br><span class="small-text">Stück</span></td>
                                    <td style="width: 25%;">Special-<br>Cargo</td>
                                </tr>
                                {awb_rows}
                            </table>
                        </td>

                        <!-- RECHTE SPALTE: SKIZZE & LAGERPLATZ (40% BREITE) -->
                        <td style="width: 40%; vertical-align: top; padding: 0px; border: none;">
                            <table style="width: 100%;">
                                <tr>
                                    <td class="right" style="border-bottom: none; font-size: 6pt;">fache Seite</td>
                                </tr>
                                <tr>
                                    <td class="center" style="height: 110px;">
                                        <!-- SVG Konturskizze -->
                                        <svg class="contour-sketch" viewBox="0 0 100 130">
                                            <polygon points="25,40 75,40 90,80 75,110 25,110 10,80" fill="none" stroke="#000" stroke-width="2"/>
                                            <line x1="25" y1="40" x2="25" y2="110" stroke="#000" stroke-width="1" stroke-dasharray="2,2"/>
                                            <line x1="75" y1="40" x2="75" y2="110" stroke="#000" stroke-width="1" stroke-dasharray="2,2"/>
                                            <circle cx="50" cy="115" r="4" fill="#000"/>
                                        </svg>
                                    </td>
                                </tr>
                                <tr class="header-bg">
                                    <td class="center">Lagerplatz</td>
                                </tr>
                            </table>

                            <table style="width: 100%; margin-top: -1px;">
                                <tr>
                                    <td style="font-size: 6.5pt;">Perisha</td>
                                    <td class="center" style="width: 12%;">1</td>
                                    <td class="center" style="width: 12%;">2</td>
                                    <td class="center" style="width: 12%;">3</td>
                                    <td class="center" style="width: 12%;">4</td>
                                    <td class="center" style="width: 12%;">5</td>
                                </tr>
                                <tr><td colspan="5" style="font-size: 6.5pt; height: 16px;">Fremdhandling Vorhaltefläche</td><td style="width: 12%;">&nbsp;</td></tr>
                                <tr><td colspan="5" style="font-size: 6.5pt; height: 16px;">LCAG Vorhaltefläche</td><td style="width: 12%;">&nbsp;</td></tr>
                                <tr><td colspan="5" style="font-size: 6.5pt; height: 16px;">LCAG Warehouse</td><td style="width: 12%;">&nbsp;</td></tr>
                                <tr><td colspan="5" style="font-size: 6.5pt; height: 16px;">Stückgut Vorhaltefläche</td><td style="width: 12%;">&nbsp;</td></tr>
                                <tr><td colspan="5" style="font-size: 6.5pt; height: 16px;">Stückgut Warehouse</td><td style="width: 12%;">&nbsp;</td></tr>
                                <tr><td colspan="5" style="font-size: 6.5pt; height: 16px;">Trucking Vorhaltefläche</td><td style="width: 12%;">&nbsp;</td></tr>
                                <tr><td colspan="5" style="font-size: 6.5pt; height: 16px;">Breakdown</td><td style="width: 12%;">&nbsp;</td></tr>
                                <tr><td colspan="5" style="font-size: 6.5pt; height: 16px;">Disponent Büro</td><td style="width: 12%;">&nbsp;</td></tr>
                                <tr><td colspan="6" style="font-size: 6.5pt; height: 20px;">Sonstiger Lagerplatz: ___________________</td></tr>
                            </table>
                        </td>
                    </tr>
                </table>

                <!-- UNTERER BLOCK: KONTUR / GEWICHT / UNTERSCHRIFTEN -->
                <table style="margin-top: -1px;">
                    <tr>
                        <!-- KONTUR & MATERIALIEN (60% BREITE) -->
                        <td style="width: 60%; vertical-align: top; padding: 0px;">
                            <table style="width: 100%;">
                                <tr class="header-bg">
                                    <td colspan="4">KONTUR: <b>{contour}</b></td>
                                </tr>
                                <tr>
                                    <td style="width: 25%; font-size: 6.5pt; height: 18px;">Stricke</td>
                                    <td style="width: 25%; font-size: 6.5pt;">Gurten</td>
                                    <td style="width: 25%; font-size: 6.5pt;">EURO - Pal.</td>
                                    <td style="width: 25%; font-size: 6.5pt;">Verzurrösen</td>
                                </tr>
                                <tr>
                                    <td style="font-size: 6.5pt; height: 18px;">Bretter 1,30m</td>
                                    <td style="font-size: 6.5pt;">Bretter 2,00m</td>
                                    <td style="font-size: 6.5pt;">Bretter 2,20m</td>
                                    <td style="font-size: 6.5pt;">Bretter 2,90m</td>
                                </tr>
                                <tr>
                                    <td colspan="4" style="height: 22px; vertical-align: top; font-size: 6.5pt;">
                                        Name / PersNr.: ________________________
                                    </td>
                                </tr>
                                <tr>
                                    <td colspan="4" style="height: 22px; vertical-align: top; font-size: 6.5pt;">
                                        Unterschrift DG: ________________________
                                    </td>
                                </tr>
                            </table>
                        </td>

                        <!-- BRUTTOGEWICHT & UNTERSCHRIFT MA (40% BREITE) -->
                        <td style="width: 40%; vertical-align: top; padding: 0px;">
                            <table style="width: 100%; height: 100%;">
                                <tr>
                                    <td style="height: 40px; vertical-align: top; padding: 4px;">
                                        <b>Grossweight</b><br>
                                        <b>Bruttogewicht:</b> <span style="font-size: 10pt; font-weight: bold;">{weight} kg</span>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="height: 22px; vertical-align: top; font-size: 6.5pt;">
                                        Name / PersNr.: ________________________
                                    </td>
                                </tr>
                                <tr>
                                    <td style="height: 22px; vertical-align: top; font-size: 6.5pt;">
                                        Unterschrift MA: ________________________
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>

                <div class="small-text" style="margin-top: 2px;">Form 752z/25 vie</div>
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
