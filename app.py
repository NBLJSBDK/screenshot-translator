#!/usr/bin/env python3
"""Screenshot Translator v0.2.1

KDE Plasma / Linux screenshot translation overlay (X11 and Wayland).

Default flow:
    Ctrl+Alt+D -> region selection -> Umi-OCR HTTP API
    -> pluggable translation backend -> translated image over original region.

X11 keeps the direct Qt/X11 grab and pynput global hotkey. KDE Plasma Wayland
uses Spectacle fullscreen capture plus the KGlobalAccel D-Bus shortcut service.

No main window and no tray icon. Failures use desktop notifications + log only.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, NamedTuple
import urllib.error
import urllib.parse
import urllib.request

import tomllib

PYNPUT_IMPORT_ERROR: Exception | None = None
try:
    from pynput import keyboard, mouse
except Exception as exc:  # pragma: no cover - depends on desktop session
    keyboard = None  # type: ignore[assignment]
    mouse = None  # type: ignore[assignment]
    PYNPUT_IMPORT_ERROR = exc

QDBUS_IMPORT_ERROR: Exception | None = None
try:
    from PySide6.QtDBus import QDBusConnection, QDBusMessage
except Exception as exc:  # pragma: no cover - optional Qt module
    QDBusConnection = None  # type: ignore[assignment]
    QDBusMessage = None  # type: ignore[assignment]
    QDBUS_IMPORT_ERROR = exc

from PySide6.QtCore import (
    QFileSystemWatcher,
    QBuffer,
    QByteArray,
    QElapsedTimer,
    QIODevice,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QIcon,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QWidget,
)

APP_NAME = "Screenshot Translator"
APP_SLUG = "screenshot-translator"
VERSION = "0.2.1"
BASE_DIR = Path(__file__).resolve().parent

SESSION_TYPE = os.environ.get("XDG_SESSION_TYPE", "").lower()
IS_WAYLAND = SESSION_TYPE == "wayland" or (
    SESSION_TYPE != "x11" and bool(os.environ.get("WAYLAND_DISPLAY"))
)

KGA_SERVICE = "org.kde.kglobalaccel"
KGA_PATH = "/kglobalaccel"
KGA_IFACE = "org.kde.KGlobalAccel"
KGA_COMPONENT = "screenshot-translator"
KGA_ACTION = "capture"
KGA_COMPONENT_FRIENDLY = "Screenshot Translator"
KGA_ACTION_FRIENDLY = "截图并翻译"
KGA_COMPONENT_PATH = f"/component/{KGA_COMPONENT.replace('-', '_').replace('.', '_')}"
KGA_COMPONENT_IFACE = "org.kde.kglobalaccel.Component"
KGA_CAPTURE_ACTION_ID = [KGA_COMPONENT, KGA_ACTION, KGA_COMPONENT_FRIENDLY, KGA_ACTION_FRIENDLY]
KGA_SET_PRESENT = 2
KGA_NO_AUTOLOADING = 4
KGA_SET_FLAGS = KGA_SET_PRESENT | KGA_NO_AUTOLOADING

XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
XDG_STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
XDG_CACHE_HOME = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
CONFIG_DIR = XDG_CONFIG_HOME / APP_SLUG
CONFIG_PATH = CONFIG_DIR / "config.toml"
KEYS_PATH = CONFIG_DIR / "keys.toml"
STATE_DIR = XDG_STATE_HOME / APP_SLUG
CACHE_DIR = XDG_CACHE_HOME / APP_SLUG
LOG_PATH = STATE_DIR / "app.log"
EXAMPLE_CONFIG = BASE_DIR / "config.example.toml"

DEFAULTS: dict[str, Any] = {
    "app": {
        "hotkey": "ctrl+alt+d",
        "input_backend": "auto",
        "tray_icon": True,
        "drag_hold_ms": 0,
        "close_on_outside_click": True,
    },
    "capture": {
        "backend": "auto",
        "min_width": 8,
        "min_height": 8,
    },
    "ocr": {
        "api_url": "http://127.0.0.1:1224/api/ocr",
        "auto_start": True,
        "umi_ocr": "~/tools/Umi-OCR_Linux_Paddle_2.1.5/umi-ocr.sh",
        "startup_timeout_s": 8.0,
        "request_timeout_s": 20.0,
        "language": "models/config_chinese.txt",
        "parser": "multi_para",
        "limit_side_len": 2880,
    },
    "translation": {
        "backend": "google",
        "source": "auto",
        "target": "zh-CN",
        "timeout_s": 12.0,
        "google": {
            "endpoint": "https://translate.googleapis.com/translate_a/single",
        },
        "google_cloud": {
            "endpoint": "https://translation.googleapis.com/language/translate/v2",
        },
        "libretranslate": {
            "endpoint": "http://127.0.0.1:5000/translate",
            "api_key": "",
        },
    },
    "overlay": {
        "mask_alpha": 220,
        "corner_radius": 4,
        "padding": 3,
        "font_min_px": 9,
        "font_max_px": 28,
        "toolbar_gap": 6,
        "toolbar_position": "auto",
    },
    "log": {
        "level": "INFO",
        "max_bytes": 2_097_152,
        "backup_count": 3,
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in base.items():
        out[key] = deep_merge(value, {}) if isinstance(value, dict) else value
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def ensure_runtime_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def ensure_config() -> None:
    ensure_runtime_dirs()
    if CONFIG_PATH.exists():
        return
    if not EXAMPLE_CONFIG.exists():
        raise RuntimeError(f"缺少默认配置模板: {EXAMPLE_CONFIG}")
    shutil.copyfile(EXAMPLE_CONFIG, CONFIG_PATH)


def load_config() -> dict[str, Any]:
    ensure_config()
    with CONFIG_PATH.open("rb") as f:
        user_cfg = tomllib.load(f)
    return deep_merge(DEFAULTS, user_cfg)


def load_keys() -> dict[str, Any]:
    """Load optional credentials without ever logging their contents."""
    if not KEYS_PATH.exists():
        return {}
    try:
        with KEYS_PATH.open("rb") as f:
            keys = tomllib.load(f)
    except Exception as exc:
        raise RuntimeError(f"密钥配置读取失败: {KEYS_PATH}") from exc
    if not isinstance(keys, dict):
        raise RuntimeError(f"密钥配置格式异常: {KEYS_PATH}")

    mode = KEYS_PATH.stat().st_mode & 0o777
    if mode & 0o077:
        LOG.warning("keys file permissions are %03o; recommend 600 path=%s", mode, KEYS_PATH)
    return keys


def configure_logging(cfg: dict[str, Any]) -> logging.Logger:
    ensure_runtime_dirs()
    logger = logging.getLogger(APP_SLUG)
    logger.handlers.clear()
    log_cfg = cfg["log"]
    logger.setLevel(getattr(logging, str(log_cfg["level"]).upper(), logging.INFO))
    handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=int(log_cfg["max_bytes"]),
        backupCount=int(log_cfg["backup_count"]),
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


CFG = load_config()
LOG = configure_logging(CFG)


def reload_log_level(cfg: dict[str, Any]) -> None:
    level = getattr(logging, str(cfg["log"]["level"]).upper(), logging.INFO)
    LOG.setLevel(level)


def notify(title: str, message: str) -> None:
    """Desktop toast only. Never opens an application error dialog."""
    try:
        if shutil.which("notify-send"):
            subprocess.Popen(
                ["notify-send", "-a", APP_NAME, title, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        if shutil.which("kdialog"):
            subprocess.Popen(
                ["kdialog", "--passivepopup", f"{title}\n{message}", "4"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        LOG.exception("system notification failed")


_LOCK_FILE: Any = None


def acquire_single_instance() -> bool:
    """Prevent two resident instances from fighting over the same hotkey."""
    global _LOCK_FILE
    ensure_runtime_dirs()
    lock_path = STATE_DIR / "app.lock"
    try:
        _LOCK_FILE = lock_path.open("a+")
        fcntl.flock(_LOCK_FILE, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if _LOCK_FILE is not None:
            _LOCK_FILE.close()
            _LOCK_FILE = None
        return False
    _LOCK_FILE.seek(0)
    _LOCK_FILE.truncate()
    _LOCK_FILE.write(str(os.getpid()))
    _LOCK_FILE.flush()
    return True


def quit_running_instance() -> int:
    lock_path = STATE_DIR / "app.lock"
    if not lock_path.exists():
        print("没有运行中的实例。")
        return 0
    try:
        pid = int(lock_path.read_text().strip())
    except Exception:
        print(f"无法从 {lock_path} 读取 PID；可用 `pgrep -af app.py` 手动结束。")
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print("实例已退出。")
        return 0
    except PermissionError:
        print(f"没有权限结束 PID {pid}。")
        return 1
    print(f"已请求退出实例 PID {pid}。")
    return 0


def _trim_transparent(image: QImage) -> QImage:
    left, top, right, bottom = image.width(), image.height(), -1, -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 8:
                left = min(left, x)
                right = max(right, x)
                top = min(top, y)
                bottom = max(bottom, y)
    if right < left or bottom < top:
        return image
    cropped = image.copy(left, top, right - left + 1, bottom - top + 1)
    # QIcon returns file-based SVG pixmaps tagged with the screen DPR; scaling
    # such an image would halve logical sizes, so normalize before reuse.
    cropped.setDevicePixelRatio(1.0)
    return cropped


def make_tray_icon() -> QIcon:
    """Monochrome tray icon tinted to the current color scheme.

    Colorful application icons look out of place on the KDE panel, so the
    theme glyph is recolored to the palette's text color (white on dark).
    Source glyphs carry their own padding (Font Awesome viewBox), so the
    transparent margin is trimmed before scaling into each icon size.
    """
    color = QColor(252, 252, 252)
    if isinstance(QGuiApplication.instance(), QApplication):
        color = QGuiApplication.instance().palette().color(QPalette.ColorRole.WindowText)
    sources = [QIcon(str(BASE_DIR / "assets" / "app-icon.svg"))]
    sources.extend(QIcon.fromTheme(name) for name in ("translate", "languages-symbolic", "accessories-screenshot-tool"))
    for source in sources:
        if source.isNull():
            continue
        image = _trim_transparent(source.pixmap(128, 128).toImage())
        if image.isNull():
            continue
        tinted = QImage(image.size(), QImage.Format.Format_ARGB32)
        tinted.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tinted)
        painter.drawImage(0, 0, image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), color)
        painter.end()

        icon = QIcon()
        # Plasma renders the first SNI pixmap at its natural/logical size and
        # does not upscale; multiple sizes make it pick the small 16px entry.
        # Provide a single large pixmap instead and let the tray scale it down.
        canvas = QImage(64, 64, QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.transparent)
        scaled = tinted.scaled(
            60,
            60,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter = QPainter(canvas)
        painter.drawImage((64 - scaled.width()) // 2, (64 - scaled.height()) // 2, scaled)
        painter.end()
        icon.addPixmap(QPixmap.fromImage(canvas))
        return icon
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(8, 8, 48, 48)
    painter.end()
    return QIcon(pixmap)


def image_to_png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    if not buf.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError("无法创建截图缓冲区")
    if not image.save(buf, "PNG"):
        buf.close()
        raise RuntimeError("无法把截图编码为 PNG")
    buf.close()
    return bytes(data)


class CaptureResult(NamedTuple):
    virtual: QRect  # logical virtual desktop rectangle
    image: QImage  # captured desktop, physical pixels
    scale_x: float  # image pixels per logical pixel
    scale_y: float


def virtual_desktop_rect() -> QRect:
    screens = QGuiApplication.screens()
    if not screens:
        raise RuntimeError("没有检测到屏幕")
    virtual = QRect(screens[0].geometry())
    for screen in screens[1:]:
        virtual = virtual.united(screen.geometry())
    return virtual


def capture_virtual_desktop() -> CaptureResult:
    """Capture all Qt screens into one image using X11-backed QScreen.grabWindow()."""
    screens = QGuiApplication.screens()
    virtual = virtual_desktop_rect()

    image = QImage(virtual.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.black)
    painter = QPainter(image)
    try:
        for screen in screens:
            geo = screen.geometry()
            pixmap = screen.grabWindow(0)
            if pixmap.isNull():
                raise RuntimeError(f"无法抓取屏幕: {screen.name()}")
            target = QRect(
                geo.x() - virtual.x(),
                geo.y() - virtual.y(),
                geo.width(),
                geo.height(),
            )
            source_image = pixmap.toImage()
            # Scale to logical screen geometry if Qt returned device-pixel-sized
            # content.
            painter.drawImage(target, source_image)
    finally:
        painter.end()
    return CaptureResult(virtual, image, 1.0, 1.0)


def _cleanup_old_captures() -> None:
    try:
        now = time.time()
        for stale in CACHE_DIR.glob("wayland-capture-*.png"):
            if now - stale.stat().st_mtime > 3600:
                stale.unlink(missing_ok=True)
    except Exception:
        LOG.debug("capture cache cleanup failed", exc_info=True)


def capture_desktop_spectacle() -> CaptureResult:
    """KDE/Wayland capture: Spectacle grabs the full desktop before selection.

    Wayland clients cannot read other surfaces, so the compositor-backed
    Spectacle CLI is used. The returned image is in physical pixels while the
    Qt screen geometry is in logical pixels; callers map between them with the
    returned scale factors.
    """
    virtual = virtual_desktop_rect()
    exe = shutil.which("spectacle")
    if not exe:
        raise RuntimeError("找不到 spectacle；KDE Wayland 截图需要安装 Spectacle")

    ensure_runtime_dirs()
    _cleanup_old_captures()
    target = CACHE_DIR / f"wayland-capture-{os.getpid()}-{time.monotonic_ns()}.png"
    # -i forces a fresh instance: without it, an already running Spectacle GUI
    # swallows the background request, exits 0 and never writes the file.
    args = [exe, "-b", "-n", "-i", "-f", "-o", str(target)]
    try:
        detail = ""
        for attempt in range(2):
            proc = subprocess.run(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=45,
            )
            detail = proc.stderr.decode("utf-8", "replace").strip()
            if proc.returncode != 0:
                detail = detail or f"spectacle 退出码 {proc.returncode}"
                continue
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and not target.exists():
                time.sleep(0.05)
            if target.exists() and target.stat().st_size > 0:
                break
            detail = "未生成文件"
        else:
            raise RuntimeError(f"Spectacle 截图失败: {detail or '未生成文件'}")
        data = target.read_bytes()
        image = QImage.fromData(data, "PNG")
        if image.isNull() or image.width() == 0 or image.height() == 0:
            raise RuntimeError("Spectacle 返回了无法读取的截图")
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Spectacle 截图超时") from exc
    finally:
        target.unlink(missing_ok=True)

    scale_x = image.width() / max(1, virtual.width())
    scale_y = image.height() / max(1, virtual.height())
    LOG.info(
        "spectacle capture image=%dx%d virtual=%dx%d scale=%.4fx%.4f",
        image.width(),
        image.height(),
        virtual.width(),
        virtual.height(),
        scale_x,
        scale_y,
    )
    return CaptureResult(virtual, image, scale_x, scale_y)


def effective_capture_backend(cfg: dict[str, Any]) -> str:
    """Resolve capture.backend=auto and guard against X11-only grabs on Wayland."""
    backend = str(cfg["capture"].get("backend", "auto")).strip().lower()
    if backend == "auto":
        return "spectacle" if IS_WAYLAND else "qt_x11"
    if backend not in {"qt_x11", "spectacle"}:
        raise RuntimeError(f"不支持的截图后端: {backend}")
    if backend == "qt_x11" and IS_WAYLAND:
        LOG.warning("capture backend qt_x11 does not work on Wayland; using spectacle")
        return "spectacle"
    return backend


def capture_desktop(cfg: dict[str, Any]) -> CaptureResult:
    if effective_capture_backend(cfg) == "spectacle":
        return capture_desktop_spectacle()
    return capture_virtual_desktop()


class Selector(QWidget):
    selected = Signal(object, object)  # QRect(global logical), QImage(physical crop)
    cancelled = Signal()

    def __init__(self, cfg: dict[str, Any]) -> None:
        super().__init__()
        self.cfg = cfg
        self.capture = capture_desktop(cfg)
        self.virtual = self.capture.virtual
        self.desktop = self.capture.image
        self.scale_x = self.capture.scale_x
        self.scale_y = self.capture.scale_y
        self.start: QPoint | None = None
        self.end: QPoint | None = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        if IS_WAYLAND:
            # Wayland clients cannot position top-level windows. The selection
            # surface is a fullscreen window on the target output; the capture
            # image is mapped into its logical coordinate space.
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                raise RuntimeError("没有检测到屏幕")
            self.setGeometry(screen.geometry())
        else:
            self.setGeometry(self.virtual)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def show_selector(self) -> None:
        # A normal top-level window can be constrained to the work area by
        # KWin, leaving the panel visible underneath the captured desktop.
        # Full-screen state makes the selection surface cover the whole screen,
        # including panels, so displayed pixels and mouse coordinates share the
        # same origin.
        if IS_WAYLAND:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                self.setGeometry(screen.geometry())
        else:
            self.setGeometry(self.virtual)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        QTimer.singleShot(0, self._log_activation)

    def _log_activation(self) -> None:
        LOG.info("selector shown fullscreen=%s active=%s", self.isFullScreen(), self.isActiveWindow())

    def selection_rect(self) -> QRect:
        if self.start is None or self.end is None:
            return QRect()
        return QRect(self.start, self.end).normalized()

    def _window_origin(self) -> QPoint:
        return self.mapToGlobal(QPoint(0, 0))

    def _logical_to_physical(self, global_rect: QRect) -> QRect:
        rel = global_rect.translated(-self.virtual.topLeft())
        return QRect(
            round(rel.x() * self.scale_x),
            round(rel.y() * self.scale_y),
            round(rel.width() * self.scale_x),
            round(rel.height() * self.scale_y),
        )

    def _physical_to_logical(self, physical_rect: QRect) -> QRect:
        return QRect(
            self.virtual.x() + round(physical_rect.x() / self.scale_x),
            self.virtual.y() + round(physical_rect.y() / self.scale_y),
            round(physical_rect.width() / self.scale_x),
            round(physical_rect.height() / self.scale_y),
        )

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        window_origin = self._window_origin()
        visible_global = QRect(window_origin, self.size())
        source_rect = self._logical_to_physical(visible_global).intersected(self.desktop.rect())
        p.drawImage(self.rect(), self.desktop, source_rect)
        p.fillRect(self.rect(), QColor(0, 0, 0, 95))

        rect = self.selection_rect()
        if not rect.isNull() and rect.width() > 0 and rect.height() > 0:
            global_rect = QRect(window_origin + rect.topLeft(), rect.size())
            selection_source = self._logical_to_physical(global_rect).intersected(self.desktop.rect())
            # Scale the physical crop back into the logical selection rectangle;
            # drawing it at 1:1 would oversize it by the physical/logical ratio.
            p.drawImage(rect, self.desktop, selection_source)
            p.setPen(QPen(QColor(240, 240, 240), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect.adjusted(0, 0, -1, -1))

            label = f"{selection_source.width()} × {selection_source.height()}"
            metrics = QFontMetricsF(self.font())
            label_rect = metrics.boundingRect(label).adjusted(-6, -4, 6, 4)
            x = min(max(4, rect.left()), max(4, self.width() - int(label_rect.width()) - 4))
            y = rect.top() - int(label_rect.height()) - 6
            if y < 4:
                y = min(self.height() - int(label_rect.height()) - 4, rect.bottom() + 6)
            label_rect.moveTopLeft(QPoint(x, y))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(20, 20, 20, 210))
            p.drawRoundedRect(label_rect, 4, 4)
            p.setPen(QColor(245, 245, 245))
            p.drawText(label_rect, int(Qt.AlignmentFlag.AlignCenter), label)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = event.position().toPoint()
            self.end = self.start
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            self.close()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.start is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.start is None:
            return
        self.end = event.position().toPoint()
        rect = self.selection_rect().intersected(self.rect())
        min_w = int(self.cfg["capture"].get("min_width", 8))
        min_h = int(self.cfg["capture"].get("min_height", 8))
        if rect.width() < min_w or rect.height() < min_h:
            self.start = None
            self.end = None
            self.update()
            return

        window_origin = self._window_origin()
        global_rect = QRect(window_origin + rect.topLeft(), rect.size())
        source_rect = self._logical_to_physical(global_rect).intersected(self.desktop.rect())
        if source_rect.width() < min_w or source_rect.height() < min_h:
            self.start = None
            self.end = None
            self.update()
            return
        crop = self.desktop.copy(source_rect)
        global_rect = self._physical_to_logical(source_rect)
        self.hide()
        self.selected.emit(global_rect, crop)
        self.close()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
            return
        super().keyPressEvent(event)


class LoadingWindow(QWidget):
    """Small non-interactive spinner shown while OCR/translation is running.

    On Wayland a fullscreen transparent canvas is used because top-level
    windows cannot be positioned; the spinner is painted at the selection
    center and the input region is limited to the spinner itself.
    """

    SPINNER_SIZE = 34

    def __init__(self, image_global: QRect) -> None:
        super().__init__()
        self.angle = 0
        self.canvas_mode = IS_WAYLAND
        self.canvas_origin = QPoint(0, 0)
        self.rect_local = QRect()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(80)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        if self.canvas_mode:
            screen = (
                QGuiApplication.screenAt(image_global.center())
                or QGuiApplication.primaryScreen()
            )
            if screen is None:
                raise RuntimeError("没有检测到屏幕")
            self.canvas_origin = screen.geometry().topLeft()
            self.setGeometry(screen.geometry())
            self.rect_local = QRect(
                image_global.center() - self.canvas_origin - QPoint(self.SPINNER_SIZE // 2, self.SPINNER_SIZE // 2),
                QSize(self.SPINNER_SIZE, self.SPINNER_SIZE),
            )
            self.setMask(QRegion(self.rect_local))
        else:
            self.setFixedSize(self.SPINNER_SIZE, self.SPINNER_SIZE)
            self.rect_local = QRect(0, 0, self.SPINNER_SIZE, self.SPINNER_SIZE)
            self._place(image_global)

    def _place(self, image_global: QRect) -> None:
        center = image_global.center()
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        if screen is None:
            self.move(center - QPoint(self.width() // 2, self.height() // 2))
            return
        bounds = screen.geometry()
        x = min(max(bounds.left(), center.x() - self.width() // 2), bounds.right() - self.width() + 1)
        y = min(max(bounds.top(), center.y() - self.height() // 2), bounds.bottom() - self.height() + 1)
        self.move(x, y)

    def _tick(self) -> None:
        self.angle = (self.angle + 30) % 360
        self.update()

    def show_loading(self) -> None:
        if self.canvas_mode:
            self.showFullScreen()
            return
        self.show()
        self.raise_()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect_local
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 20, 205))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))

        pen = QPen(QColor(248, 248, 248, 245), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect.adjusted(9, 9, -9, -9), self.angle * 16, 270 * 16)
        p.end()

    def closeEvent(self, event) -> None:
        self.timer.stop()
        super().closeEvent(event)


class PipelineWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, png: bytes, cfg: dict[str, Any], keys: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.png = png
        self.cfg = cfg
        self.keys = keys or {}

    def run(self) -> None:
        try:
            started = time.monotonic()
            self._ensure_umi()
            blocks = self._ocr()
            source_text = "".join(
                str(item.get("text", "")) + str(item.get("end", "")) for item in blocks
            ).strip()
            if not source_text:
                raise RuntimeError("没有识别到文字")

            paragraphs = self._make_paragraphs(blocks)
            paragraphs = [para for para in paragraphs if str(para["text"]).strip()]
            texts = [str(para["text"]).strip() for para in paragraphs]
            translated_texts = self._translate_many(texts)
            translated = [
                {
                    "source": text,
                    "translated": translated_text,
                    "bbox": para["bbox"],
                }
                for para, text, translated_text in zip(paragraphs, texts, translated_texts)
            ]

            if not translated:
                raise RuntimeError("OCR 有结果，但没有可翻译文本")

            result = {
                "source_text": source_text,
                "translated_text": "\n".join(x["translated"] for x in translated),
                "paragraphs": translated,
                "elapsed": time.monotonic() - started,
            }
            self.done.emit(result)
        except Exception as exc:
            LOG.exception("pipeline failed")
            self.failed.emit(str(exc))

    def _http_json(
        self,
        url: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> Any:
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            # Do not dump returned HTML/body into the UI/log by default.
            raise RuntimeError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"网络错误: {exc.reason}") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError("服务返回了无法解析的 JSON") from exc

    def _options_url(self) -> str:
        api_url = str(self.cfg["ocr"]["api_url"]).rstrip("/")
        if api_url.endswith("/api/ocr"):
            return api_url + "/get_options"
        return api_url.rsplit("/", 1)[0] + "/get_options"

    def _umi_ready(self) -> bool:
        try:
            self._http_json(self._options_url(), timeout=0.8)
            return True
        except Exception:
            return False

    def _ensure_umi(self) -> None:
        ocr_cfg = self.cfg["ocr"]
        if self._umi_ready():
            return
        if not bool(ocr_cfg.get("auto_start", True)):
            raise RuntimeError("Umi-OCR HTTP 服务未运行")

        script = Path(os.path.expanduser(str(ocr_cfg["umi_ocr"]))).resolve()
        if not script.exists():
            raise RuntimeError(f"找不到 Umi-OCR 启动脚本: {script}")

        LOG.info("starting Umi-OCR script=%s", script)
        subprocess.Popen(
            [str(script), "--hide"],
            cwd=str(script.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        deadline = time.monotonic() + float(ocr_cfg.get("startup_timeout_s", 8.0))
        while time.monotonic() < deadline:
            if self._umi_ready():
                # Umi-OCR Linux cold start can miss the first control command.
                try:
                    subprocess.Popen(
                        [str(script), "--hide"],
                        cwd=str(script.parent),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
                return
            time.sleep(0.25)
        raise RuntimeError("Umi-OCR 启动超时；请确认 HTTP 服务已启用")

    def _ocr(self) -> list[dict[str, Any]]:
        ocr_cfg = self.cfg["ocr"]
        payload = {
            "base64": base64.b64encode(self.png).decode("ascii"),
            "options": {
                "ocr.language": str(ocr_cfg["language"]),
                "ocr.limit_side_len": int(ocr_cfg["limit_side_len"]),
                "tbpu.parser": str(ocr_cfg["parser"]),
                "data.format": "dict",
            },
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = str(ocr_cfg["api_url"])
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                res = self._http_json(
                    url,
                    method="POST",
                    body=body,
                    headers={"Content-Type": "application/json"},
                    timeout=float(ocr_cfg.get("request_timeout_s", 20.0)),
                )
                if not isinstance(res, dict):
                    raise RuntimeError("Umi-OCR 返回格式异常")
                code = int(res.get("code", -1))
                if code == 101:
                    raise RuntimeError("没有识别到文字")
                if code != 100:
                    raise RuntimeError(f"Umi-OCR 失败(code={code})")
                data = res.get("data")
                if not isinstance(data, list):
                    raise RuntimeError("Umi-OCR 返回格式异常")
                return data
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.3)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _bbox_for_group(group: list[dict[str, Any]]) -> list[int] | None:
        xs: list[int] = []
        ys: list[int] = []
        for item in group:
            box = item.get("box", [])
            for point in box:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    xs.append(int(point[0]))
                    ys.append(int(point[1]))
        if not xs or not ys:
            return None
        return [min(xs), min(ys), max(xs), max(ys)]

    def _make_paragraphs(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Use Umi-OCR's end field, with a small safety cap for malformed output."""
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for item in blocks:
            if not str(item.get("text", "")).strip():
                continue
            current.append(item)
            end = str(item.get("end", ""))
            if "\n" in end or len(current) >= 8:
                groups.append(current)
                current = []
        if current:
            groups.append(current)

        out: list[dict[str, Any]] = []
        for group in groups:
            text = "".join(str(x.get("text", "")) + str(x.get("end", "")) for x in group).strip()
            bbox = self._bbox_for_group(group)
            if text and bbox:
                out.append({"text": text, "bbox": bbox})
        return out

    def _translate(self, text: str) -> str:
        cfg = self.cfg["translation"]
        backend = str(cfg["backend"]).strip().lower()
        if backend == "identity":
            return text
        if backend == "google":
            return self._translate_google(text)
        if backend in {"google_cloud", "google-cloud", "cloud_google"}:
            return self._translate_google_cloud([text])[0]
        if backend in {"libre", "libretranslate"}:
            return self._translate_libre(text)
        raise RuntimeError(f"未知翻译后端: {backend}")

    def _translate_many(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        backend = str(self.cfg["translation"]["backend"]).strip().lower()
        if backend in {"google_cloud", "google-cloud", "cloud_google"}:
            return self._translate_google_cloud(texts)
        return [self._translate(text) for text in texts]

    def _translate_google(self, text: str) -> str:
        cfg = self.cfg["translation"]
        endpoint = str(cfg.get("google", {}).get("endpoint", DEFAULTS["translation"]["google"]["endpoint"]))
        form = urllib.parse.urlencode(
            {
                "client": "gtx",
                "sl": str(cfg["source"]),
                "tl": str(cfg["target"]),
                "dt": "t",
                "q": text,
            }
        ).encode("utf-8")
        res = self._http_json(
            endpoint,
            method="POST",
            body=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=float(cfg["timeout_s"]),
        )
        try:
            parts = res[0]
            translated = "".join(str(seg[0]) for seg in parts if seg and seg[0] is not None)
        except Exception as exc:
            raise RuntimeError("Google 翻译返回格式异常") from exc
        if not translated:
            raise RuntimeError("Google 翻译返回空结果")
        return translated

    def _translate_google_cloud(self, texts: list[str]) -> list[str]:
        cfg = self.cfg["translation"]
        cloud_cfg = cfg.get("google_cloud", {})
        cloud_keys = self.keys.get("google_cloud", {})
        if not isinstance(cloud_keys, dict):
            raise RuntimeError(f"Google Cloud 密钥配置格式异常: {KEYS_PATH}")
        api_key = str(cloud_keys.get("api_key", "")).strip()
        if not api_key:
            raise RuntimeError(f"未配置 Google Cloud API Key: {KEYS_PATH}")
        if len(texts) > 128:
            translated: list[str] = []
            for offset in range(0, len(texts), 128):
                translated.extend(self._translate_google_cloud(texts[offset : offset + 128]))
            return translated

        target = str(cfg["target"]).strip()
        if not target or target.lower() == "auto":
            raise RuntimeError("Google Cloud 翻译需要有效的 target 语言")
        payload: dict[str, Any] = {
            "q": texts,
            "target": target,
            "format": "text",
        }
        source = str(cfg["source"]).strip()
        if source and source.lower() != "auto":
            payload["source"] = source

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = str(
            cloud_cfg.get(
                "endpoint",
                DEFAULTS["translation"]["google_cloud"]["endpoint"],
            )
        )
        res = self._http_json(
            endpoint,
            method="POST",
            body=body,
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "X-Goog-Api-Key": api_key,
            },
            timeout=float(cfg["timeout_s"]),
        )
        try:
            items = res["data"]["translations"]
            translated = [str(item["translatedText"]) for item in items]
        except Exception as exc:
            raise RuntimeError("Google Cloud 翻译返回格式异常") from exc
        if len(translated) != len(texts) or any(not item for item in translated):
            raise RuntimeError("Google Cloud 翻译返回数量异常")
        return translated

    def _translate_libre(self, text: str) -> str:
        cfg = self.cfg["translation"]
        libre = cfg.get("libretranslate", {})
        target = str(cfg["target"])
        if "-" in target:
            target = target.split("-", 1)[0]
        payload: dict[str, Any] = {
            "q": text,
            "source": str(cfg["source"]),
            "target": target,
            "format": "text",
        }
        api_key = str(libre.get("api_key", "")).strip()
        if api_key:
            payload["api_key"] = api_key
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        res = self._http_json(
            str(libre.get("endpoint", DEFAULTS["translation"]["libretranslate"]["endpoint"])),
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
            timeout=float(cfg["timeout_s"]),
        )
        translated = res.get("translatedText") if isinstance(res, dict) else None
        if not translated:
            raise RuntimeError("LibreTranslate 返回空结果")
        return str(translated)


def fit_font(rect: QRectF, text: str, min_size: int, max_size: int) -> QFont:
    font = QFont(QGuiApplication.font())
    font.setWeight(QFont.Weight.Medium)
    # OCR boxes track the text ink, not the font line box; start from the box
    # height and pick the largest size whose ink still fits.
    start = min(max_size, max(min_size, int(rect.height())))
    flags = int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for size in range(start, min_size - 1, -1):
        font.setPixelSize(size)
        metrics = QFontMetricsF(font)
        if "\n" not in text:
            ink = metrics.tightBoundingRect(text)
            if ink.width() <= rect.width() + 1 and ink.height() <= rect.height() + 2:
                return QFont(font)
        br = metrics.boundingRect(rect, flags, text)
        if br.height() <= rect.height() and br.width() <= rect.width() + 1:
            return QFont(font)
    font.setPixelSize(min_size)
    return font


def render_translation(
    original: QImage,
    result: dict[str, Any],
    cfg: dict[str, Any],
    scale: float = 1.0,
) -> QImage:
    out = original.copy()
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    ov = cfg["overlay"]
    mask_alpha = max(0, min(255, int(ov["mask_alpha"])))
    # Font limits are configured in logical pixels; the image is in physical
    # pixels, so scale them for the Wayland HiDPI case.
    font_scale = max(0.1, float(scale))
    min_size = max(1, int(round(int(ov["font_min_px"]) * font_scale)))
    max_size = max(min_size, int(round(int(ov["font_max_px"]) * font_scale)))
    pad = max(0, int(ov.get("padding", 3)))
    radius = max(0, int(ov.get("corner_radius", 4)))

    try:
        for para in result["paragraphs"]:
            x1, y1, x2, y2 = [int(v) for v in para["bbox"]]
            left = max(0, x1 - pad)
            top = max(0, y1 - pad)
            right = min(out.width(), x2 + pad)
            bottom = min(out.height(), y2 + pad)
            if right <= left or bottom <= top:
                continue
            rect = QRectF(left, top, right - left, bottom - top)

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(22, 22, 22, mask_alpha))
            p.drawRoundedRect(rect, radius, radius)

            text_rect = rect.adjusted(4, 1, -4, -1)
            translated = str(para["translated"])
            p.setFont(fit_font(text_rect, translated, min_size, max_size))
            p.setPen(QColor(248, 248, 248))
            p.drawText(
                text_rect,
                int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                translated,
            )
    finally:
        p.end()
    return out


class DraggableImage(QLabel):
    def __init__(self, overlay: "OverlayWindow") -> None:
        super().__init__(overlay)
        self.overlay = overlay
        self.timer = QElapsedTimer()
        self.press_global: QPoint | None = None
        self.window_start: QPoint | None = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.overlay.close()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self.overlay.reset_position()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_global = event.globalPosition().toPoint()
            if self.overlay.canvas_mode:
                self.overlay.begin_content_drag()
            else:
                self.window_start = self.overlay.pos()
            self.timer.start()
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta:
            self.overlay.zoom_at(delta / 120.0, event.globalPosition().toPoint())
            event.accept()
            return
        super().wheelEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self.press_global is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
            and self.timer.isValid()
            and self.timer.elapsed() >= self.overlay.drag_hold_ms
        ):
            delta = event.globalPosition().toPoint() - self.press_global
            if self.overlay.canvas_mode:
                self.overlay.move_content(delta)
            elif self.window_start is not None:
                self.overlay.move(self.window_start + delta)
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_global = None
            self.window_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)


class OverlayWindow(QWidget):
    closed = Signal()

    def __init__(
        self,
        global_rect: QRect,
        original: QImage,
        translated: QImage,
        source_text: str,
        translated_text: str,
        cfg: dict[str, Any],
    ) -> None:
        super().__init__()
        self.original = original
        self.translated = translated
        self.source_text = source_text
        self.translated_text = translated_text
        self.cfg = cfg
        self.drag_hold_ms = int(cfg["app"]["drag_hold_ms"])
        self.showing_translation = True
        self.current_image = self.translated
        self.zoom = 1.0
        self.base_rect = QRect(global_rect)
        self.canvas_mode = IS_WAYLAND
        self.logical_size = global_rect.size()
        self.canvas_origin = QPoint(0, 0)
        self._drag_image_start = QPoint(0, 0)
        self._drag_toolbar_start = QPoint(0, 0)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if self.canvas_mode:
            # Wayland cannot position top-level windows; use a fullscreen
            # transparent canvas and rely on the input region mask so clicks
            # outside the overlay pass through to other applications.
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            screen = (
                QGuiApplication.screenAt(global_rect.center())
                or QGuiApplication.primaryScreen()
            )
            if screen is None:
                raise RuntimeError("没有检测到屏幕")
            self.canvas_origin = screen.geometry().topLeft()
            self.setGeometry(screen.geometry())
        else:
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.image = DraggableImage(self)
        self.image.setScaledContents(False)

        self.toolbar = QWidget(self)
        layout = QHBoxLayout(self.toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.toggle_btn = self._button("原/译", "切换原图 / 译图", 52)
        self.copy_src_btn = self._button("原", "复制原文", 38)
        self.copy_dst_btn = self._button("译", "复制译文", 38)
        self.close_btn = self._button("×", "关闭", 30)

        for btn in (self.toggle_btn, self.copy_src_btn, self.copy_dst_btn, self.close_btn):
            layout.addWidget(btn)

        self.toggle_btn.clicked.connect(self.toggle_view)
        self.copy_src_btn.clicked.connect(self.copy_source)
        self.copy_dst_btn.clicked.connect(self.copy_translation)
        self.close_btn.clicked.connect(self.close)

        self.toolbar.adjustSize()
        self._place(global_rect)

    def _button(self, text: str, tooltip: str, width: int) -> QPushButton:
        btn = QPushButton(text, self.toolbar)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(width, 30)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setStyleSheet(
            "QPushButton {"
            " color: white; background: rgba(28,28,28,220);"
            " border: 1px solid rgba(255,255,255,55); border-radius: 15px;"
            " padding: 0 6px; font-weight: 600;"
            "}"
            "QPushButton:hover { background: rgba(55,55,55,235); }"
            "QPushButton:pressed { background: rgba(15,15,15,245); }"
        )
        return btn

    def _pixmap_for_target(self, image: QImage, target: QSize) -> QPixmap:
        if target.width() <= 0 or target.height() <= 0:
            return QPixmap.fromImage(image)
        dpr = self.devicePixelRatioF() or 1.0
        phys = QSize(
            max(1, round(target.width() * dpr)),
            max(1, round(target.height() * dpr)),
        )
        if abs(phys.width() - image.width()) <= 1 and abs(phys.height() - image.height()) <= 1:
            # Near-native zoom: keep the physical pixels and map them 1:1 so the
            # overlay stays sharp instead of being resampled twice.
            pixmap = QPixmap.fromImage(image)
            ratio = (image.width() / target.width() + image.height() / target.height()) / 2
            pixmap.setDevicePixelRatio(ratio)
            return pixmap
        scaled = image.scaled(
            phys,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap.fromImage(scaled)
        pixmap.setDevicePixelRatio(dpr)
        return pixmap

    def _refresh_pixmap(self) -> None:
        self.image.setPixmap(self._pixmap_for_target(self.current_image, self.image.size()))

    def image_rect_global(self) -> QRect:
        origin = self.canvas_origin if self.canvas_mode else self.mapToGlobal(QPoint(0, 0))
        return self.image.geometry().translated(origin)

    def reset_position(self) -> None:
        self.zoom = 1.0
        self._place(QRect(self.base_rect))

    def zoom_at(self, steps: float, anchor: QPoint) -> None:
        new_zoom = min(4.0, max(0.25, self.zoom * (1.15 ** steps)))
        if abs(new_zoom - self.zoom) < 1e-6:
            return
        current = self.image_rect_global()
        rel_x = (anchor.x() - current.x()) / max(1, current.width())
        rel_y = (anchor.y() - current.y()) / max(1, current.height())
        new_w = max(1, round(self.base_rect.width() * new_zoom))
        new_h = max(1, round(self.base_rect.height() * new_zoom))
        new_x = round(anchor.x() - rel_x * new_w)
        new_y = round(anchor.y() - rel_y * new_h)
        self.zoom = new_zoom
        self._place(QRect(new_x, new_y, new_w, new_h))

    def _update_mask(self) -> None:
        if not self.canvas_mode:
            return
        region = QRegion(self.image.geometry()) | QRegion(self.toolbar.geometry())
        self.setMask(region)

    def begin_content_drag(self) -> None:
        self._drag_image_start = self.image.pos()
        self._drag_toolbar_start = self.toolbar.pos()

    def move_content(self, delta: QPoint) -> None:
        self.image.move(self._drag_image_start + delta)
        self.toolbar.move(self._drag_toolbar_start + delta)
        self._update_mask()

    def _place(self, image_global: QRect) -> None:
        self.toolbar.adjustSize()
        tw = self.toolbar.sizeHint().width()
        th = self.toolbar.sizeHint().height()
        gap = int(self.cfg["overlay"]["toolbar_gap"])
        screen = QGuiApplication.screenAt(image_global.center()) or QGuiApplication.primaryScreen()
        sg = screen.availableGeometry() if screen else image_global
        mode = str(self.cfg["overlay"].get("toolbar_position", "auto")).lower()

        below = QRect(image_global.right() - tw + 1, image_global.bottom() + gap + 1, tw, th)
        above = QRect(image_global.right() - tw + 1, image_global.top() - gap - th, tw, th)
        inside = QRect(
            max(image_global.left(), image_global.right() - tw + 1),
            max(image_global.top(), image_global.bottom() - th + 1),
            tw,
            th,
        )

        if mode == "below":
            toolbar_global = below if sg.contains(below) else inside
        elif mode == "above":
            toolbar_global = above if sg.contains(above) else inside
        elif mode == "inside":
            toolbar_global = inside
        elif sg.contains(below):
            toolbar_global = below
        elif sg.contains(above):
            toolbar_global = above
        else:
            toolbar_global = inside

        if self.canvas_mode:
            self.image.setGeometry(image_global.translated(-self.canvas_origin))
            self.toolbar.setGeometry(toolbar_global.translated(-self.canvas_origin))
            self.toolbar.raise_()
            self._refresh_pixmap()
            self._update_mask()
            return

        union = image_global.united(toolbar_global)
        self.setGeometry(union)
        self.image.setGeometry(image_global.translated(-union.topLeft()))
        self.toolbar.setGeometry(toolbar_global.translated(-union.topLeft()))
        self.toolbar.raise_()
        self._refresh_pixmap()

    def show_overlay(self) -> None:
        if self.canvas_mode:
            self.showFullScreen()
            self.raise_()
            return
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def toggle_view(self) -> None:
        self.showing_translation = not self.showing_translation
        self.current_image = self.translated if self.showing_translation else self.original
        self._refresh_pixmap()

    def copy_source(self) -> None:
        QGuiApplication.clipboard().setText(self.source_text)

    def copy_translation(self) -> None:
        QGuiApplication.clipboard().setText(self.translated_text)

    def contains_global_point(self, point: QPoint) -> bool:
        origin = self.canvas_origin if self.canvas_mode else self.mapToGlobal(QPoint(0, 0))
        image_rect = self.image.geometry().translated(origin)
        toolbar_rect = self.toolbar.geometry().translated(origin)
        return image_rect.contains(point) or toolbar_rect.contains(point)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)


class InputService(QObject):
    hotkey_pressed = Signal()
    mouse_pressed = Signal(int, int)

    def __init__(self, hotkey_text: str) -> None:
        super().__init__()
        if keyboard is None or mouse is None:
            raise RuntimeError(f"pynput 初始化失败: {PYNPUT_IMPORT_ERROR}")
        self.hotkey_text = ""
        self._kbd_listener = None
        self._hotkey = None
        self._mouse_listener = None
        self._start_keyboard(hotkey_text)
        self._start_mouse()

    @staticmethod
    def _normalize_hotkey(text: str) -> str:
        aliases = {
            "ctrl": "<ctrl>",
            "control": "<ctrl>",
            "alt": "<alt>",
            "shift": "<shift>",
            "super": "<cmd>",
            "meta": "<cmd>",
            "win": "<cmd>",
        }
        parts: list[str] = []
        for raw in text.lower().replace(" ", "").replace("-", "+").split("+"):
            if not raw:
                continue
            if raw in aliases:
                parts.append(aliases[raw])
            elif raw.startswith("f") and raw[1:].isdigit():
                parts.append(f"<{raw}>")
            elif len(raw) == 1:
                parts.append(raw)
            else:
                raise ValueError(f"不支持的快捷键按键: {raw}")
        if len(parts) < 2:
            raise ValueError("快捷键至少包含一个修饰键和一个普通键")
        return "+".join(parts)

    def _start_keyboard(self, hotkey_text: str) -> None:
        normalized = self._normalize_hotkey(hotkey_text)
        self._hotkey = keyboard.HotKey(  # type: ignore[union-attr]
            keyboard.HotKey.parse(normalized),  # type: ignore[union-attr]
            self.hotkey_pressed.emit,
        )

        def on_press(key) -> None:
            if self._kbd_listener is not None and self._hotkey is not None:
                self._hotkey.press(self._kbd_listener.canonical(key))

        def on_release(key) -> None:
            if self._kbd_listener is not None and self._hotkey is not None:
                self._hotkey.release(self._kbd_listener.canonical(key))

        self._kbd_listener = keyboard.Listener(on_press=on_press, on_release=on_release)  # type: ignore[union-attr]
        self._kbd_listener.start()
        self.hotkey_text = hotkey_text
        LOG.info("global hotkey=%s backend=pynput", hotkey_text)

    def restart_hotkey(self, hotkey_text: str) -> None:
        if hotkey_text == self.hotkey_text:
            return
        if self._kbd_listener is not None:
            self._kbd_listener.stop()
            self._kbd_listener = None
        self._start_keyboard(hotkey_text)

    def _start_mouse(self) -> None:
        def on_click(x, y, _button, pressed) -> None:
            if pressed:
                self.mouse_pressed.emit(int(x), int(y))

        self._mouse_listener = mouse.Listener(on_click=on_click)  # type: ignore[union-attr]
        self._mouse_listener.start()

    def stop(self) -> None:
        if self._kbd_listener is not None:
            self._kbd_listener.stop()
        if self._mouse_listener is not None:
            self._mouse_listener.stop()


HOTKEY_MODIFIERS = {
    "ctrl": 0x04000000,
    "control": 0x04000000,
    "alt": 0x08000000,
    "shift": 0x02000000,
    "super": 0x10000000,
    "meta": 0x10000000,
    "win": 0x10000000,
    "cmd": 0x10000000,
}

HOTKEY_NAMES = {
    "space": "Key_Space",
    "tab": "Key_Tab",
    "return": "Key_Return",
    "enter": "Key_Return",
    "escape": "Key_Escape",
    "esc": "Key_Escape",
    "backspace": "Key_Backspace",
    "delete": "Key_Delete",
    "del": "Key_Delete",
    "insert": "Key_Insert",
    "ins": "Key_Insert",
    "home": "Key_Home",
    "end": "Key_End",
    "pageup": "Key_PageUp",
    "pagedown": "Key_PageDown",
    "up": "Key_Up",
    "down": "Key_Down",
    "left": "Key_Left",
    "right": "Key_Right",
    "minus": "Key_Minus",
    "equal": "Key_Equal",
    "plus": "Key_Plus",
    "comma": "Key_Comma",
    "period": "Key_Period",
    "slash": "Key_Slash",
    "semicolon": "Key_Semicolon",
    "apostrophe": "Key_Apostrophe",
    "grave": "Key_QuoteLeft",
    "bracketleft": "Key_BracketLeft",
    "bracketright": "Key_BracketRight",
    "backslash": "Key_Backslash",
}


def hotkey_to_qt_key(text: str) -> int:
    """Convert "ctrl+alt+d" into a Qt key sequence int used by KGlobalAccel."""
    modifiers = 0
    keys: list[int] = []
    for raw in text.lower().replace(" ", "").replace("-", "+").split("+"):
        if not raw:
            continue
        if raw in HOTKEY_MODIFIERS:
            modifiers |= HOTKEY_MODIFIERS[raw]
            continue
        key_enum = None
        if raw in HOTKEY_NAMES:
            key_enum = getattr(Qt.Key, HOTKEY_NAMES[raw], None)
        elif len(raw) == 1 and (raw.isalpha() or raw.isdigit()):
            key_enum = getattr(Qt.Key, f"Key_{raw.upper()}", None)
        elif raw.startswith("f") and raw[1:].isdigit():
            key_enum = getattr(Qt.Key, f"Key_F{raw[1:]}", None)
        if key_enum is None:
            raise ValueError(f"不支持的快捷键按键: {raw}")
        keys.append(int(key_enum.value))
    if modifiers == 0 or not keys:
        raise ValueError("快捷键至少包含一个修饰键和一个普通键")
    if len(keys) != 1:
        raise ValueError("快捷键只能包含一个普通键")
    combined = modifiers | keys[0]
    return combined


def kglobalaccel_set_shortcut(keys: list[int], flags: int) -> None:
    """Set a KGlobalAccel binding.

    PySide6 cannot marshal the unsigned-int flags argument of
    KGlobalAccel.setShortcut, so gdbus (which coerces types using the service
    introspection data) or dbus-send is used for this single call.
    """
    action = json.dumps(list(KGA_CAPTURE_ACTION_ID), ensure_ascii=False)
    key_array = "[" + ",".join(str(int(key)) for key in keys) + "]"
    gdbus = shutil.which("gdbus")
    if gdbus:
        proc = subprocess.run(
            [
                gdbus, "call", "--session",
                "--dest", KGA_SERVICE,
                "--object-path", KGA_PATH,
                "--method", f"{KGA_IFACE}.setShortcut",
                action, key_array, str(int(flags)),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(f"KGlobalAccel setShortcut 失败: {detail}")
        return

    dbus_send = shutil.which("dbus-send")
    if dbus_send:
        action_arg = "array:string:" + ",".join(f'"{value}"' for value in KGA_CAPTURE_ACTION_ID)
        keys_arg = "array:int32:" + ",".join(str(int(key)) for key in keys)
        proc = subprocess.run(
            [
                dbus_send, "--session", "--print-reply", f"--dest={KGA_SERVICE}", KGA_PATH,
                f"{KGA_IFACE}.setShortcut",
                action_arg, keys_arg, f"uint32:{int(flags)}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(f"KGlobalAccel setShortcut 失败: {detail}")
        return

    raise RuntimeError("需要 gdbus 或 dbus-send 来设置 KDE 全局快捷键")


def kglobalaccel_get_shortcut() -> list[int]:
    """Read the current KGlobalAccel binding for the capture action."""
    action = json.dumps(list(KGA_CAPTURE_ACTION_ID), ensure_ascii=False)
    gdbus = shutil.which("gdbus")
    if gdbus:
        proc = subprocess.run(
            [
                gdbus, "call", "--session",
                "--dest", KGA_SERVICE,
                "--object-path", KGA_PATH,
                "--method", f"{KGA_IFACE}.shortcut",
                action,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        if proc.returncode == 0:
            payload = proc.stdout.decode("utf-8", "replace").strip().strip("()").rstrip(",")
            payload = payload.strip("[]")
            return [int(part) for part in payload.split(",") if part.strip()]

    dbus_send = shutil.which("dbus-send")
    if dbus_send:
        action_arg = "array:string:" + ",".join(f'"{value}"' for value in KGA_CAPTURE_ACTION_ID)
        proc = subprocess.run(
            [
                dbus_send, "--session", "--print-reply", f"--dest={KGA_SERVICE}", KGA_PATH,
                f"{KGA_IFACE}.shortcut", action_arg,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        if proc.returncode == 0:
            keys: list[int] = []
            for line in proc.stdout.decode("utf-8", "replace").splitlines():
                if "int32" in line:
                    keys.append(int(line.split()[-1]))
            return keys
    return []


class WaylandInputService(QObject):
    """KDE global shortcuts through the KGlobalAccel D-Bus service.

    Wayland compositors do not expose global keyboard/mouse input to clients,
    so the hotkey is registered with KDE instead. Shortcut binding is owned by
    KGlobalAccel and can also be changed in System Settings; the config hotkey
    is applied on first registration and when the config changes.
    """

    hotkey_pressed = Signal()
    mouse_pressed = Signal(int, int)  # global mouse monitoring is unavailable

    def __init__(self, hotkey_text: str) -> None:
        super().__init__()
        if QDBusConnection is None or QDBusMessage is None:
            raise RuntimeError(f"QtDBus 不可用: {QDBUS_IMPORT_ERROR}")
        self.bus = QDBusConnection.sessionBus()
        if not self.bus.isConnected():
            raise RuntimeError("无法连接会话 D-Bus")
        self.hotkey_text = hotkey_text
        self._key = hotkey_to_qt_key(hotkey_text)
        self._register()
        ok = self.bus.connect(
            KGA_SERVICE,
            KGA_COMPONENT_PATH,
            KGA_COMPONENT_IFACE,
            "globalShortcutPressed",
            self,
            "1on_pressed(QString,QString,qlonglong)",
        )
        if not ok:
            raise RuntimeError("无法订阅 KGlobalAccel globalShortcutPressed 信号")
        LOG.info("global hotkey=%s backend=kglobalaccel key=%#x", hotkey_text, self._key)

    def _call(self, path: str, interface: str, method: str, args: list[Any]) -> list[Any]:
        message = QDBusMessage.createMethodCall(KGA_SERVICE, path, interface, method)
        message.setArguments(args)
        reply = self.bus.call(message)
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            raise RuntimeError(f"KGlobalAccel {method} 失败: {reply.errorName()}: {reply.errorMessage()}")
        return list(reply.arguments())

    def _current_keys(self) -> list[int]:
        return kglobalaccel_get_shortcut()

    def _register(self) -> None:
        self._call(KGA_PATH, KGA_IFACE, "doRegister", [list(KGA_CAPTURE_ACTION_ID)])
        keys = self._current_keys()
        key = int(keys[0]) if keys else int(self._key)
        # Re-assert the binding with SetPresent so the daemon grabs the key in
        # this session while keeping any binding customized in System Settings.
        self._set_key(key)
        if keys:
            LOG.info("kglobalaccel kept existing shortcut key=%#x", self._key)

    def _set_key(self, key: int) -> None:
        kglobalaccel_set_shortcut([int(key)], KGA_SET_FLAGS)
        keys = self._current_keys()
        if int(key) not in [int(value) for value in keys]:
            raise RuntimeError("KGlobalAccel 未接受快捷键；可能与其他全局快捷键冲突")
        self._key = int(key)

    @Slot(str, str, "qlonglong")
    def on_pressed(self, component: str, shortcut: str, _timestamp: int) -> None:
        if component == KGA_COMPONENT and shortcut == KGA_ACTION:
            self.hotkey_pressed.emit()

    def restart_hotkey(self, hotkey_text: str) -> None:
        if hotkey_text == self.hotkey_text:
            return
        self._set_key(hotkey_to_qt_key(hotkey_text))
        self.hotkey_text = hotkey_text
        LOG.info("kglobalaccel shortcut updated key=%#x", self._key)

    def stop(self) -> None:
        try:
            self._call(KGA_PATH, KGA_IFACE, "setInactive", [list(KGA_CAPTURE_ACTION_ID)])
        except Exception:
            LOG.debug("kglobalaccel setInactive failed", exc_info=True)


def create_input_service(cfg: dict[str, Any]) -> QObject:
    hotkey = str(cfg["app"]["hotkey"])
    mode = str(cfg["app"].get("input_backend", "auto")).strip().lower()
    if mode == "auto":
        mode = "kglobalaccel" if IS_WAYLAND else "pynput"
    if mode == "kglobalaccel":
        return WaylandInputService(hotkey)
    if mode == "pynput":
        return InputService(hotkey)
    raise RuntimeError(f"不支持的输入后端: {mode}")


class Controller(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.cfg = load_config()
        self.input = create_input_service(self.cfg)
        self.input.hotkey_pressed.connect(self.trigger)
        self.input.mouse_pressed.connect(self.global_mouse_press)
        if IS_WAYLAND and bool(self.cfg["app"].get("close_on_outside_click", True)):
            LOG.info("Wayland: 点击贴图外部关闭不可用；请使用 × 或重新触发快捷键")
        self.selector: Selector | None = None
        self.loading: LoadingWindow | None = None
        self.overlay: OverlayWindow | None = None
        self.worker: PipelineWorker | None = None
        self.pending_rect: QRect | None = None
        self.pending_image: QImage | None = None
        self.busy = False
        self.tray: QSystemTrayIcon | None = None
        self.tray_menu: QMenu | None = None

        self.watcher = QFileSystemWatcher(self)
        self.watcher.addPath(str(CONFIG_PATH))
        self.watcher.fileChanged.connect(self.config_changed)

        self._setup_tray()

        app.aboutToQuit.connect(self.input.stop)
        app.aboutToQuit.connect(self.close_loading)
        LOG.info("started version=%s hotkey=%s", VERSION, self.cfg["app"]["hotkey"])

    def _setup_tray(self) -> None:
        if not bool(self.cfg["app"].get("tray_icon", True)):
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            LOG.warning("系统托盘不可用；跳过托盘图标注册")
            return
        icon = make_tray_icon()
        self.app.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self.app)
        self.tray.setToolTip(f"{APP_NAME} {VERSION} · {self.cfg['app']['hotkey']}")
        self.tray_menu = QMenu()
        capture_action = self.tray_menu.addAction("截图并翻译")
        capture_action.triggered.connect(self.trigger)
        config_action = self.tray_menu.addAction("打开配置文件")
        config_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(CONFIG_PATH)))
        )
        log_action = self.tray_menu.addAction("打开日志")
        log_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_PATH)))
        )
        self.tray_menu.addSeparator()
        quit_action = self.tray_menu.addAction("退出")
        quit_action.triggered.connect(self.app.quit)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        LOG.info("tray icon registered theme_icon=%s", not icon.isNull())

    def _teardown_tray(self) -> None:
        if self.tray is None:
            return
        self.tray.hide()
        self.tray.deleteLater()
        self.tray = None
        self.tray_menu = None

    def _apply_tray_config(self) -> None:
        wanted = bool(self.cfg["app"].get("tray_icon", True))
        if wanted and self.tray is None:
            self._setup_tray()
        elif not wanted and self.tray is not None:
            self._teardown_tray()
        elif self.tray is not None:
            self.tray.setToolTip(f"{APP_NAME} {VERSION} · {self.cfg['app']['hotkey']}")

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.trigger()

    def config_changed(self, _path: str) -> None:
        try:
            new_cfg = load_config()
            self.input.restart_hotkey(str(new_cfg["app"]["hotkey"]))
            self.cfg = new_cfg
            self._apply_tray_config()
            reload_log_level(self.cfg)
            LOG.info("config reloaded")
        except Exception:
            LOG.exception("config reload failed")
            notify("配置读取失败", "继续使用上一份有效配置；详情见日志")
        QTimer.singleShot(100, self._restore_config_watch)

    def _restore_config_watch(self) -> None:
        if CONFIG_PATH.exists() and str(CONFIG_PATH) not in self.watcher.files():
            self.watcher.addPath(str(CONFIG_PATH))

    def trigger(self) -> None:
        if self.busy or self.selector is not None:
            return
        try:
            self.cfg = load_config()
            reload_log_level(self.cfg)
            if self.overlay is not None:
                self.overlay.close()
                self.overlay = None
            self.selector = Selector(self.cfg)
            self.selector.selected.connect(self.selection_done)
            self.selector.cancelled.connect(self.selection_cancelled)
            self.selector.destroyed.connect(lambda: setattr(self, "selector", None))
            self.selector.show_selector()
        except Exception as exc:
            LOG.exception("selector failed")
            notify("截图失败", str(exc))
            self.selector = None

    def selection_cancelled(self) -> None:
        self.selector = None

    def selection_done(self, rect: QRect, image: QImage) -> None:
        self.selector = None
        self.busy = True
        self.pending_rect = QRect(rect)
        self.pending_image = image.copy()
        try:
            self.loading = LoadingWindow(self.pending_rect)
            self.loading.show_loading()
            png = image_to_png_bytes(image)
        except Exception as exc:
            self.close_loading()
            self.busy = False
            self.pending_rect = None
            self.pending_image = None
            LOG.exception("screenshot encode failed")
            notify("截图编码失败", str(exc))
            return

        backend = str(self.cfg["translation"]["backend"]).strip().lower()
        keys: dict[str, Any] = {}
        if backend in {"google_cloud", "google-cloud", "cloud_google"}:
            try:
                keys = load_keys()
            except Exception as exc:
                self.close_loading()
                self.busy = False
                self.pending_rect = None
                self.pending_image = None
                LOG.exception("keys load failed")
                notify("密钥配置失败", str(exc))
                return

        LOG.info("capture width=%d height=%d x=%d y=%d", rect.width(), rect.height(), rect.x(), rect.y())
        self.worker = PipelineWorker(png, self.cfg, keys)
        self.worker.done.connect(self.pipeline_done)
        self.worker.failed.connect(self.pipeline_failed)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def pipeline_done(self, result: dict[str, Any]) -> None:
        try:
            if self.pending_image is None or self.pending_rect is None:
                raise RuntimeError("内部状态丢失")
            scale = 1.0
            if self.pending_rect.width() > 0 and self.pending_rect.height() > 0:
                scale = (
                    self.pending_image.width() / self.pending_rect.width()
                    + self.pending_image.height() / self.pending_rect.height()
                ) / 2
            translated_image = render_translation(self.pending_image, result, self.cfg, scale)
            self.overlay = OverlayWindow(
                self.pending_rect,
                self.pending_image,
                translated_image,
                str(result["source_text"]),
                str(result["translated_text"]),
                self.cfg,
            )
            self.overlay.closed.connect(self.overlay_closed)
            self.overlay.show_overlay()
            LOG.info(
                "overlay shown paragraphs=%d elapsed=%.3fs",
                len(result["paragraphs"]),
                float(result["elapsed"]),
            )
        except Exception as exc:
            LOG.exception("overlay failed")
            notify("贴图失败", str(exc))
        finally:
            self.close_loading()
            self.busy = False
            self.pending_image = None
            self.pending_rect = None
            self.worker = None

    def pipeline_failed(self, message: str) -> None:
        self.close_loading()
        self.busy = False
        self.pending_image = None
        self.pending_rect = None
        self.worker = None
        notify("截图翻译失败", message)

    def overlay_closed(self) -> None:
        self.overlay = None

    def close_loading(self) -> None:
        if self.loading is not None:
            self.loading.close()
            self.loading = None

    def global_mouse_press(self, x: int, y: int) -> None:
        if not bool(self.cfg["app"].get("close_on_outside_click", True)):
            return
        overlay = self.overlay
        if overlay is None or not overlay.isVisible():
            return
        if not overlay.contains_global_point(QPoint(x, y)):
            overlay.close()


def standalone_http_json(url: str, timeout: float = 0.8) -> Any:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ocr_options_url(cfg: dict[str, Any]) -> str:
    api_url = str(cfg["ocr"]["api_url"]).rstrip("/")
    if api_url.endswith("/api/ocr"):
        return api_url + "/get_options"
    return api_url.rsplit("/", 1)[0] + "/get_options"


def kglobalaccel_available() -> bool:
    if QDBusConnection is None or QDBusMessage is None:
        return False
    try:
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return False
        message = QDBusMessage.createMethodCall(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
        )
        message.setArguments([KGA_SERVICE])
        reply = bus.call(message)
        args = reply.arguments()
        if args and bool(args[0]):
            return True
    except Exception:
        LOG.debug("kglobalaccel availability probe failed", exc_info=True)
    for path in (
        Path("/usr/share/dbus-1/services/org.kde.kglobalaccel.service"),
        Path("/usr/lib/kglobalacceld"),
        Path("/etc/xdg/autostart/kglobalacceld.desktop"),
    ):
        if path.exists():
            return True
    return shutil.which("kglobalacceld") is not None


def run_check(app: QApplication, cfg: dict[str, Any]) -> int:
    critical = 0
    print(f"{APP_NAME} {VERSION}")
    print(f"配置: {CONFIG_PATH}")
    print(f"密钥: {KEYS_PATH}")
    print(f"日志: {LOG_PATH}")
    print()

    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    display = os.environ.get("DISPLAY", "")
    if session == "x11" and display:
        print(f"会话: OK (x11 {display})")
    elif IS_WAYLAND:
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
        print(f"会话: OK (wayland {desktop})")
    else:
        print(f"会话: FAIL (XDG_SESSION_TYPE={session or 'unknown'})")
        critical += 1

    try:
        capture_backend = effective_capture_backend(cfg)
    except Exception as exc:
        capture_backend = None
        print(f"截图后端: FAIL ({exc})")
        critical += 1
    if capture_backend == "qt_x11":
        if display:
            print("截图后端: OK (qt_x11)")
        else:
            print("截图后端: FAIL (qt_x11 需要 X11 DISPLAY)")
            critical += 1
    elif capture_backend == "spectacle":
        spectacle = shutil.which("spectacle")
        if spectacle:
            print(f"截图后端: OK (spectacle: {spectacle})")
        else:
            print("截图后端: FAIL (KDE Wayland 需要 spectacle)")
            critical += 1

    input_mode = str(cfg["app"].get("input_backend", "auto")).strip().lower()
    if input_mode == "auto":
        input_mode = "kglobalaccel" if IS_WAYLAND else "pynput"
    if input_mode == "pynput":
        if PYNPUT_IMPORT_ERROR is None:
            print("全局快捷键(pynput): OK")
        else:
            print(f"全局快捷键(pynput): FAIL ({PYNPUT_IMPORT_ERROR})")
            critical += 1
    elif input_mode == "kglobalaccel":
        if QDBUS_IMPORT_ERROR is not None:
            print(f"全局快捷键(KGlobalAccel): FAIL (QtDBus 不可用: {QDBUS_IMPORT_ERROR})")
            critical += 1
        elif not kglobalaccel_available():
            print("全局快捷键(KGlobalAccel): FAIL (未找到 org.kde.kglobalaccel)")
            critical += 1
        elif not (shutil.which("gdbus") or shutil.which("dbus-send")):
            print("全局快捷键(KGlobalAccel): FAIL (需要 gdbus 或 dbus-send 设置快捷键)")
            critical += 1
        else:
            tool = shutil.which("gdbus") or shutil.which("dbus-send")
            print(f"全局快捷键(KGlobalAccel): OK (KDE D-Bus, {tool})")
    else:
        print(f"全局快捷键: FAIL (不支持的输入后端 {input_mode})")
        critical += 1

    screens = QGuiApplication.screens()
    if screens:
        desc = ", ".join(
            f"{s.name()}={s.geometry().width()}x{s.geometry().height()}@{s.devicePixelRatio():g}x"
            for s in screens
        )
        print(f"Qt 屏幕: OK ({desc})")
    else:
        print("Qt 屏幕: FAIL")
        critical += 1

    umi_script = Path(os.path.expanduser(str(cfg["ocr"]["umi_ocr"]))).resolve()
    if umi_script.exists():
        print(f"Umi-OCR 启动脚本: OK ({umi_script})")
    else:
        print(f"Umi-OCR 启动脚本: WARN (未找到 {umi_script})")

    try:
        standalone_http_json(ocr_options_url(cfg), timeout=0.8)
        print("Umi-OCR HTTP: OK")
    except Exception as exc:
        if bool(cfg["ocr"].get("auto_start", True)) and umi_script.exists():
            print(f"Umi-OCR HTTP: WARN (当前未响应；运行时会自动启动: {exc})")
        else:
            print(f"Umi-OCR HTTP: FAIL ({exc})")
            critical += 1

    if shutil.which("notify-send"):
        print(f"系统通知: OK ({shutil.which('notify-send')})")
    elif shutil.which("kdialog"):
        print(f"系统通知: OK (kdialog fallback: {shutil.which('kdialog')})")
    else:
        print("系统通知: WARN (notify-send / kdialog 均未找到)")

    trans = cfg["translation"]
    print(
        "翻译配置: "
        f"backend={trans['backend']} source={trans['source']} target={trans['target']}"
    )
    print("提示: --check 不会主动访问外部翻译服务。")
    print()
    print("检查结果:", "PASS" if critical == 0 else f"FAIL ({critical} 个关键问题)")
    return 0 if critical == 0 else 2


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KDE screenshot translation overlay (X11/Wayland)")
    parser.add_argument("--check", action="store_true", help="检查本地运行环境，不调用外部翻译服务")
    parser.add_argument("--config-path", action="store_true", help="只打印配置文件路径")
    parser.add_argument("--keys-path", action="store_true", help="只打印密钥配置文件路径")
    parser.add_argument("--log-path", action="store_true", help="只打印日志文件路径")
    parser.add_argument("--quit", action="store_true", help="停止正在运行的常驻实例")
    parser.add_argument("--version", action="store_true", help="打印版本")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])
    if args.version:
        print(VERSION)
        return 0
    if args.config_path:
        print(CONFIG_PATH)
        return 0
    if args.keys_path:
        print(KEYS_PATH)
        return 0
    if args.log_path:
        print(LOG_PATH)
        return 0
    if args.quit:
        return quit_running_instance()

    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("没有图形会话；需要在 KDE/X11 或 KDE/Wayland 中运行。", file=sys.stderr)
        return 2

    if not args.check and not acquire_single_instance():
        print(f"{APP_NAME} 已在运行。", file=sys.stderr)
        notify(APP_NAME, "程序已在运行，未重复启动")
        return 0

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    if args.check:
        return run_check(app, load_config())

    try:
        controller = Controller(app)
    except Exception as exc:
        LOG.exception("startup failed")
        print(f"启动失败: {exc}", file=sys.stderr)
        notify("Screenshot Translator 启动失败", str(exc))
        return 2

    # Keep a strong reference for the whole application lifetime.
    app.setProperty("controller", controller)

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    sig_timer = QTimer()
    sig_timer.timeout.connect(lambda: None)
    sig_timer.start(500)
    app.setProperty("sig_timer", sig_timer)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
