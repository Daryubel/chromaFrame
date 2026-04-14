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
    def __init__(self, key: str, input_path: Path, cfg: LayoutConfig, title_gap: int, camera_gap: int, swatch_height: int, swatch_width: int):
        super().__init__()
        self.key = key
        self.input_path = input_path
        self.cfg = cfg
        self.title_gap = title_gap
        self.camera_gap = camera_gap
        self.swatch_height = swatch_height
        self.swatch_width = swatch_width
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
    preview_max_pixels: int | None = None,
) -> None:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    source = Image.open(input_path)
    source = ef.ImageOps.exif_transpose(source).convert("RGB")
    source.filename = str(input_path)
    width, height = source.size

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
            swatch_box_width=_scaled(cfg.swatch_box_width),
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
    swatch_w = max(80, min(width, swatch_width))
    swatch_h = max(8, swatch_height)
    swatch_label_bbox = draw.textbbox((0, 0), "#FFFFFF", font=swatch_font)
    swatch_label_h = swatch_label_bbox[3] - swatch_label_bbox[1]
    swatch_block_h = swatch_h + 6 + swatch_label_h
    colors = ef.dominant_colors(source, n_colors=cfg.swatch_count)
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
    draw.text((right_x - camera_w, start_y), camera, fill=(20, 20, 20), font=info_font)
    specs_y = start_y + camera_h + camera_gap
    specs_w = specs_bbox[2] - specs_bbox[0]
    draw.text((right_x - specs_w, specs_y), specs, fill=(120, 120, 120), font=meta_font)
    if gps_line:
        gps_y = specs_y + specs_h + 8
        gps_bbox = draw.textbbox((0, 0), gps_line, font=meta_font)
        gps_w = gps_bbox[2] - gps_bbox[0]
        draw.text((right_x - gps_w, gps_y), gps_line, fill=(120, 120, 120), font=meta_font)

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
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setWidget(self.preview)
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

        self.title_edit = QLineEdit("Nature's poetry")
        self.subtitle_edit = QLineEdit("")
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
        self.font_path = QLineEdit("")
        self.export_template = QLineEdit("${filename}_framed")
        self.dump_exif = QCheckBox("Dump EXIF")

        help_btn = QPushButton("Template Help")
        help_btn.clicked.connect(self.template_help)

        form.addRow("Title", self.title_edit)
        form.addRow("Subtitle", self.subtitle_edit)
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
        form.addRow("Font path", self.font_path)
        form.addRow("Export template", self.export_template)
        form.addRow("", help_btn)
        form.addRow("", self.dump_exif)

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
            self.font_path,
            self.dump_exif,
        ]:
            self._connect_changed(widget)

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
        if isinstance(widget, QLineEdit):
            widget.textChanged.connect(self.schedule_preview)
        elif isinstance(widget, QSpinBox):
            widget.valueChanged.connect(self.schedule_preview)
        elif isinstance(widget, QCheckBox):
            widget.stateChanged.connect(self.schedule_preview)

    def pick_color(self) -> None:
        color = QColorDialog.getColor()
        if color.isValid():
            self.frame_color_edit.setText(color.name())

    def template_help(self) -> None:
        QMessageBox.information(
            self,
            "Template Help",
            "Use placeholders like ${filename}, ${stem}, ${ext}, ${make}, ${model}, ${datetime}, ${iso}.\n"
            "You can also use any EXIF key, e.g. ${DateTimeOriginal}.",
        )

    def open_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Open image", "", "JPEG (*.jpg *.jpeg)")
        if not file_path:
            return
        self.image_paths = [Path(file_path)]
        self.current_index = 0
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
        self.rebuild_minimap()
        self.update_selection_label()
        self.update_exif_panel()
        self.schedule_preview()

    def clear_images(self) -> None:
        self.image_paths = []
        self.current_index = 0
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
        self.current_index = idx
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
        w = max(300, self.preview_scroll.viewport().width() - 20)
        h = max(300, self.preview_scroll.viewport().height() - 20)
        scaled = pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) if PYQT_VER == 6 else pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(scaled)
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
