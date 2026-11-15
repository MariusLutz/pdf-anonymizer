# Local PDF Anonymizer

A Windows 11 desktop application for reviewing and removing identifiers from financial PDFs. Python 3.11+, Tkinter, PyMuPDF, Pillow, local OpenCV QR detection and local Tesseract OCR. No application network requests, telemetry, accounts, uploads or cloud services.

## Start

Install from source using the commands below, then double-click `launch.bat`. The launcher uses the corrected standalone build at `dist/LocalPDFAnonymizer-Reviewed/LocalPDFAnonymizer-Reviewed.exe` when available, otherwise the local `.venv`. Build the executable with `build.bat`; generated binaries and virtual environments are not committed. Keep the executable's `_internal` folder alongside it. Close any earlier app instance before relaunching.

## Additional final-output gate

The first version could leave names, addresses, account references and German tax IDs in text output. Passing its structural PDF checks did not establish that unselected identifiers were removed. Previously exported files are not automatically repaired and must be reviewed again.

Before either desktop export, a separate screen displays the complete OCR text and scans it for possible names, German/English addresses, account references, tax labels and 11-digit identifiers. Known custom terms and accepted redaction values are searched again after normalizing punctuation and whitespace, including across line breaks. Known terms that remain block approval. All other matches require individual explicit decisions to retain them; ambiguous names and business references can produce false positives.

You must inspect the entire text and tick a review checkbox, even when there are no matches. Editing resets the checkbox. Text export lets you edit remaining identifiers; these edits do not change the PDF. For a PDF, cancel the read-only OCR review and add rectangles, then export again. Text files receive a `.txt.review.json` report containing a digest of the reviewed text and finding counts, without sensitive excerpts. This is an acknowledgment record, not anonymity certification. The source `text_export()` function generates a draft for review; production desktop text saving uses `write_reviewed_text()`. The `--self-test` command is a synthetic-fixture packaging test, not a sharing workflow.

OCR and these heuristics still miss identifiers, especially unlabeled names, unusual addresses and recognition errors. Add known personal values to Custom terms, review all unflagged text, and inspect the final PDF visually. No zero-findings result means "safe to share."

For a source installation:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Dependency installation needs internet access unless wheels are supplied locally. Runtime is entirely offline. The English OCR model is supplied in `tessdata/eng.traineddata`; no model download occurs at runtime. Other languages can be installed separately, then selected with Local OCR. Language codes must match locally installed `.traineddata` files.

## Workflow

1. Open a PDF; password-protected PDFs request a password in memory.
2. Inspect automatic suggestions. Enter known names, addresses or account details one per line, then click Detect. Names are detected from labels and custom terms, not a general name-recognition model.
3. For scans, click Local OCR and use bundled English or a local language folder. Then review the added suggestions. OCR may take several seconds per page.
4. Select suggestions in the list and Accept or Reject them. Ctrl/Shift selection allows multiple items. Orange overlays are pending, red accepted, green rejected. Rejected regions remain visible in the export.
5. Drag rectangles over missed information. Manual rectangles are accepted immediately and expand to intersecting known words. To correct one, reject it and draw another. Undo/redo restores review state and rectangles. Marks are kept only in memory and are discarded when closing/opening another document.
6. Inspect **every page**. Look especially for handwriting, faces, signatures, barcodes, QR codes, stamps, addresses, reference numbers and identifiers in financial descriptions. The detector cannot find everything.
7. Export PDF and export text separately. Every pending suggestion must be resolved first. Use neutral output filenames, which the app cannot anonymize automatically.
8. **Open and review both final files before sharing.** Compare financial amounts, checkboxes and page completeness against the original. An automated pass is not a certificate of anonymity.

## Export design

The original is never modified. Each PDF output is built in a new PDF using only freshly rendered, sanitized RGB pixels, at 200 DPI. Original streams, attachments, document properties, bookmarks, hidden layers, actions, hyperlinks, form dictionaries, OCR layers and annotation payloads are not copied. Form values and checkbox appearances are preserved visually. Visible annotation appearances can remain; mark any identifying visible annotation content as well.

- **Flattened (recommended):** render the page, replace selected pixels with solid black, and build a fresh image-only PDF. This is not a black overlay on the original PDF: the original image/text objects are absent from the output.
- **Secure redacted:** first bake form appearances and apply PyMuPDF true redactions to text, images and contained graphics on an in-memory copy; then use the same image rebuild as an additional safety boundary.

Both modes intentionally lose selectable text, vector resolution, interactive fields, accessibility tagging and digital-signature validity. This is a conservative deviation from a conventional searchable/vector-preserving redaction mode. It avoids claiming that arbitrary untrusted PDF object graphs can be safely scrubbed while preserving them. Small details can lose sharpness; inspect the output. PDF amounts and visible content outside rectangles are retained visually, rather than reconstructed from OCR.

**Text export reads sanitized pixels using local OCR.** It never exports the original PDF text layer, so invisible source text cannot reappear. It inserts `[NAME REDACTED]`, `[ADDRESS REDACTED]`, `[ACCOUNT REDACTED]`, `[PERSONAL ID REDACTED]` and related labels at approximate reading positions. Reading order is geometric and tables are approximate. OCR can misread amounts, decimal separators, dates, symbols and checkboxes. Always compare the text against the image-based PDF; use the PDF as the more faithful financial record. Rotated PDF pages are unrotated for OCR; intrinsically sideways scans may need a separately corrected source.

## Detection and limits

- Emails, phone-like numbers, IBAN-like identifiers, Luhn-valid card numbers, US SSNs and Swiss AHV-like numbers.
- Label-based names, addresses, birth dates, bank accounts, passport/ID, employee/customer IDs and signatures, including form field names. Some English, German and French labels are supported.
- Street-like addresses, user-defined exact phrases and locally detected QR geometry. QR data is not decoded or opened.
- Suggested signature areas near labels are uncertain. Unlabelled handwritten signatures, generic bank numbers, every country's ID formats, multiline addresses, damaged/rotated QR codes and ordinary barcodes are not reliably recognized.
- Dates and monetary values are not deliberately redacted. Ambiguous phone/address patterns may still cause false positives; all automatic suggestions start pending and can be rejected.
- Extremely large/malformed PDFs may exhaust memory or fail to render. Operations run synchronously; the UI may pause during OCR/export. No document data is saved in logs or review-session files. The operating system may page process memory or create crash dumps; the application does not promise forensic erasure of the computer or source files.

## Verification report

Each PDF export writes a sibling `.verification.json` with no original terms or filenames. The output is reopened, all text is checked for selected terms, standard identifying metadata/XML metadata, annotations, fields, links, bookmarks and attachments are checked, and every page is rendered. Interiors of selected rectangles must render black. A SHA-256 digest binds the report to the PDF. Failed checks prevent publication of the temporary PDF.

The fresh image-only output has no text layer, so term-search success alone is weak evidence. Verification does **not** OCR all unmarked output looking for unknown identities, prove that original identifiers were all selected, or certify anonymity. Reports always require manual review. Temporary export files contain only sanitized pixels and are deleted on normal failure; a crash may leave a sanitized `.anonymized-*.pdf` file next to the target. Exported text has an explicit review warning and no anonymity certification.

## Tests and packaging

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe sample.py
.venv\Scripts\python.exe app.py --smoke-test examples/synthetic-claim.pdf
build.bat
```

Tests generate synthetic PDFs containing searchable text, tables, a scan, images, QR codes, a filled text field, a checkbox, multiple pages, rotations, metadata, annotations and attachments. They verify removal through extraction and PDF object inspection, preservation of financial text, pending-review enforcement, original-file protection and pixel coverage. Additional tests cover hidden text and real local OCR. Tests disable Python socket creation during the main export test; the application has no networking code.

Run `sample.py` to generate `examples/synthetic-claim.pdf`, which is deliberately **not anonymized** and contains only fictional identifiers. Run `make_demo.py` to generate an anonymized demonstration PDF, text and report. These demonstrate completed redactions, not a detector guarantee. Generated documents and local validation reports are excluded from Git.

## License

This project's original source code is licensed under the **GNU Affero General Public License, version 3 only** (SPDX identifier: `AGPL-3.0-only`). See [LICENSE](LICENSE) for the full license text.

Third-party components remain under their respective licenses; the project license does not replace their license terms or notices. In particular, the bundled English OCR model retains its Apache 2.0 license in [tessdata/LICENSE](tessdata/LICENSE).

## Dependency notices

PyMuPDF is distributed under AGPL/commercial licensing; review its license before redistributing this application. Pillow, OpenCV, NumPy, Python/Tk and PyInstaller have their own license terms, included by their distributions. The English model is from `tesseract-ocr/tessdata_fast`, licensed Apache 2.0; see `tessdata/LICENSE`. This app uses no model requiring a cloud service.
