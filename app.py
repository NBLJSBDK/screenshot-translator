#!/usr/bin/env python3
"""Screenshot Translator v0.1.2

KDE Plasma / Linux / X11 screenshot translation overlay.

Default flow:
    Ctrl+Alt+D -> Qt/X11 region selection -> Umi-OCR HTTP API
    -> pluggable translation backend -> translated image over original region.

No main window and no tray icon. Failures use desktop notifications + log only.
"""

from __future__ import annotations

import argparse
import base64
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
from typing import Any
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
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QWidget

APP_NAME = "Screenshot Translator"
APP_SLUG = "screenshot-translator"
VERSION = "0.1.2"
BASE_DIR = Path(__file__).resolve().parent

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
        "drag_hold_ms": 350,
        "close_on_outside_click": True,
    },
    "capture": {
        "backend": "qt_x11",
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


def capture_virtual_desktop() -> tuple[QRect, QImage]:
    """Capture all Qt screens into one image using X11-backed QScreen.grabWindow()."""
    screens = QGuiApplication.screens()
    if not screens:
        raise RuntimeError("没有检测到屏幕")

    virtual = QRect(screens[0].geometry())
    for screen in screens[1:]:
        virtual = virtual.united(screen.geometry())

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
            # v0.1.2 targets normal X11 scaling. Scale to logical screen geometry
            # if Qt returned device-pixel-sized content.
            painter.drawImage(target, source_image)
    finally:
        painter.end()
    return virtual, image


class Selector(QWidget):
    selected = Signal(object, object)  # QRect(global), QImage
    cancelled = Signal()

    def __init__(self, cfg: dict[str, Any]) -> None:
        super().__init__()
        self.cfg = cfg
        backend = str(cfg["capture"].get("backend", "qt_x11")).lower()
        if backend != "qt_x11":
            raise RuntimeError(f"v0.1.2 暂不支持截图后端: {backend}")
        self.virtual, self.desktop = capture_virtual_desktop()
        self.start: QPoint | None = None
        self.end: QPoint | None = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setGeometry(self.virtual)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def show_selector(self) -> None:
        # A normal top-level window can be constrained to the work area by
        # KWin, leaving the panel visible underneath the captured desktop.
        # Full-screen state makes the selection surface cover the whole X11
        # screen, including panels, so displayed pixels and mouse coordinates
        # share the same origin.
        self.setGeometry(self.virtual)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def selection_rect(self) -> QRect:
        if self.start is None or self.end is None:
            return QRect()
        return QRect(self.start, self.end).normalized()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        window_origin = self.mapToGlobal(QPoint(0, 0))
        image_origin = window_origin - self.virtual.topLeft()
        p.drawImage(-image_origin, self.desktop)
        p.fillRect(self.rect(), QColor(0, 0, 0, 95))

        rect = self.selection_rect()
        if not rect.isNull() and rect.width() > 0 and rect.height() > 0:
            global_rect = QRect(window_origin + rect.topLeft(), rect.size())
            source_rect = global_rect.translated(-self.virtual.topLeft())
            p.drawImage(rect.topLeft(), self.desktop, source_rect)
            p.setPen(QPen(QColor(240, 240, 240), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect.adjusted(0, 0, -1, -1))

            label = f"{rect.width()} × {rect.height()}"
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

        window_origin = self.mapToGlobal(QPoint(0, 0))
        global_rect = QRect(window_origin + rect.topLeft(), rect.size())
        source_rect = global_rect.translated(-self.virtual.topLeft())
        source_rect = source_rect.intersected(self.desktop.rect())
        if source_rect.width() < min_w or source_rect.height() < min_h:
            self.start = None
            self.end = None
            self.update()
            return
        crop = self.desktop.copy(source_rect)
        global_rect = source_rect.translated(self.virtual.topLeft())
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
    """Small non-interactive spinner shown while OCR/translation is running."""

    def __init__(self, image_global: QRect) -> None:
        super().__init__()
        self.angle = 0
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
        self.setFixedSize(34, 34)
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
        self.show()
        self.raise_()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        margin = 1
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 20, 205))
        p.drawEllipse(self.rect().adjusted(margin, margin, -margin, -margin))

        pen = QPen(QColor(248, 248, 248, 245), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(self.rect().adjusted(9, 9, -9, -9), self.angle * 16, 270 * 16)
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
    start = min(max_size, max(min_size, int(rect.height() * 0.58)))
    flags = int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for size in range(start, min_size - 1, -1):
        font.setPixelSize(size)
        metrics = QFontMetricsF(font)
        br = metrics.boundingRect(rect, flags, text)
        if br.height() <= rect.height() and br.width() <= rect.width() + 1:
            return QFont(font)
    font.setPixelSize(min_size)
    return font


def render_translation(original: QImage, result: dict[str, Any], cfg: dict[str, Any]) -> QImage:
    out = original.copy()
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    ov = cfg["overlay"]
    mask_alpha = max(0, min(255, int(ov["mask_alpha"])))
    min_size = int(ov["font_min_px"])
    max_size = int(ov["font_max_px"])
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
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_global = event.globalPosition().toPoint()
            self.window_start = self.overlay.pos()
            self.timer.start()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self.press_global is not None
            and self.window_start is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
            and self.timer.isValid()
            and self.timer.elapsed() >= self.overlay.drag_hold_ms
        ):
            delta = event.globalPosition().toPoint() - self.press_global
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

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.image = DraggableImage(self)
        self.image.setPixmap(QPixmap.fromImage(self.translated))
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

        union = image_global.united(toolbar_global)
        self.setGeometry(union)
        self.image.setGeometry(image_global.translated(-union.topLeft()))
        self.toolbar.setGeometry(toolbar_global.translated(-union.topLeft()))
        self.toolbar.raise_()

    def show_overlay(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def toggle_view(self) -> None:
        self.showing_translation = not self.showing_translation
        image = self.translated if self.showing_translation else self.original
        self.image.setPixmap(QPixmap.fromImage(image))

    def copy_source(self) -> None:
        QGuiApplication.clipboard().setText(self.source_text)

    def copy_translation(self) -> None:
        QGuiApplication.clipboard().setText(self.translated_text)

    def contains_global_point(self, point: QPoint) -> bool:
        origin = self.mapToGlobal(QPoint(0, 0))
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
        LOG.info("global hotkey=%s", hotkey_text)

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


class Controller(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.cfg = load_config()
        self.input = InputService(str(self.cfg["app"]["hotkey"]))
        self.input.hotkey_pressed.connect(self.trigger)
        self.input.mouse_pressed.connect(self.global_mouse_press)
        self.selector: Selector | None = None
        self.loading: LoadingWindow | None = None
        self.overlay: OverlayWindow | None = None
        self.worker: PipelineWorker | None = None
        self.pending_rect: QRect | None = None
        self.pending_image: QImage | None = None
        self.busy = False

        self.watcher = QFileSystemWatcher(self)
        self.watcher.addPath(str(CONFIG_PATH))
        self.watcher.fileChanged.connect(self.config_changed)

        app.aboutToQuit.connect(self.input.stop)
        app.aboutToQuit.connect(self.close_loading)
        LOG.info("started version=%s hotkey=%s", VERSION, self.cfg["app"]["hotkey"])

    def config_changed(self, _path: str) -> None:
        try:
            new_cfg = load_config()
            self.input.restart_hotkey(str(new_cfg["app"]["hotkey"]))
            self.cfg = new_cfg
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
            translated_image = render_translation(self.pending_image, result, self.cfg)
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
        print(f"X11: OK ({display})")
    else:
        print(f"X11: FAIL (XDG_SESSION_TYPE={session or 'unknown'}, DISPLAY={display or 'empty'})")
        critical += 1

    if PYNPUT_IMPORT_ERROR is None:
        print("全局输入监听(pynput): OK")
    else:
        print(f"全局输入监听(pynput): FAIL ({PYNPUT_IMPORT_ERROR})")
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

    backend = str(cfg["capture"].get("backend", "qt_x11"))
    if backend == "qt_x11":
        print("截图后端: OK (qt_x11)")
    else:
        print(f"截图后端: FAIL ({backend})")
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
    parser = argparse.ArgumentParser(description="KDE/X11 screenshot translation overlay")
    parser.add_argument("--check", action="store_true", help="检查本地运行环境，不调用外部翻译服务")
    parser.add_argument("--config-path", action="store_true", help="只打印配置文件路径")
    parser.add_argument("--keys-path", action="store_true", help="只打印密钥配置文件路径")
    parser.add_argument("--log-path", action="store_true", help="只打印日志文件路径")
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

    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland":
        print(f"{APP_NAME} {VERSION} 目前只支持 X11。", file=sys.stderr)
        return 2
    if not os.environ.get("DISPLAY"):
        print("没有 DISPLAY；需要在图形化 X11 会话中运行。", file=sys.stderr)
        return 2

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
