import json
import pytest
from preflight import scan, digest, write_reviewed_text


@pytest.mark.parametrize("text,kind", [
    ("Anna Beispiel", "POSSIBLE PERSONAL NAME"),
    ("Frau Anna Beispiel", "POSSIBLE PERSONAL NAME"),
    ("Musterstraße 12", "GERMAN ADDRESS"),
    ("Musterstrasse 12a", "GERMAN ADDRESS"),
    ("12345 Berlin", "GERMAN ADDRESS"),
    ("123 Example Street", "ENGLISH ADDRESS"),
    ("Mandatsreferenz ABC-7788", "ACCOUNT REFERENCE"),
    ("Kundenreferenz: ABC-7788", "ACCOUNT REFERENCE"),
    ("Steuer-ID: 12 345 678 901", "TAX IDENTIFIER"),
    ("12345678901", "GERMAN TAX ID / 11-DIGIT IDENTIFIER"),
    ("DE89 3704 0044 0532 0130 00", "IBAN / ACCOUNT"),
])
def test_missed_identifiers(text, kind):
    assert any(f.kind == kind for f in scan(text))


def test_known_terms_across_lines_and_punctuation():
    assert any(f.kind == "KNOWN SENSITIVE TERM" for f in scan("Anna\nBeispiel", ["Anna Beispiel"]))
    assert any(f.kind == "KNOWN SENSITIVE TERM" for f in scan("ABC - 7788", ["ABC7788"]))


def test_no_publication_without_exact_review(tmp_path):
    target = tmp_path / "clean.txt"
    text = "Total CHF 365.50"
    with pytest.raises(ValueError, match="review"):
        write_reviewed_text(target, text)
    assert not target.exists()
    with pytest.raises(ValueError, match="review"):
        write_reviewed_text(target, text + " changed", approved_digest=digest(text))
    assert not target.exists()
    write_reviewed_text(target, text, approved_digest=digest(text))
    report = json.loads(target.with_suffix(".txt.review.json").read_text())
    assert report["sha256"] == digest(target.read_text())
    assert report["anonymity_certified"] is False


def test_known_identifier_cannot_be_approved(tmp_path):
    text = "Anna Beispiel"
    with pytest.raises(ValueError, match="Known"):
        write_reviewed_text(tmp_path / "clean.txt", text, [text], digest(text))
    assert not (tmp_path / "clean.txt").exists()


def test_financial_values_and_redaction_labels_not_flagged():
    assert not scan("2026-11-01\nCHF 365.50\nTax: 19%\n[NAME REDACTED]\n[ACCOUNT REDACTED]")
