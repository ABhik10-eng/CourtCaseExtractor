import os
import re
import io
from flask import Flask, render_template, request, send_file
import pypdf
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

app = Flask(__name__)

def parse_courtroom_sections(pdf_path):
    """
    Scans the cause list text to divide blocks by active Courtroom numbers
    """
    courtroom_map = {}
    current_court = "General Roster Bench"
    
    try:
        reader = pypdf.PdfReader(pdf_path)
        for page in reader.pages:
            text = page.extract_text()
            if not text:
                continue
            lines = text.split("\n")
            for line in lines:
                # Catch courtroom headers (e.g., "COURT NO. 1", "BEFORE HON'BLE JUDGE...")
                court_match = re.search(r'(COURT\s+NO\.\s*\d+|BENCH\s*\d+)', line, re.IGNORECASE)
                if court_match:
                    current_court = court_match.group(1).upper()
                
                # Check case signature line structures
                if re.search(r'([A-Z]{2,5}/\d+/\d+)', line):
                    case_match = re.search(r'([A-Z]{2,5}/\d+/\d+)', line).group(1)
                    courtroom_map[case_match] = current_court
    except Exception as e:
        print(f"Courtroom parsing alert: {e}")
    return courtroom_map

def extract_case_details(pdf_path, name_q, number_q):
    """
    Extracts raw text data matching target items out of the main cause list safely
    """
    records = []
    nq_low = name_q.lower()
    num_q_clean = number_q.replace(" ", "").lower() if number_q else None
    
    try:
        reader = pypdf.PdfReader(pdf_path)
        for page in reader.pages:
            text = page.extract_text()
            if not text:
                continue
            lines = text.split("\n")
            current_block = []
            
            for line in lines:
                if re.match(r'^\s*\d+\s+', line) or " vs " in line.lower():
                    if current_block:
                        block_str = " ".join(current_block).lower()
                        matched = False
                        if nq_low in block_str:
                            matched = True
                        if num_q_clean and num_q_clean in block_str.replace(" ", ""):
                            matched = True
                        if matched:
                            records.append(current_block)
                        current_block = []
                current_block.append(line.strip())
            if current_block:
                block_str = " ".join(current_block).lower()
                if nq_low in block_str or (num_q_clean and num_q_clean in block_str.replace(" ", "")):
                    records.append(current_block)
    except Exception as e:
        print(f"Cause list extractor exception: {e}")
    return records

def scan_transfer_orders(pdf_path, case_lines_list):
    """
    Cross-references matching numbers inside the official transfer order memo
    """
    transfer_data = {}
    full_text_log = ""
    
    try:
        reader = pypdf.PdfReader(pdf_path)
        for page in reader.pages:
            t = page.extract_text()
            if t:
                full_text_log += "\n" + t
    except Exception as e:
        print(f"Transfer index mapping error: {e}")
        return {}

    # Isolate global transfer metric counts
    total_transfers_count = len(re.findall(r'(transferred|posted\s+to|ready\s+list)', full_text_log, re.IGNORECASE))
    
    for case_lines in case_lines_list:
        combined = " ".join(case_lines)
        case_match = re.search(r'([A-Z]{2,5}/\d+/\d+)', combined)
        if case_match:
            c_no = case_match.group(1)
            # Pull specific row text lines inside order mapping to extract match
            lines = full_text_log.split("\n")
            matched_note = "No direct modification matching found inside current general transfer order sheets."
            for line in lines:
                if c_no in line or any(word in line.lower() for word in combined.lower().split()[:2] if len(word) > 4):
                    matched_note = f"Impact Alert: {line.strip()}"
                    break
            transfer_data[c_no] = {
                "note": matched_note,
                "global_stat": f"Total document reshuffles parsed: {total_transfers_count} actions tracked."
            }
    return transfer_data

def format_row(case_lines, court_map, transfer_map, idx):
    full_text = " ".join(case_lines)
    sr_match = re.match(r'^\s*(\d+)', full_text)
    sr_no = sr_match.group(1) if sr_match else str(idx)
    
    case_no = "Details Unspecified"
    case_match = re.search(r'([A-Z]{2,5}/\d+/\d+)', full_text)
    if case_match:
        case_no = case_match.group(1)
        
    courtroom = court_map.get(case_no, "Roster Court assignment pending")
    
    parties = full_text
    if " vs " in full_text.lower():
        parts = re.split(r'\s+vs\s+', full_text, flags=re.IGNORECASE)
        parties = f"{parts[0].strip()}\nVS\n{parts[1].split('Notice')[0].strip()}"

    t_info = transfer_map.get(case_no, {"note": "No direct transfer note identified.", "global_stat": "0 active shifts"})
    final_notes = f"Location: {courtroom}\n\nTransfer Intel:\n{t_info['note']}\n\n({t_info['global_stat']})"
    
    return [sr_no, case_no, parties, final_notes]

def create_summary_pdf(cases, court_map, transfer_map, search_name):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=14, textColor=colors.HexColor("#1E293B"), spaceAfter=15)
    cell_style = ParagraphStyle('CellStyle', parent=styles['Normal'], fontSize=8, leading=11)
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=9, fontName="Helvetica-Bold", textColor=colors.white)
    
    story.append(Paragraph(f"CROSS-REFERENCE SYSTEM INTEL REPORT FOR: {search_name.upper()}", title_style))
    story.append(Spacer(1, 5))
    
    table_data = [[
        Paragraph("Sr No.", header_style),
        Paragraph("Case Reference ID", header_style),
        Paragraph("Party Particulars (Petitioner vs Respondent)", header_style),
        Paragraph("Cross-Referenced Courtroom Allocation & Transfer Notes", header_style)
    ]]
    
    if not cases:
        table_data.append(["-", "-", "No matches located matching targets across daily metrics.", "-"])
    else:
        for idx, case_lines in enumerate(cases, 1):
            row = format_row(case_lines, court_map, transfer_map, idx)
            table_data.append([
                Paragraph(str(row[0]), cell_style),
                Paragraph(str(row[1]), cell_style),
                Paragraph(str(row[2]).replace("\n", "<br/>"), cell_style),
                Paragraph(str(row[3]).replace("\n", "<br/>"), cell_style)
            ])
            
    column_widths = [40, 110, 250, 352]
    court_table = Table(table_data, colWidths=column_widths, repeatRows=1)
    court_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    
    story.append(court_table)
    doc.build(story)
    buffer.seek(0)
    return buffer

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'cause_pdf' not in request.files or 'transfer_pdf' not in request.files:
            return "Please provide both PDF files.", 400
            
        c_file = request.files['cause_pdf']
        t_file = request.files['transfer_pdf']
        search_name = request.form.get('search_name', '')
        case_num = request.form.get('case_number', '')
        
        if c_file.filename == '' or t_file.filename == '':
            return "Invalid file attachments.", 400
            
        c_path = "temp_cause.pdf"
        t_path = "temp_transfer.pdf"
        
        c_file.save(c_path)
        t_file.save(t_path)
        
        # Core data lookup
        court_map = parse_courtroom_sections(c_path)
        matched_cases = extract_case_details(c_path, search_name, case_num)
        transfer_map = scan_transfer_orders(t_path, matched_cases)
        
        if os.path.exists(c_path): os.remove(c_path)
        if os.path.exists(t_path): os.remove(t_path)
        
        output_pdf = create_summary_pdf(matched_cases, court_map, transfer_map, search_name)
        return send_file(output_pdf, mimetype='application/pdf', as_attachment=True, download_name="Court_Intelligence_Report.pdf")
        
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
