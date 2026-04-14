#!/usr/bin/env python3
"""Tkinter GUI wrapper for exif_frame.py poster generation."""

from __future__ import annotations

import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, colorchooser, ttk

from PIL import Image, ImageTk

from exif_frame import LayoutConfig, create_framed_image, get_exif_data, parse_hex_color


class ExifFrameGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EXIF Frame Studio")
        self.root.geometry("1600x980")

        self.image_paths: list[Path] = []
        self.current_index = 0
        self.thumbnail_cache: dict[Path, ImageTk.PhotoImage] = {}
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.preview_job: str | None = None
        self.export_progress = tk.DoubleVar(value=0.0)

        self.vars = {
            "title": tk.StringVar(value="Nature's poetry"),
            "subtitle": tk.StringVar(value=""),
            "frame_color": tk.StringVar(value="#F2F2F2"),
            "top_margin": tk.IntVar(value=170),
            "bottom_margin": tk.IntVar(value=190),
            "side_margin": tk.IntVar(value=40),
            "title_size": tk.IntVar(value=62),
            "subtitle_size": tk.IntVar(value=42),
            "info_size": tk.IntVar(value=64),
            "meta_size": tk.IntVar(value=38),
            "swatch_count": tk.IntVar(value=5),
            "swatch_label_size": tk.IntVar(value=20),
            "font_path": tk.StringVar(value=""),
            "dump_exif": tk.BooleanVar(value=False),
        }

        self._build_ui()
        self._wire_live_updates()

    @property
    def current_image_path(self) -> Path | None:
        if not self.image_paths:
            return None
        return self.image_paths[self.current_index]

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="Open Image", command=self.open_image).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Open Folder", command=self.open_folder).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Apply Settings To All", command=self.apply_settings_to_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Export", command=self.export).pack(side=tk.LEFT, padx=4)

        body = ttk.Frame(self.root)
        body.pack(fill=tk.BOTH, expand=True)

        preview_wrap = ttk.Frame(body, padding=(8, 0, 8, 8))
        preview_wrap.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.preview_label = ttk.Label(preview_wrap, anchor="center")
        self.preview_label.pack(fill=tk.BOTH, expand=True)

        mini_wrap = ttk.Frame(preview_wrap)
        mini_wrap.pack(fill=tk.X, pady=(8, 0))

        self.mini_canvas = tk.Canvas(mini_wrap, height=110)
        h_scroll = ttk.Scrollbar(mini_wrap, orient=tk.HORIZONTAL, command=self.mini_canvas.xview)
        self.mini_canvas.configure(xscrollcommand=h_scroll.set)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.mini_canvas.pack(side=tk.TOP, fill=tk.X, expand=True)

        self.mini_inner = ttk.Frame(self.mini_canvas)
        self.mini_canvas.create_window((0, 0), window=self.mini_inner, anchor="nw")
        self.mini_inner.bind("<Configure>", lambda _: self.mini_canvas.configure(scrollregion=self.mini_canvas.bbox("all")))

        settings = ttk.LabelFrame(body, text="Settings", padding=10)
        settings.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8), pady=(0, 8))

        self._setting_entry(settings, "Title", "title")
        self._setting_entry(settings, "Subtitle (blank=auto date)", "subtitle")
        self._setting_slider(settings, "Top margin", "top_margin", 0, 2000)
        self._setting_slider(settings, "Bottom margin", "bottom_margin", 0, 2000)
        self._setting_slider(settings, "Side margin", "side_margin", 0, 1000)
        self._setting_slider(settings, "Title size", "title_size", 8, 300)
        self._setting_slider(settings, "Subtitle size", "subtitle_size", 8, 300)
        self._setting_slider(settings, "Camera size", "info_size", 8, 300)
        self._setting_slider(settings, "Meta size", "meta_size", 8, 300)
        self._setting_spin(settings, "Swatch count", "swatch_count", 1, 20)
        self._setting_spin(settings, "Swatch hex size", "swatch_label_size", 8, 120)

        row = ttk.Frame(settings)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="Frame color").pack(anchor="w")
        color_row = ttk.Frame(row)
        color_row.pack(fill=tk.X)
        ttk.Entry(color_row, textvariable=self.vars["frame_color"]).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(color_row, text="Pick", command=self.pick_color).pack(side=tk.LEFT, padx=4)

        self._setting_entry(settings, "Font path (optional)", "font_path")
        ttk.Checkbutton(settings, text="Dump EXIF to console", variable=self.vars["dump_exif"]).pack(anchor="w", pady=3)

        ttk.Label(settings, text="Export progress").pack(anchor="w", pady=(8, 0))
        ttk.Progressbar(settings, variable=self.export_progress, maximum=100, mode="determinate").pack(fill=tk.X, pady=(0, 8))

        info_panel = ttk.LabelFrame(settings, text="Current image EXIF", padding=8)
        info_panel.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.exif_text = tk.Text(info_panel, height=14, wrap="word")
        exif_scroll = ttk.Scrollbar(info_panel, orient=tk.VERTICAL, command=self.exif_text.yview)
        self.exif_text.configure(yscrollcommand=exif_scroll.set)
        self.exif_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        exif_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.exif_text.insert("1.0", "Open an image to view EXIF metadata.")
        self.exif_text.configure(state=tk.DISABLED)

    def _setting_entry(self, parent: ttk.Widget, label: str, key: str) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text=label).pack(anchor="w")
        ttk.Entry(row, textvariable=self.vars[key]).pack(fill=tk.X)

    def _setting_spin(self, parent: ttk.Widget, label: str, key: str, mn: int, mx: int) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text=label).pack(anchor="w")
        ttk.Spinbox(row, from_=mn, to=mx, textvariable=self.vars[key]).pack(fill=tk.X)

    def _setting_slider(self, parent: ttk.Widget, label: str, key: str, mn: int, mx: int) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text=label).pack(anchor="w")
        controls = ttk.Frame(row)
        controls.pack(fill=tk.X)
        ttk.Scale(controls, from_=mn, to=mx, orient=tk.HORIZONTAL, variable=self.vars[key]).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Spinbox(controls, from_=mn, to=mx, textvariable=self.vars[key], width=7).pack(side=tk.LEFT, padx=(6, 0))

    def _wire_live_updates(self) -> None:
        for var in self.vars.values():
            var.trace_add("write", lambda *_: self.schedule_preview())
        self.root.bind("<Configure>", lambda _: self.schedule_preview())

    def pick_color(self) -> None:
        color, _ = colorchooser.askcolor(color=self.vars["frame_color"].get(), parent=self.root)
        if color:
            r, g, b = [int(c) for c in color]
            self.vars["frame_color"].set(f"#{r:02X}{g:02X}{b:02X}")

    def open_image(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JPEG", "*.jpg *.jpeg")])
        if not path:
            return
        self.image_paths = [Path(path)]
        self.current_index = 0
        self.refresh_minimap()
        self.update_exif_panel()
        self.schedule_preview()

    def open_folder(self) -> None:
        folder = filedialog.askdirectory()
        if not folder:
            return
        files = sorted(
            [
                p
                for p in Path(folder).iterdir()
                if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg"}
            ]
        )
        if not files:
            messagebox.showwarning("No images", "No JPG/JPEG files found in selected folder.")
            return
        self.image_paths = files
        self.current_index = 0
        self.refresh_minimap()
        self.update_exif_panel()
        self.schedule_preview()

    def refresh_minimap(self) -> None:
        for child in self.mini_inner.winfo_children():
            child.destroy()
        self.thumbnail_cache.clear()

        for idx, path in enumerate(self.image_paths):
            with Image.open(path) as img:
                thumb = img.convert("RGB")
                thumb.thumbnail((140, 90))
            photo = ImageTk.PhotoImage(thumb)
            self.thumbnail_cache[path] = photo
            btn = ttk.Button(
                self.mini_inner,
                image=photo,
                text=path.name,
                compound="top",
                width=18,
                command=lambda i=idx: self.select_image(i),
            )
            btn.pack(side=tk.LEFT, padx=4, pady=2)

    def select_image(self, index: int) -> None:
        self.current_index = index
        self.update_exif_panel()
        self.schedule_preview()

    def update_exif_panel(self) -> None:
        img_path = self.current_image_path
        self.exif_text.configure(state=tk.NORMAL)
        self.exif_text.delete("1.0", tk.END)
        if not img_path:
            self.exif_text.insert("1.0", "Open an image to view EXIF metadata.")
            self.exif_text.configure(state=tk.DISABLED)
            return
        try:
            with Image.open(img_path) as image:
                exif = get_exif_data(image)
            if not exif:
                self.exif_text.insert("1.0", f"{img_path.name}\n\nNo EXIF metadata found.")
            else:
                lines = [f"{img_path.name}", ""]
                for k in sorted(exif.keys()):
                    if k == "GPSInfo" and isinstance(exif[k], dict):
                        lines.append("GPSInfo:")
                        for gk in sorted(exif[k].keys()):
                            lines.append(f"  {gk}: {exif[k][gk]}")
                    else:
                        lines.append(f"{k}: {exif[k]}")
                self.exif_text.insert("1.0", "\n".join(lines))
        except Exception as exc:
            self.exif_text.insert("1.0", f"Failed to read EXIF:\n{exc}")
        self.exif_text.configure(state=tk.DISABLED)

    def _build_config(self) -> LayoutConfig:
        frame_color = parse_hex_color(self.vars["frame_color"].get())
        font_value = self.vars["font_path"].get().strip() or None
        subtitle_value = self.vars["subtitle"].get().strip() or None
        return LayoutConfig(
            frame_color=frame_color,
            top_margin=self.vars["top_margin"].get(),
            bottom_margin=self.vars["bottom_margin"].get(),
            side_margin=self.vars["side_margin"].get(),
            title=self.vars["title"].get(),
            subtitle=subtitle_value,
            title_size=self.vars["title_size"].get(),
            subtitle_size=self.vars["subtitle_size"].get(),
            info_size=self.vars["info_size"].get(),
            meta_size=self.vars["meta_size"].get(),
            font_path=font_value,
            dump_exif=self.vars["dump_exif"].get(),
            swatch_count=self.vars["swatch_count"].get(),
            swatch_label_size=self.vars["swatch_label_size"].get(),
        )

    def schedule_preview(self) -> None:
        if self.preview_job:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after(200, self.update_preview)

    def update_preview(self) -> None:
        self.preview_job = None
        img_path = self.current_image_path
        if not img_path:
            self.preview_label.configure(text="Open an image or folder to start.", image="")
            return

        try:
            cfg = self._build_config()
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            create_framed_image(img_path, tmp_path, cfg)
            preview = Image.open(tmp_path).convert("RGB")
            preview.thumbnail((max(300, self.preview_label.winfo_width() - 20), max(300, self.preview_label.winfo_height() - 20)))
            self.preview_photo = ImageTk.PhotoImage(preview)
            self.preview_label.configure(image=self.preview_photo, text="")
            tmp_path.unlink(missing_ok=True)
        except Exception as exc:
            self.preview_label.configure(text=f"Preview error: {exc}", image="")

    def apply_settings_to_all(self) -> None:
        if not self.image_paths:
            messagebox.showinfo("No images", "Open an image or folder first.")
            return
        messagebox.showinfo("Settings applied", f"Settings are now active for {len(self.image_paths)} image(s).")

    def export(self) -> None:
        if not self.image_paths:
            messagebox.showinfo("No images", "Open an image or folder first.")
            return

        try:
            cfg = self._build_config()
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        if len(self.image_paths) == 1:
            out = filedialog.asksaveasfilename(defaultextension=".jpg", filetypes=[("JPEG", "*.jpg")])
            if not out:
                return
            try:
                self.export_progress.set(0)
                create_framed_image(self.image_paths[0], Path(out), cfg)
                self.export_progress.set(100)
                messagebox.showinfo("Done", f"Exported:\n{out}")
            except Exception as exc:
                messagebox.showerror("Export failed", str(exc))
            return

        out_dir = filedialog.askdirectory(title="Select output folder")
        if not out_dir:
            return
        out_dir_path = Path(out_dir)

        failures: list[str] = []
        total = len(self.image_paths)
        self.export_progress.set(0)
        for idx, src in enumerate(self.image_paths, start=1):
            dst = out_dir_path / f"{src.stem}_framed.jpg"
            try:
                create_framed_image(src, dst, cfg)
            except Exception as exc:
                failures.append(f"{src.name}: {exc}")
            self.export_progress.set((idx / total) * 100)
            self.root.update_idletasks()

        if failures:
            messagebox.showwarning("Export completed with issues", "\n".join(failures[:10]))
        else:
            messagebox.showinfo("Done", f"Exported {len(self.image_paths)} image(s) to:\n{out_dir}")


def main() -> None:
    root = tk.Tk()
    ExifFrameGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
