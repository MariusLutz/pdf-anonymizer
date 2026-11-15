"""Offline PDF sanitization. Original objects are never copied into output."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import re
import os
import tempfile
import pymupdf as fitz
from PIL import Image, ImageDraw


@dataclass
class Mark:
    page: int
    rect: tuple
    kind: str
    text: str = ""
    status: str = "pending"
    reason: str = "Heuristic: review required"


PATTERNS = {
    "GERMAN TAX ID": r"(?<!\d)(?:\d[ \t.-]?){10}\d(?!\d)",
    "EMAIL": r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
    "ACCOUNT": r"\b[A-Z]{2}\s?\d{2}(?:\s?[A-Z0-9]){11,30}\b",
    "PHONE": r"(?<!\w)(?:\+\d{1,3}[ .()-]*)?(?:\(?\d{2,4}\)?[ .-]){2,4}\d{2,4}(?!\w)",
    "PERSONAL ID": r"\b\d{3}-\d{2}-\d{4}\b|\b756[ .]\d{4}[ .]\d{4}[ .]\d{2}\b",
    "CARD": r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)",
}
LABELS = {
    "NAME": r"(?:full name|employee name|customer name|patient name|name|nom|vorname|nachname)",
    "ADDRESS": r"(?:postal address|home address|address|adresse|anschrift)",
    "DATE OF BIRTH": r"(?:date of birth|birth date|dob|geburtsdatum|date de naissance)",
    "ACCOUNT": r"(?:bank account|account number|account no\.?|iban|kontonummer|kontoinhaber|mandatsreferenz|kundenreferenz|kundennummer|account reference|aktenzeichen)",
    "PERSONAL ID": r"(?:passport(?: number)?|national id|id number|social security|employee id|customer id|ahv|avs|personnel number|steuer[ -]?(?:id|idnr\.?|identifikationsnummer|nummer)|identifikationsnummer|idnr\.?)",
    "SIGNATURE": r"(?:signature|signed by|unterschrift)",
}


def luhn(value):
    digits = [int(c) for c in value if c.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    return sum((n * 2 - 9 if n > 4 else n * 2) if i % 2 else n
               for i, n in enumerate(reversed(digits))) % 10 == 0


def normalized(text):
    return re.sub(r"\W", "", text).casefold()


class Document:
    def __init__(self, path, password=""):
        self.path = Path(path).resolve()
        self.pdf = fitz.open(self.path)
        if self.pdf.needs_pass and not self.pdf.authenticate(password):
            self.pdf.close()
            raise ValueError("Password required or incorrect password.")
        if not self.pdf.is_pdf or not len(self.pdf):
            self.pdf.close()
            raise ValueError("Select a non-empty PDF.")
        self.ocr = {}
        self.warnings = []

    def close(self):
        self.pdf.close()

    def words(self, index):
        page = self.pdf[index]
        words = list(page.get_text("words", sort=True))
        if index in self.ocr:
            words = self.ocr[index]
        # Form values may not appear in the ordinary text layer.
        for n, w in enumerate(page.widgets() or []):
            if w.field_type not in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                if w.field_value:
                    words.append((*tuple(w.rect), str(w.field_value), 100000 + n, 0, 0))
        return words

    def run_ocr(self, index, tessdata, language="eng"):
        # PyMuPDF uses local Tesseract data; it never downloads language models.
        if not Path(tessdata).is_dir():
            raise ValueError("Choose a local tessdata folder containing .traineddata files.")
        page = self.pdf[index]
        tp = page.get_textpage_ocr(language=language, dpi=200, full=True, tessdata=tessdata)
        self.ocr[index] = page.get_text("words", textpage=tp, sort=True)

    def detect(self, custom=()):
        found = []
        self.warnings = []
        def add(index, rect, kind, text="", reason="Heuristic: review required"):
            rect = fitz.Rect(rect)
            rect = (rect + (-1, -1, 1, 1)) & self.pdf[index].rect * self.pdf[index].derotation_matrix
            if not rect.is_empty:
                found.append(Mark(index, tuple(rect), kind, text, reason=reason))
        for i, page in enumerate(self.pdf):
            words = self.words(i)
            if not words:
                self.warnings.append(f"Page {i+1}: no readable text. Run local OCR or mark manually.")
            lines = {}
            for word in words:
                lines.setdefault((word[5], word[6]), []).append(word)
            for row in lines.values():
                row.sort(key=lambda w: w[0])
                text = " ".join(w[4] for w in row)
                spans, offset = [], 0
                for word in row:
                    spans.append((offset, offset + len(word[4]), word))
                    offset += len(word[4]) + 1
                def match_range(start, end, kind, value):
                    hits = [w for a, b, w in spans if a < end and b > start]
                    if hits:
                        rect = fitz.Rect(hits[0][:4])
                        for w in hits[1:]:
                            rect |= fitz.Rect(w[:4])
                        add(i, rect, kind, value)
                for kind, pattern in PATTERNS.items():
                    for m in re.finditer(pattern, text, re.I):
                        if kind == "PHONE" and (re.fullmatch(r"\d{4}-\d{2}-\d{2}", m[0]) or len(re.sub(r"\D", "", m[0])) < 9):
                            continue
                        if kind == "CARD" and not luhn(m[0]):
                            continue
                        match_range(*m.span(), kind, m[0])
                for kind, label in LABELS.items():
                    m = re.search(r"\b" + label + r"\s*[:#]\s*(\S.*)$", text, re.I)
                    if m:
                        match_range(*m.span(1), kind, m[1])
                for m in re.finditer(r"\b[\wÄÖÜäöüß.-]*(?:straße|strasse|str\.|weg|platz|allee|gasse|ring)\s+\d+\s*[a-z]?\b|\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+\b", text):
                    match_range(*m.span(), "ADDRESS", m[0])
                if re.search(r"\b(signature|unterschrift)\s*:?\s*$", text, re.I):
                    r = fitz.Rect(row[-1][:4])
                    add(i, (r.x1+4, r.y0-12, min(r.x1+200, page.rect.width), r.y1+28), "SIGNATURE", reason="Possible signature area beside label; inspect and resize manually if needed")
                # Street-like text is deliberately uncertain, never auto-accepted.
                for m in re.finditer(r"\b\d{1,5}\s+(?:\w+\s+){1,4}(?:Street|Road|Avenue|Lane|Drive|St|Rd)\b", text, re.I):
                    match_range(*m.span(), "ADDRESS", m[0])
            for term in custom:
                if term.strip():
                    for rect in page.search_for(term.strip()):
                        add(i, rect, "CUSTOM", term.strip(), "User-specified term; check extent")
                    # Includes OCR and form values.
                    for row in lines.values():
                        value = " ".join(w[4] for w in row)
                        if term.casefold() in value.casefold():
                            # Limit to matching word span rather than the entire financial row.
                            offset = 0
                            for m in re.finditer(re.escape(term), value, re.I):
                                hits = []
                                offset = 0
                                for w in row:
                                    if offset < m.end() and offset + len(w[4]) > m.start():
                                        hits.append(w)
                                    offset += len(w[4]) + 1
                                if hits:
                                    rect = fitz.Rect(hits[0][:4])
                                    for w in hits[1:]: rect |= fitz.Rect(w[:4])
                                    add(i, rect, "CUSTOM", term)
            for w in page.widgets() or []:
                name = (w.field_label or "") + " " + (w.field_name or "")
                for kind, label in LABELS.items():
                    if re.search(label, name, re.I) and w.field_type not in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                        add(i, w.rect, kind, str(w.field_value or ""), "Form field name suggests identifier")
                        break
            # Detect QR geometry locally without decoding payloads or opening links.
            try:
                import cv2
                import numpy as np
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                ok, points = cv2.QRCodeDetector().detectMulti(img)
                if ok:
                    for quad in points:
                        r = fitz.Rect(float(quad[:, 0].min()/2), float(quad[:, 1].min()/2), float(quad[:, 0].max()/2), float(quad[:, 1].max()/2)) * page.derotation_matrix
                        add(i, r + (-4, -4, 4, 4), "QR CODE", reason="QR region: payload not inspected")
            except ImportError:
                self.warnings.append("QR detection unavailable: install optional OpenCV dependency.")
            except Exception:
                self.warnings.append(f"Page {i+1}: QR detection failed; inspect manually.")
        unique = {}
        for mark in found:
            key = (mark.page, tuple(round(v, 1) for v in mark.rect), mark.kind)
            unique[key] = mark
        return list(unique.values())

    def accepted(self, marks):
        if any(m.status == "pending" for m in marks):
            raise ValueError("Accept or reject every pending suggestion before exporting.")
        return [m for m in marks if m.status == "accepted"]

    def text_export(self, marks, tessdata=None, language="eng"):
        """OCR only sanitized pixels, never copy the source text layer into text output."""
        import sys
        accepted = self.accepted(marks)
        tessdata = tessdata or str(Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "tessdata")
        if not Path(tessdata, language.split("+")[0] + ".traineddata").is_file():
            raise ValueError("Local OCR language data is required for safe text export.")
        chunks = ["DRAFT OCR TEXT - final identifier review required; check amounts before sharing.\n"]
        for i, page in enumerate(self.pdf):
            pix = page.get_pixmap(matrix=page.derotation_matrix * fitz.Matrix(3, 3), colorspace=fitz.csRGB, alpha=False, annots=True)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            draw = ImageDraw.Draw(im)
            local = [m for m in accepted if m.page == i]
            for m in local:
                r = fitz.Rect(m.rect)
                draw.rectangle((int(r.x0*3), int(r.y0*3), int(r.x1*3+1), int(r.y1*3+1)), fill="black")
            safe_pix = fitz.Pixmap(fitz.csRGB, im.width, im.height, im.tobytes(), False)
            safe_pix.set_dpi(216, 216)
            with fitz.open(stream=safe_pix.pdfocr_tobytes(language=language, tessdata=tessdata), filetype="pdf") as ocr_pdf:
                words = list(ocr_pdf[0].get_text("words", sort=True))
            # Exclude OCR artefacts intersecting redacted areas, then add labels.
            tokens = []
            for w in words:
                if not any(fitz.Rect(w[:4]).intersects(fitz.Rect(m.rect)) for m in local):
                    tokens.append((w[0], w[1], w[3], w[4]))
            seen = set()
            for m in local:
                r = fitz.Rect(m.rect)
                key = tuple(round(v/5) for v in r)
                if key not in seen:
                    tokens.append((r.x0, r.y0, r.y1, f"[{m.kind} REDACTED]"))
                    seen.add(key)
            tokens.sort(key=lambda t: (t[1], t[0]))
            rows = []
            for token in tokens:
                row = next((row for row in rows if abs(row[0][1]-token[1]) < 6), None)
                if row is None: rows.append([token])
                else: row.append(token)
            chunks.append(f"\n--- Page {i+1} ---\n")
            chunks.extend(" ".join(t[3] for t in sorted(row)) + "\n" for row in rows)
            if not rows: chunks.append("[No text recognized on this page.]\n")
        result = "".join(chunks)
        for mark in sorted(accepted, key=lambda m: len(m.text), reverse=True):
            if mark.text.strip():
                pattern = r"\s+".join(re.escape(t) for t in mark.text.split())
                result = re.sub(pattern, lambda _: f"[{mark.kind} REDACTED]", result, flags=re.I)
        return result

    def export(self, target, marks, mode="flattened", dpi=200):
        target = Path(target).resolve()
        if target == self.path:
            raise ValueError("Export to a new file; the original must remain untouched.")
        if mode not in ("secure", "flattened"):
            raise ValueError("Unknown export mode")
        accepted = self.accepted(marks)
        result = fitz.open()
        # Secure mode applies true redactions on a private in-memory copy first.
        work = fitz.open(stream=self.pdf.tobytes(), filetype="pdf")
        boxes = []
        try:
            for i, page in enumerate(work):
                local = [m for m in accepted if m.page == i]
                # Bake visible form values and checkboxes before removing source objects.
                work.bake(annots=True, widgets=True) if i == 0 else None
                if mode == "secure":
                    for m in local: page.add_redact_annot(fitz.Rect(m.rect), fill=(0, 0, 0))
                    page.apply_redactions(images=2, graphics=1, text=0)
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72), colorspace=fitz.csRGB, alpha=False, annots=True)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                draw = ImageDraw.Draw(image)
                page_boxes = []
                for m in local:
                    rect = fitz.Rect(m.rect) * page.rotation_matrix
                    r = (max(0, int(rect.x0*dpi/72)), max(0, int(rect.y0*dpi/72)), min(pix.width-1, int(rect.x1*dpi/72+1)), min(pix.height-1, int(rect.y1*dpi/72+1)))
                    draw.rectangle(r, fill="black")
                    page_boxes.append(tuple(rect))
                clean = result.new_page(width=page.rect.width, height=page.rect.height)
                clean.insert_image(clean.rect, pixmap=fitz.Pixmap(fitz.csRGB, image.width, image.height, image.tobytes(), False))
                boxes.append(page_boxes)
            result.set_metadata({})
            result.set_toc([])
            fd, temp = tempfile.mkstemp(suffix=".pdf", prefix=".anonymized-", dir=target.parent)
            os.close(fd)
            try:
                result.save(temp, garbage=4, deflate=True, clean=True, no_new_id=True)
                report = verify(temp, accepted, boxes)
                if not report["checks_passed"]:
                    raise ValueError("Export verification failed. Output was not published.")
                os.replace(temp, target)
            finally:
                if os.path.exists(temp): os.unlink(temp)
            report["mode"] = mode
            report["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
            report_path = target.with_suffix(".verification.json")
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            return report
        finally:
            work.close()
            result.close()


def verify(path, marks, boxes):
    failures = []
    with fitz.open(path) as pdf:
        text = normalized("\n".join(p.get_text() for p in pdf))
        if any(normalized(m.text) and normalized(m.text) in text for m in marks):
            failures.append("A removed term remains in extracted text.")
        if pdf.embfile_count() or pdf.get_toc() or pdf.get_xml_metadata():
            failures.append("Document-level objects remain.")
        if any(pdf.metadata.get(k) for k in ("title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate")):
            failures.append("Identifying metadata remains.")
        for i, page in enumerate(pdf):
            if list(page.annots() or []) or list(page.widgets() or []) or page.get_links():
                failures.append(f"Page {i+1}: annotations, forms or links remain.")
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            for b in boxes[i]:
                r = fitz.Rect(b)
                # Interior check avoids interpolation at the black boundary.
                crop = im.crop((int(r.x0*2)+2, int(r.y0*2)+2, max(int(r.x0*2)+3, int(r.x1*2)-2), max(int(r.y0*2)+3, int(r.y1*2)-2)))
                if max(hi for lo, hi in crop.getextrema()) > 30:
                    failures.append(f"Page {i+1}: redaction coverage check failed.")
        return {"checks_passed": not failures, "failures": failures, "pages": len(pdf),
                "redaction_count": len(marks), "all_pages_rendered": True,
                "review_required": True, "anonymity_certified": False,
                "limitations": ["Checks cover selected rectangles, not all possible personal information.",
                                "Visible unmarked text, handwriting, faces, logos, barcodes and QR codes may identify people.",
                                "Raster output has no searchable text layer; OCR recognition is not a proof of anonymity.",
                                "Text export uses OCR of sanitized pixels; recognition errors and missing content require manual review.",
                                "Review every output page and the text file before sharing."]}
