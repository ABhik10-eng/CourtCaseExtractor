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
            current_case = []
            
            for line in lines:
                if re.match(r'^\s*\d+\s+', line):
                    if current_case:
                        case_block_str = " ".join(current_case)
                        if search_name_lower in case_block_str.lower():
                            extracted_records.append(current_case)
                        current_case = []
                current_case.append(line.strip())
                
            if current_case:
                case_block_str = " ".join(current_case)
                if search_name_lower in case_block_str.lower():
                    extracted_records.append(current_case)
    except Exception as e:
        print(f"Error reading PDF: {e}")
        
    return extracted_records

def format_court_columns(case_lines, fallback_idx):
    full_text = " ".join(case_lines)
    
    sr_match = re.match(r'^\s*(\d+)', full_text)
    sr_no = sr_match.group(1) if sr_match else str(fallback_idx)
    
    case_info = "Case Details"
    parties = full_text
    pet_counsel = "As per List"
    res_counsel = "C.S.C."

    case_match = re.search(r'([A-Z]{2,5}/\d+/\d+)', full_text)
    if case_match:
        case_info = case_match.group(1)
        loc_match = re.search(case_match.group(1) + r'\s+([A-Z\s\(\)]+?)(?=VS|Vs|$)', full_text)
        if loc_match:
            case_info += "\n" + loc_match.group(1).strip()

    if " vs " in full_text.lower():
        parts = re.split(r'\s+vs\s+', full_text, flags=re.IGNORECASE)
        if len(parts) >= 2:
            p1 = parts[0]
            p2 = parts[1]
            
            p1_clean = re.sub(r'^\s*\d+\s+', '', p1)
            p1_clean = re.sub(r'[A-Z]{2,5}/\d+/\d+', '', p1_clean)
            
            counsel_split = re.split(r'\s{2,}', p2)
            p2_clean = counsel_split[0]
            
            parties = f"{p1_clean.strip()}\n\nVS\n\n{p2_clean.strip()}"
            
            if len(counsel_split) > 1:
                pet_counsel = counsel_split[1].strip()
            if len(counsel_split) > 2:
                res_counsel = counsel_split[2].strip()

    return [sr_no, case_info, parties, pet_counsel, res_counsel]

def create_summary_pdf(cases, search_name):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=15, textColor=colors.HexColor("#000000"), spaceAfter=15)
    cell_style = ParagraphStyle('CellStyle', parent=styles['Normal'], fontSize=8.5, leading=12)
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=9.5, fontName="Helvetica-Bold", textColor=colors.black)
    
    story.append(Paragraph(f"HIGH COURT OF JUDICATURE AT ALLAHABAD - FILTERED REPORT FOR: {search_name.upper()}", title_style))
    story.append(Spacer(1, 5))
    
    table_data = [[
        Paragraph("<b>Sr No.</b>", header_style),
        Paragraph("<b>Case Type / No.</b>", header_style),
        Paragraph("<b>Parties (Petitioner vs Respondent)</b>", header_style),
        Paragraph("<b>Petitioner Counsel</b>", header_style),
        Paragraph("<b>Respondent Counsel</b>", header_style)
    ]]
    
    if not cases:
        table_data.append(["-", "-", f"No matching cases found for '{search_name}'", "-", "-"])
    else:
        for idx, case_lines in enumerate(cases, 1):
            cols = format_court_columns(case_lines, idx)
            table_data.append([
                Paragraph(cols[0], cell_style),
                Paragraph(cols[1].replace("\n", "<br/>"), cell_style),
                Paragraph(cols[2].replace("\n", "<br/>"), cell_style),
                Paragraph(cols[3].replace("\n", "<br/>"), cell_style),
                Paragraph(cols[4].replace("\n", "<br/>"), cell_style)
            ])
            
    column_widths = [40, 120, 292, 150, 150]
    
    court_table = Table(table_data, colWidths=column_widths, repeatRows=1)
    court_table.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 1, colors.black),
        ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.black),
        ('LINEBELOW', (0, 1), (-1, -1), 0.5, colors.gray),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    
    story.append(court_table)
    doc.build(story)
    buffer.seek(0)
    return buffer

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'pdf_file' not in request.files or request.form.get('search_name') == '':
            return "Please provide both a PDF file and a Name.", 400
        file = request.files['pdf_file']
        search_name = request.form.get('search_name')
        if file.filename == '' or not file.filename.endswith('.pdf'):
            return "Invalid file selection", 400
            
        temp_path = "temp_court_list.pdf"
        file.save(temp_path)
        matched_cases = extract_cases_by_name(temp_path, search_name)
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        output_pdf = create_summary_pdf(matched_cases, search_name)
        return send_file(output_pdf, mimetype='application/pdf', as_attachment=True, download_name=f"Court_Format_{search_name.replace(' ', '_')}.pdf")
        
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
