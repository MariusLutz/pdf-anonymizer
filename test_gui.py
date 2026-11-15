from app import App
from engine import Document, Mark
from sample import create_sample


def test_gui_preview_and_undo_redo(tmp_path):
    path = tmp_path / "sample.pdf"
    create_sample(path)
    app = App()
    app.withdraw()
    try:
        app.doc = Document(path)
        app.refresh()
        app.checkpoint()
        app.marks.append(Mark(0, (40, 60, 200, 90), "NAME", "", "accepted"))
        app.refresh()
        app.undo()
        assert not app.marks
        app.redo()
        assert len(app.marks) == 1
        app.tree.selection_set("0")
        app.change("rejected")
        assert app.marks[0].status == "rejected"
        app.undo()
        assert app.marks[0].status == "accepted"
        app.turn(1)
        assert app.page == 1
        app.scale(1.25)
        app.update_idletasks()
        assert app.photo.width() > 0
    finally:
        app.quit_app()


def test_final_review_requires_explicit_checkbox(monkeypatch):
    import tkinter as tk
    from tkinter import ttk
    import app as module
    app = App()
    app.withdraw()
    warnings = []
    monkeypatch.setattr(module.messagebox, "showwarning", lambda *a, **k: warnings.append(a))
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    def interact():
        dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel))
        widgets = list(descendants(dialog))
        approve = next(w for w in widgets if isinstance(w, ttk.Button) and w.cget("text") == "Approve exact output")
        approve.invoke()
        assert warnings
        assert dialog.winfo_exists()
        next(w for w in widgets if isinstance(w, ttk.Checkbutton)).invoke()
        approve.invoke()
    try:
        app.after(100, interact)
        # Ensure test cannot hang indefinitely on a broken modal callback.
        app.after(3000, lambda: [w.destroy() for w in app.winfo_children() if isinstance(w, tk.Toplevel)])
        assert app.review_output("Total CHF 365.50") == "Total CHF 365.50"
    finally:
        app.quit_app()
