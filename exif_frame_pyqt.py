#!/usr/bin/env python3
"""High-performance PyQt GUI for exif_frame poster rendering."""

from __future__ import annotations

import hashlib
import re
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from exif_frame import LayoutConfig, create_framed_image, get_exif_data, parse_hex_color

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
    def __init__(self, key: str, input_path: Path, cfg: LayoutConfig):
        super().__init__()
        self.key = key
        self.input_path = input_path
        self.cfg = cfg
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                out_path = Path(tmp.name)
            create_framed_image(self.input_path, out_path, self.cfg)
            self.signals.done.emit(self.key, str(out_path))
        except Exception as exc:
            self.signals.error.emit(str(exc))


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

        self.preview = QLabel("Open an image or folder")
        self.preview.setAlignment(_align_center())
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setWidget(self.preview)
        left_layout.addWidget(self.preview_scroll)

        self.selection_label = QLabel("No image selected")
        left_layout.addWidget(self.selection_label)

        self.mini_list = QListWidget()
        self.mini_list.setViewMode(QListWidget.ViewMode.ListMode if PYQT_VER == 6 else QListWidget.ListMode)
        self.mini_list.setFlow(QListWidget.Flow.TopToBottom if PYQT_VER == 6 else QListWidget.TopToBottom)
        self.mini_list.setWrapping(False)
        self.mini_list.setIconSize(QPixmap(140, 90).size())
        self.mini_list.currentRowChanged.connect(self.select_index)
        left_layout.addWidget(self.mini_list)

        splitter.addWidget(left)

        # Right settings panel
        right = QWidget()
        right_layout = QVBoxLayout(right)
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
        form.addRow("Font path", self.font_path)
        form.addRow("Export template", self.export_template)
        form.addRow("", help_btn)
        form.addRow("", self.dump_exif)

        right_layout.addLayout(form)

        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 100)
        right_layout.addWidget(QLabel("Export progress"))
        right_layout.addWidget(self.export_progress)

        right_layout.addWidget(QLabel("Current image EXIF"))
        self.exif_box = QTextEdit()
        self.exif_box.setReadOnly(True)
        right_layout.addWidget(self.exif_box, 1)

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
        files = sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg"})
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
        self.mini_list.clear()
        for p in self.image_paths:
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
        worker = RenderWorker(key, src, cfg)
        worker.signals.done.connect(self._preview_done)
        worker.signals.error.connect(lambda msg: self.preview.setText(f"Preview error: {msg}"))
        self.pool.start(worker)

    def _preview_done(self, key: str, path: str) -> None:
        if self.pending_key != key:
            Path(path).unlink(missing_ok=True)
            return
        pix = QPixmap(path)
        Path(path).unlink(missing_ok=True)
        self.preview_cache[key] = pix
        self._set_preview_pixmap(pix)

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
        payload = f"{src}|{src.stat().st_mtime_ns}|{asdict(cfg)}"
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
            create_framed_image(self.image_paths[0], Path(out), cfg)
            self.export_progress.setValue(100)
            QMessageBox.information(self, "Done", f"Exported:\n{out}")
            return

        out_dir = QFileDialog.getExistingDirectory(self, "Select output folder")
        if not out_dir:
            return

        progress = QProgressDialog("Exporting...", "Cancel", 0, len(self.image_paths), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal if PYQT_VER == 6 else Qt.WindowModal)
        failures: list[str] = []

        for idx, src in enumerate(self.image_paths, start=1):
            if progress.wasCanceled():
                break
            dst = Path(out_dir) / f"{self._render_template_name(src)}.jpg"
            try:
                create_framed_image(src, dst, cfg)
            except Exception as exc:
                failures.append(f"{src.name}: {exc}")
            progress.setValue(idx)
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
