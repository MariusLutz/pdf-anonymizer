"""Local-only Tkinter desktop application."""
import copy
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import pymupdf as fitz
from engine import Document, Mark
from preflight import scan, digest, write_reviewed_text


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Local PDF Anonymizer")
        self.geometry("1260x850")
        self.minsize(900, 600)
        self.doc = None
        self.marks = []
        self.undo_stack, self.redo_stack = [], []
        self.page, self.zoom = 0, 1.2
        self.start = None
        self.drag = None
        self.busy = False
        self.tessdata = str(Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "tessdata")
        self.language = "eng"
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=3)
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        for title, action in [("Open PDF", self.open_pdf), ("Detect", self.detect), ("Local OCR", self.ocr), ("Undo", self.undo), ("Redo", self.redo), ("Export PDF", self.export_pdf), ("Export text", self.export_text)]:
            ttk.Button(bar, text=title, command=lambda fn=action: self.guard(fn)).pack(side="left", padx=3)
        ttk.Label(self, text="OFFLINE  |  Orange = pending   Red = accepted   Green = rejected  |  Drag on the page to redact manually.").pack(fill="x", padx=10)
        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=10, pady=6)
        preview = ttk.Frame(pane)
        pane.add(preview, weight=4)
        nav = ttk.Frame(preview)
        nav.pack(fill="x")
        ttk.Button(nav, text="Previous", command=lambda: self.turn(-1)).pack(side="left")
        ttk.Button(nav, text="Next", command=lambda: self.turn(1)).pack(side="left")
        ttk.Button(nav, text="Zoom -", command=lambda: self.scale(.8)).pack(side="left")
        ttk.Button(nav, text="Zoom +", command=lambda: self.scale(1.25)).pack(side="left")
        self.page_label = ttk.Label(nav, text="Open a PDF to begin")
        self.page_label.pack(side="left")
        frame = ttk.Frame(preview)
        frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(frame, bg="#303943", highlightthickness=0)
        x = ttk.Scrollbar(frame, orient="horizontal", command=self.canvas.xview)
        y = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=x.set, yscrollcommand=y.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        x.grid(row=1, column=0, sticky="ew")
        y.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.canvas.bind("<ButtonPress-1>", self.begin)
        self.canvas.bind("<B1-Motion>", self.motion)
        self.canvas.bind("<ButtonRelease-1>", self.end)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-int(e.delta/120), "units"))
        side = ttk.Frame(pane, padding=8)
        pane.add(side, weight=2)
        ttk.Label(side, text="Custom names / phrases (one per line)").pack(anchor="w")
        self.terms = tk.Text(side, height=5, width=35)
        self.terms.pack(fill="x")
        ttk.Label(side, text="Suggestions: select an item, then accept or reject").pack(anchor="w")
        self.tree = ttk.Treeview(side, columns=("page", "kind", "status"), show="headings", selectmode="extended")
        for col, width in [("page", 45), ("kind", 110), ("status", 85)]:
            self.tree.heading(col, text=col.title())
            self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.select)
        buttons = ttk.Frame(side)
        buttons.pack(fill="x")
        for title, status in [("Accept", "accepted"), ("Reject", "rejected"), ("Reset", "pending")]:
            ttk.Button(buttons, text=title, command=lambda s=status: self.change(s)).pack(side="left")
        self.detail = tk.StringVar(value="Automatic detection is incomplete. Inspect every page, especially signatures and scans.")
        ttk.Label(side, textvariable=self.detail, wraplength=340).pack(fill="x", pady=10)
        self.status = tk.StringVar(value="Ready. Files remain on this computer.")
        ttk.Label(self, textvariable=self.status).pack(fill="x", padx=10, pady=5)
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-y>", lambda e: self.redo())

    def guard(self, action):
        if self.busy: return
        self.busy = True
        self.configure(cursor="watch")
        self.update_idletasks()
        try: action()
        except Exception as exc: messagebox.showerror("Operation could not complete", str(exc), parent=self)
        finally:
            self.busy = False
            self.configure(cursor="")

    def checkpoint(self):
        self.undo_stack.append(copy.deepcopy(self.marks))
        self.redo_stack.clear()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(copy.deepcopy(self.marks))
            self.marks = self.undo_stack.pop()
            self.refresh()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(copy.deepcopy(self.marks))
            self.marks = self.redo_stack.pop()
            self.refresh()

    def open_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF documents", "*.pdf")])
        if not path: return
        if self.doc and not messagebox.askokcancel("Open another PDF", "Current review marks will be discarded. Continue?"): return
        try: doc = Document(path)
        except ValueError as exc:
            if "Password" not in str(exc): raise
            password = simpledialog.askstring("Encrypted PDF", "Password (kept in memory only):", show="*")
            if password is None: return
            doc = Document(path, password)
        if self.doc: self.doc.close()
        self.doc, self.page = doc, 0
        self.marks, self.undo_stack, self.redo_stack = [], [], []
        self.terms.delete("1.0", "end")
        self.detect()

    def detect(self):
        if not self.doc: return
        self.status.set("Detecting locally; large files may take a moment...")
        self.update_idletasks()
        new = self.doc.detect(self.terms.get("1.0", "end").splitlines())
        self.checkpoint()
        keys = {(m.page, m.rect, m.kind) for m in self.marks}
        self.marks.extend(m for m in new if (m.page, m.rect, m.kind) not in keys)
        self.refresh()
        if self.doc.warnings: messagebox.showwarning("Review limitations", "\n".join(dict.fromkeys(self.doc.warnings)))

    def ocr(self):
        if not self.doc: return
        use_bundled = messagebox.askyesnocancel("Local OCR", "Use bundled English OCR?\n\nYes: bundled English.\nNo: choose another local tessdata folder.")
        if use_bundled is None: return
        folder = self.tessdata if use_bundled else filedialog.askdirectory(title="Select local Tesseract tessdata folder")
        if not folder: return
        language = simpledialog.askstring("OCR language", "Installed language code(s), e.g. eng or eng+deu:", initialvalue="eng")
        if not language: return
        self.tessdata, self.language = folder, language
        for i in range(len(self.doc.pdf)):
            self.status.set(f"Local OCR: page {i+1}/{len(self.doc.pdf)}")
            self.update_idletasks()
            self.doc.run_ocr(i, folder, language)
        self.detect()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, m in enumerate(self.marks):
            self.tree.insert("", "end", iid=str(i), values=(m.page+1, m.kind, m.status))
        pending = sum(m.status == "pending" for m in self.marks)
        self.status.set(f"{len(self.marks)} regions | {pending} pending. Review every page before export.")
        self.render()

    def render(self):
        if not self.doc: return
        page = self.doc.pdf[self.page]
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
        self.photo = ImageTk.PhotoImage(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, pix.width, pix.height))
        for m in self.marks:
            if m.page != self.page: continue
            r = fitz.Rect(m.rect) * page.rotation_matrix
            color = {"pending": "#ef9b22", "accepted": "#d72d43", "rejected": "#32985b"}[m.status]
            self.canvas.create_rectangle(*(v*self.zoom for v in r), fill=color, stipple="gray25", outline=color, width=2)
        self.page_label.configure(text=f"Page {self.page+1}/{len(self.doc.pdf)}  {self.zoom:.0%}")

    def turn(self, delta):
        if self.doc:
            self.page = max(0, min(len(self.doc.pdf)-1, self.page+delta))
            self.canvas.yview_moveto(0)
            self.render()

    def scale(self, factor):
        self.zoom = max(.3, min(3, self.zoom*factor))
        self.render()

    def select(self, event=None):
        ids = self.tree.selection()
        if ids:
            m = self.marks[int(ids[0])]
            self.page = m.page
            self.detail.set(f"{m.kind}: {m.text[:250] or '(visual region)'}\n{m.reason}")
            self.render()

    def change(self, status):
        ids = self.tree.selection()
        if not ids: return
        self.checkpoint()
        for key in ids: self.marks[int(key)].status = status
        self.refresh()

    def begin(self, event):
        if self.doc: self.start = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))

    def motion(self, event):
        if self.start:
            if self.drag: self.canvas.delete(self.drag)
            self.drag = self.canvas.create_rectangle(*self.start, self.canvas.canvasx(event.x), self.canvas.canvasy(event.y), outline="red", width=2)

    def end(self, event):
        if not self.start or not self.doc: return
        x, y = self.start
        self.start = None
        xx, yy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if abs(xx-x) < 4 or abs(yy-y) < 4:
            self.render()
            return
        page = self.doc.pdf[self.page]
        rect = fitz.Rect(min(x, xx)/self.zoom, min(y, yy)/self.zoom, max(x, xx)/self.zoom, max(y, yy)/self.zoom) & page.rect
        rect = rect * page.derotation_matrix
        if rect.is_empty: return
        # Expand through intersecting known words to avoid exposing word fragments.
        for w in self.doc.words(self.page):
            if fitz.Rect(w[:4]).intersects(rect): rect |= fitz.Rect(w[:4])
        self.checkpoint()
        value = " ".join(w[4] for w in self.doc.words(self.page) if fitz.Rect(w[:4]).intersects(rect))
        self.marks.append(Mark(self.page, tuple(rect), "MANUAL", value, "accepted", "Manually selected"))
        self.refresh()

    def ready(self):
        if not self.doc: return False
        self.doc.accepted(self.marks)
        return messagebox.askokcancel("Final review is required", "Have you inspected every page, including signatures, QR codes and images?\n\nExport checks cannot certify anonymity. You must review the final PDF and text before sharing.")

    def export_pdf(self):
        if not self.ready(): return
        if self.review_output(self.doc.text_export(self.marks, self.tessdata, self.language), editable=False) is None:
            return
        choice = messagebox.askyesnocancel("Export mode", "Use Secure redacted mode?\n\nYes: true PyMuPDF redaction, then rebuild from images.\nNo: flatten directly from covered page images (recommended).\n\nBoth remove original PDF objects and text searchability.")
        if choice is None: return
        path = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile="anonymized.pdf", filetypes=[("PDF", "*.pdf")])
        if not path: return
        self.doc.export(path, self.marks, "secure" if choice else "flattened")
        messagebox.showinfo("PDF structure checked - visual review required", "PDF exported with a structural verification report.\n\nThe additional OCR review can miss content. Open the final PDF and inspect every page before sharing. Neither check proves anonymity.")

    def export_text(self):
        if not self.ready(): return
        text = self.review_output(self.doc.text_export(self.marks, self.tessdata, self.language))
        if text is None: return
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="anonymized.txt", filetypes=[("Text", "*.txt")])
        if not path: return
        if Path(path).resolve() == self.doc.path: raise ValueError("Cannot overwrite the original.")
        write_reviewed_text(path, text, self.known_terms(), approved_digest=digest(text))
        messagebox.showinfo("Review text before sharing", "Text exported. Check missing scan content, table order and any unmarked identifiers before sharing.")

    def known_terms(self):
        return [m.text for m in self.marks if m.status == "accepted" and m.text.strip()] + self.terms.get("1.0", "end").splitlines()

    def review_output(self, text, editable=True):
        """Separate final-content review; no save path exists until this completes."""
        dialog = tk.Toplevel(self)
        dialog.title("Final identifier check - not certified anonymous")
        dialog.geometry("1000x760")
        dialog.transient(self)
        dialog.grab_set()
        result = []
        ttk.Label(dialog, text=("Inspect the ENTIRE text for names, addresses, accounts and tax IDs. Edit remaining identifiers here.\nEdits affect only the text export, not the PDF." if editable else "Inspect this OCR view for remaining identifiers. Cancel to add PDF redactions.\nOCR can miss content: also inspect every PDF page."), wraplength=950).pack(fill="x", padx=10, pady=8)
        frame = ttk.Frame(dialog)
        frame.pack(fill="both", expand=True, padx=10)
        editor = tk.Text(frame, wrap="word", undo=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=editor.yview)
        editor.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        editor.pack(fill="both", expand=True)
        editor.insert("1.0", text)
        if not editable: editor.configure(state="disabled")
        findings_box = tk.Text(dialog, height=8, wrap="word")
        findings_box.pack(fill="x", padx=10, pady=5)
        reviewed = tk.BooleanVar(value=False)
        ttk.Checkbutton(dialog, text="I inspected the entire final text, including unflagged content.", variable=reviewed).pack(anchor="w", padx=10)
        def check():
            findings = scan(editor.get("1.0", "end-1c"), self.known_terms())
            findings_box.configure(state="normal")
            findings_box.delete("1.0", "end")
            findings_box.insert("1.0", "\n".join(f"Line {f.line or 'multiple'} | {f.kind}: {f.excerpt}" for f in findings) or "No pattern matches. This does NOT establish anonymity; inspect all text.")
            findings_box.configure(state="disabled")
            return findings
        def approve():
            findings = check()
            if not reviewed.get():
                messagebox.showwarning("Review required", "Inspect the entire output and tick the review checkbox.", parent=dialog)
                return
            if any(f.kind == "KNOWN SENSITIVE TERM" for f in findings):
                messagebox.showwarning("Known identifier remains", "Remove the remaining known terms before exporting. For PDFs, cancel and add redactions.", parent=dialog)
                return
            for finding in findings:
                if not messagebox.askyesno("Explicitly retain this flagged content?", f"{finding.kind}, line {finding.line}\n\n{finding.excerpt}\n\nKeep this content? Choose No to return and remove it. This may be a false positive, but it is not automatically safe.", parent=dialog):
                    return
            result.append(editor.get("1.0", "end-1c"))
            dialog.destroy()
        def changed(event=None):
            if editor.edit_modified():
                reviewed.set(False)
                editor.edit_modified(False)
        editor.edit_modified(False)
        editor.bind("<<Modified>>", changed)
        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=10, pady=8)
        ttk.Button(buttons, text="Rescan", command=check).pack(side="left")
        ttk.Button(buttons, text="Cancel / add redactions", command=dialog.destroy).pack(side="left", padx=10)
        ttk.Button(buttons, text="Approve exact output", command=approve).pack(side="right")
        check()
        self.wait_window(dialog)
        return result[0] if result else None

    def quit_app(self):
        if self.doc: self.doc.close()
        self.destroy()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        # Packaging check using an explicitly supplied synthetic input and output folder.
        source, output = sys.argv[-2:]
        folder = Path(output)
        folder.mkdir(parents=True, exist_ok=True)
        doc = Document(source)
        marks = doc.detect()
        for mark in marks: mark.status = "accepted"
        doc.export(folder / "packaged-test.pdf", marks)
        (folder / "packaged-test.txt").write_text(doc.text_export(marks), encoding="utf-8")
        doc.close()
        sys.exit(0)
    app = App()
    if "--smoke-test" in sys.argv:
        if len(sys.argv) > 2:
            app.doc = Document(sys.argv[-1])
            app.refresh()
        app.after(800, app.quit_app)
    app.mainloop()
