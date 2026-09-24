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

def extract_cases_by_name(pdf_path, search_name):
    extracted_records = []
    search_name_lower = search_name.lower()
    
    try:
        reader = pypdf.PdfReader(pdf_path)
        for page in reader.pages:
            text = page.extract_text()
            if not text:
                continue
            
            lines = text.split("\n")
            current_block = []
            
            for line in lines:
                # Check for row delimiters (Serial numbers, Item indexes, or Notification tags)
                if re.match(r'^\s*\d+\s+', line) or "notification" in line.lower() or "o.m." in line.lower():
                    if current_block:
                        block_str = " ".join(current_block)
                        if search_name_lower in block_str.lower():
                            extracted_records.append(current_block)
                        current_block = []
                current_block.append(line.strip())
                
            if current_block:
                block_str = " ".join(current_block)
                if search_name_lower in block_str.lower():
                    extracted_records.append(current_block)
    except Exception as e:
        print(f"Error reading PDF: {e}")
        
    return extracted_records

def advanced_case_parser(lines, fallback_idx):
    """
    Intelligently parses context blocks, scanning patterns for dates, rooms, transfers, or counsel logs.
    """
    full_text = " ".join(lines)
    
    # Extract structural indices
    sr_match = re.match(r'^\s*(\d+)', full_text)
    sr_no = sr_match.group(1) if sr_match else str(fallback_idx)
    
    # 1. Look for Date values inside lists (e.g., Fixed Date: 25/09/2026 or 15-04-2026)
    date_match = re.search(r'(\d{1,2}[\./-]\d{1,2}[\./-]\d{4})', full_text)
    fixed_date = date_match.group(1) if date_match else "As per Listing"
    
    # 2. Check if this is a Transfer Order or a Cause List entry
    is_transfer = any(k in full_text.lower() for k in ["transfer", "posted", "posting", "assigned", "office memorandum"])
    
    if is_transfer:
        doc_type = "Transfer Order"
        # Parse transfer metrics (From -> To structures)
        route_info = "Transfer/Posting Notification details matching target."
        station_matches = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', full_text)
        if len(station_matches) >= 2:
            route_info = f"Movement tracked in official notification."
            
        counsel_or_details = full_text
        return [sr_no, doc_type, f"Date: {fixed_date}", route_info, counsel_or_details]
        
    else:
        doc_type = "Court Cause List"
        case_info = "Case Listing"
        court_room = "Main Bench"
        
        # Pull Case details strings
        case_match = re.search(r'([A-Z]{2,5}/\d+/\d+)', full_text)
        if case_match:
            case_info = case_match.group(1)
            
        # Parse Courtroom number strings
        room_match = re.search(r'(?:Court\s+No\.|Court\b)\s*(\d+)', full_text, re.IGNORECASE)
        if room_match:
            court_room = f"Court Room {room_match.group(1)}"
            
        parties = full_text
        if " vs " in full_text.lower():
            parts = re.split(r'\s+vs\s+', full_text, flags=re.IGNORECASE)
            parties = f"{parts[0].strip()} \nVS\n {parts[1].split('   ')[0].strip()}"
            
        metadata = f"Type: {doc_type}\n{court_room}\nListed: {fixed_date}"
        return [sr_no, case_info, parties, metadata, full_text]

def create_summary_pdf(records, search_name):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=14, textColor=colors.HexColor("#0F172A"), spaceAfter=15)
    cell_style = ParagraphStyle('CellStyle', parent=styles['Normal'], fontSize=8, leading=11)
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=9, fontName="Helvetica-Bold", textColor=colors.black)
    
    story.append(Paragraph(f"COMPREHENSIVE CASE DISPOSITION & TRACKING REPORT: {search_name.upper()}", title_style))
    story.append(Spacer(1, 5))
    
    # 5 Strategic Case Diary Data Categories
    table_data = [[
        Paragraph("<b>Index</b>", header_style),
        Paragraph("<b>Matter Reference / ID</b>", header_style),
        Paragraph("<b>Target Details / Party Layout</b>", header_style),
        Paragraph("<b>Case Management Status & Schedule</b>", header_style),
        Paragraph("<b>Extracted Raw Context Block</b>", header_style)
    ]]
    
    if not records:
        table_data.append(["-", "-", f"No matching litigation logs found for tracking parameter.", "-", "-"])
    else:
        for idx, lines in enumerate(records, 1):
            cols = advanced_case_parser(lines, idx)
            table_data.append([
                Paragraph(str(cols[0]), cell_style),
                Paragraph(str(cols[1]).replace("\n", "<br/>"), cell_style),
                Paragraph(str(cols[2]).replace("\n", "<br/>"), cell_style),
                Paragraph(str(cols[3]).replace("\n", "<br/>"), cell_style),
                Paragraph(str(cols[4]), cell_style)
            ])
            
    column_widths = [40, 110, 180, 150, 272]
    
    court_table = Table(table_data, colWidths=column_widths, repeatRows=1)
    court_table.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 1, colors.slate),
        ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.black),
        ('LINEBELOW', (0, 1), (-1, -1), 0.5, colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    story.append(court_table)
    doc.build(story)
    buffer.seek(0)
    return buffer

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'pdf_file' not in request.files or request.form.get('search_name') == '':
            return "Missing configuration metrics.", 400
        file = request.files['pdf_file']
        search_name = request.form.get('search_name')
        if file.filename == '' or not file.filename.endswith('.pdf'):
            return "Invalid file mapping selection.", 400
            
        temp_path = "temp_court_list.pdf"
        file.save(temp_path)
        matched_records = extract_cases_by_name(temp_path, search_name)
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        output_pdf = create_summary_pdf(matched_records, search_name)
        return send_file(output_pdf, mimetype='application/pdf', as_attachment=True, download_name=f"Case_Diary_{search_name.replace(' ', '_')}.pdf")
        
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
