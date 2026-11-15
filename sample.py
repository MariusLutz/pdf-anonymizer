"""Generate synthetic fixtures only. No real personal information."""
from pathlib import Path
import io
import pymupdf as fitz
from PIL import Image, ImageDraw


def create_sample(path):
    pdf = fitz.open()
    p = pdf.new_page()
    p.insert_text((40, 40), "SYNTHETIC REIMBURSEMENT CLAIM", fontsize=18)
    lines = ["Name: Alice Example", "Address: 123 Example Street", "Email: alice@example.invalid",
             "Phone: +41 79 123 45 67", "IBAN: CH93 0076 2011 6238 5295 7", "Date of birth: 1980-03-21",
             "Employee ID: EMP-123456", "Card: 4111 1111 1111 1111", "Signature: Alice Example"]
    for y, text in enumerate(lines): p.insert_text((40, 80+y*24), text)
    p.insert_text((40, 335), "Date                 Category             Amount          Status")
    p.insert_text((40, 360), "2026-11-01        Rail travel             CHF 125.50     Paid")
    p.insert_text((40, 385), "2026-11-02        Hotel                    CHF 240.00     Paid")
    p.insert_text((40, 420), "Total: CHF 365.50     Tax: CHF 27.39     Reimbursement: CHF 365.50")
    p.insert_text((40, 460), "Conditions: original receipts required; submit within 30 days.")
    widget = fitz.Widget()
    widget.field_name, widget.field_value = "Customer name", "Bob Sample"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = fitz.Rect(40, 495, 240, 520)
    p.add_widget(widget)
    check = fitz.Widget()
    check.field_name = "Receipt attached"
    check.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    check.rect = fitz.Rect(40, 540, 56, 556)
    check.field_value = "Yes"
    p.add_widget(check)
    p.insert_text((65, 553), "Receipt attached")
    note = p.add_text_annot((500, 50), "Secret annotation: Alice Example")
    note.update()
    # Local QR encoder; no payload is decoded or visited by the application.
    import cv2
    qr = cv2.QRCodeEncoder_create().encode("SYNTHETIC-PERSON-ALICE")
    qrimage = Image.fromarray(qr).convert("RGB").resize((150, 150), Image.Resampling.NEAREST)
    buf = io.BytesIO()
    qrimage.save(buf, format="PNG")
    p.insert_image(fitz.Rect(390, 540, 540, 690), stream=buf.getvalue())
    # Second page is a rotated searchable table.
    p = pdf.new_page(width=595, height=842)
    p.insert_text((40, 60), "Name: Rotated Person")
    p.insert_text((40, 95), "2026-11-03   Meals   EUR 42.00   Approved")
    p.set_rotation(90)
    # Third page is image-only, including a handwritten-like signature region.
    im = Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(im)
    draw.text((50, 50), "SCANNED SYNTHETIC RECEIPT", fill="black", font_size=30)
    draw.text((50, 120), "Name: Scanned Person", fill="black", font_size=28)
    draw.text((50, 200), "2026-11-04  Bus ticket  CHF 12.00", fill="black", font_size=28)
    draw.line([(60, 330), (130, 280), (95, 350), (200, 310), (300, 340)], fill="black", width=4)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    p = pdf.new_page(width=500, height=350)
    p.insert_image(p.rect, stream=buf.getvalue())
    pdf.set_metadata({"author": "Alice Example", "title": "Secret customer document"})
    pdf.set_toc([[1, "Alice Example private bookmark", 1]])
    pdf.embfile_add("private.txt", b"Alice Example - secret attachment")
    pdf.save(path)
    pdf.close()


if __name__ == "__main__":
    Path("examples").mkdir(exist_ok=True)
    create_sample("examples/synthetic-claim.pdf")
