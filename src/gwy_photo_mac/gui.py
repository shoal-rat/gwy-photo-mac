"""Local desktop UI: open → check → preview → save, with no upload step."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QImageReader, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .core import (
    COMPATIBILITY_NOTICE,
    PhotoError,
    ProcessedPhoto,
    Settings,
    process_photo,
    write_output,
)

STYLE = """
QMainWindow, QDialog { background: #f4f6f9; color: #162438; }
QWidget { font-family: 'PingFang SC', sans-serif; font-size: 13px; color: #162438; }
QLabel#title { font-size: 27px; font-weight: 700; }
QLabel#muted { color: #586778; }
QLabel#notice { color: #655320; background: #fff8e6; border-radius: 8px; padding: 10px; }
QFrame#card { background: white; border: 1px solid #dce3ec; border-radius: 12px; }
QLabel#cardTitle { font-size: 15px; font-weight: 600; }
QLabel#preview { background: #edf1f6; border-radius: 8px; color: #7b8797; }
QLabel#status { color: #34485f; background: #e7edf6; border-radius: 8px; padding: 12px; }
QPushButton { background: white; border: 1px solid #d2dbe7; border-radius: 7px; padding: 9px 16px; }
QPushButton:hover { background: #edf3fd; border-color: #93b1dc; }
QPushButton#primary { background: #245bd7; color: white; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #194bc0; }
QPushButton:disabled { background: #e4e9f0; color: #8996a7; border-color: #e4e9f0; }
QPlainTextEdit { background: white; color: #162438; }
"""


class Worker(QObject):
    succeeded = Signal(object)
    failed = Signal(str, str)
    done = Signal()

    def __init__(self, path: Path, settings: Settings, allow_png: bool):
        super().__init__()
        self.path, self.settings, self.allow_png = path, settings, allow_png

    def run(self):
        try:
            self.succeeded.emit(process_photo(self.path, self.settings, allow_png=self.allow_png))
        except PhotoError as exc:
            self.failed.emit(exc.code, str(exc))
        except Exception:
            self.failed.emit("internal", "处理失败。请确认安装完整，或通过命令行复现并反馈问题。")
        finally:
            self.done.emit()


class PhotoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.source: Path | None = None
        self.result: ProcessedPhoto | None = None
        self.thread: QThread | None = None
        self.worker: Worker | None = None
        self.busy = False
        self.setWindowTitle("国考照片处理工具 · macOS 非官方版")
        self.setMinimumSize(870, 760)
        self.resize(980, 840)
        self.setAcceptDrops(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        title = QLabel("国考照片处理工具")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("macOS · 全程本地处理 · 无需 Windows 或上传照片")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        notice = QLabel(COMPATIBILITY_NOTICE)
        notice.setObjectName("notice")
        notice.setWordWrap(True)
        layout.addWidget(notice)

        toolbar = QHBoxLayout()
        self.open_button = QPushButton("打开照片文件…")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.choose_photo)
        self.save_button = QPushButton("保存照片文件…")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_photo)
        self.details_button = QPushButton("处理详情")
        self.details_button.setEnabled(False)
        self.details_button.clicked.connect(self.show_details)
        self.quit_button = QPushButton("退出")
        self.quit_button.clicked.connect(self.close)
        for button in (self.open_button, self.save_button, self.details_button):
            toolbar.addWidget(button)
        toolbar.addStretch()
        toolbar.addWidget(self.quit_button)
        layout.addLayout(toolbar)

        columns = QHBoxLayout()
        self.source_preview, self.source_caption = self.add_preview(
            columns, "源照片", "拖入照片或点击“打开照片文件”"
        )
        self.output_preview, self.output_caption = self.add_preview(
            columns, "处理结果", "检查通过后显示处理结果"
        )
        layout.addLayout(columns, 1)

        self.status = QLabel("等待打开照片。默认严格接受 JPG / JPEG；文件不会自动上传。")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.requirements = QLabel()
        self.requirements.setObjectName("muted")
        self.requirements.setWordWrap(True)
        layout.addWidget(self.requirements)
        options = QHBoxLayout()
        self.png_checkbox = QCheckBox("额外接受 PNG（原版只接受 JPEG）")
        self.png_checkbox.toggled.connect(self.invalidate)
        options.addWidget(self.png_checkbox)
        options.addStretch()
        self.profile_button = QPushButton("载入 photo.ini…")
        self.profile_button.clicked.connect(self.choose_profile)
        options.addWidget(self.profile_button)
        self.reset_button = QPushButton("恢复参考配置")
        self.reset_button.clicked.connect(self.reset_profile)
        options.addWidget(self.reset_button)
        layout.addLayout(options)
        self.profile_label = QLabel("配置：参考 Windows 分发包（2024-10-18）")
        self.profile_label.setObjectName("muted")
        layout.addWidget(self.profile_label)
        self.setCentralWidget(host)
        self.refresh_requirements()
        self.setup_menu()

    def setup_menu(self):
        menu = self.menuBar().addMenu("文件")
        self.open_action = QAction("打开照片…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.choose_photo)
        menu.addAction(self.open_action)
        self.save_action = QAction("保存照片…", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.setEnabled(False)
        self.save_action.triggered.connect(self.save_photo)
        menu.addAction(self.save_action)
        quit_action = QAction("退出", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)
        help_menu = self.menuBar().addMenu("帮助")
        about = QAction("关于与兼容性", self)
        about.triggered.connect(
            lambda: QMessageBox.information(
                self,
                "关于",
                f"国考照片处理工具 macOS 版 {__version__}\n\n{COMPATIBILITY_NOTICE}\n\n"
                "不隶属于招录、考试或人事部门。只做规则检查、裁切、缩小、JPEG编码及参考文件尾标记。"
                "不进行美颜、换底、身份判断或官网审核。\n\n"
                "开源项目：https://github.com/shoal-rat/gwy-photo-mac\n"
                "第三方许可随应用内 data/THIRD_PARTY_NOTICES.txt 提供。",
            )
        )
        help_menu.addAction(about)

    def add_preview(self, row: QHBoxLayout, title: str, empty: str):
        card = QFrame()
        card.setObjectName("card")
        content = QVBoxLayout(card)
        content.setContentsMargins(16, 15, 16, 14)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        content.addWidget(heading)
        preview = QLabel(empty)
        preview.setObjectName("preview")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumSize(280, 240)
        preview.setWordWrap(True)
        content.addWidget(preview, 1)
        caption = QLabel(" ")
        caption.setObjectName("muted")
        caption.setWordWrap(True)
        content.addWidget(caption)
        row.addWidget(card, 1)
        return preview, caption

    def refresh_requirements(self):
        cfg = self.settings
        self.requirements.setText(
            f"源照片：本人近期免冠正面证件照，白底或蓝底，至少 {cfg.min_width}×{cfg.min_height} 像素。"
            f"输出：{cfg.dst_width}×{cfg.dst_height} 像素 JPEG，通常约10KB（随内容变化）。禁止放大低像素照片；不做美颜修饰。"
        )

    def invalidate(self):
        self.source = None
        self.result = None
        self.save_button.setEnabled(False)
        self.save_action.setEnabled(False)
        self.details_button.setEnabled(False)
        self.source_preview.clear()
        self.source_preview.setText("拖入照片或点击“打开照片文件”")
        self.output_preview.clear()
        self.output_preview.setText("检查通过后显示处理结果")
        self.source_caption.setText(" ")
        self.output_caption.setText(" ")
        self.status.setText("等待打开照片。当前检查规则已就绪。")

    def choose_photo(self):
        if self.busy:
            return
        extensions = "*.jpg *.jpeg *.jpe *.jfif"
        if self.png_checkbox.isChecked():
            extensions += " *.png"
        filename, _ = QFileDialog.getOpenFileName(
            self, "打开照片文件", "", f"证件照片 ({extensions})"
        )
        if filename:
            self.load_photo(Path(filename))

    def load_photo(self, path: Path):
        if self.busy:
            return
        self.invalidate()
        self.source = path
        self.busy = True
        self.toggle_controls(False)
        self.status.setText("正在检查文件、像素、背景、人像比例，并生成照片…")
        self.thread = QThread(self)
        self.worker = Worker(path, self.settings, self.png_checkbox.isChecked())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.succeeded.connect(self.on_result)
        self.worker.failed.connect(self.on_failure)
        self.worker.done.connect(self.thread.quit)
        self.worker.done.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.on_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def toggle_controls(self, enabled: bool):
        for control in (
            self.open_button,
            self.png_checkbox,
            self.profile_button,
            self.reset_button,
            self.quit_button,
        ):
            control.setEnabled(enabled)
        self.open_action.setEnabled(enabled)

    def on_finished(self):
        self.busy = False
        self.thread, self.worker = None, None
        self.toggle_controls(True)

    def on_result(self, result: ProcessedPhoto):
        self.result = result
        reader = QImageReader(str(self.source))
        reader.setAutoTransform(True)
        self.set_preview(self.source_preview, QPixmap.fromImage(reader.read()))
        pixmap = QPixmap()
        pixmap.loadFromData(result.jpeg)
        self.set_preview(self.output_preview, pixmap)
        width, height = result.report["source_dimensions"]
        self.source_caption.setText(f"{self.source.name} · {width}×{height} 像素")
        ow, oh = result.report["output_dimensions"]
        self.output_caption.setText(f"{ow}×{oh} 像素 · {len(result.jpeg) / 1024:.2f} KiB · JPG")
        background = "白底" if result.report["background"] == "white" else "蓝底"
        extra = " PNG已按额外兼容流程转换。" if result.report["png_conversion"] else ""
        self.status.setText(
            f"检查通过：文件格式、源图像素、{background}采样、人像比例。预览已生成，可保存照片。{extra}"
            " 此结果不代表报名网站已审核通过。"
        )
        self.save_button.setEnabled(True)
        self.save_action.setEnabled(True)
        self.details_button.setEnabled(True)

    @staticmethod
    def set_preview(label: QLabel, pixmap: QPixmap):
        label.setPixmap(
            pixmap.scaled(
                label.size() - QSize(16, 16),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def on_failure(self, code: str, message: str):
        self.result = None
        self.save_button.setEnabled(False)
        self.save_action.setEnabled(False)
        self.details_button.setEnabled(False)
        self.output_preview.clear()
        self.output_preview.setText("照片未通过检查，请重新选择")
        self.status.setText(f"检查未通过：{message}")

    def save_photo(self):
        if self.busy or self.result is None or self.source is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "保存照片文件", str(self.source.parent / "报名照片.JPG"), "JPEG照片 (*.JPG *.jpg)"
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() not in (".jpg", ".jpeg", ".jpe", ".jfif"):
            path = path.with_name(path.name + ".JPG")
            if (
                path.exists()
                and QMessageBox.question(self, "替换已有文件？", f"“{path.name}”已存在，是否替换？")
                != QMessageBox.StandardButton.Yes
            ):
                return
        try:
            write_output(self.result, path, overwrite=True, source=self.source)
        except PhotoError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        answer = QMessageBox.question(
            self,
            "照片已保存",
            "照片已保存成功，是否退出？\n\n请直接上传保存的JPG，避免再次压缩或编辑。"
            "\n最终是否接受，以报名网站结果为准。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.close()

    def show_details(self):
        if self.result is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("处理详情（不包含文件路径）")
        dialog.resize(700, 560)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(json.dumps(self.result.report, ensure_ascii=False, indent=2))
        text.setReadOnly(True)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def choose_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "载入原工具photo.ini", "", "配置文件 (*.ini)")
        if not path:
            return
        try:
            settings = Settings.load(Path(path))
        except PhotoError as exc:
            QMessageBox.warning(self, "配置无效", str(exc))
            return
        self.settings = settings
        self.invalidate()
        self.refresh_requirements()
        self.profile_label.setText(f"配置：自定义 {Path(path).name}（不能据此保证新版本兼容性）")

    def reset_profile(self):
        self.settings = Settings.load()
        self.invalidate()
        self.refresh_requirements()
        self.profile_label.setText("配置：参考 Windows 分发包（2024-10-18）")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if not self.busy and event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        if not self.busy and event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                self.load_photo(Path(urls[0].toLocalFile()))

    def closeEvent(self, event):
        if self.busy:
            self.status.setText("正在完成本地处理，请稍候再退出。")
            event.ignore()
        else:
            event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("国考照片处理工具")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("shoal-rat")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = PhotoWindow()
    window.show()
    if "--smoke-test" in sys.argv:
        # Exercise bundled model/config/encoder without shipping a person's photo.
        import numpy as np

        from .core import encode_jpeg, inspect_output, load_classifier

        load_classifier()
        inspect_output(encode_jpeg(np.full((413, 295, 3), 255, dtype=np.uint8)), (295, 413))
        QTimer.singleShot(400, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
