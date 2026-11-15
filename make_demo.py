from pathlib import Path
from engine import Document, Mark
from sample import create_sample

Path("examples").mkdir(exist_ok=True)
create_sample("examples/synthetic-claim.pdf")
doc = Document("examples/synthetic-claim.pdf")
doc.run_ocr(2, str(Path("tessdata").resolve()))
marks = doc.detect(["Alice Example", "Bob Sample", "Rotated Person", "Scanned Person"])
for m in marks: m.status = "accepted"
marks.append(Mark(2, (20, 130, 170, 180), "SIGNATURE", "", "accepted"))
doc.export("examples/anonymized-claim.pdf", marks, "secure")
Path("examples/anonymized-claim.txt").write_text(doc.text_export(marks), encoding="utf-8")
doc.close()
import pymupdf
with pymupdf.open("examples/anonymized-claim.pdf") as pdf:
    for i, p in enumerate(pdf):
        p.get_pixmap().save(f"examples/preview-{i+1}.png")
