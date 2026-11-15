"""Independent, conservative output screening. No network or sensitive logging."""
from dataclasses import dataclass
import hashlib
import re
import unicodedata


@dataclass(frozen=True)
class Finding:
    line: int
    kind: str
    excerpt: str


RULES = {
    "EMAIL": r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
    "GERMAN TAX ID / 11-DIGIT IDENTIFIER": r"(?<!\d)(?:\d[ \t.-]?){10}\d(?!\d)",
    "IBAN / ACCOUNT": r"\b[A-Z]{2}\s*\d{2}(?:[ \t]*[A-Z0-9]){11,30}\b",
    "ACCOUNT REFERENCE": r"\b(?:Konto(?:nummer|inhaber)?|Kunden(?:nummer|referenz)?|Mandatsreferenz|Gläubiger[ -]?ID|Glaeubiger[ -]?ID|Aktenzeichen|Vertragsnummer|Versicherungsnummer|Buchungsreferenz|account(?:\s+(?:number|reference|holder))?|customer\s+(?:id|reference)|reference\s*(?:no\.?|number))\s*[:#=]?\s*\S.*",
    "TAX IDENTIFIER": r"\b(?:Steuer[ -]?(?:ID|IdNr\.?|Identifikationsnummer|nummer)|Identifikationsnummer|IdNr\.?|tax\s*(?:id|number))\s*[:#=]?\s*\S.*",
    "NAME / ADDRESS FIELD": r"\b(?:Name|Vorname|Nachname|Familienname|Kontoinhaber|Empfänger|Empfaenger|Anschrift|Adresse|address|full name)\s*[:=]\s*\S.*",
    "GERMAN ADDRESS": r"\b[\wÄÖÜäöüß.-]*(?:straße|strasse|str\.|weg|platz|allee|gasse|ring)\s+\d+\s*[a-z]?\b|\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+\b",
    "ENGLISH ADDRESS": r"\b\d{1,5}\s+(?:\w+\s+){1,4}(?:Street|Road|Avenue|Lane|Drive|St|Rd)\b",
    "POSSIBLE PERSONAL NAME": r"\b(?:Herrn?|Frau|Mr\.?|Mrs\.?|Ms\.?|Dr\.?)\s+[A-ZÄÖÜ][a-zäöüß'-]+(?:\s+[A-ZÄÖÜ][a-zäöüß'-]+)*|\b[A-ZÄÖÜ][a-zäöüß'-]{2,}\s+[A-ZÄÖÜ][a-zäöüß'-]{2,}\b",
}


def compact(value):
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", value)).casefold()


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def scan(text, known_terms=()):
    """False positives are intentional; findings are review prompts, not identities."""
    findings = []
    clean_lines = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith(("ANONYMIZED OCR TEXT", "--- Page", "DRAFT OCR TEXT")):
            clean_lines.append("")
            continue
        clean = re.sub(r"\[[^\]\n]*REDACTED\]", "", line)
        clean_lines.append(clean)
        for kind, pattern in RULES.items():
            match = re.search(pattern, clean, re.I if kind not in ("POSSIBLE PERSONAL NAME", "GERMAN ADDRESS") else 0)
            if match:
                findings.append(Finding(number, kind, match[0][:180]))
    # Normalized checks detect punctuation/whitespace changes and split-line repeats.
    combined = compact("\n".join(clean_lines))
    for term in known_terms:
        needle = compact(term)
        if len(needle) >= 3 and needle in combined:
            findings.append(Finding(0, "KNOWN SENSITIVE TERM", term[:180]))
    return findings


def write_reviewed_text(target, text, known_terms=(), approved_digest=None):
    """No file is written until the exact final text has been explicitly reviewed."""
    import json
    import os
    import tempfile
    from pathlib import Path
    findings = scan(text, known_terms)
    if any(f.kind == "KNOWN SENSITIVE TERM" for f in findings):
        raise ValueError("Known sensitive terms remain; remove them before saving.")
    if approved_digest != digest(text):
        raise ValueError("Final-text review required: inspect and approve this exact text before saving.")
    target = Path(target)
    fd, temp = tempfile.mkstemp(prefix=".reviewed-", suffix=".txt", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
            out.write(text)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp): os.unlink(temp)
    report = {"sha256": digest(text), "final_text_reviewed": True,
              "residual_findings_acknowledged": len(findings), "anonymity_certified": False,
              "limitations": "Heuristics can miss names, addresses and OCR errors. Manual review remains necessary."}
    target.with_suffix(".txt.review.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
