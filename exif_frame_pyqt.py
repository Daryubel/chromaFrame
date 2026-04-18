#!/usr/bin/env python3
"""High-performance PyQt GUI for exif_frame poster rendering."""

from __future__ import annotations

import hashlib
import math
import re
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

import exif_frame as ef
from exif_frame import LayoutConfig, get_exif_data, parse_hex_color

try:
    from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal
    from PyQt6.QtGui import QAction, QIcon, QImage, QPixmap
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QColorDialog,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QProgressDialog,
        QPushButton,
        QScrollArea,
        QSlider,
        QSpinBox,
        QSplitter,
        QTextEdit,
        QToolBar,
        QVBoxLayout,
        QWidget,
    )
    PYQT_VER = 6
except ImportError:
    from PyQt5.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal
    from PyQt5.QtGui import QAction, QIcon, QImage, QPixmap
    from PyQt5.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QColorDialog,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QProgressDialog,
        QPushButton,
        QScrollArea,
        QSlider,
        QSpinBox,
        QSplitter,
        QTextEdit,
        QToolBar,
        QVBoxLayout,
        QWidget,
    )
    PYQT_VER = 5


def _align_center() -> Qt.AlignmentFlag:
    return Qt.AlignmentFlag.AlignCenter if PYQT_VER == 6 else Qt.AlignCenter


class WorkerSignals(QObject):
    done = pyqtSignal(str, str)  # key, output path
    error = pyqtSignal(str)


class RenderWorker(QRunnable):
    def __init__(
        self,
        key: str,
        input_path: Path,
        cfg: LayoutConfig,
        title_gap: int,
        camera_gap: int,
        swatch_height: int,
        swatch_width: int,
        forced_colors: list[tuple[int, int, int]] | None = None,
        style: str = "chroma",
        text_align: str = "left",
        photographer: str | None = None,
        style_options: dict | None = None,
    ):
        super().__init__()
        self.key = key
        self.input_path = input_path
        self.cfg = cfg
        self.title_gap = title_gap
        self.camera_gap = camera_gap
        self.swatch_height = swatch_height
        self.swatch_width = swatch_width
        self.forced_colors = forced_colors
        self.style = style
        self.text_align = text_align
        self.photographer = photographer
        self.style_options = style_options or {}
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                out_path = Path(tmp.name)
            render_with_options(
                self.input_path,
                out_path,
                self.cfg,
                self.title_gap,
                self.camera_gap,
                self.swatch_height,
                self.swatch_width,
                forced_colors=self.forced_colors,
                style=self.style,
                text_align=self.text_align,
                photographer=self.photographer,
                style_options=self.style_options,
                preview_max_pixels=24_000_000,
            )
            self.signals.done.emit(self.key, str(out_path))
        except Exception as exc:
            self.signals.error.emit(str(exc))


def render_with_options(
    input_path: Path,
    output_path: Path,
    cfg: LayoutConfig,
    title_gap: int,
    camera_gap: int,
    swatch_height: int,
    swatch_width: int,
    forced_colors: list[tuple[int, int, int]] | None = None,
    style: str = "chroma",
    text_align: str = "left",
    photographer: str | None = None,
    style_options: dict | None = None,
    preview_max_pixels: int | None = None,
) -> None:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    source = Image.open(input_path)
    source = ef.ImageOps.exif_transpose(source).convert("RGB")
    source.filename = str(input_path)
    width, height = source.size

    if style == "float":
        opts = style_options or {}
        canvas_float = source.copy()
        draw_f = ef.ImageDraw.Draw(canvas_float)
        info_font_f = ef.load_font(cfg.font_path, cfg.info_size)
        meta_font_f = ef.load_font(cfg.font_path, cfg.meta_size)
        logo_size = max(12, int(opts.get("plateau_logo_size", cfg.info_size)))
        logo_font_f = ef.load_font(cfg.font_path, logo_size)
        exif_f = ef.get_exif_data(source)
        make_f = str(ef._decode_if_bytes(ef._first_present(exif_f, "Make") or "")).strip()
        model_f = str(ef._decode_if_bytes(ef._first_present(exif_f, "Model", "LensModel") or "")).strip()
        date_f = ef._format_date(ef._first_present(exif_f, "DateTimeOriginal", "CreateDate", "DateTime")) or "--"
        focal_f = ef._to_float_fraction(ef._first_present(exif_f, "FocalLength", "FocalLengthIn35mmFilm"))
        fnum_f = ef._to_float_fraction(ef._first_present(exif_f, "FNumber", "ApertureValue"))
        exp_f = ef._first_present(exif_f, "ExposureTime", "ShutterSpeedValue")
        iso_f = ef._decode_if_bytes(ef._first_present(exif_f, "ISOSpeedRatings", "PhotographicSensitivity", "ISO"))
        specs_f = "    ".join([f"{focal_f:.0f}mm" if focal_f else "--mm", f"f/{fnum_f:.1f}" if fnum_f else "f/--", ef._format_exposure(exp_f), f"ISO{iso_f}" if iso_f else "ISO--"])
        line1 = f"{photographer or 'Unknown'}    {date_f}"
        line2 = f"{model_f or '--'}    {specs_f}"
        l1_bbox = draw_f.textbbox((0, 0), line1, font=info_font_f)
        l2_bbox = draw_f.textbbox((0, 0), line2, font=meta_font_f)
        l1_h = l1_bbox[3] - l1_bbox[1]
        l2_h = l2_bbox[3] - l2_bbox[1]
        needed_h = l1_h + l2_h + 26
        overlay_h = max(needed_h, int(opts.get("float_display_height", max(80, int(height * 0.14)))))
        left_pad = int(opts.get("plateau_left_padding", 20))
        divider_gap = int(opts.get("float_divider_gap", 24))
        y0 = height - overlay_h
        logo_text = (make_f or "CAMERA").upper()
        logo_bbox = draw_f.textbbox((0, 0), logo_text, font=logo_font_f)
        logo_h = logo_bbox[3] - logo_bbox[1]
        logo_y = y0 + (overlay_h - logo_h) // 2
        logo_x = left_pad
        draw_f.text((logo_x, logo_y), logo_text, fill=(245, 245, 245), font=logo_font_f)
        divider_x = logo_x + (logo_bbox[2] - logo_bbox[0]) + divider_gap
        draw_f.line((divider_x, y0 + overlay_h * 0.25, divider_x, y0 + overlay_h * 0.75), fill=(255, 255, 255), width=2)
        text_x = divider_x + divider_gap
        line1_y = y0 + (overlay_h - (l1_h + l2_h + 10)) // 2
        line2_y = line1_y + l1_h + 10
        draw_f.text((text_x, line1_y), line1, fill=(238, 238, 238), font=info_font_f)
        draw_f.text((text_x, line2_y), line2, fill=(220, 220, 220), font=meta_font_f)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas_float.save(output_path, quality=95)
        return

    scale = 1.0
    if preview_max_pixels and preview_max_pixels > 0:
        output_pixels = (width + cfg.side_margin * 2) * (height + cfg.top_margin + cfg.bottom_margin)
        if output_pixels > preview_max_pixels:
            scale = math.sqrt(preview_max_pixels / float(output_pixels))

    def _scaled(v: int, min_value: int = 1) -> int:
        return max(min_value, int(round(v * scale)))

    if scale < 1.0:
        resample_lanczos = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        width = _scaled(width)
        height = _scaled(height)
        source = source.resize((width, height), resample_lanczos)
        cfg = LayoutConfig(
            frame_color=cfg.frame_color,
            top_margin=_scaled(cfg.top_margin, 0),
            bottom_margin=_scaled(cfg.bottom_margin, 0),
            side_margin=_scaled(cfg.side_margin, 0),
            title=cfg.title,
            subtitle=cfg.subtitle,
            font_path=cfg.font_path,
            title_size=_scaled(cfg.title_size),
            subtitle_size=_scaled(cfg.subtitle_size),
            info_size=_scaled(cfg.info_size),
            meta_size=_scaled(cfg.meta_size),
            swatch_count=cfg.swatch_count,
            swatch_label_size=_scaled(cfg.swatch_label_size),
            dump_exif=cfg.dump_exif,
        )
        title_gap = _scaled(title_gap, 0)
        camera_gap = _scaled(camera_gap, 0)
        swatch_height = _scaled(swatch_height)
        swatch_width = _scaled(swatch_width)

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
    if cfg.subtitle:
        subtitle = cfg.subtitle
    else:
        subtitle = f"PHOTOGRAPHED IN : {date_value}" if date_value else ""
        if photographer and style in {"chroma", "simple"}:
            subtitle = f"{subtitle}  by {photographer}" if subtitle else f"by {photographer}"

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
    if style == "float":
        opts = style_options or {}
        overlay_h = max(40, int(opts.get("float_display_height", max(80, int(height * 0.14)))))
        left_pad = int(opts.get("plateau_left_padding", 20))
        logo_size = max(12, int(opts.get("plateau_logo_size", cfg.info_size)))
        divider_gap = int(opts.get("float_divider_gap", 24))
        y0 = cfg.top_margin + height - overlay_h
        logo_text = (make or "CAMERA").upper()
        logo_font = ef.load_font(cfg.font_path, logo_size)
        logo_bbox = draw.textbbox((0, 0), logo_text, font=logo_font)
        logo_h = logo_bbox[3] - logo_bbox[1]
        logo_y = y0 + (overlay_h - logo_h) // 2
        logo_x = left_pad
        draw.text((logo_x, logo_y), logo_text, fill=(245, 245, 245), font=logo_font)
        divider_x = logo_x + (logo_bbox[2] - logo_bbox[0]) + divider_gap
        draw.line((divider_x, y0 + overlay_h * 0.25, divider_x, y0 + overlay_h * 0.75), fill=(255, 255, 255), width=2)
        text_x = divider_x + divider_gap
        draw.text((text_x, y0 + int(overlay_h * 0.22)), f"{photographer or 'Unknown'}    {date_value or '--'}", fill=(238, 238, 238), font=info_font)
        draw.text((text_x, y0 + int(overlay_h * 0.56)), f"{model or camera}    {specs}", fill=(220, 220, 220), font=meta_font)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, quality=95)
        return

    if style == "explicit":
        opts = style_options or {}
        panel_w = max(260, int(width * 0.28))
        draw.rectangle((canvas_w - panel_w, 0, canvas_w, canvas_h), fill=(235, 235, 235))
        x_mid = canvas_w - panel_w // 2
        y = canvas_h - int(opts.get("explicit_bottom_gap", 64))
        row_gap = int(opts.get("explicit_row_gap", max(18, int(cfg.meta_size * 1.4))))
        ev_gap = int(opts.get("explicit_entry_value_gap", 120))
        sections = [
            [("TakenAt", date_value or "--"), ("Location", gps_line or "--")],
            [("Focal", f"{focal_length:.0f}mm" if focal_length else "--"), ("Aperture", f"f/{f_number:.1f}" if f_number else "--"), ("Shutter", ef._format_exposure(exposure)), ("ISO", str(iso) if iso else "--")],
            [("PhotoBy", photographer or "--")],
            [("ShotOn", model or make or "--")],
            [("Logo", (make or "CAMERA").upper())],
        ]
        for si, section in enumerate(reversed(sections)):
            for k, v in reversed(section):
                key_bbox = draw.textbbox((0, 0), k, font=meta_font)
                val_font = info_font if k in {"PhotoBy", "ShotOn", "Logo"} else meta_font
                kw = key_bbox[2] - key_bbox[0]
                x_key = x_mid - (ev_gap // 2)
                x_val = x_mid + (ev_gap // 2)
                draw.text((x_key, y), k, fill=(145, 145, 145), font=meta_font, anchor="ra")
                draw.text((x_val, y), v, fill=(35, 35, 35), font=val_font, anchor="la")
                y -= row_gap
            if si < len(sections) - 1:
                sep_y = y + row_gap // 2
                draw.line((canvas_w - panel_w + 26, sep_y, canvas_w - 26, sep_y), fill=(205, 205, 205), width=2)
                y -= row_gap
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, quality=95)
        return

    title_bbox = draw.textbbox((0, 0), cfg.title, font=title_font)
    title_h = title_bbox[3] - title_bbox[1]
    subtitle_h = 0
    if subtitle:
        subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
        subtitle_h = subtitle_bbox[3] - subtitle_bbox[1]
    top_block_h = title_h + (title_gap if subtitle else 0) + subtitle_h
    top_y = max(0, int((cfg.top_margin - top_block_h) / 2))
    top_text_x = pad_x
    if text_align == "center":
        top_text_x = max(pad_x, int((canvas_w - (title_bbox[2] - title_bbox[0])) / 2))
    elif text_align == "right":
        top_text_x = canvas_w - cfg.side_margin - (title_bbox[2] - title_bbox[0])
    draw.text((top_text_x, top_y), cfg.title, fill=(20, 20, 20), font=title_font)
    if subtitle:
        sub_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
        sub_w = sub_bbox[2] - sub_bbox[0]
        sub_x = pad_x if text_align == "left" else (max(pad_x, int((canvas_w - sub_w) / 2)) if text_align == "center" else canvas_w - cfg.side_margin - sub_w)
        draw.text((sub_x, top_y + title_h + title_gap), subtitle, fill=(120, 120, 120), font=subtitle_font)

    bottom_margin_start = cfg.top_margin + height
    swatch_w = max(80, min(width, swatch_width))
    swatch_h = max(8, swatch_height)
    swatch_block_h = 0
    if style == "chroma":
        swatch_label_bbox = draw.textbbox((0, 0), "#FFFFFF", font=swatch_font)
        swatch_label_h = swatch_label_bbox[3] - swatch_label_bbox[1]
        swatch_block_h = swatch_h + 6 + swatch_label_h
        colors = ef.dominant_colors(source, n_colors=cfg.swatch_count)
        if forced_colors:
            for i, color in enumerate(forced_colors[: len(colors)]):
                colors[i] = color
        swatch_y = bottom_margin_start + max(0, int((cfg.bottom_margin - swatch_block_h) / 2))
        ef.draw_color_swatches(draw, colors, pad_x, swatch_y, swatch_w, swatch_h, swatch_font)

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
    start_y = bottom_margin_start + max(0, int((cfg.bottom_margin - text_block_h) / 2))
    if style == "simple" and text_align in {"left", "center"}:
        camera_x = pad_x if text_align == "left" else max(pad_x, int((canvas_w - camera_w) / 2))
    else:
        camera_x = right_x - camera_w
    draw.text((camera_x, start_y), camera, fill=(20, 20, 20), font=info_font)
    specs_y = start_y + camera_h + camera_gap
    specs_w = specs_bbox[2] - specs_bbox[0]
    if style == "simple" and text_align in {"left", "center"}:
        specs_x = pad_x if text_align == "left" else max(pad_x, int((canvas_w - specs_w) / 2))
    else:
        specs_x = right_x - specs_w
    draw.text((specs_x, specs_y), specs, fill=(120, 120, 120), font=meta_font)
    if gps_line:
        gps_y = specs_y + specs_h + 8
        gps_bbox = draw.textbbox((0, 0), gps_line, font=meta_font)
        gps_w = gps_bbox[2] - gps_bbox[0]
        if style == "simple" and text_align in {"left", "center"}:
            gps_x = pad_x if text_align == "left" else max(pad_x, int((canvas_w - gps_w) / 2))
        else:
            gps_x = right_x - gps_w
        draw.text((gps_x, gps_y), gps_line, fill=(120, 120, 120), font=meta_font)

    if style == "plateau":
        opts = style_options or {}
        bar_h = max(96, cfg.bottom_margin)
        canvas_plateau = Image.new("RGB", (width, height + bar_h), cfg.frame_color)
        canvas_plateau.paste(source, (0, 0))
        draw_p = ef.ImageDraw.Draw(canvas_plateau)
        y0 = height
        draw_p.rectangle((0, y0, width, height + bar_h), fill=(236, 236, 236))
        logo_text = (make or "CAMERA").upper()
        left_pad = int(opts.get("plateau_left_padding", 24))
        logo_size = max(12, int(opts.get("plateau_logo_size", cfg.info_size)))
        logo_font = ef.load_font(cfg.font_path, logo_size)
        logo_bbox = draw_p.textbbox((0, 0), logo_text, font=logo_font)
        logo_y = y0 + (bar_h - (logo_bbox[3] - logo_bbox[1])) // 2
        draw_p.text((left_pad, logo_y), logo_text, fill=(26, 26, 26), font=logo_font)
        mid_x = int(opts.get("plateau_mid_x", int(width * 0.6)))
        model_gap = int(opts.get("plateau_model_exif_gap", 10))
        focal_gap = int(opts.get("plateau_model_focal_gap", 30))
        model_font = ef.load_font(cfg.font_path, cfg.info_size)
        if opts.get("plateau_model_bold"):
            model_font = ef.load_font(cfg.font_path, cfg.info_size + 2)
        model_text = model or camera
        model_bbox = draw_p.textbbox((0, 0), model_text, font=model_font)
        specs_bbox = draw_p.textbbox((0, 0), specs, font=meta_font)
        model_h = model_bbox[3] - model_bbox[1]
        specs_h = specs_bbox[3] - specs_bbox[1]
        block_h = model_h + model_gap + specs_h
        model_y = y0 + (bar_h - block_h) // 2
        draw_p.text((mid_x, model_y), model_text, fill=(25, 25, 25), font=model_font, anchor="ra")
        draw_p.text((mid_x, model_y + model_h + model_gap), specs, fill=(30, 30, 30), font=meta_font, anchor="ra")
        focal_txt = f"{focal_length:.0f}mm" if focal_length else "--mm"
        draw_p.text((mid_x + focal_gap, y0 + bar_h // 2), focal_txt, fill=(22, 22, 22), font=ef.load_font(cfg.font_path, cfg.meta_size * 2), anchor="lm")
        by_font = ef.load_font(cfg.font_path, cfg.info_size + 2 if opts.get("plateau_photographer_bold") else cfg.info_size)
        right_x = width - max(18, cfg.side_margin)
        by_bbox = draw_p.textbbox((0, 0), f"by {photographer or 'Unknown'}", font=by_font)
        by_h = by_bbox[3] - by_bbox[1]
        by_y = y0 + (bar_h - by_h - cfg.meta_size) // 2
        draw_p.text((right_x, by_y), f"by {photographer or 'Unknown'}", fill=(20, 20, 20), font=by_font, anchor="ra")
        draw_p.text((right_x, by_y + by_h + 6), date_value or "--", fill=(30, 30, 30), font=meta_font, anchor="ra")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas_plateau.save(output_path, quality=95)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=95)


class ExifFrameQt(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EXIF Frame Studio (PyQt)")
        self.resize(1700, 1000)

        self.image_paths: list[Path] = []
        self.current_index = 0
        self.preview_cache: dict[str, QPixmap] = {}
        self.pending_key: str | None = None
        self.active_pick_index: int | None = None
        self.manual_swatch_rows: list[tuple[QLabel, QLineEdit, QPushButton]] = []
        self.manual_swatch_map: dict[Path, list[str]] = {}
        self.preview_zoom = 1.0
        self.base_preview_pixmap = QPixmap()
        self._pan_last = None
        self.current_style = "chroma"
        self.style_states: dict[str, dict] = {}
        self._applying_style_state = False

        self.pool = QThreadPool.globalInstance()
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.render_preview)

        self._build_ui()

    def _build_ui(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)

        for text, cb in [
            ("Open Image", self.open_image),
            ("Open Folder", self.open_folder),
            ("Close", self.clear_images),
            ("Apply To All", self.apply_to_all),
            ("Export", self.export_images),
        ]:
            action = QAction(text, self)
            action.triggered.connect(cb)
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Style:"))
        self.style_selector = QComboBox()
        self.style_selector.addItems(["chroma", "simple", "plateau", "float", "explicit"])
        self.style_selector.setCurrentText(self.current_style)
        self.style_selector.currentTextChanged.connect(self.on_style_changed)
        toolbar.addWidget(self.style_selector)

        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QHBoxLayout(root)

        splitter = QSplitter()
        main_layout.addWidget(splitter)

        # Left preview area
        left = QWidget()
        left_layout = QVBoxLayout(left)

        self.selection_label = QLabel("No image selected")
        left_layout.addWidget(self.selection_label)

        preview_splitter = QSplitter(Qt.Orientation.Vertical if PYQT_VER == 6 else Qt.Vertical)
        left_layout.addWidget(preview_splitter, 1)

        self.preview = QLabel("Open an image or folder")
        self.preview.setAlignment(_align_center())
        self.preview.mousePressEvent = self._on_preview_mouse_press  # type: ignore[method-assign]
        self.preview.mouseMoveEvent = self._on_preview_mouse_move  # type: ignore[method-assign]
        self.preview.mouseReleaseEvent = self._on_preview_mouse_release  # type: ignore[method-assign]
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setWidget(self.preview)
        self.preview_scroll.setAlignment(_align_center())
        self.preview_scroll.viewport().wheelEvent = self._on_preview_wheel  # type: ignore[method-assign]
        preview_splitter.addWidget(self.preview_scroll)

        self.mini_list = QListWidget()
        self.mini_list.setViewMode(QListWidget.ViewMode.ListMode if PYQT_VER == 6 else QListWidget.ListMode)
        self.mini_list.setFlow(QListWidget.Flow.TopToBottom if PYQT_VER == 6 else QListWidget.TopToBottom)
        self.mini_list.setWrapping(False)
        self.mini_list.setIconSize(QPixmap(140, 90).size())
        self.mini_list.currentRowChanged.connect(self.select_index)
        preview_splitter.addWidget(self.mini_list)
        preview_splitter.setSizes([760, 220])

        splitter.addWidget(left)

        # Right settings panel
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_splitter = QSplitter(Qt.Orientation.Vertical if PYQT_VER == 6 else Qt.Vertical)
        right_layout.addWidget(right_splitter, 1)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_body = QWidget()
        settings_layout = QVBoxLayout(settings_body)
        form = QFormLayout()
        self.form = form

        self.title_edit = QLineEdit("Nature's poetry")
        self.subtitle_edit = QLineEdit("")
        self.photographer_edit = QLineEdit("")
        self.frame_color_edit = QLineEdit("#F2F2F2")
        color_btn = QPushButton("Pick")
        color_btn.clicked.connect(self.pick_color)
        color_row = QWidget()
        color_l = QHBoxLayout(color_row)
        color_l.setContentsMargins(0, 0, 0, 0)
        color_l.addWidget(self.frame_color_edit)
        color_l.addWidget(color_btn)

        top_margin_row, self.top_margin = self._slider_spin(0, 2000, 170)
        bottom_margin_row, self.bottom_margin = self._slider_spin(0, 2000, 190)
        side_margin_row, self.side_margin = self._slider_spin(0, 1000, 40)
        title_size_row, self.title_size = self._slider_spin(8, 300, 62)
        subtitle_size_row, self.subtitle_size = self._slider_spin(8, 300, 42)
        info_size_row, self.info_size = self._slider_spin(8, 300, 64)
        meta_size_row, self.meta_size = self._slider_spin(8, 300, 38)
        swatch_count_row, self.swatch_count = self._slider_spin(1, 20, 5)
        swatch_hex_row, self.swatch_label_size = self._slider_spin(8, 120, 20)
        title_gap_row, self.title_subtitle_gap = self._slider_spin(0, 200, 8)
        camera_gap_row, self.camera_meta_gap = self._slider_spin(0, 200, 12)
        swatch_box_row, self.swatch_box_height = self._slider_spin(8, 300, 40)
        swatch_width_row, self.swatch_box_width = self._slider_spin(80, 5000, 520)
        self.text_align = QComboBox()
        self.text_align.addItems(["left", "center", "right"])
        self.text_align.setCurrentText("left")
        self.text_align.setVisible(False)
        plateau_left_row, self.plateau_left_padding = self._slider_spin(0, 500, 24)
        plateau_logo_row, self.plateau_logo_size = self._slider_spin(8, 200, 42)
        plateau_mid_row, self.plateau_mid_x = self._slider_spin(0, 8000, 2972)
        plateau_exif_gap_row, self.plateau_model_exif_gap = self._slider_spin(0, 120, 10)
        plateau_focal_gap_row, self.plateau_model_focal_gap = self._slider_spin(0, 400, 126)
        self.plateau_photographer_bold = QCheckBox("Bold photographer")
        self.plateau_model_bold = QCheckBox("Bold camera model")
        float_height_row, self.float_display_height = self._slider_spin(40, 1200, 120)
        float_divider_row, self.float_divider_gap = self._slider_spin(2, 120, 24)
        explicit_row_gap_row, self.explicit_row_gap = self._slider_spin(8, 220, 36)
        explicit_entry_gap_row, self.explicit_entry_gap = self._slider_spin(20, 300, 120)
        explicit_bottom_gap_row, self.explicit_bottom_gap = self._slider_spin(10, 500, 64)
        self.font_path = QLineEdit("")
        self.export_template = QLineEdit("${filename}_framed")
        self.dump_exif = QCheckBox("Dump EXIF")
        self.manual_swatch_enable = QCheckBox("Enable manual swatch colors")
        self.manual_swatch_enable.stateChanged.connect(self._update_manual_swatch_ui)

        help_btn = QPushButton("Template Help")
        help_btn.clicked.connect(self.template_help)

        form.addRow("Title", self.title_edit)
        form.addRow("Subtitle", self.subtitle_edit)
        form.addRow("Photographer", self.photographer_edit)
        form.addRow("Frame color", color_row)
        form.addRow("Top margin", top_margin_row)
        form.addRow("Bottom margin", bottom_margin_row)
        form.addRow("Side margin", side_margin_row)
        form.addRow("Title size", title_size_row)
        form.addRow("Subtitle size", subtitle_size_row)
        form.addRow("Camera size", info_size_row)
        form.addRow("Meta size", meta_size_row)
        form.addRow("Swatch count", swatch_count_row)
        form.addRow("Swatch hex size", swatch_hex_row)
        form.addRow("Title-Subtitle gap", title_gap_row)
        form.addRow("Camera-Meta gap", camera_gap_row)
        form.addRow("Swatch box height", swatch_box_row)
        form.addRow("Swatch box width", swatch_width_row)
        form.addRow("Text alignment", self.text_align)
        form.addRow("Plateau left padding", plateau_left_row)
        form.addRow("Plateau logo size", plateau_logo_row)
        form.addRow("Plateau center X", plateau_mid_row)
        form.addRow("Plateau model-exif gap", plateau_exif_gap_row)
        form.addRow("Plateau model-focal gap", plateau_focal_gap_row)
        form.addRow("", self.plateau_photographer_bold)
        form.addRow("", self.plateau_model_bold)
        form.addRow("Float display height", float_height_row)
        form.addRow("Float divider gap", float_divider_row)
        form.addRow("Explicit row gap", explicit_row_gap_row)
        form.addRow("Explicit entry-value gap", explicit_entry_gap_row)
        form.addRow("Explicit bottom gap", explicit_bottom_gap_row)
        form.addRow("Font path", self.font_path)
        form.addRow("Export template", self.export_template)
        form.addRow("", help_btn)
        form.addRow("", self.dump_exif)
        form.addRow("", self.manual_swatch_enable)

        self.manual_swatch_wrap = QWidget()
        manual_layout = QVBoxLayout(self.manual_swatch_wrap)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        for idx in range(20):
            row = QWidget()
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 0, 0, 0)
            chip = QLabel("")
            chip.setFixedSize(22, 22)
            chip.setStyleSheet("background:#000000;border:1px solid #888;")
            hex_edit = QLineEdit("#000000")
            hex_edit.setReadOnly(True)
            pick_btn = QPushButton(f"Pick {idx + 1}")
            pick_btn.clicked.connect(lambda _=False, i=idx: self._start_pick_color(i))
            row_l.addWidget(chip)
            row_l.addWidget(hex_edit, 1)
            row_l.addWidget(pick_btn)
            manual_layout.addWidget(row)
            self.manual_swatch_rows.append((chip, hex_edit, pick_btn))
        self.manual_hint = QLabel("Click Pick N, then click a color in the preview.")
        manual_layout.addWidget(self.manual_hint)
        settings_layout.addWidget(self.manual_swatch_wrap)
        self._update_manual_swatch_ui()
        self.chroma_only_widgets = [swatch_count_row, swatch_hex_row, swatch_box_row, swatch_width_row, self.manual_swatch_enable, self.manual_swatch_wrap]
        self.simple_only_widgets = [self.text_align]
        self.plateau_only_widgets = [plateau_left_row, plateau_logo_row, plateau_mid_row, plateau_exif_gap_row, plateau_focal_gap_row, self.plateau_photographer_bold, self.plateau_model_bold]
        self.float_only_widgets = [float_height_row, float_divider_row]
        self.explicit_only_widgets = [explicit_row_gap_row, explicit_entry_gap_row, explicit_bottom_gap_row]
        self.margin_widgets = [top_margin_row, bottom_margin_row, side_margin_row]
        self.base_common_fields = [
            self.title_edit,
            self.subtitle_edit,
            self.photographer_edit,
            color_row,
            title_size_row,
            subtitle_size_row,
            info_size_row,
            meta_size_row,
            title_gap_row,
            camera_gap_row,
            self.font_path,
            self.export_template,
            help_btn,
            self.dump_exif,
        ]

        settings_layout.addLayout(form)
        settings_body.setLayout(settings_layout)
        settings_scroll.setWidget(settings_body)
        right_splitter.addWidget(settings_scroll)

        bottom_panel = QWidget()
        bottom_layout = QVBoxLayout(bottom_panel)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 100)
        bottom_layout.addWidget(QLabel("Progress"))
        bottom_layout.addWidget(self.export_progress)
        bottom_layout.addWidget(QLabel("Current image EXIF"))
        self.exif_box = QTextEdit()
        self.exif_box.setReadOnly(True)
        bottom_layout.addWidget(self.exif_box, 1)
        right_splitter.addWidget(bottom_panel)
        right_splitter.setSizes([620, 320])

        splitter.addWidget(right)
        splitter.setSizes([1100, 500])

        # live updates
        for widget in [
            self.title_edit,
            self.subtitle_edit,
            self.photographer_edit,
            self.frame_color_edit,
            self.top_margin,
            self.bottom_margin,
            self.side_margin,
            self.title_size,
            self.subtitle_size,
            self.info_size,
            self.meta_size,
            self.swatch_count,
            self.swatch_label_size,
            self.title_subtitle_gap,
            self.camera_meta_gap,
            self.swatch_box_height,
            self.swatch_box_width,
            self.text_align,
            self.plateau_left_padding,
            self.plateau_logo_size,
            self.plateau_mid_x,
            self.plateau_model_exif_gap,
            self.plateau_model_focal_gap,
            self.plateau_photographer_bold,
            self.plateau_model_bold,
            self.float_display_height,
            self.float_divider_gap,
            self.explicit_row_gap,
            self.explicit_entry_gap,
            self.explicit_bottom_gap,
            self.font_path,
            self.dump_exif,
            self.manual_swatch_enable,
        ]:
            self._connect_changed(widget)
        self.swatch_count.valueChanged.connect(self._update_manual_swatch_ui)
        self.manual_swatch_enable.stateChanged.connect(self._update_manual_swatch_ui)
        self.on_style_changed(self.current_style)

    def _spin(self, mn: int, mx: int, val: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(mn, mx)
        s.setValue(val)
        return s

    def _slider_spin(self, mn: int, mx: int, val: int) -> tuple[QWidget, QSpinBox]:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        slider = QSlider(Qt.Orientation.Horizontal if PYQT_VER == 6 else Qt.Horizontal)
        slider.setRange(mn, mx)
        spin = self._spin(mn, mx, val)
        slider.setValue(val)
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        layout.addWidget(slider, 1)
        layout.addWidget(spin)
        return row, spin

    def _connect_changed(self, widget: QWidget) -> None:
        def _maybe_schedule(*_args):
            if not self._applying_style_state:
                self.schedule_preview()

        if isinstance(widget, QLineEdit):
            widget.textChanged.connect(_maybe_schedule)
        elif isinstance(widget, QSpinBox):
            widget.valueChanged.connect(_maybe_schedule)
        elif isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(_maybe_schedule)
        elif isinstance(widget, QCheckBox):
            widget.stateChanged.connect(_maybe_schedule)

    def pick_color(self) -> None:
        color = QColorDialog.getColor()
        if color.isValid():
            self.frame_color_edit.setText(color.name())

    def _update_manual_swatch_ui(self) -> None:
        if self.current_style != "chroma":
            self.manual_swatch_wrap.setVisible(False)
            self.active_pick_index = None
            return
        enabled = self.manual_swatch_enable.isChecked()
        count = self.swatch_count.value()
        self.manual_swatch_wrap.setVisible(enabled)
        for i, (chip, hex_edit, btn) in enumerate(self.manual_swatch_rows):
            visible = enabled and i < count
            chip.setVisible(visible)
            hex_edit.setVisible(visible)
            btn.setVisible(visible)
        if not enabled:
            self.active_pick_index = None
        p = self.current_image_path()
        if enabled and p:
            existing = self.manual_swatch_map.get(p, [])
            if (not existing) or all(c.upper() == "#000000" for c in existing[:count]):
                self.manual_swatch_map[p] = self._auto_swatch_hexes(p, count)
        if p:
            self._load_manual_colors(p)

    def _start_pick_color(self, idx: int) -> None:
        self.active_pick_index = idx
        self.selection_label.setText(f"Pick mode: click preview for swatch {idx + 1}")

    def _on_preview_mouse_press(self, event) -> None:
        if self.active_pick_index is not None:
            self._sample_preview_color(event)
            return
        self._pan_last = event.pos()

    def _on_preview_mouse_move(self, event) -> None:
        if self._pan_last is None:
            return
        dx = event.pos().x() - self._pan_last.x()
        dy = event.pos().y() - self._pan_last.y()
        self.preview_scroll.horizontalScrollBar().setValue(self.preview_scroll.horizontalScrollBar().value() - dx)
        self.preview_scroll.verticalScrollBar().setValue(self.preview_scroll.verticalScrollBar().value() - dy)
        self._pan_last = event.pos()

    def _on_preview_mouse_release(self, _event) -> None:
        self._pan_last = None

    def _on_preview_wheel(self, event) -> None:
        delta = event.angleDelta().y() if hasattr(event, "angleDelta") else 0
        if delta > 0:
            self.preview_zoom = min(6.0, self.preview_zoom * 1.12)
        elif delta < 0:
            self.preview_zoom = max(0.2, self.preview_zoom / 1.12)
        self._apply_preview_transform()

    def _sample_preview_color(self, event) -> None:
        if self.active_pick_index is None:
            return
        pix = self.preview.pixmap()
        if not pix:
            return
        x = event.position().x() if PYQT_VER == 6 else event.x()
        y = event.position().y() if PYQT_VER == 6 else event.y()
        x_i, y_i = int(x), int(y)
        if x_i < 0 or y_i < 0 or x_i >= pix.width() or y_i >= pix.height():
            return
        qc = pix.toImage().pixelColor(x_i, y_i)
        hex_color = qc.name().upper()
        chip, hex_edit, _ = self.manual_swatch_rows[self.active_pick_index]
        chip.setStyleSheet(f"background:{hex_color};border:1px solid #888;")
        hex_edit.setText(hex_color)
        p = self.current_image_path()
        if p:
            self._persist_manual_colors(p)
        self.active_pick_index = None
        self.schedule_preview()

    def current_image_path(self) -> Path | None:
        if not self.image_paths:
            return None
        return self.image_paths[self.current_index]

    def _persist_manual_colors(self, img_path: Path) -> None:
        count = self.swatch_count.value()
        self.manual_swatch_map[img_path] = [self.manual_swatch_rows[i][1].text() for i in range(count)]

    def _load_manual_colors(self, img_path: Path) -> None:
        count = self.swatch_count.value()
        colors = list(self.manual_swatch_map.get(img_path, []))
        while len(colors) < count:
            colors.append("#000000")
        colors = colors[:count]
        self.manual_swatch_map[img_path] = colors
        for i in range(count):
            chip, hex_edit, _ = self.manual_swatch_rows[i]
            hex_edit.setText(colors[i])
            chip.setStyleSheet(f"background:{colors[i]};border:1px solid #888;")

    def _auto_swatch_hexes(self, img_path: Path, count: int) -> list[str]:
        try:
            from PIL import Image as PILImage

            with PILImage.open(img_path) as image:
                image = ef.ImageOps.exif_transpose(image).convert("RGB")
                cols = ef.dominant_colors(image, n_colors=count)
            return [f"#{r:02X}{g:02X}{b:02X}" for r, g, b in cols[:count]]
        except Exception:
            return ["#000000"] * count

    def _manual_color_tuples(self, img_path: Path | None = None) -> list[tuple[int, int, int]] | None:
        if self.current_style != "chroma" or not self.manual_swatch_enable.isChecked():
            return None
        if img_path is None:
            img_path = self.current_image_path()
        if img_path:
            self._load_manual_colors(img_path)
        out: list[tuple[int, int, int]] = []
        for i in range(self.swatch_count.value()):
            out.append(parse_hex_color(self.manual_swatch_rows[i][1].text().strip() or "#000000"))
        return out

    def _style_options(self) -> dict:
        return {
            "plateau_left_padding": self.plateau_left_padding.value(),
            "plateau_logo_size": self.plateau_logo_size.value(),
            "plateau_mid_x": self.plateau_mid_x.value(),
            "plateau_model_exif_gap": self.plateau_model_exif_gap.value(),
            "plateau_model_focal_gap": self.plateau_model_focal_gap.value(),
            "plateau_photographer_bold": self.plateau_photographer_bold.isChecked(),
            "plateau_model_bold": self.plateau_model_bold.isChecked(),
            "float_display_height": self.float_display_height.value(),
            "float_divider_gap": self.float_divider_gap.value(),
            "explicit_row_gap": self.explicit_row_gap.value(),
            "explicit_entry_value_gap": self.explicit_entry_gap.value(),
            "explicit_bottom_gap": self.explicit_bottom_gap.value(),
        }

    def _capture_style_state(self) -> dict:
        return {
            "top_margin": self.top_margin.value(),
            "bottom_margin": self.bottom_margin.value(),
            "side_margin": self.side_margin.value(),
            "title_size": self.title_size.value(),
            "subtitle_size": self.subtitle_size.value(),
            "info_size": self.info_size.value(),
            "meta_size": self.meta_size.value(),
            "swatch_count": self.swatch_count.value(),
            "swatch_label_size": self.swatch_label_size.value(),
            "swatch_box_height": self.swatch_box_height.value(),
            "swatch_box_width": self.swatch_box_width.value(),
            "title_gap": self.title_subtitle_gap.value(),
            "camera_gap": self.camera_meta_gap.value(),
            "text_align": self.text_align.currentText(),
            **self._style_options(),
        }

    def _apply_style_state(self, state: dict) -> None:
        self._applying_style_state = True
        self.top_margin.setValue(int(state.get("top_margin", self.top_margin.value())))
        self.bottom_margin.setValue(int(state.get("bottom_margin", self.bottom_margin.value())))
        self.side_margin.setValue(int(state.get("side_margin", self.side_margin.value())))
        self.title_size.setValue(int(state.get("title_size", self.title_size.value())))
        self.subtitle_size.setValue(int(state.get("subtitle_size", self.subtitle_size.value())))
        self.info_size.setValue(int(state.get("info_size", self.info_size.value())))
        self.meta_size.setValue(int(state.get("meta_size", self.meta_size.value())))
        self.swatch_count.setValue(int(state.get("swatch_count", self.swatch_count.value())))
        self.swatch_label_size.setValue(int(state.get("swatch_label_size", self.swatch_label_size.value())))
        self.swatch_box_height.setValue(int(state.get("swatch_box_height", self.swatch_box_height.value())))
        self.swatch_box_width.setValue(int(state.get("swatch_box_width", self.swatch_box_width.value())))
        self.title_subtitle_gap.setValue(int(state.get("title_gap", self.title_subtitle_gap.value())))
        self.camera_meta_gap.setValue(int(state.get("camera_gap", self.camera_meta_gap.value())))
        self.text_align.setCurrentText(str(state.get("text_align", self.text_align.currentText())))
        self.plateau_left_padding.setValue(int(state.get("plateau_left_padding", self.plateau_left_padding.value())))
        self.plateau_logo_size.setValue(int(state.get("plateau_logo_size", self.plateau_logo_size.value())))
        self.plateau_mid_x.setValue(int(state.get("plateau_mid_x", self.plateau_mid_x.value())))
        self.plateau_model_exif_gap.setValue(int(state.get("plateau_model_exif_gap", self.plateau_model_exif_gap.value())))
        self.plateau_model_focal_gap.setValue(int(state.get("plateau_model_focal_gap", self.plateau_model_focal_gap.value())))
        self.plateau_photographer_bold.setChecked(bool(state.get("plateau_photographer_bold", self.plateau_photographer_bold.isChecked())))
        self.plateau_model_bold.setChecked(bool(state.get("plateau_model_bold", self.plateau_model_bold.isChecked())))
        self.float_display_height.setValue(int(state.get("float_display_height", self.float_display_height.value())))
        self.float_divider_gap.setValue(int(state.get("float_divider_gap", self.float_divider_gap.value())))
        self.explicit_row_gap.setValue(int(state.get("explicit_row_gap", self.explicit_row_gap.value())))
        self.explicit_entry_gap.setValue(int(state.get("explicit_entry_value_gap", self.explicit_entry_gap.value())))
        self.explicit_bottom_gap.setValue(int(state.get("explicit_bottom_gap", self.explicit_bottom_gap.value())))
        self._applying_style_state = False

    def template_help(self) -> None:
        QMessageBox.information(
            self,
            "Template Help",
            "Use placeholders like ${filename}, ${stem}, ${ext}, ${make}, ${model}, ${datetime}, ${iso}.\n"
            "You can also use any EXIF key, e.g. ${DateTimeOriginal}.",
        )

    def _set_field_visible(self, field: QWidget, visible: bool) -> None:
        lbl = self.form.labelForField(field)
        if lbl is not None:
            lbl.setVisible(visible)
        field.setVisible(visible)

    def on_style_changed(self, style: str) -> None:
        if hasattr(self, "current_style") and self.current_style:
            self.style_states[self.current_style] = self._capture_style_state()
        self.current_style = style if style in {"chroma", "simple", "plateau", "float", "explicit"} else "chroma"
        if self.current_style in self.style_states:
            self._apply_style_state(self.style_states[self.current_style])
        for f in self.base_common_fields:
            self._set_field_visible(f, True)
        for w in self.margin_widgets + self.chroma_only_widgets + self.simple_only_widgets + self.plateau_only_widgets + self.float_only_widgets + self.explicit_only_widgets:
            self._set_field_visible(w, False)

        if self.current_style == "chroma":
            for w in self.margin_widgets + self.chroma_only_widgets:
                self._set_field_visible(w, True)
        elif self.current_style == "simple":
            for w in self.margin_widgets + self.simple_only_widgets:
                self._set_field_visible(w, True)
            self.manual_swatch_enable.setChecked(False)
        elif self.current_style == "plateau":
            for w in self.margin_widgets + self.plateau_only_widgets:
                self._set_field_visible(w, True)
            self.manual_swatch_enable.setChecked(False)
        elif self.current_style == "float":
            for w in self.float_only_widgets:
                self._set_field_visible(w, True)
            self.manual_swatch_enable.setChecked(False)
        elif self.current_style == "explicit":
            for w in self.margin_widgets + self.explicit_only_widgets:
                self._set_field_visible(w, True)
            self.manual_swatch_enable.setChecked(False)
        self._update_manual_swatch_ui()
        self.schedule_preview()

    def open_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Open image", "", "JPEG (*.jpg *.jpeg)")
        if not file_path:
            return
        self.image_paths = [Path(file_path)]
        self.current_index = 0
        self._load_manual_colors(self.image_paths[0])
        self.rebuild_minimap()
        self.update_selection_label()
        self.update_exif_panel()
        self.schedule_preview()

    def open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open folder")
        if not folder:
            return
        all_items = [p for p in Path(folder).iterdir() if p.is_file()]
        total_items = max(1, len(all_items))
        files: list[Path] = []
        for idx, p in enumerate(all_items, start=1):
            if p.suffix.lower() in {".jpg", ".jpeg"}:
                files.append(p)
            self.export_progress.setValue(int((idx / total_items) * 100))
            QApplication.processEvents()
        files = sorted(files)
        if not files:
            QMessageBox.warning(self, "No images", "No JPG/JPEG files found.")
            return
        self.image_paths = files
        self.current_index = 0
        self._load_manual_colors(self.image_paths[0])
        self.rebuild_minimap()
        self.update_selection_label()
        self.update_exif_panel()
        self.schedule_preview()

    def clear_images(self) -> None:
        self.image_paths = []
        self.current_index = 0
        self.manual_swatch_map.clear()
        self.preview_cache.clear()
        self.pending_key = None
        self.preview.setText("Open an image or folder")
        self.preview.setPixmap(QPixmap())
        self.mini_list.clear()
        self.selection_label.setText("No image selected")
        self.exif_box.setText("Open an image to view EXIF metadata.")

    def apply_to_all(self) -> None:
        QMessageBox.information(self, "Apply", f"Current settings will be used for {len(self.image_paths)} image(s).")

    def rebuild_minimap(self) -> None:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None
        self.mini_list.clear()
        for p in self.image_paths:
            pix = QPixmap()
            try:
                with Image.open(p) as img:
                    img = ef.ImageOps.exif_transpose(img).convert("RGB")
                    img.thumbnail((140, 90))
                    data = img.tobytes("raw", "RGB")
                    fmt = QImage.Format.Format_RGB888 if PYQT_VER == 6 else QImage.Format_RGB888
                    qimg = QImage(data, img.width, img.height, img.width * 3, fmt)
                    pix = QPixmap.fromImage(qimg.copy())
            except Exception:
                pix = QPixmap(str(p)).scaled(140, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) if PYQT_VER == 6 else QPixmap(str(p)).scaled(140, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            item = QListWidgetItem(p.name)
            item.setIcon(QIcon(pix))
            self.mini_list.addItem(item)
        if self.image_paths:
            self.mini_list.setCurrentRow(0)

    def select_index(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.image_paths):
            return
        prev = self.current_image_path()
        if prev:
            self._persist_manual_colors(prev)
        self.current_index = idx
        self._load_manual_colors(self.image_paths[idx])
        self.update_selection_label()
        self.update_exif_panel()
        self.schedule_preview()

    def update_selection_label(self) -> None:
        if not self.image_paths:
            self.selection_label.setText("No image selected")
            return
        p = self.image_paths[self.current_index]
        self.selection_label.setText(f"{p} ({self.current_index + 1} of {len(self.image_paths)})")

    def update_exif_panel(self) -> None:
        if not self.image_paths:
            self.exif_box.setText("Open an image to view EXIF metadata.")
            return
        try:
            p = self.image_paths[self.current_index]
            from PIL import Image as PILImage

            PILImage.MAX_IMAGE_PIXELS = None
            with PILImage.open(p) as image:
                exif = get_exif_data(image)
            if not exif:
                self.exif_box.setText(f"{p.name}\n\nNo EXIF metadata found.")
                return
            lines = [p.name, ""]
            for k in sorted(exif.keys()):
                if k == "GPSInfo" and isinstance(exif[k], dict):
                    lines.append("GPSInfo:")
                    for gk in sorted(exif[k].keys()):
                        lines.append(f"  {gk}: {exif[k][gk]}")
                else:
                    lines.append(f"{k}: {exif[k]}")
            self.exif_box.setText("\n".join(lines))
        except Exception as exc:
            self.exif_box.setText(f"Failed to read EXIF:\n{exc}")

    def _build_cfg(self) -> LayoutConfig:
        return LayoutConfig(
            frame_color=parse_hex_color(self.frame_color_edit.text()),
            top_margin=self.top_margin.value(),
            bottom_margin=self.bottom_margin.value(),
            side_margin=self.side_margin.value(),
            title=self.title_edit.text(),
            subtitle=self.subtitle_edit.text().strip() or None,
            title_size=self.title_size.value(),
            subtitle_size=self.subtitle_size.value(),
            info_size=self.info_size.value(),
            meta_size=self.meta_size.value(),
            font_path=self.font_path.text().strip() or None,
            dump_exif=self.dump_exif.isChecked(),
            swatch_count=self.swatch_count.value(),
            swatch_label_size=self.swatch_label_size.value(),
        )

    def schedule_preview(self) -> None:
        self.preview_timer.start(150)

    def render_preview(self) -> None:
        if not self.image_paths:
            return
        try:
            cfg = self._build_cfg()
        except Exception as exc:
            self.preview.setText(f"Invalid settings: {exc}")
            return

        src = self.image_paths[self.current_index]
        key = self._preview_key(src, cfg)
        self.pending_key = key

        if key in self.preview_cache:
            self._set_preview_pixmap(self.preview_cache[key])
            return

        self.preview.setText("Rendering preview...")
        self.export_progress.setValue(10)
        worker = RenderWorker(
            key,
            src,
            cfg,
            self.title_subtitle_gap.value(),
            self.camera_meta_gap.value(),
            self.swatch_box_height.value(),
            self.swatch_box_width.value(),
            self._manual_color_tuples(src),
            style=self.current_style,
            text_align=self.text_align.currentText(),
            photographer=self.photographer_edit.text().strip() or None,
            style_options=self._style_options(),
        )
        worker.signals.done.connect(self._preview_done)
        worker.signals.error.connect(lambda msg: (self.preview.setText(f"Preview error: {msg}"), self.export_progress.setValue(0)))
        self.pool.start(worker)

    def _preview_done(self, key: str, path: str) -> None:
        if self.pending_key != key:
            Path(path).unlink(missing_ok=True)
            return
        pix = QPixmap(path)
        Path(path).unlink(missing_ok=True)
        self.preview_cache[key] = pix
        self._set_preview_pixmap(pix)
        self.export_progress.setValue(100)

    def _set_preview_pixmap(self, pix: QPixmap) -> None:
        self.base_preview_pixmap = pix
        self._apply_preview_transform()

    def _apply_preview_transform(self) -> None:
        if self.base_preview_pixmap.isNull():
            return
        vw = max(300, self.preview_scroll.viewport().width() - 20)
        vh = max(300, self.preview_scroll.viewport().height() - 20)
        fit_scale = min(vw / max(1, self.base_preview_pixmap.width()), vh / max(1, self.base_preview_pixmap.height()))
        final_scale = max(0.05, fit_scale * self.preview_zoom)
        tw = max(1, int(self.base_preview_pixmap.width() * final_scale))
        th = max(1, int(self.base_preview_pixmap.height() * final_scale))
        scaled = self.base_preview_pixmap.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) if PYQT_VER == 6 else self.base_preview_pixmap.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(scaled)
        self.preview.resize(scaled.size())
        self.preview.setText("")

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        if self.pending_key and self.pending_key in self.preview_cache:
            self._set_preview_pixmap(self.preview_cache[self.pending_key])

    def _preview_key(self, src: Path, cfg: LayoutConfig) -> str:
        extra = {
            "title_gap": self.title_subtitle_gap.value(),
            "camera_gap": self.camera_meta_gap.value(),
            "swatch_box_height": self.swatch_box_height.value(),
            "swatch_box_width": self.swatch_box_width.value(),
            "manual_colors": self._manual_color_tuples(src),
            "style": self.current_style,
            "text_align": self.text_align.currentText(),
            "photographer": self.photographer_edit.text().strip(),
            "style_opts": self._style_options(),
        }
        payload = f"{src}|{src.stat().st_mtime_ns}|{asdict(cfg)}|{extra}"
        return hashlib.sha1(payload.encode()).hexdigest()

    def _render_template_name(self, src: Path) -> str:
        replacements = {"filename": src.stem, "stem": src.stem, "ext": src.suffix.lstrip(".")}
        try:
            from PIL import Image as PILImage

            with PILImage.open(src) as image:
                exif = get_exif_data(image)
            for k, v in exif.items():
                if isinstance(v, dict):
                    continue
                replacements[str(k)] = str(v).strip()
                replacements[str(k).lower()] = str(v).strip()
        except Exception:
            pass

        template = self.export_template.text().strip() or "${filename}_framed"

        def repl(m):
            t = m.group(1)
            return replacements.get(t, replacements.get(t.lower(), ""))

        rendered = re.sub(r"\$\{([^}]+)\}", repl, template).strip() or f"{src.stem}_framed"
        return re.sub(r'[\\/:*?"<>|]+', "_", rendered)

    def export_images(self) -> None:
        if not self.image_paths:
            QMessageBox.information(self, "No images", "Open an image or folder first.")
            return
        try:
            cfg = self._build_cfg()
        except Exception as exc:
            QMessageBox.critical(self, "Invalid settings", str(exc))
            return

        if len(self.image_paths) == 1:
            suggested = f"{self._render_template_name(self.image_paths[0])}.jpg"
            out, _ = QFileDialog.getSaveFileName(self, "Export image", suggested, "JPEG (*.jpg)")
            if not out:
                return
            render_with_options(
                self.image_paths[0],
                Path(out),
                cfg,
                self.title_subtitle_gap.value(),
                self.camera_meta_gap.value(),
                self.swatch_box_height.value(),
                self.swatch_box_width.value(),
                forced_colors=self._manual_color_tuples(self.image_paths[0]),
                style=self.current_style,
                text_align=self.text_align.currentText(),
                photographer=self.photographer_edit.text().strip() or None,
                style_options=self._style_options(),
            )
            self.export_progress.setValue(100)
            QMessageBox.information(self, "Done", f"Exported:\n{out}")
            return

        out_dir = QFileDialog.getExistingDirectory(self, "Select output folder")
        if not out_dir:
            return

        failures: list[str] = []
        self.export_progress.setValue(0)

        for idx, src in enumerate(self.image_paths, start=1):
            dst = Path(out_dir) / f"{self._render_template_name(src)}.jpg"
            try:
                render_with_options(
                    src,
                    dst,
                    cfg,
                    self.title_subtitle_gap.value(),
                    self.camera_meta_gap.value(),
                    self.swatch_box_height.value(),
                    self.swatch_box_width.value(),
                    forced_colors=self._manual_color_tuples(src),
                    style=self.current_style,
                    text_align=self.text_align.currentText(),
                    photographer=self.photographer_edit.text().strip() or None,
                    style_options=self._style_options(),
                )
            except Exception as exc:
                failures.append(f"{src.name}: {exc}")
            self.export_progress.setValue(int((idx / len(self.image_paths)) * 100))
            QApplication.processEvents()

        if failures:
            QMessageBox.warning(self, "Done with issues", "\n".join(failures[:10]))
        else:
            QMessageBox.information(self, "Done", f"Exported {len(self.image_paths)} image(s) to\n{out_dir}")


def main() -> None:
    app = QApplication(sys.argv)
    w = ExifFrameQt()
    w.show()
    runner = app.exec if PYQT_VER == 6 else app.exec_
    sys.exit(runner())


if __name__ == "__main__":
    main()
