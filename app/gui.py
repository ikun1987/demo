# -*- coding: utf-8 -*-
"""玉用去水印 —— 图形界面（PySide6）。

界面结构:
    ┌ 侧边栏 ┬────────── 主区 ──────────┬ 参数面板 ┐
    │ 单图   │  拖拽导入 / 前后对比      │ 强度     │
    │ 批量   │  对比滑块 / 缩放          │ 区域     │
    │ 设置   │  文件列表                 │ 输出     │
    │ 关于   │                          │ 去水印   │
    └────────┴──────────────────────────┴──────────┘
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import (QEvent, QObject, QPoint, QRect, QSize, Qt, QThread,
                            Signal, QTimer)
from PySide6.QtGui import (QAction, QColor, QFont, QIcon, QImage, QKeySequence,
                           QPainter, QPainterPath, QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QFileDialog, QFrame, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton,
                               QScrollArea, QSizePolicy, QSlider, QSpinBox,
                               QSplitter, QStackedWidget, QStatusBar,
                               QStyle, QStyleFactory, QSystemTrayIcon,
                               QToolButton, QVBoxLayout, QWidget)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import watermark as W                                  # noqa: E402
from core.config import (APP_NAME, APP_VERSION, Settings,        # noqa: E402
                         auto_start_enabled, resource_path,
                         set_auto_start)

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# ---------------------------------------------------------------- 主题配色
BG0 = "#12151b"
BG1 = "#181c24"
BG2 = "#1f2430"
BG3 = "#2a3140"
LINE = "#333c4d"
FG0 = "#e8edf5"
FG1 = "#9aa7bd"
ACCENT = "#5eead4"
ACCENT2 = "#38bdf8"
DANGER = "#f87171"

QSS = f"""
QWidget {{ background: {BG1}; color: {FG0}; font-family: "Microsoft YaHei UI","Microsoft YaHei",sans-serif; font-size: 13px; }}
QMainWindow, #Root {{ background: {BG0}; }}
#Sidebar {{ background: {BG0}; border-right: 1px solid {LINE}; }}
#SideBtn {{ text-align: left; padding: 11px 14px; border: none; border-radius: 9px; color: {FG1}; font-size: 14px; background: transparent; }}
#SideBtn:hover {{ background: {BG2}; color: {FG0}; }}
#SideBtn:checked {{ background: {BG2}; color: {ACCENT}; font-weight: 600; }}
#Card {{ background: {BG1}; border: 1px solid {LINE}; border-radius: 12px; }}
#Title {{ font-size: 17px; font-weight: 700; color: {FG0}; }}
#Sub {{ color: {FG1}; font-size: 12px; }}
#Preview {{ background: {BG0}; border: 1px solid {LINE}; border-radius: 12px; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 10px; margin-top: 14px; padding: 12px 10px 10px 10px; color: {FG1}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; color: {FG1}; font-size: 12px; }}
QPushButton {{ background: {BG3}; color: {FG0}; border: 1px solid {LINE}; border-radius: 9px; padding: 8px 14px; }}
QPushButton:hover {{ background: #333c4d; }}
QPushButton:pressed {{ background: #232a36; }}
QPushButton:disabled {{ color: #5a6577; background: {BG2}; border-color: #2b3342; }}
#Primary {{ background: {ACCENT}; color: #06231f; border: none; font-weight: 700; }}
#Primary:hover {{ background: #7ff0dd; }}
#Primary:disabled {{ background: #2f6b62; color: #0a2b27; }}
#Ghost {{ background: transparent; }}
QLineEdit, QSpinBox, QComboBox {{ background: {BG2}; border: 1px solid {LINE}; border-radius: 8px; padding: 6px 9px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT2}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{ background: {BG2}; border: 1px solid {LINE}; selection-background-color: {BG3}; }}
QSlider::groove:horizontal {{ height: 5px; background: {BG3}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 15px; height: 15px; margin: -5px 0; border-radius: 8px; }}
QListWidget {{ background: {BG2}; border: 1px solid {LINE}; border-radius: 10px; outline: none; }}
QListWidget::item {{ padding: 7px 9px; border-radius: 7px; }}
QListWidget::item:selected {{ background: {BG3}; color: {ACCENT}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {LINE}; background: {BG2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QProgressBar {{ background: {BG2}; border: 1px solid {LINE}; border-radius: 8px; text-align: center; height: 20px; color: {FG0}; }}
QProgressBar::chunk {{ background: {ACCENT2}; border-radius: 7px; }}
QStatusBar {{ background: {BG0}; color: {FG1}; border-top: 1px solid {LINE}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BG3}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {BG2}; color: {FG0}; border: 1px solid {LINE}; padding: 5px; }}
"""


# =============================================================== 图像工具
def imread_unicode(path: str) -> np.ndarray | None:
    try:
        buf = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        # EXIF 方向
        try:
            from PIL import Image, ImageOps
            with Image.open(path) as pim:
                exif = pim.getexif()
                orient = exif.get(274)
            if orient and orient != 1:
                rot = {2: None, 3: 180, 4: None, 5: 90, 6: 270, 7: 270, 8: 90}.get(orient)
                if rot:
                    img = cv2.rotate(img, {90: cv2.ROTATE_90_CLOCKWISE,
                                           180: cv2.ROTATE_180,
                                           270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rot])
        except Exception:
            pass
        return img
    except Exception:
        return None


def imwrite_unicode(path: str, img: np.ndarray, quality: int = 98, png_level: int = 6) -> bool:
    ext = Path(path).suffix.lower()
    params = []
    if ext in (".jpg", ".jpeg"):
        params = [cv2.IMWRITE_JPEG_QUALITY, int(quality), cv2.IMWRITE_JPEG_OPTIMIZE, 1]
    elif ext == ".png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, int(png_level)]
    elif ext == ".webp":
        params = [cv2.IMWRITE_WEBP_QUALITY, int(quality)]
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        return False
    try:
        buf.tofile(path)
        return True
    except Exception:
        return False


def bgr_to_qimage(img: np.ndarray) -> QImage:
    if img.ndim == 2:
        return QImage(img.data, img.shape[1], img.shape[0], img.strides[0],
                      QImage.Format_Grayscale8).copy()
    if img.shape[2] == 4:
        rgba = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        return QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0],
                      QImage.Format_RGBA8888).copy()
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0],
                  QImage.Format_RGB888).copy()


def fmt_size(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024.0
    return f"{n:.1f}GB"


# =============================================================== 后台处理线程
class Job(QThread):
    progress = Signal(int, int, str)
    one_done = Signal(str, str, bool, str)   # 输入, 输出, 成功, 信息
    finished_all = Signal(int, int, float)   # 成功数, 总数, 用时

    def __init__(self, files, settings: Settings, preview_only=False, parent=None):
        super().__init__(parent)
        self.files = list(files)
        self.st = settings
        self.preview_only = preview_only
        self.custom_rect = None          # (x0, y0, x1, y1) 原图像素坐标；手动框选/强制清理用
        self.force_clean = False
        self._lama_warned = False
        self._last_describe = ""
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        t0 = time.time()
        ok = 0
        total = len(self.files)
        for i, src in enumerate(self.files):
            if self._stop:
                break
            self.progress.emit(i, total, Path(src).name)
            try:
                success, msg, out = self.process_one(src)
            except Exception as e:
                success, msg, out = False, f"异常: {e}", ""
                traceback.print_exc()
            if success:
                ok += 1
            self.one_done.emit(src, out, success, msg)
        self.finished_all.emit(ok, total, time.time() - t0)

    # -------------------------------------------------- 单文件处理
    def process_one(self, src: str):
        st = self.st
        img = imread_unicode(src)
        if img is None:
            return False, "无法读取（格式不支持或文件损坏）", ""

        original_mode = "gray" if img.ndim == 2 else ("rgba" if img.shape[2] == 4 else "color")
        work = img
        alpha_ch = None
        if original_mode == "rgba":
            alpha_ch = work[:, :, 3].copy()
            work = cv2.cvtColor(work, cv2.COLOR_BGRA2BGR)
        elif original_mode == "gray":
            work = cv2.cvtColor(work, cv2.COLOR_GRAY2BGR)

        use_lama = bool(getattr(st, "use_lama", False))
        det_found = False
        rep = None

        # ① 深度修补路线（LaMa）：专治「白色描边」水印
        if use_lama:
            try:
                from core import lama_inpaint as LI
                out_img, linfo = LI.clean(work, strength=st.strength, use_lama=True)
                if linfo.get("found") and linfo.get("engine") == "lama":
                    det_found = True
                    msg = (f"LaMa 深度修补｜掩膜 {linfo.get('mask_px', 0)}px"
                           f"｜改动 {linfo.get('changed_px', 0)}px"
                           f"｜均值 {linfo.get('mean_change', 0):.2f}")
                    rep = W.RemoveReport(
                        mask_pixels=int(linfo.get("mask_px", 0)),
                        unmixed_pixels=0,
                        inpainted_pixels=int(linfo.get("changed_px", 0)),
                        coverage=float(linfo.get("coverage", 0.0)),
                        peak_before=0.0, peak_after=0.0,
                        method="lama", conf=float(linfo.get("score", 1.0)),
                        change_mean=float(linfo.get("mean_change", 0.0)),
                        significant=True,
                    )
                    self._last_describe = msg
            except Exception as e:                       # noqa: BLE001
                traceback.print_exc()
                if not self._lama_warned:
                    self._lama_warned = True
                    return False, f"深度修补不可用，已转传统算法：{type(e).__name__}: {e}", ""

        # ② 传统算法路线（回退 / 常规浅灰水印）
        if not det_found:
            out_img, det, rep = W.remove(
                work,
                strength=st.strength,
                preset=st.region_preset,
                custom_roi=self.custom_rect,
                force_clean=self.force_clean and self.custom_rect is not None,
                render_repair=st.bitmap_repair,
                margin_ratio=st.margin_ratio,
            )
            det_found = bool(det.found)

        if not det_found or rep is None or getattr(rep, "mask_pixels", 0) == 0:
            return False, "未检测到水印（可提高强度，或改用手动框选 + 强制清理）", ""
        if not getattr(rep, "significant", True):
            return False, (f"未发现可见水印，原图已干净（检出疑似痕迹仅 {rep.mask_pixels}px、"
                           f"平均改动 {getattr(rep,'change_mean',0):.2f} 灰阶），未写出文件"), ""

        if original_mode == "gray":
            out_img = cv2.cvtColor(out_img, cv2.COLOR_BGR2GRAY)
        elif original_mode == "rgba":
            out_img = cv2.cvtColor(out_img, cv2.COLOR_BGR2BGRA)
            out_img[:, :, 3] = alpha_ch

        # 输出路径
        p = Path(src)
        ext = p.suffix.lower()
        if ext not in IMAGE_EXT:
            ext = ".png"
        if st.same_as_source:
            outdir = p.parent
        else:
            outdir = Path(st.output_dir)
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / f"{p.stem}{st.suffix}{ext}"
        k = 1
        while out.exists() and not self.preview_only:
            out = outdir / f"{p.stem}{st.suffix}_{k}{ext}"
            k += 1

        if self.preview_only:
            return True, self.describe(rep), ""

        if not imwrite_unicode(str(out), out_img, st.jpeg_quality, st.png_compress):
            return False, "写入失败（目录无权限或磁盘已满）", ""
        return True, self.describe(rep), str(out)

    @staticmethod
    def describe(rep: W.RemoveReport) -> str:
        base = (f"掩膜 {rep.mask_pixels}px（{rep.coverage*100:.3f}%）"
                f"｜反混合 {rep.unmixed_pixels}｜修复 {rep.inpainted_pixels}"
                f"｜改动均值 {rep.change_mean:.2f}｜残差 {rep.peak_before:.0f}→{rep.peak_after:.0f}")
        if not getattr(rep, "significant", True):
            base += "｜判定：无可去除水印"
        return base


# =============================================================== 预览控件
class BeforeAfter(QWidget):
    """带可拖动分割线的前后对比预览。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Preview")
        self.setMinimumSize(420, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAcceptDrops(True)
        self.before: QPixmap | None = None
        self.after: QPixmap | None = None
        self.split = 0.5
        self.zoom = 1.0
        self.pan = QPoint(0, 0)
        self._drag_split = False
        self._drag_pan = False
        self._last = QPoint()
        self.placeholder = "把豆包保存的图片拖到这里\n或点击左上角「导入图片」"
        self.hint = ""
        # 手动框选（强制清理模式）
        self.select_mode = False
        self.sel_rect: QRect | None = None
        self._dragging_sel = False
        self._sel_anchor = QPoint()
        self.on_select = None            # 回调：接收 QRect（图像像素坐标）

    # ------------------------------------------------ 数据
    def set_images(self, before: np.ndarray | None, after: np.ndarray | None):
        self.before = QPixmap.fromImage(bgr_to_qimage(before)) if before is not None else None
        self.after = QPixmap.fromImage(bgr_to_qimage(after)) if after is not None else None
        self.zoom = 1.0
        self.pan = QPoint(0, 0)
        self.split = 0.5
        self.update()

    # ------------------------------------------------ 绘制
    def _fit_scale(self, pm: QPixmap) -> float:
        if pm is None:
            return 1.0
        aw, ah = self.width() - 24, self.height() - 24
        return min(aw / pm.width(), ah / pm.height())

    def _target_rect(self, pm: QPixmap) -> QRect:
        s = self._fit_scale(pm) * self.zoom
        w, h = int(pm.width() * s), int(pm.height() * s)
        cx, cy = self.width() // 2 + self.pan.x(), self.height() // 2 + self.pan.y()
        return QRect(cx - w // 2, cy - h // 2, w, h)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(BG0))

        if self.before is None and self.after is None:
            p.setPen(QColor(FG1))
            f = QFont(); f.setPointSize(11); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, self.placeholder)
            return

        pm_b = self.before or self.after
        rect = self._target_rect(pm_b)

        # 棋盘底纹
        p.save()
        p.setClipRect(rect)
        c = 16
        for yy in range(rect.top(), rect.bottom(), c):
            for xx in range(rect.left(), rect.right(), c):
                shade = QColor("#1a1f28") if ((xx // c + yy // c) % 2 == 0) else QColor("#151a22")
                p.fillRect(xx, yy, c, c, shade)
        p.restore()

        p.drawPixmap(rect, pm_b)

        if self.after is not None:
            split_x = rect.left() + int(rect.width() * self.split)
            p.save()
            p.setClipRect(QRect(rect.left(), rect.top(),
                                max(0, split_x - rect.left()), rect.height()))
            p.drawPixmap(self._target_rect(self.after), self.after)
            p.restore()

            # 分割线
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawLine(split_x, rect.top(), split_x, rect.bottom())
            p.setBrush(QColor(ACCENT))
            p.setPen(Qt.NoPen)
            cy = rect.center().y()
            p.drawEllipse(QPoint(split_x, cy), 11, 11)
            p.setPen(QPen(QColor("#06231f"), 2))
            p.drawText(QRect(split_x - 11, cy - 11, 22, 22), Qt.AlignCenter, "⇔")

            # 标签
            p.setPen(QColor(FG0))
            f = QFont(); f.setPointSize(9); f.setBold(True); p.setFont(f)
            p.drawText(rect.adjusted(10, 8, 0, 0), Qt.AlignLeft | Qt.AlignTop, "原始")
            p.drawText(rect.adjusted(0, 8, -10, 0), Qt.AlignRight | Qt.AlignTop, "去水印后")

        if self.hint:
            p.setPen(QColor(ACCENT))
            f = QFont(); f.setPointSize(9); p.setFont(f)
            p.drawText(rect.adjusted(0, 0, 0, -8), Qt.AlignHCenter | Qt.AlignBottom, self.hint)

        # 手动框选矩形
        if self.sel_rect is not None and not self.sel_rect.isNull():
            sel = self.sel_rect.normalized()
            p.setPen(QPen(QColor(ACCENT2), 2, Qt.DashLine))
            p.setBrush(QColor(56, 189, 248, 40))
            p.drawRect(sel)
            p.setPen(QColor(FG0))
            f = QFont(); f.setPointSize(9); f.setBold(True); p.setFont(f)
            p.drawText(sel.adjusted(4, 2, -4, 0), Qt.AlignLeft | Qt.AlignTop,
                       f"{sel.width()} × {sel.height()}")

    # ------------------------------------------------ 坐标换算
    def _to_image_rect(self, widget_rect: QRect) -> QRect | None:
        """把控件坐标的选区换算成原图像素坐标。"""
        pm = self.before or self.after
        if pm is None:
            return None
        r = self._target_rect(pm).normalized()
        inter = widget_rect.normalized().intersected(r)
        if inter.width() < 4 or inter.height() < 4:
            return None
        sx = pm.width() / max(r.width(), 1)
        sy = pm.height() / max(r.height(), 1)
        return QRect(int((inter.left() - r.left()) * sx),
                     int((inter.top() - r.top()) * sy),
                     max(1, int(inter.width() * sx)),
                     max(1, int(inter.height() * sy)))

    # ------------------------------------------------ 交互
    def _split_x(self) -> int:
        pm = self.before or self.after
        r = self._target_rect(pm)
        return r.left() + int(r.width() * self.split)

    def mousePressEvent(self, ev):
        if self.before is None and self.after is None:
            return
        if self.select_mode and ev.button() == Qt.LeftButton:
            self._dragging_sel = True
            self._sel_anchor = ev.position().toPoint()
            self.sel_rect = QRect(self._sel_anchor, self._sel_anchor)
            self.update()
            return
        if self.after is not None and abs(ev.position().x() - self._split_x()) < 16:
            self._drag_split = True
        else:
            self._drag_pan = True
            self._last = ev.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        if self._dragging_sel:
            self.sel_rect = QRect(self._sel_anchor, ev.position().toPoint()).normalized()
            self.update()
            return
        if self._drag_split:
            pm = self.before or self.after
            r = self._target_rect(pm)
            if r.width() > 0:
                self.split = float(np.clip((ev.position().x() - r.left()) / r.width(), 0, 1))
                self.update()
        elif self._drag_pan:
            cur = ev.position().toPoint()
            self.pan += cur - self._last
            self._last = cur
            self.update()
        elif self.select_mode:
            self.setCursor(Qt.CrossCursor)
        elif self.after is not None and abs(ev.position().x() - self._split_x()) < 16:
            self.setCursor(Qt.SplitHCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, ev):
        if self._dragging_sel:
            self._dragging_sel = False
            img_rect = self._to_image_rect(self.sel_rect) if self.sel_rect else None
            if img_rect is not None and self.on_select:
                self.on_select(img_rect)
            self.update()
            return
        self._drag_split = self._drag_pan = False
        self.setCursor(Qt.CrossCursor if self.select_mode else Qt.ArrowCursor)

    def wheelEvent(self, ev):
        if self.before is None and self.after is None:
            return
        d = ev.angleDelta().y()
        factor = 1.12 if d > 0 else 1 / 1.12
        self.zoom = float(np.clip(self.zoom * factor, 0.2, 12.0))
        self.update()

    def mouseDoubleClickEvent(self, ev):
        self.zoom = 1.0
        self.pan = QPoint(0, 0)
        self.split = 0.5
        self.update()

    # ------------------------------------------------ 拖拽导入
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls()]
        files = [p for p in paths if Path(p).suffix.lower() in IMAGE_EXT]
        if files:
            self.window().on_dropped(files)


# =============================================================== 主窗口
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.st = Settings.load()
        self.files: list[str] = []
        self.current: str | None = None
        self.cur_before: np.ndarray | None = None
        self.cur_after: np.ndarray | None = None
        self.job: Job | None = None
        self.preview_job: Job | None = None
        self.start_minimized = "--autostart" in sys.argv
        self.tray: QSystemTrayIcon | None = None
        self._really_quit = False
        self.custom_rect: QRect | None = None
        if len(getattr(self.st, "custom_rect", []) or []) == 4:
            x, y, rw, rh = [int(v) for v in self.st.custom_rect]
            self.custom_rect = QRect(x, y, rw, rh)

        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.resize(1360, 880)
        self.setMinimumSize(1080, 720)
        self._set_icon()
        self._build_ui()
        self._build_tray()
        self._wire()
        self._restore_geometry()
        self._sync_autostart_ui()
        # 恢复上次的手动框选状态
        self.chk_seal.setChecked(bool(getattr(self.st, "force_clean", False)))
        if self.custom_rect is not None:
            self.lbl_seal.setText(f"已选 {self.custom_rect.width()}×{self.custom_rect.height()}"
                                  f" @({self.custom_rect.x()},{self.custom_rect.y()})")
        if self.cb_region.currentData() == "custom" or self.chk_seal.isChecked():
            self.preview.select_mode = True
            self.preview.setCursor(Qt.CrossCursor)

        if self.start_minimized:
            QTimer.singleShot(1500, self._hide_to_tray)
            QTimer.singleShot(2600, lambda: self._tray_tip(
                f"{APP_NAME} 已在后台运行", "右下角托盘图标可以随时叫回主界面"))

        shot_arg = next((a for a in sys.argv if a.startswith("--screenshot=")), None)
        if shot_arg:
            page_arg = next((a for a in sys.argv if a.startswith("--page=")), None)
            if page_arg:
                try:
                    idx = max(0, min(3, int(page_arg.split("=", 1)[1])))
                    key = ("single", "batch", "settings", "about")[idx]
                    self.nav_buttons[key].setChecked(True)
                    self._on_nav(self.nav_buttons[key])
                except Exception:
                    pass
            img_arg = next((a for a in sys.argv if a.startswith("--open=")), None)
            if img_arg:
                target = img_arg.split("=", 1)[1]
                if Path(target).exists():
                    self.add_files([target])
                    self.select_file(target)
            self._auto_screenshot(shot_arg.split("=", 1)[1])

    # -------------------------------------------------- 托盘
    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = self.windowIcon()
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(f"{APP_NAME} v{APP_VERSION}")
        menu = QMenu()
        act_show = QAction("显示主界面", self)
        act_show.triggered.connect(self._show_from_tray)
        act_out = QAction("打开输出目录", self)
        act_out.triggered.connect(self._open_output_dir)
        self.act_auto = QAction("开机自动启动", self)
        self.act_auto.setCheckable(True)
        self.act_auto.setChecked(auto_start_enabled())
        self.act_auto.triggered.connect(self._tray_toggle_auto)
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self._quit_app)
        menu.addAction(act_show)
        menu.addAction(act_out)
        menu.addSeparator()
        menu.addAction(self.act_auto)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_tip(self, title: str, msg: str):
        if self.tray:
            self.tray.showMessage(title, msg, self.windowIcon(), 4000)

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self._show_from_tray()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _hide_to_tray(self):
        self.hide()
        self._tray_tip(f"{APP_NAME} 仍在后台运行", "双击托盘图标可以再打开主界面")

    def _open_output_dir(self):
        d = Path(self._collect().output_dir)
        try:
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(str(d))  # noqa: S606
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"打不开输出目录：{e}")

    def _tray_toggle_auto(self, checked):
        actual = set_auto_start(bool(checked))
        self.act_auto.setChecked(actual)
        self._sync_autostart_ui()
        self._tray_tip("开机自启", "已开启" if actual else "已关闭")

    def _quit_app(self):
        self._really_quit = True
        if self.job and self.job.isRunning():
            self.job.stop()
            self.job.wait(4000)
        try:
            self.st.saved_geometry = bytes(self.saveGeometry().toBase64()).decode()
            self._collect().save()
        except Exception:
            pass
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    # -------------------------------------------------- 图标
    def _set_icon(self):
        for cand in (resource_path("assets", "app.ico"),
                     resource_path("assets", "app.png"),
                     Path(__file__).resolve().parent / "assets" / "app.png"):
            if cand.exists():
                self.setWindowIcon(QIcon(str(cand)))
                return

    # -------------------------------------------------- 自检截图（打包后验证字体/渲染用）
    def _auto_screenshot(self, target: str):
        """隐藏参数 --screenshot=路径：把主界面渲染成 PNG 后退出。

        用途：打包成 exe 之后验证中文字体是否正常、界面是否布局正确，
        不依赖外部截图工具的权限与 DWM 状态。
        """
        def shot():
            try:
                pm = self.grab()
                ok = pm.save(target, "PNG")
                print(f"[screenshot] {target} saved={ok} size={pm.width()}x{pm.height()}")
            except Exception as e:
                print(f"[screenshot] 失败: {e}")
            finally:
                QTimer.singleShot(200, self._quit_app)
        QTimer.singleShot(1800, shot)

    # -------------------------------------------------- 构建界面
    def _build_ui(self):
        root = QWidget(); root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        # ---- 侧边栏
        side = QFrame(); side.setObjectName("Sidebar"); side.setFixedWidth(210)
        sl = QVBoxLayout(side); sl.setContentsMargins(14, 18, 14, 16); sl.setSpacing(6)

        brand = QLabel(APP_NAME); brand.setObjectName("Title")
        sl.addWidget(brand)
        sub = QLabel("豆包水印 · 一键渲染修复"); sub.setObjectName("Sub")
        sl.addWidget(sub)
        sl.addSpacing(16)

        self.nav_group = QButtonGroup(self)
        self.nav_buttons = {}
        for key, text in (("single", "  单图处理"), ("batch", "  批量处理"),
                          ("settings", "  设置"), ("about", "  关于")):
            b = QPushButton(text); b.setObjectName("SideBtn"); b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            sl.addWidget(b)
        self.nav_buttons["single"].setChecked(True)
        sl.addStretch(1)

        self.side_status = QLabel("就绪"); self.side_status.setObjectName("Sub")
        self.side_status.setWordWrap(True)
        sl.addWidget(self.side_status)
        outer.addWidget(side)

        # ---- 主区
        main = QWidget(); ml = QVBoxLayout(main)
        ml.setContentsMargins(18, 16, 12, 12); ml.setSpacing(12)

        head = QHBoxLayout(); head.setSpacing(8)
        self.btn_import = QPushButton("导入图片")
        self.btn_import_dir = QPushButton("导入文件夹")
        self.btn_clear = QPushButton("清空列表"); self.btn_clear.setObjectName("Ghost")
        head.addWidget(self.btn_import); head.addWidget(self.btn_import_dir)
        head.addStretch(1)
        self.lbl_file = QLabel("未选择文件"); self.lbl_file.setObjectName("Sub")
        head.addWidget(self.lbl_file)
        head.addWidget(self.btn_clear)
        ml.addLayout(head)

        self.stack = QStackedWidget()
        # 页 0：单图
        page_single = QWidget(); psl = QVBoxLayout(page_single)
        psl.setContentsMargins(0, 0, 0, 0); psl.setSpacing(10)
        self.preview = BeforeAfter()
        psl.addWidget(self.preview, 1)

        info = QFrame(); info.setObjectName("Card")
        il = QHBoxLayout(info); il.setContentsMargins(14, 9, 14, 9); il.setSpacing(18)
        self.lbl_meta = QLabel("—"); self.lbl_meta.setObjectName("Sub")
        self.lbl_result = QLabel("等待处理"); self.lbl_result.setObjectName("Sub")
        il.addWidget(self.lbl_meta); il.addStretch(1); il.addWidget(self.lbl_result)
        psl.addWidget(info)
        self.stack.addWidget(page_single)

        # 页 1：批量
        page_batch = QWidget(); pbl = QHBoxLayout(page_batch)
        pbl.setContentsMargins(0, 0, 0, 0); pbl.setSpacing(10)
        left = QWidget(); lvl = QVBoxLayout(left); lvl.setContentsMargins(0, 0, 0, 0)
        self.list_files = QListWidget()
        self.list_files.setSelectionMode(QListWidget.ExtendedSelection)
        lvl.addWidget(QLabel("待处理文件")); lvl.addWidget(self.list_files, 1)
        pbl.addWidget(left, 1)
        right = QWidget(); rvl = QVBoxLayout(right); rvl.setContentsMargins(0, 0, 0, 0)
        self.preview_batch = BeforeAfter()
        self.preview_batch.placeholder = "在左侧选择文件查看前后对比"
        rvl.addWidget(self.preview_batch, 1)
        pbl.addWidget(right, 2)
        self.stack.addWidget(page_batch)

        # 页 2：设置
        page_set = QWidget(); setl = QVBoxLayout(page_set)
        setl.setContentsMargins(0, 0, 0, 0)
        self._build_settings_page(setl)
        self.stack.addWidget(page_set)

        # 页 3：关于
        page_about = QWidget(); abtl = QVBoxLayout(page_about)
        abtl.setContentsMargins(0, 0, 0, 0)
        about = QLabel(
            f"<h2>{APP_NAME} v{APP_VERSION}</h2>"
            "<p>专门清理豆包（Doubao）导出图片右下角的半透明「豆包AI生成」字样。</p>"
            "<p><b>技术链路</b>：局部背景残差检测 → 文字形状先验校验 → 半透明反混合还原 → "
            "结构感知背景修复 → 引导滤波渲染修复（把被文字压住的纹理重新注入）。</p>"
            "<p>全程本地处理，不联网、不上传。支持 PNG / JPG / WEBP / BMP / TIFF，保留透明通道与分辨率。</p>"
            "<p style='color:#9aa7bd'>提示：把图片直接拖进窗口即可处理；处理前后可用对比滑块逐像素检查。</p>"
        )
        about.setWordWrap(True)
        abtl.addWidget(about); abtl.addStretch(1)
        self.stack.addWidget(page_about)

        ml.addWidget(self.stack, 1)
        outer.addWidget(main, 1)

        # ---- 右侧参数面板
        panel = QFrame(); panel.setFixedWidth(300)
        pl = QVBoxLayout(panel); pl.setContentsMargins(12, 16, 16, 12); pl.setSpacing(10)
        pl.addWidget(self._build_params())
        pl.addStretch(1)

        self.btn_run = QPushButton("开始去水印")
        self.btn_run.setObjectName("Primary"); self.btn_run.setMinimumHeight(44)
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_stop = QPushButton("停止"); self.btn_stop.setEnabled(False)
        pl.addWidget(self.btn_run); pl.addWidget(self.btn_stop)
        outer.addWidget(panel)

        # ---- 状态栏
        sb = QStatusBar(); self.setStatusBar(sb)
        self.progress = QProgressBar(); self.progress.setFixedWidth(240)
        self.progress.setRange(0, 100); self.progress.setValue(0)
        sb.addPermanentWidget(QLabel("进度")); sb.addPermanentWidget(self.progress)
        sb.showMessage("就绪")

    def _build_params(self) -> QWidget:
        box = QWidget(); gl = QVBoxLayout(box); gl.setContentsMargins(0, 0, 0, 0); gl.setSpacing(12)

        g1 = QGroupBox("去水印强度")
        g1l = QVBoxLayout(g1)
        self.sl_strength = QSlider(Qt.Horizontal)
        self.sl_strength.setRange(1, 5); self.sl_strength.setValue(self.st.strength)
        self.lbl_strength = QLabel(W.STRENGTH_NAMES[self.st.strength])
        self.lbl_strength.setObjectName("Sub")
        row = QHBoxLayout(); row.addWidget(QLabel("1")); row.addWidget(self.sl_strength, 1)
        row.addWidget(QLabel("5"))
        g1l.addLayout(row); g1l.addWidget(self.lbl_strength)
        gl.addWidget(g1)

        g2 = QGroupBox("水印位置")
        g2l = QVBoxLayout(g2)
        self.cb_region = QComboBox()
        self.cb_region.addItem("自动探测（推荐）", "auto")
        self.cb_region.addItem("右下角（豆包默认）", "corner_br")
        self.cb_region.addItem("左下角", "corner_bl")
        self.cb_region.addItem("右上角", "corner_tr")
        self.cb_region.addItem("左上角", "corner_tl")
        self.cb_region.addItem("手动框选（极淡水印）", "custom")
        idx = max(0, self.cb_region.findData(self.st.region_preset))
        self.cb_region.setCurrentIndex(idx)
        g2l.addWidget(self.cb_region)
        self.chk_repair = QCheckBox("渲染修复（还原被文字压住的纹理）")
        self.chk_repair.setChecked(self.st.bitmap_repair)
        g2l.addWidget(self.chk_repair)
        self.chk_lama = QCheckBox("深度修补（LaMa）· 白色描边水印专用")
        self.chk_lama.setToolTip(
            "针对豆包新版的「白色填充 + 亮描边」水印：\n"
            "传统算法只能把它压淡、还容易留糊痕；LaMa 是专门为大块缺失\n"
            "训练的修补网络，能干净还原水印覆盖的区域。\n"
            "代价：首次使用要加载约 200MB 模型（多等几秒），单张约 8~12 秒。")
        self.chk_lama.setChecked(bool(getattr(self.st, "use_lama", True)))
        g2l.addWidget(self.chk_lama)
        self.chk_seal = QCheckBox("强制清理选中区域（只抬接近纸白的像素）")
        self.chk_seal.setToolTip(
            "水印淡到只有 1~3 个灰阶、常规检测抓不到时用。\n"
            "先选「手动框选」，在图上拖一个框把水印圈住，再勾选此项。\n"
            "它只抹平纸上那层薄灰，深色画面内容不会被改动。")
        g2l.addWidget(self.chk_seal)
        self.lbl_seal = QLabel("未框选区域"); self.lbl_seal.setObjectName("Sub")
        g2l.addWidget(self.lbl_seal)
        gl.addWidget(g2)

        g3 = QGroupBox("输出")
        g3l = QGridLayout(g3); g3l.setHorizontalSpacing(8); g3l.setVerticalSpacing(8)
        g3l.addWidget(QLabel("目录"), 0, 0)
        self.ed_out = QLineEdit(self.st.output_dir)
        g3l.addWidget(self.ed_out, 0, 1, 1, 2)
        self.btn_pick = QPushButton("…"); self.btn_pick.setFixedWidth(34)
        g3l.addWidget(self.btn_pick, 0, 3)
        self.chk_same = QCheckBox("保存在原图目录")
        self.chk_same.setChecked(self.st.same_as_source)
        g3l.addWidget(self.chk_same, 1, 0, 1, 4)
        g3l.addWidget(QLabel("后缀"), 2, 0)
        self.ed_suffix = QLineEdit(self.st.suffix)
        g3l.addWidget(self.ed_suffix, 2, 1, 1, 3)
        g3l.addWidget(QLabel("画质"), 3, 0)
        self.sp_quality = QSpinBox(); self.sp_quality.setRange(60, 100)
        self.sp_quality.setValue(self.st.jpeg_quality)
        g3l.addWidget(self.sp_quality, 3, 1, 1, 3)
        gl.addWidget(g3)

        g4 = QGroupBox("系统")
        g4l = QVBoxLayout(g4)
        self.chk_auto = QCheckBox("开机自动启动")
        self.chk_auto.setChecked(auto_start_enabled())
        g4l.addWidget(self.chk_auto)
        self.chk_min = QCheckBox("启动时最小化到后台")
        self.chk_min.setChecked(True)
        g4l.addWidget(self.chk_min)
        gl.addWidget(g4)
        return box

    def _build_settings_page(self, layout):
        card = QFrame(); card.setObjectName("Card")
        cl = QVBoxLayout(card); cl.setContentsMargins(20, 18, 20, 18); cl.setSpacing(14)

        t = QLabel("处理设置"); t.setObjectName("Title"); cl.addWidget(t)

        self.pg_slider = QSlider(Qt.Horizontal); self.pg_slider.setRange(1, 5)
        self.pg_slider.setValue(self.st.strength)
        h1 = QHBoxLayout(); h1.addWidget(QLabel("去水印强度")); h1.addWidget(self.pg_slider, 1)
        self.pg_label = QLabel(W.STRENGTH_NAMES[self.st.strength]); self.pg_label.setObjectName("Sub")
        h1.addWidget(self.pg_label)
        cl.addLayout(h1)

        h2 = QHBoxLayout()
        h2.addWidget(QLabel("水印区域"))
        self.pg_region = QComboBox()
        for text, data in (("自动探测（推荐）", "auto"), ("右下角（豆包默认）", "corner_br"),
                           ("左下角", "corner_bl"), ("右上角", "corner_tr"), ("左上角", "corner_tl")):
            self.pg_region.addItem(text, data)
        self.pg_region.setCurrentIndex(max(0, self.pg_region.findData(self.st.region_preset)))
        h2.addWidget(self.pg_region, 1)
        cl.addLayout(h2)

        self.pg_repair = QCheckBox("渲染修复：把被文字压住的纹理按邻域重新生成（推荐开启）")
        self.pg_repair.setChecked(self.st.bitmap_repair)
        cl.addWidget(self.pg_repair)

        self.pg_auto = QCheckBox("开机自动启动（写入注册表 HKCU\\...\\Run）")
        self.pg_auto.setChecked(auto_start_enabled())
        cl.addWidget(self.pg_auto)

        self.pg_same = QCheckBox("输出到原图所在目录")
        self.pg_same.setChecked(self.st.same_as_source)
        cl.addWidget(self.pg_same)

        self.pg_quality = QSpinBox(); self.pg_quality.setRange(60, 100)
        self.pg_quality.setValue(self.st.jpeg_quality)
        h3 = QHBoxLayout(); h3.addWidget(QLabel("JPEG 输出画质")); h3.addWidget(self.pg_quality)
        h3.addStretch(1); cl.addLayout(h3)

        tip = QLabel("说明：强度越高，检测阈值越低、掩膜膨胀越大，适合水印明显或压在复杂内容上的图；"
                     "保守档只剥离高置信笔画，几乎不动原图。")
        tip.setObjectName("Sub"); tip.setWordWrap(True)
        cl.addWidget(tip)
        layout.addWidget(card)
        layout.addStretch(1)

    # -------------------------------------------------- 信号连接
    def _wire(self):
        self.nav_group.buttonClicked.connect(self._on_nav)
        self.btn_import.clicked.connect(self.import_files)
        self.btn_import_dir.clicked.connect(self.import_folder)
        self.btn_clear.clicked.connect(self.clear_list)
        self.btn_pick.clicked.connect(self.pick_outdir)
        self.btn_run.clicked.connect(self.run_job)
        self.btn_stop.clicked.connect(self.stop_job)
        self.list_files.currentItemChanged.connect(self._on_list_sel)
        self.list_files.itemDoubleClicked.connect(lambda _i: self.open_in_explorer())

        self.sl_strength.valueChanged.connect(self._on_strength)
        self.pg_slider.valueChanged.connect(self._on_strength_page)
        self.cb_region.currentIndexChanged.connect(self._on_region_changed)
        self.chk_seal.toggled.connect(self._on_seal_toggled)
        self.preview.on_select = self._on_user_select
        self.pg_region.currentIndexChanged.connect(self._on_param_change)
        self.chk_repair.toggled.connect(self._on_param_change)
        self.pg_repair.toggled.connect(self._on_param_change)
        self.chk_same.toggled.connect(self._on_param_change)
        self.pg_same.toggled.connect(self._on_param_change)
        self.ed_out.editingFinished.connect(self._on_param_change)
        self.ed_suffix.editingFinished.connect(self._on_param_change)
        self.sp_quality.valueChanged.connect(self._on_param_change)
        self.pg_quality.valueChanged.connect(self._on_param_change)
        self.chk_auto.toggled.connect(self._toggle_auto)
        self.pg_auto.toggled.connect(self._toggle_auto)

        QShortcut(QKeySequence("Ctrl+O"), self, self.import_files)
        QShortcut(QKeySequence("Ctrl+R"), self, self.run_job)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_current)
        QShortcut(QKeySequence("Delete"), self, self.remove_selected)

    # -------------------------------------------------- 参数同步
    def _collect(self):
        st = self.st
        st.strength = self.sl_strength.value()
        st.region_preset = self.cb_region.currentData()
        st.bitmap_repair = self.chk_repair.isChecked()
        st.use_lama = self.chk_lama.isChecked()
        st.force_clean = self.chk_seal.isChecked()
        st.output_dir = self.ed_out.text().strip() or st.output_dir
        st.suffix = self.ed_suffix.text().strip() or "_已去水印"
        st.same_as_source = self.chk_same.isChecked()
        st.jpeg_quality = self.sp_quality.value()
        st.auto_start = auto_start_enabled()
        if self.custom_rect is not None:
            st.custom_rect = [self.custom_rect.x(), self.custom_rect.y(),
                              self.custom_rect.width(), self.custom_rect.height()]
        return st

    # -------------------------------------------------- 手动框选
    def _on_region_changed(self, *a):
        manual = self.cb_region.currentData() == "custom"
        self.preview.select_mode = manual or self.chk_seal.isChecked()
        self.preview.setCursor(Qt.CrossCursor if self.preview.select_mode else Qt.ArrowCursor)
        if manual:
            self.preview.hint = "在图上按住左键拖一个框，把水印圈住"
            self.statusBar().showMessage("手动框选：请在图上拖框圈住水印，再勾选「强制清理选中区域」或直接点开始", 9000)
        else:
            self.preview.hint = ""
        self.preview.update()
        self._on_param_change()

    def _on_seal_toggled(self, checked):
        if checked and self.custom_rect is None:
            # 没框就默认给右下角一个候选区域，用户可再拖框调整
            if self.cur_before is not None:
                h, w = self.cur_before.shape[:2]
                self.custom_rect = QRect(int(w * 0.72), int(h * 0.90), w - int(w * 0.72), h - int(h * 0.90))
                self.preview.sel_rect = self._img_rect_to_widget(self.custom_rect)
                self.lbl_seal.setText(f"已选 {self.custom_rect.width()}×{self.custom_rect.height()}"
                                      f" @({self.custom_rect.x()},{self.custom_rect.y()})  ← 可拖动调整")
                self.preview.update()
        self.preview.select_mode = checked or self.cb_region.currentData() == "custom"
        self.preview.setCursor(Qt.CrossCursor if self.preview.select_mode else Qt.ArrowCursor)
        self._on_param_change()

    def _on_user_select(self, rect: QRect):
        self.custom_rect = rect
        self.lbl_seal.setText(f"已选 {rect.width()}×{rect.height()} @({rect.x()},{rect.y()})")
        if not self.chk_seal.isChecked():
            self.chk_seal.setChecked(True)
        self.statusBar().showMessage(
            f"已框选 {rect.width()}×{rect.height()} 区域，点「开始去水印」执行强制清理", 8000)

    def _img_rect_to_widget(self, r: QRect) -> QRect | None:
        pm = self.preview.before or self.preview.after
        if pm is None or self.cur_before is None:
            return None
        tr = self.preview._target_rect(pm).normalized()
        h, w = self.cur_before.shape[:2]
        sx = tr.width() / max(w, 1); sy = tr.height() / max(h, 1)
        return QRect(tr.left() + int(r.x() * sx), tr.top() + int(r.y() * sy),
                     int(r.width() * sx), int(r.height() * sy))

    def _on_param_change(self, *a):
        st = self._collect()
        st.save()
        self._sync_dependent()

    def _on_strength(self, v):
        self.lbl_strength.setText(W.STRENGTH_NAMES[v])
        if self.pg_slider.value() != v:
            self.pg_slider.blockSignals(True); self.pg_slider.setValue(v); self.pg_slider.blockSignals(False)
        if self.pg_label.text() != W.STRENGTH_NAMES[v]:
            self.pg_label.setText(W.STRENGTH_NAMES[v])
        self._on_param_change()

    def _on_strength_page(self, v):
        if self.sl_strength.value() != v:
            self.sl_strength.setValue(v)

    def _sync_dependent(self):
        st = self.st
        self.ed_out.setEnabled(not st.same_as_source)
        self.btn_pick.setEnabled(not st.same_as_source)

    def _toggle_auto(self, checked):
        sender = self.sender()
        for w in (self.chk_auto, self.pg_auto):
            if w is not sender:
                w.blockSignals(True); w.setChecked(checked); w.blockSignals(False)
        actual = set_auto_start(bool(checked))
        for w in (self.chk_auto, self.pg_auto):
            w.blockSignals(True); w.setChecked(actual); w.blockSignals(False)
        if getattr(self, "act_auto", None) is not None:
            self.act_auto.blockSignals(True); self.act_auto.setChecked(actual)
            self.act_auto.blockSignals(False)
        self.st.auto_start = actual
        self.st.save()
        self.statusBar().showMessage(
            "已开启开机自启" if actual else "已关闭开机自启", 4000)

    def _sync_autostart_ui(self):
        actual = auto_start_enabled()
        self.chk_auto.blockSignals(True); self.chk_auto.setChecked(actual); self.chk_auto.blockSignals(False)
        self.pg_auto.blockSignals(True); self.pg_auto.setChecked(actual); self.pg_auto.blockSignals(False)
        if getattr(self, "act_auto", None) is not None:
            self.act_auto.blockSignals(True); self.act_auto.setChecked(actual)
            self.act_auto.blockSignals(False)
        self._sync_dependent()

    # -------------------------------------------------- 导入
    def import_files(self):
        start = self.st.last_input_dir or str(Path.home() / "Pictures")
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", start,
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;所有文件 (*)")
        if files:
            self.add_files(files)

    def import_folder(self):
        start = self.st.last_input_dir or str(Path.home() / "Pictures")
        d = QFileDialog.getExistingDirectory(self, "选择文件夹", start)
        if not d:
            return
        files = [str(p) for p in sorted(Path(d).rglob("*")) if p.suffix.lower() in IMAGE_EXT]
        if not files:
            QMessageBox.information(self, APP_NAME, "该文件夹里没有找到图片。")
            return
        self.add_files(files)

    def add_files(self, files: list[str]):
        new = [f for f in files if f not in self.files]
        if not new:
            return
        self.files.extend(new)
        self.st.last_input_dir = str(Path(new[0]).parent)
        self.st.save()
        for f in new:
            p = Path(f)
            it = QListWidgetItem(f"{p.name}    ({fmt_size(p.stat().st_size)})")
            it.setData(Qt.UserRole, f)
            it.setToolTip(f)
            self.list_files.addItem(it)
        if self.current is None:
            self.select_file(new[0])
        if len(self.files) > 1 and self.nav_buttons["single"].isChecked():
            self.nav_buttons["batch"].setChecked(True)
            self._on_nav(self.nav_buttons["batch"])
        self.statusBar().showMessage(f"已加入 {len(new)} 个文件，共 {len(self.files)} 个", 5000)

    def on_dropped(self, files):
        self.add_files(files)

    def clear_list(self):
        self.files.clear()
        self.list_files.clear()
        self.current = None
        self.cur_before = self.cur_after = None
        self.preview.set_images(None, None)
        self.preview_batch.set_images(None, None)
        self.lbl_file.setText("未选择文件")
        self.lbl_meta.setText("—")
        self.lbl_result.setText("等待处理")
        self.statusBar().showMessage("列表已清空", 3000)

    def remove_selected(self):
        items = self.list_files.selectedItems()
        if not items:
            return
        for it in items:
            f = it.data(Qt.UserRole)
            if f in self.files:
                self.files.remove(f)
            self.list_files.takeItem(self.list_files.row(it))
        self.statusBar().showMessage(f"已移除 {len(items)} 个文件", 3000)

    def _on_list_sel(self, cur, _prev):
        if cur is None:
            return
        f = cur.data(Qt.UserRole)
        self.select_file(f)

    def select_file(self, f: str):
        img = imread_unicode(f)
        if img is None:
            self.statusBar().showMessage("无法读取该文件", 4000)
            return
        self.current = f
        self.cur_before = img
        self.cur_after = None
        self.preview.set_images(img, None)
        self.preview_batch.set_images(img, None)
        h, w = img.shape[:2]
        p = Path(f)
        self.lbl_file.setText(p.name)
        self.lbl_meta.setText(f"{w}×{h}   {fmt_size(p.stat().st_size)}   {p.suffix.upper().lstrip('.')}")
        self.lbl_result.setText("已载入，点右侧「开始去水印」")
        self.preview.hint = "原始图（尚未处理）"
        self.preview.update()
        for i in range(self.list_files.count()):
            it = self.list_files.item(i)
            if it.data(Qt.UserRole) == f:
                self.list_files.blockSignals(True)
                self.list_files.setCurrentItem(it)
                self.list_files.blockSignals(False)
                break

    # -------------------------------------------------- 处理
    def run_job(self):
        if self.job and self.job.isRunning():
            return
        if not self.files:
            QMessageBox.information(self, APP_NAME, "先导入图片吧，拖进来也行。")
            return
        st = self._collect(); st.save()

        # 单图模式只处理当前选中（或全部）
        files = [self.current] if (self.nav_buttons["single"].isChecked() and self.current) else list(self.files)
        files = [f for f in files if f]

        self.job = Job(files, st, preview_only=False)
        # 手动框选 / 强制清理
        manual = self.cb_region.currentData() == "custom"
        if (manual or self.chk_seal.isChecked()) and self.custom_rect is not None:
            r = self.custom_rect
            self.job.custom_rect = (r.x(), r.y(), r.x() + r.width(), r.y() + r.height())
            self.job.force_clean = self.chk_seal.isChecked()
        elif manual:
            QMessageBox.information(self, APP_NAME,
                                    "手动框选模式下，请先在图片上按住左键拖一个框，把水印圈住。")
            return
        self.job.progress.connect(self._on_progress)
        self.job.one_done.connect(self._on_one_done)
        self.job.finished_all.connect(self._on_all_done)
        self.btn_run.setEnabled(False); self.btn_stop.setEnabled(True)
        self.progress.setRange(0, len(files)); self.progress.setValue(0)
        self.statusBar().showMessage(f"开始处理 {len(files)} 张…")
        self.job.start()

    def stop_job(self):
        if self.job and self.job.isRunning():
            self.job.stop()
            self.statusBar().showMessage("正在停止…")

    def _on_progress(self, i, total, name):
        self.progress.setValue(i)
        self.statusBar().showMessage(f"[{i+1}/{total}] {name}")

    def _on_one_done(self, src, out, ok, msg):
        p = Path(src)
        for i in range(self.list_files.count()):
            it = self.list_files.item(i)
            if it.data(Qt.UserRole) == src:
                it.setText(f"{'✓' if ok else '✗'} {p.name}    ({fmt_size(p.stat().st_size)})")
                it.setForeground(QColor(ACCENT) if ok else QColor(DANGER))
                break
        if src == self.current:
            if ok:
                after = imread_unicode(out)
                self.cur_after = after
                self.preview.set_images(self.cur_before, after)
                self.preview.hint = "拖动中间滑块对比 · 双击复位 · 滚轮缩放"
                self.lbl_result.setText(msg)
                self.preview_batch.set_images(self.cur_before, after)
            else:
                self.lbl_result.setText(f"未处理：{msg}")

    def _on_all_done(self, ok, total, secs):
        self.btn_run.setEnabled(True); self.btn_stop.setEnabled(False)
        self.progress.setValue(total)
        # 结束后明确复位，避免"进度条停在 100% 像是卡死"
        QTimer.singleShot(700, lambda: self.progress.setRange(0, 100) or self.progress.setValue(0))
        self.statusBar().showMessage(f"完成：成功 {ok} / {total}，用时 {secs:.1f}s", 8000)
        self.side_status.setText(f"上次任务\n成功 {ok}/{total}\n{secs:.1f}s")
        if ok and not self.st.same_as_source:
            self.lbl_result.setText(self.lbl_result.text() + "  →  已输出到 " + self.st.output_dir)

        # 明确的结束反馈：失败时弹一个可操作的提示，而不是静默留个满格进度条
        if ok == 0:
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setIcon(QMessageBox.Information)
            box.setText(f"处理完毕：{total} 张里有 {0} 张需要处理。")
            box.setInformativeText(
                "这通常意味着：图片里没有可检测的水印，或者水印淡到低于检测下限。\n\n"
                "想强行去掉很淡的水印，可以这样做：\n"
                "1. 右侧「水印位置」选「手动框选（极淡水印）」；\n"
                "2. 在图上按住左键拖一个框，把水印圈住；\n"
                "3. 勾选「强制清理选中区域」，再点「开始去水印」。\n\n"
                "该模式只把接近纸白的像素抬平，画面深色内容不会被改动。")
            b_try = box.addButton("手动框选去试试", QMessageBox.AcceptRole)
            box.addButton("知道了", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is b_try:
                self.cb_region.setCurrentIndex(max(0, self.cb_region.findData("custom")))
                self._on_region_changed()
                self.nav_buttons["single"].setChecked(True)
                self._on_nav(self.nav_buttons["single"])
        elif ok < total:
            QMessageBox.information(
                self, APP_NAME,
                f"完成：成功 {ok} / {total}。\n没处理的那几张多为「未检测到可见水印」，"
                f"详情见文件列表与下方状态提示。")

    # -------------------------------------------------- 其他动作
    def save_current(self):
        if self.cur_after is None or self.current is None:
            return
        p = Path(self.current)
        default = str(Path(self.st.output_dir) / f"{p.stem}{self.st.suffix}{p.suffix}")
        out, _ = QFileDialog.getSaveFileName(self, "保存为", default,
                                             "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)")
        if out:
            if imwrite_unicode(out, self.cur_after, self.st.jpeg_quality, self.st.png_compress):
                self.statusBar().showMessage(f"已保存：{out}", 6000)
            else:
                QMessageBox.warning(self, APP_NAME, "保存失败。")

    def open_in_explorer(self):
        if not self.current:
            return
        d = str(Path(self.current).parent)
        if sys.platform == "win32":
            os.startfile(d)  # noqa: S606
        else:
            os.system(f'xdg-open "{d}"')

    def pick_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.ed_out.text() or str(Path.home()))
        if d:
            self.ed_out.setText(d)
            self._on_param_change()

    def _on_nav(self, btn):
        key = next((k for k, b in self.nav_buttons.items() if b is btn), "single")
        self.stack.setCurrentIndex({"single": 0, "batch": 1, "settings": 2, "about": 3}[key])

    # -------------------------------------------------- 窗口状态
    def _restore_geometry(self):
        if self.st.saved_geometry:
            try:
                from PySide6.QtCore import QByteArray
                self.restoreGeometry(QByteArray.fromBase64(self.st.saved_geometry.encode()))
            except Exception:
                pass

    def closeEvent(self, ev):
        try:
            self.st.saved_geometry = bytes(self.saveGeometry().toBase64()).decode()
            self._collect().save()
        except Exception:
            pass

        if self._really_quit:
            ev.accept()
            return

        # 有任务在跑：收进后台继续跑，不打断
        if self.job and self.job.isRunning():
            ev.ignore()
            self._hide_to_tray()
            self.statusBar().showMessage("已最小化到后台，任务继续")
            return

        if self.tray is None:
            ev.accept()
            return

        if self.st.close_to_tray:
            ev.ignore()
            self._hide_to_tray()
            return

        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Question)
        box.setText("关闭主窗口后要怎么处理？")
        box.setInformativeText("收进托盘可以继续后台待命（开机自启时更合适）；直接退出则完全不运行。")
        btn_tray = box.addButton("收进托盘", QMessageBox.AcceptRole)
        btn_quit = box.addButton("直接退出", QMessageBox.RejectRole)
        box.setDefaultButton(btn_tray)
        box.exec()

        if box.clickedButton() is btn_quit:
            self._really_quit = True
            ev.accept()
            return

        self.st.close_to_tray = True
        self.st.save()
        ev.ignore()
        self._hide_to_tray()


# =============================================================== 命令行模式
def _setup_console() -> None:
    """让命令行输出在 Windows 控制台正确显示中文、且永不因编码崩溃。

    Windows 控制台默认活动代码页常是 936(GBK)：直接 print 中文会乱码，
    遇到 ✓/✗ 之类字符还会直接抛 UnicodeEncodeError。这里先试着把控制台
    切成 UTF-8(65001)，再给 stdout/stderr 兜上 errors="replace" 保底。
    """
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


CLI_HELP = f"""{APP_NAME} v{APP_VERSION} —— 豆包水印清理

用法:
  {APP_NAME}.exe                       打开图形界面
  {APP_NAME}.exe <文件或目录> ...       直接批量处理（不弹界面）
  {APP_NAME}.exe --s 4 <文件>          指定强度 1~5
  {APP_NAME}.exe --out D:\\去水印 <目录>  指定输出目录
  {APP_NAME}.exe --region br <文件>     指定水印位置 auto/br/bl/tr/tl
  {APP_NAME}.exe --same <文件>          输出到原图目录
  {APP_NAME}.exe --check <文件...>      只检测不写文件，打印检测结论

退出码: 0 全部成功 / 1 有文件未处理 / 2 参数错误
"""


def _collect_cli_inputs(paths: list[str]) -> list[str]:
    files: list[str] = []
    for p in paths:
        pth = Path(p)
        if pth.is_dir():
            files.extend(str(x) for x in sorted(pth.rglob("*")) if x.suffix.lower() in IMAGE_EXT)
        elif pth.is_file() and pth.suffix.lower() in IMAGE_EXT:
            files.append(str(pth))
    return files


def cli_main(argv: list[str]) -> int:
    """无界面批处理。返回进程退出码。"""
    _setup_console()
    strength = 4
    out_dir: str | None = None
    region = "auto"
    same = False
    check_only = False
    inputs: list[str] = []

    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help", "/?"):
            print(CLI_HELP)
            return 0
        if a in ("--s", "--strength") and i + 1 < len(argv):
            try:
                strength = int(argv[i + 1])
            except ValueError:
                print("强度必须是 1~5 的整数")
                return 2
            i += 2
            continue
        if a in ("--out", "-o") and i + 1 < len(argv):
            out_dir = argv[i + 1]
            i += 2
            continue
        if a == "--region" and i + 1 < len(argv):
            region = argv[i + 1]
            i += 2
            continue
        if a == "--check":
            check_only = True
            i += 1
            continue
        if a == "--same":
            same = True
            i += 1
            continue
        inputs.append(a)
        i += 1

    strength = min(5, max(1, strength))
    files = _collect_cli_inputs(inputs)
    if not files:
        print("没有找到可处理的图片。\n")
        print(CLI_HELP)
        return 2

    st = Settings.load()
    st.strength = strength
    st.region_preset = region if region in ("auto", "corner_br", "corner_bl",
                                            "corner_tr", "corner_tl") else "auto"
    st.same_as_source = same
    if out_dir:
        st.output_dir = out_dir
    if check_only:
        st.use_lama = False          # 仅检测时不需要跑模型
    if "--no-lama" in inputs:
        inputs.remove("--no-lama")
        st.use_lama = False
    if "--debug" in inputs:
        inputs.remove("--debug")
        try:
            def _p(m):
                print(m, flush=True)
            from core import lama_inpaint as _LI
            _p("[调试] 1 开始 import torch")
            import torch
            _p(f"[调试] 2 torch 已导入 {torch.__version__}")
            from PIL import Image  # noqa: F401
            _p("[调试] 3 PIL 就绪")
            _ok, _why = _LI.lama_available()
            _p(f"[调试] 4 use_lama={st.use_lama}  LaMa依赖={_ok} ({_why})")
            _p(f"[调试] 5 模型路径={_LI._bundled_model_path()}")
            _p("[调试] 6 尝试加载模型…")
            _m, _err = _LI._load_model()
            _p(f"[调试] 7 模型加载={'成功' if _m is not None else '失败: ' + str(_err)}")
        except Exception as _e:                       # noqa: BLE001
            import traceback as _tb
            print(f"[调试] 异常: {type(_e).__name__}: {_e}", flush=True)
            print(_tb.format_exc(), flush=True)
    job = Job(files, st, preview_only=check_only)

    print(f"{APP_NAME} v{APP_VERSION}  共 {len(files)} 个文件  "
          f"强度={W.STRENGTH_NAMES[strength]}  位置={st.region_preset}"
          f"{'  [仅检测]' if check_only else ''}")
    ok = bad = 0
    t0 = time.time()
    for idx, src in enumerate(files, 1):
        try:
            success, msg, out = job.process_one(src)
        except Exception as e:
            success, msg, out = False, f"异常: {e}", ""
        if success:
            ok += 1
            print(f"  [{idx}/{len(files)}] OK  {Path(src).name}  {msg}"
                  + (f"\n        -> {out}" if out else ""))
        else:
            bad += 1
            print(f"  [{idx}/{len(files)}] --  {Path(src).name}  {msg}")
    print(f"完成：成功 {ok} / {len(files)}，失败 {bad}，用时 {time.time() - t0:.1f}s")
    return 0 if bad == 0 else 1


def main():
    argv = sys.argv[1:]
    # 有位置参数就走命令行批处理（GUI 参数除外）
    if argv and not any(a.startswith("--screenshot") or a == "--autostart" for a in argv):
        sys.exit(cli_main(argv))

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setStyleSheet(QSS)
    win = MainWindow()
    # 有托盘时，关窗口只收进托盘、不结束进程；没有托盘则保持常规退出行为
    app.setQuitOnLastWindowClosed(win.tray is None)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
