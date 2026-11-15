import socket
import pytest
import pymupdf as fitz
from engine import Document, Mark
from sample import create_sample


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.pdf"
    create_sample(path)
    return path


@pytest.mark.parametrize("mode", ["secure", "flattened"])
def test_all_document_types_and_privacy(source, tmp_path, mode, monkeypatch):
    def no_network(*args, **kwargs): raise AssertionError("Network access attempted")
    monkeypatch.setattr(socket, "socket", no_network)
    original = source.read_bytes()
    doc = Document(source)
    marks = doc.detect(["Alice Example", "Rotated Person"])
    assert any(m.kind == "EMAIL" for m in marks)
    assert any(m.kind == "QR CODE" for m in marks)
    assert any(m.text == "Bob Sample" for m in marks)
    assert any(m.kind == "CARD" for m in marks)
    assert any(m.kind == "DATE OF BIRTH" for m in marks)
    for m in marks: m.status = "accepted"
    marks.append(Mark(2, (20, 50, 350, 85), "NAME", "Scanned Person", "accepted"))
    marks.append(Mark(2, (20, 130, 170, 180), "SIGNATURE", "", "accepted"))
    target = tmp_path / f"{mode}.pdf"
    report = doc.export(target, marks, mode)
    assert report["checks_passed"] and report["review_required"]
    with fitz.open(target) as out:
        assert len(out) == 3
        assert out[1].rect == doc.pdf[1].rect
        assert out.embfile_count() == 0
        assert not out.get_toc()
        assert all(not list(p.widgets() or []) and not list(p.annots() or []) for p in out)
        assert not any(p.get_text().strip() for p in out)
        # Output object streams contain only rebuilt page pixels, never source strings.
        for i in range(1, out.xref_length()):
            obj = out.xref_object(i).encode()
            assert b"Alice" not in obj and b"Bob Sample" not in obj
    text = doc.text_export(marks)
    assert "Alice Example" not in text
    assert "Bob Sample" not in text
    assert "Rotated Person" not in text
    assert "CHF 365.50" in text
    assert "2026-11-01" in text
    assert "[NAME REDACTED]" in text
    assert "original receipts required" in text
    assert source.read_bytes() == original
    doc.close()


def test_pending_and_original_protection(source, tmp_path):
    doc = Document(source)
    marks = doc.detect()
    with pytest.raises(ValueError, match="pending"): doc.export(tmp_path / "out.pdf", marks)
    with pytest.raises(ValueError, match="pending"): doc.text_export(marks)
    with pytest.raises(ValueError, match="original"): doc.export(source, [])
    doc.close()


def test_rejected_and_partial_words(source):
    doc = Document(source)
    word = next(w for w in doc.words(0) if w[4] == "alice@example.invalid")
    rect = (word[0], word[1], word[0]+2, word[3])
    mark = Mark(0, rect, "EMAIL", "", "accepted")
    assert "alice@example.invalid" not in doc.text_export([mark])
    mark.status = "rejected"
    assert "alice@example.invalid" in doc.text_export([mark])
    doc.close()


def test_missing_ocr_data(source):
    doc = Document(source)
    with pytest.raises(ValueError, match="tessdata"): doc.run_ocr(2, "missing-folder")
    doc.close()


def test_financial_values_not_suggested(source):
    doc = Document(source)
    marks = doc.detect()
    assert not any("365.50" in m.text or "2026-11-01" in m.text for m in marks)
    doc.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotation_geometry(tmp_path, rotation):
    path = tmp_path / "rotate.pdf"
    pdf = fitz.open()
    page = pdf.new_page(width=300, height=400)
    page.insert_text((50, 80), "SECRET123")
    page.insert_text((50, 160), "CHF 100.00")
    page.set_rotation(rotation)
    pdf.save(path)
    pdf.close()
    doc = Document(path)
    marks = doc.detect(["SECRET123"])
    assert marks
    for m in marks: m.status = "accepted"
    assert doc.export(tmp_path / "clean.pdf", marks)["checks_passed"]
    assert "SECRET123" not in doc.text_export(marks)
    assert "CHF 100.00" in doc.text_export(marks)
    doc.close()


def test_hidden_text_never_reappears(tmp_path):
    path = tmp_path / "hidden.pdf"
    pdf = fitz.open()
    p = pdf.new_page()
    p.insert_text((40, 60), "INVISIBLEPERSON", render_mode=3)
    p.insert_text((40, 100), "COVEREDPERSON")
    p.draw_rect(fitz.Rect(30, 80, 250, 110), color=None, fill=(1, 1, 1), overlay=True)
    p.insert_text((40, 150), "Total CHF 125.50")
    pdf.save(path)
    pdf.close()
    doc = Document(path)
    assert "INVISIBLEPERSON" in doc.pdf[0].get_text()
    text = doc.text_export([])
    assert "INVISIBLEPERSON" not in text and "COVEREDPERSON" not in text
    assert "125.50" in text
    doc.export(tmp_path / "safe.pdf", [])
    doc.close()


def test_real_local_ocr_scan(source):
    from pathlib import Path
    doc = Document(source)
    doc.run_ocr(2, str(Path(__file__).parent / "tessdata"))
    assert "Scanned" in " ".join(w[4] for w in doc.words(2))
    marks = doc.detect(["Scanned Person"])
    assert any(m.page == 2 and m.kind == "CUSTOM" for m in marks)
    for m in marks: m.status = "accepted"
    text = doc.text_export(marks)
    assert "Scanned Person" not in text
    assert "12.00" in text
    doc.close()


def test_financial_and_checkbox_pixels_preserved(source, tmp_path):
    from PIL import Image, ImageChops
    doc = Document(source)
    marks = doc.detect()
    for m in marks: m.status = "accepted"
    outpath = tmp_path / "safe.pdf"
    doc.export(outpath, marks)
    with fitz.open(outpath) as out:
        # Compare a financial table and a checkbox well outside all selected regions.
        for rect in [fitz.Rect(35, 330, 550, 470), fitz.Rect(35, 535, 250, 565)]:
            a = doc.pdf[0].get_pixmap(matrix=fitz.Matrix(200/72, 200/72), clip=rect, alpha=False)
            b = out[0].get_pixmap(matrix=fitz.Matrix(200/72, 200/72), clip=rect, alpha=False)
            ia, ib = (Image.frombytes("RGB", (p.width, p.height), p.samples) for p in (a, b))
            # Re-embedding can move antialiasing by a pixel, but the bulk must agree.
            delta = ImageChops.difference(ia, ib)
            import PIL.ImageStat
            assert max(PIL.ImageStat.Stat(delta).mean) < 12
    doc.close()
