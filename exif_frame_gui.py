#!/usr/bin/env python3
"""Tkinter GUI wrapper for exif_frame.py poster generation."""

from __future__ import annotations

import configparser
import re
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, colorchooser, ttk

from PIL import Image, ImageTk

import exif_frame as ef
from exif_frame import LayoutConfig, get_exif_data, parse_hex_color


class ExifFrameGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EXIF Frame Studio")
        self.root.geometry("1600x980")

        self.image_paths: list[Path] = []
        self.current_index = 0
        self.thumbnail_cache: dict[Path, ImageTk.PhotoImage] = {}
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.preview_image: Image.Image | None = None
        self.preview_job: str | None = None
        self.progress_value = tk.DoubleVar(value=0.0)
        self.active_pick_index: int | None = None
        self.manual_swatch_rows: list[tuple[tk.Canvas, tk.StringVar]] = []
        self.manual_swatch_map: dict[Path, list[str]] = {}

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
            "swatch_box_width": tk.IntVar(value=520),
            "font_path": tk.StringVar(value=""),
            "dump_exif": tk.BooleanVar(value=False),
            "export_template": tk.StringVar(value="${filename}_framed"),
            "title_subtitle_gap": tk.IntVar(value=8),
            "camera_meta_gap": tk.IntVar(value=12),
            "manual_swatch_enable": tk.BooleanVar(value=False),
        }
        self.defaults_path = Path(__file__).with_name("exif_frame_gui.ini")
        self.load_defaults()

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
        ttk.Button(toolbar, text="Close", command=self.clear_images).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Save As Default", command=self.save_defaults).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Apply Settings To All", command=self.apply_settings_to_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Export", command=self.export).pack(side=tk.LEFT, padx=4)

        body = ttk.Frame(self.root)
        body.pack(fill=tk.BOTH, expand=True)

        preview_wrap = ttk.Frame(body, padding=(8, 0, 8, 8))
        preview_wrap.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.preview_label = ttk.Label(preview_wrap, anchor="center")
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        self.preview_label.bind("<Button-1>", self.on_preview_click)

        mini_wrap = ttk.Frame(preview_wrap)
        mini_wrap.pack(fill=tk.X, pady=(8, 0))
        self.selection_label = ttk.Label(mini_wrap, text="No image selected")
        self.selection_label.pack(anchor="w", pady=(0, 4))

        self.mini_canvas = tk.Canvas(mini_wrap, height=110)
        h_scroll = ttk.Scrollbar(mini_wrap, orient=tk.HORIZONTAL, command=self.mini_canvas.xview)
        self.mini_canvas.configure(xscrollcommand=h_scroll.set)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.mini_canvas.pack(side=tk.TOP, fill=tk.X, expand=True)

        self.mini_inner = ttk.Frame(self.mini_canvas)
        self.mini_canvas.create_window((0, 0), window=self.mini_inner, anchor="nw")
        self.mini_inner.bind("<Configure>", lambda _: self.mini_canvas.configure(scrollregion=self.mini_canvas.bbox("all")))

        settings_outer = ttk.LabelFrame(body, text="Settings")
        settings_outer.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(0, 8), pady=(0, 8))
        settings_pane = ttk.Panedwindow(settings_outer, orient=tk.VERTICAL)
        settings_pane.pack(fill=tk.BOTH, expand=True)
        settings_top = ttk.Frame(settings_pane)
        settings_bottom = ttk.Frame(settings_pane)
        settings_pane.add(settings_top, weight=4)
        settings_pane.add(settings_bottom, weight=2)

        settings_canvas = tk.Canvas(settings_top, highlightthickness=0, width=420)
        settings_scroll = ttk.Scrollbar(settings_top, orient=tk.VERTICAL, command=settings_canvas.yview)
        settings_canvas.configure(yscrollcommand=settings_scroll.set)
        settings_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        settings_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        settings = ttk.Frame(settings_canvas, padding=10)
        settings_window = settings_canvas.create_window((0, 0), window=settings, anchor="nw")
        settings.bind("<Configure>", lambda _: settings_canvas.configure(scrollregion=settings_canvas.bbox("all")))
        settings_canvas.bind("<Configure>", lambda e: settings_canvas.itemconfigure(settings_window, width=e.width))

        self._setting_entry(settings, "Title", "title")
        self._setting_entry(settings, "Subtitle (blank=auto date)", "subtitle")
        self._setting_slider(settings, "Top margin", "top_margin", 0, 2000)
        self._setting_slider(settings, "Bottom margin", "bottom_margin", 0, 2000)
        self._setting_slider(settings, "Side margin", "side_margin", 0, 1000)
        self._setting_slider(settings, "Title size", "title_size", 8, 300)
        self._setting_slider(settings, "Subtitle size", "subtitle_size", 8, 300)
        self._setting_slider(settings, "Camera size", "info_size", 8, 300)
        self._setting_slider(settings, "Meta size", "meta_size", 8, 300)
        self._setting_slider(settings, "Title-Subtitle line space", "title_subtitle_gap", 0, 200)
        self._setting_slider(settings, "Camera-Meta line space", "camera_meta_gap", 0, 200)
        self._setting_spin(settings, "Swatch count", "swatch_count", 1, 20)
        self._setting_spin(settings, "Swatch hex size", "swatch_label_size", 8, 120)
        self._setting_slider(settings, "Swatch box width", "swatch_box_width", 80, 5000)
        ttk.Checkbutton(settings, text="Enable manual swatch colors", variable=self.vars["manual_swatch_enable"], command=self.sync_manual_swatches).pack(anchor="w", pady=(2, 6))
        self.manual_swatch_wrap = ttk.Frame(settings)
        self.manual_swatch_wrap.pack(fill=tk.X, pady=(0, 6))
        for i in range(20):
            row = ttk.Frame(self.manual_swatch_wrap)
            chip = tk.Canvas(row, width=18, height=18, highlightthickness=1, highlightbackground="#666666", bg="#000000")
            chip.pack(side=tk.LEFT)
            hex_var = tk.StringVar(value="#000000")
            hex_entry = ttk.Entry(row, textvariable=hex_var, width=10, state="readonly")
            hex_entry.pack(side=tk.LEFT, padx=(6, 6))
            ttk.Button(row, text=f"Pick {i+1}", command=lambda idx=i: self.start_pick_color(idx)).pack(side=tk.LEFT)
            self.manual_swatch_rows.append((chip, hex_var))
            row.pack(fill=tk.X, pady=2)
        ttk.Label(self.manual_swatch_wrap, text="Click Pick N, then click a color in preview.").pack(anchor="w")
        self.sync_manual_swatches()

        row = ttk.Frame(settings)
        row.pack(fill=tk.X, pady=3)
        ttk.Label(row, text="Frame color").pack(anchor="w")
        color_row = ttk.Frame(row)
        color_row.pack(fill=tk.X)
        ttk.Entry(color_row, textvariable=self.vars["frame_color"]).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(color_row, text="Pick", command=self.pick_color).pack(side=tk.LEFT, padx=4)

        self._setting_entry(settings, "Font path (optional)", "font_path")
        ttk.Checkbutton(settings, text="Dump EXIF to console", variable=self.vars["dump_exif"]).pack(anchor="w", pady=3)
        self._setting_entry(settings, "Export filename template", "export_template")
        ttk.Button(settings, text="Template Help", command=self.show_template_help).pack(anchor="w", pady=(2, 6))

        ttk.Label(settings, text="Progress").pack(anchor="w", pady=(8, 0))
        ttk.Progressbar(settings, variable=self.progress_value, maximum=100, mode="determinate").pack(fill=tk.X, pady=(0, 8))

        info_panel = ttk.LabelFrame(settings_bottom, text="Current image EXIF", padding=8)
        info_panel.pack(fill=tk.BOTH, expand=True)
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
        tk.Scale(controls, from_=mn, to=mx, orient=tk.HORIZONTAL, variable=self.vars[key], resolution=1, showvalue=False).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Spinbox(controls, from_=mn, to=mx, textvariable=self.vars[key], width=7).pack(side=tk.LEFT, padx=(6, 0))

    def _wire_live_updates(self) -> None:
        for var in self.vars.values():
            var.trace_add("write", lambda *_: self.schedule_preview())
        self.vars["swatch_count"].trace_add("write", lambda *_: self.sync_manual_swatches())
        self.vars["manual_swatch_enable"].trace_add("write", lambda *_: self.sync_manual_swatches())
        self.root.bind("<Configure>", lambda _: self.schedule_preview())

    def sync_manual_swatches(self) -> None:
        enabled = self.vars["manual_swatch_enable"].get()
        if enabled:
            self.manual_swatch_wrap.pack(fill=tk.X, pady=(0, 6))
        else:
            self.manual_swatch_wrap.pack_forget()
            self.active_pick_index = None
        count = self.vars["swatch_count"].get()
        for i, child in enumerate(self.manual_swatch_wrap.winfo_children()[:-1]):
            if enabled and i < count:
                child.pack(fill=tk.X, pady=2)
            else:
                child.pack_forget()

    def start_pick_color(self, idx: int) -> None:
        self.active_pick_index = idx
        self.selection_label.configure(text=f"Pick mode: click preview for swatch {idx + 1}")

    def on_preview_click(self, event: tk.Event) -> None:
        if self.active_pick_index is None or self.preview_image is None:
            return
        img_w, img_h = self.preview_image.size
        lbl_w = max(1, self.preview_label.winfo_width())
        lbl_h = max(1, self.preview_label.winfo_height())
        off_x = max(0, (lbl_w - img_w) // 2)
        off_y = max(0, (lbl_h - img_h) // 2)
        x = event.x - off_x
        y = event.y - off_y
        if x < 0 or y < 0 or x >= img_w or y >= img_h:
            return
        r, g, b = self.preview_image.getpixel((x, y))
        hex_color = f"#{r:02X}{g:02X}{b:02X}"
        chip, hex_var = self.manual_swatch_rows[self.active_pick_index]
        chip.configure(bg=hex_color)
        hex_var.set(hex_color)
        img_path = self.current_image_path
        if img_path:
            self._persist_manual_colors(img_path)
        self.active_pick_index = None
        self.schedule_preview()

    def manual_color_tuples(self, img_path: Path | None = None) -> list[tuple[int, int, int]] | None:
        if not self.vars["manual_swatch_enable"].get():
            return None
        if img_path is None:
            img_path = self.current_image_path
        if img_path:
            self._load_manual_colors(img_path)
        out: list[tuple[int, int, int]] = []
        for i in range(self.vars["swatch_count"].get()):
            out.append(parse_hex_color(self.manual_swatch_rows[i][1].get()))
        return out

    def _persist_manual_colors(self, img_path: Path) -> None:
        count = self.vars["swatch_count"].get()
        self.manual_swatch_map[img_path] = [self.manual_swatch_rows[i][1].get() for i in range(count)]

    def _load_manual_colors(self, img_path: Path) -> None:
        count = self.vars["swatch_count"].get()
        colors = list(self.manual_swatch_map.get(img_path, []))
        while len(colors) < count:
            colors.append("#000000")
        colors = colors[:count]
        self.manual_swatch_map[img_path] = colors
        for i in range(count):
            chip, var = self.manual_swatch_rows[i]
            var.set(colors[i])
            chip.configure(bg=colors[i])

    def load_defaults(self) -> None:
        if not self.defaults_path.exists():
            return
        cp = configparser.ConfigParser()
        cp.read(self.defaults_path)
        if "settings" not in cp:
            return
        for key, var in self.vars.items():
            if key not in cp["settings"]:
                continue
            raw = cp["settings"][key]
            try:
                if isinstance(var, tk.BooleanVar):
                    var.set(raw.lower() in {"1", "true", "yes", "on"})
                elif isinstance(var, tk.IntVar):
                    var.set(int(raw))
                else:
                    var.set(raw)
            except Exception:
                continue

    def save_defaults(self) -> None:
        cp = configparser.ConfigParser()
        cp["settings"] = {}
        for key, var in self.vars.items():
            cp["settings"][key] = str(var.get())
        with open(self.defaults_path, "w", encoding="utf-8") as fh:
            cp.write(fh)
        messagebox.showinfo("Saved", f"Default settings saved to:\n{self.defaults_path}")

    def clear_images(self) -> None:
        self.image_paths = []
        self.current_index = 0
        self.preview_photo = None
        self.preview_image = None
        self.manual_swatch_map.clear()
        self.preview_label.configure(text="Open an image or folder to start.", image="")
        self.selection_label.configure(text="No image selected")
        self.exif_text.configure(state=tk.NORMAL)
        self.exif_text.delete("1.0", tk.END)
        self.exif_text.insert("1.0", "Open an image to view EXIF metadata.")
        self.exif_text.configure(state=tk.DISABLED)
        for child in self.mini_inner.winfo_children():
            child.destroy()
        self.thumbnail_cache.clear()

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
        self._load_manual_colors(self.image_paths[0])
        self.refresh_minimap()
        self.update_selection_label()
        self.update_exif_panel()
        self.schedule_preview()

    def open_folder(self) -> None:
        folder = filedialog.askdirectory()
        if not folder:
            return
        all_items = [p for p in Path(folder).iterdir() if p.is_file()]
        total_items = max(1, len(all_items))
        files: list[Path] = []
        for idx, p in enumerate(all_items, start=1):
            if p.suffix.lower() in {".jpg", ".jpeg"}:
                files.append(p)
            self.progress_value.set((idx / total_items) * 100)
            self.root.update_idletasks()
        files = sorted(files)
        if not files:
            messagebox.showwarning("No images", "No JPG/JPEG files found in selected folder.")
            return
        self.image_paths = files
        self.current_index = 0
        self._load_manual_colors(self.image_paths[0])
        self.refresh_minimap()
        self.update_selection_label()
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
        old = self.current_image_path
        if old:
            self._persist_manual_colors(old)
        self.current_index = index
        if self.current_image_path:
            self._load_manual_colors(self.current_image_path)
        self.update_selection_label()
        self.update_exif_panel()
        self.schedule_preview()

    def update_selection_label(self) -> None:
        img_path = self.current_image_path
        if not img_path:
            self.selection_label.configure(text="No image selected")
            return
        total = len(self.image_paths) if self.image_paths else 1
        self.selection_label.configure(text=f"{img_path}   ({self.current_index + 1} of {total})")

    def show_template_help(self) -> None:
        msg = (
            "Template placeholders:\\n"
            "- ${filename}: original filename without extension\\n"
            "- ${stem}: same as filename\\n"
            "- ${ext}: original extension without dot\\n"
            "- ${make}, ${model}, ${iso}, ${datetime}, ${fnumber}, ${focallength}\\n"
            "- Any raw EXIF key, e.g. ${DateTimeOriginal}, ${LensModel}\\n\\n"
            "Example:\\n"
            "${datetime}_${make}_${filename}_framed"
        )
        messagebox.showinfo("Export template help", msg)

    def _render_template_name(self, src: Path) -> str:
        replacements = {
            "filename": src.stem,
            "stem": src.stem,
            "ext": src.suffix.lstrip("."),
        }
        try:
            with Image.open(src) as image:
                exif = get_exif_data(image)
            for k, v in exif.items():
                if isinstance(v, dict):
                    continue
                key = str(k)
                val = str(v).strip()
                replacements[key] = val
                replacements[key.lower()] = val
        except Exception:
            pass

        template = self.vars["export_template"].get().strip() or "${filename}_framed"

        def repl(match: re.Match[str]) -> str:
            token = match.group(1)
            return replacements.get(token, replacements.get(token.lower(), ""))

        rendered = re.sub(r"\$\{([^}]+)\}", repl, template).strip()
        if not rendered:
            rendered = f"{src.stem}_framed"
        rendered = re.sub(r'[\\\\/:*?\"<>|]+', "_", rendered)
        return rendered

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
            self.progress_value.set(10)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            self.render_with_spacing(img_path, tmp_path, cfg, self.manual_color_tuples(img_path))
            preview = Image.open(tmp_path).convert("RGB")
            preview.thumbnail((max(300, self.preview_label.winfo_width() - 20), max(300, self.preview_label.winfo_height() - 20)))
            self.preview_image = preview.copy()
            self.preview_photo = ImageTk.PhotoImage(preview)
            self.preview_label.configure(image=self.preview_photo, text="")
            tmp_path.unlink(missing_ok=True)
            self.progress_value.set(100)
        except Exception as exc:
            self.preview_label.configure(text=f"Preview error: {exc}", image="")
            self.progress_value.set(0)

    def render_with_spacing(
        self,
        input_path: Path,
        output_path: Path,
        cfg: LayoutConfig,
        forced_colors: list[tuple[int, int, int]] | None = None,
    ) -> None:
        title_gap = self.vars["title_subtitle_gap"].get()
        camera_gap = self.vars["camera_meta_gap"].get()

        source = Image.open(input_path)
        source = ef.ImageOps.exif_transpose(source).convert("RGB")
        source.filename = str(input_path)
        width, height = source.size

        canvas_w = width + cfg.side_margin * 2
        canvas_h = height + cfg.top_margin + cfg.bottom_margin

        canvas = Image.new("RGB", (canvas_w, canvas_h), cfg.frame_color)
        canvas.paste(source, (cfg.side_margin, cfg.top_margin))
        draw = ef.ImageDraw.Draw(canvas)

        title_font = ef.load_font(cfg.font_path, cfg.title_size)
        subtitle_font = ef.load_font(cfg.font_path, cfg.subtitle_size)
        info_font = ef.load_font(cfg.font_path, cfg.info_size)
        meta_font = ef.load_font(cfg.font_path, cfg.meta_size)
        swatch_font = ef.load_font(cfg.font_path, cfg.swatch_label_size)

        exif = ef.get_exif_data(source)
        make = str(ef._decode_if_bytes(ef._first_present(exif, "Make") or "")).strip()
        model = str(ef._decode_if_bytes(ef._first_present(exif, "Model", "LensModel") or "")).strip()
        camera = f"{make} {model}".strip() or "Unknown Camera"

        date_value = ef._format_date(ef._first_present(exif, "DateTimeOriginal", "CreateDate", "DateTime"))
        subtitle = cfg.subtitle if cfg.subtitle else (f"PHOTOGRAPHED IN : {date_value}" if date_value else "")

        gps = exif.get("GPSInfo", {}) if isinstance(exif.get("GPSInfo"), dict) else {}
        lat = ef._format_gps_coord(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"), "lat") if gps else None
        lon = ef._format_gps_coord(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"), "lon") if gps else None
        gps_line = f"{lat} {lon}" if lat and lon else ""

        focal_length = ef._to_float_fraction(ef._first_present(exif, "FocalLength", "FocalLengthIn35mmFilm"))
        f_number = ef._to_float_fraction(ef._first_present(exif, "FNumber", "ApertureValue"))
        exposure = ef._first_present(exif, "ExposureTime", "ShutterSpeedValue")
        iso = ef._decode_if_bytes(ef._first_present(exif, "ISOSpeedRatings", "PhotographicSensitivity", "ISO"))
        specs = "    ".join(
            [
                f"{focal_length:.0f}mm" if focal_length else "--mm",
                f"f/{f_number:.1f}" if f_number else "f/--",
                ef._format_exposure(exposure),
                f"ISO{iso}" if iso else "ISO--",
            ]
        )

        pad_x = cfg.side_margin
        title_bbox = draw.textbbox((0, 0), cfg.title, font=title_font)
        title_h = title_bbox[3] - title_bbox[1]
        subtitle_h = 0
        if subtitle:
            subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
            subtitle_h = subtitle_bbox[3] - subtitle_bbox[1]
        top_block_h = title_h + (title_gap if subtitle else 0) + subtitle_h
        top_y = max(0, int((cfg.top_margin - top_block_h) / 2))
        draw.text((pad_x, top_y), cfg.title, fill=(20, 20, 20), font=title_font)
        if subtitle:
            draw.text((pad_x, top_y + title_h + title_gap), subtitle, fill=(120, 120, 120), font=subtitle_font)

        bottom_margin_start = cfg.top_margin + height
        swatch_height = max(24, cfg.bottom_margin // 6)
        swatch_width = max(80, min(width, self.vars["swatch_box_width"].get()))
        swatch_label_bbox = draw.textbbox((0, 0), "#FFFFFF", font=swatch_font)
        swatch_label_h = swatch_label_bbox[3] - swatch_label_bbox[1]
        swatch_block_h = swatch_height + 6 + swatch_label_h
        colors = ef.dominant_colors(source, n_colors=cfg.swatch_count)
        if forced_colors:
            for i, c in enumerate(forced_colors[: len(colors)]):
                colors[i] = c
        bottom_swatch_y = bottom_margin_start + max(0, int((cfg.bottom_margin - swatch_block_h) / 2))
        ef.draw_color_swatches(draw, colors, pad_x, bottom_swatch_y, swatch_width, swatch_height, swatch_font)

        right_x = canvas_w - cfg.side_margin
        specs_bbox = draw.textbbox((0, 0), specs, font=meta_font)
        specs_h = specs_bbox[3] - specs_bbox[1]
        camera_bbox = draw.textbbox((0, 0), camera, font=info_font)
        camera_w = camera_bbox[2] - camera_bbox[0]
        camera_h = camera_bbox[3] - camera_bbox[1]
        text_block_h = camera_h + camera_gap + specs_h
        if gps_line:
            gps_bbox = draw.textbbox((0, 0), gps_line, font=meta_font)
            gps_h = gps_bbox[3] - gps_bbox[1]
            text_block_h += 8 + gps_h
        text_start_y = bottom_margin_start + max(0, int((cfg.bottom_margin - text_block_h) / 2))
        draw.text((right_x - camera_w, text_start_y), camera, fill=(20, 20, 20), font=info_font)
        specs_y = text_start_y + camera_h + camera_gap
        specs_w = specs_bbox[2] - specs_bbox[0]
        draw.text((right_x - specs_w, specs_y), specs, fill=(120, 120, 120), font=meta_font)
        if gps_line:
            gps_y = specs_y + specs_h + 8
            gps_bbox = draw.textbbox((0, 0), gps_line, font=meta_font)
            gps_w = gps_bbox[2] - gps_bbox[0]
            draw.text((right_x - gps_w, gps_y), gps_line, fill=(120, 120, 120), font=meta_font)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, quality=95)

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
            suggested = f"{self._render_template_name(self.image_paths[0])}.jpg"
            out = filedialog.asksaveasfilename(
                defaultextension=".jpg",
                initialfile=suggested,
                filetypes=[("JPEG", "*.jpg")],
            )
            if not out:
                return
            try:
                self.progress_value.set(0)
                self.render_with_spacing(self.image_paths[0], Path(out), cfg, self.manual_color_tuples(self.image_paths[0]))
                self.progress_value.set(100)
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
        self.progress_value.set(0)
        for idx, src in enumerate(self.image_paths, start=1):
            dst = out_dir_path / f"{self._render_template_name(src)}.jpg"
            try:
                self.render_with_spacing(src, dst, cfg, self.manual_color_tuples(src))
            except Exception as exc:
                failures.append(f"{src.name}: {exc}")
            self.progress_value.set((idx / total) * 100)
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
