"""
Always-On-Top Desktop Companion Character & AI Chat Popup (PySide6).

Features:
- Always present on your Windows screen (frameless, transparent, stays on top)
- Cute built-in animated desktop pet (idle breathing, blinking, hover perk,
  thinking sparkles, talking bounce)
- Supports custom PNG / animated GIF / WebP character sprites (via Settings,
  right-click menu, --sprite flag, or drag-and-drop onto the character!)
- Customizable Character Name & Personality Prompt with presets
- Quick-access floating Chat Popup with live SSE/token streaming, tool call
  badges, Markdown formatting, and Stop/Clear controls
- System Tray icon + global Windows hotkey (Ctrl+Shift+Space) to summon/hide

Run:
    python desktop_companion.py
    python desktop_companion.py --provider nvidia
    python desktop_companion.py --sprite path/to/pet.gif
    python chatbot.py --desktop
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
from dataclasses import asdict, dataclass, field
import html
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional
import weakref

from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets

import chatbot
import system_tools


def _resolve_config_file() -> Path:
    app_dir = chatbot.get_app_dir()
    primary = app_dir / "character_config.json"
    if (
        not primary.exists()
        and getattr(sys, "frozen", False)
        and app_dir.name.lower() == "dist"
        and (app_dir.parent / "character_config.json").is_file()
    ):
        return app_dir.parent / "character_config.json"
    return primary


CONFIG_FILE = _resolve_config_file()
IMAGE_EXTENSIONS = {".png", ".gif", ".webp", ".jpg", ".jpeg", ".bmp"}
SINGLE_INSTANCE_NAME = "ai_desktop_companion_v1"
STARTUP_SHORTCUT_NAME = "AICharacterCompanion.lnk"

PERSONA_PRESETS: Dict[str, str] = {
    "Cute Desktop Pet": (
        "You are a cheerful, affectionate, playful little desktop companion who lives on the user's screen. "
        "Keep answers helpful, clear, and warm with occasional gentle charm, without being overly verbose."
    ),
    "Tech & Coding Buddy": (
        "You are a sharp, friendly engineering sidekick sitting on the user's desktop. "
        "Give concise, accurate technical help with clean code snippets and practical tips."
    ),
    "Concise Assistant": (
        "You are a calm, ultra-concise desktop assistant. Answer directly in short, clear Markdown bullet points."
    ),
    "Productivity Coach": (
        "You are an encouraging, organized focus partner. Help break tasks into clear next steps and keep momentum high."
    ),
}


# ============================================================
# CONFIG & MARKDOWN HELPERS
# ============================================================

@dataclass
class CharacterConfig:
    character_name: str = "Lumi"
    personality_prompt: str = PERSONA_PRESETS["Cute Desktop Pet"]
    sprite_path: str = ""
    character_size: int = 140
    opacity: float = 1.0
    provider: str = "gemini"
    model_name: str = ""
    thinking_level: str = "MEDIUM"
    temperature: float = 0.7
    use_tools: bool = True
    enable_system_tools: bool = False
    confirm_app_launch: bool = True
    allow_all_user_folders: bool = True
    allowed_folders: List[str] = field(default_factory=system_tools.default_allowed_dir_strings)
    hotkey_enabled: bool = True
    window_pos: Optional[List[int]] = None

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> "CharacterConfig":
        if not path.is_file():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in raw.items() if k in valid_fields}
            cfg = cls(**filtered)
            if cfg.model_name:
                cfg.model_name = chatbot.normalize_model_for_provider(cfg.provider, cfg.model_name)
            return cfg
        except Exception:
            return cls()

    def save(self, path: Path = CONFIG_FILE) -> None:
        try:
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except Exception:
            pass


def build_effective_system_prompt(
    name: str,
    personality: str,
    use_tools: bool,
    enable_system_tools: bool = False,
    allow_all_drives: bool = False,
) -> str:
    clean_name = (name or "Lumi").strip() or "Lumi"
    clean_persona = (personality or PERSONA_PRESETS["Cute Desktop Pet"]).strip()
    parts = [f"Your name is {clean_name}.", clean_persona]
    if use_tools:
        parts.append(
            "When the user asks about live web information, gold/silver prices in India, latest news, "
            "or the current date/time, call your available tools first and cite the real-time result honestly."
        )
    if enable_system_tools:
        parts.append(
            "You also have PC & File Control tools (search_files, list_drives, list_directory, get_folder_size, "
            "list_recycle_bin, read_text_file, create_item, copy_or_move, delete_item, clipboard_action, "
            "launch_app_or_file, list_running_apps, close_app). "
            "Use get_folder_size for storage or folder size questions, search or list paths first before moving or "
            "deleting, use list_running_apps/close_app when asked to close an app, never guess paths, and respect user confirmations."
        )
        if allow_all_drives:
            parts.append(
                "All-Drive Control is ON across all mounted drives (C:\\, D:\\, K:\\, etc., excluding protected OS "
                "and .env/.git folders). Call list_drives to discover drives or list_directory with paths like 'K:\\'."
            )
    return " ".join(parts)


def _format_inline_md(text: str) -> str:
    code_spans: List[str] = []
    escaped = html.escape(text)

    def _keep_code(m: re.Match[str]) -> str:
        idx = len(code_spans)
        code_spans.append(
            f"<code style='background:#1e293b;color:#38bdf8;padding:1px 4px;"
            f"border-radius:4px;font-family:Consolas,monospace;'>{m.group(1)}</code>"
        )
        return f"\x00CODE{idx}\x00"

    escaped = re.sub(r"`([^`]+)`", _keep_code, escaped)

    def _link_repl(m: re.Match[str]) -> str:
        label, url = m.group(1), m.group(2).strip()
        if re.match(r"^(https?://|/)", url, re.IGNORECASE):
            return f"<a href='{url}' style='color:#38bdf8;'>{label}</a>"
        return label

    escaped = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _link_repl, escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"__([^_]+)__", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"<i>\1</i>", escaped)
    escaped = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"<i>\1</i>", escaped)

    for idx, snippet in enumerate(code_spans):
        escaped = escaped.replace(f"\x00CODE{idx}\x00", snippet)
    return escaped


def markdown_to_qt_html(md_text: str) -> str:
    """Convert Markdown text safely to Qt-compatible rich HTML."""
    lines = (md_text or "").replace("\r\n", "\n").split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        start_i = i
        line = lines[i]
        fence = re.match(r"^```(.*)$", line)
        if fence:
            code_lines: List[str] = []
            i += 1
            while i < len(lines) and not re.match(r"^```\s*$", lines[i]):
                code_lines.append(html.escape(lines[i]))
                i += 1
            if i < len(lines):
                i += 1
            out.append(
                "<pre style='background:#090d14;color:#e2e8f0;padding:8px 10px;"
                "border-radius:6px;font-family:Consolas,monospace;font-size:12px;"
                "white-space:pre-wrap;'>" + "\n".join(code_lines) + "</pre>"
            )
            continue

        if not line.strip():
            i += 1
            continue

        h = re.match(r"^(#{1,3})\s+(.*)$", line)
        if h:
            lvl = len(h.group(1))
            size = {1: "16px", 2: "14px", 3: "13px"}[lvl]
            content_html = _format_inline_md(h.group(2).strip()) or "&nbsp;"
            out.append(f"<p style='font-size:{size};font-weight:700;margin:6px 0 3px;'>{content_html}</p>")
            i += 1
            continue

        if re.match(r"^\s*[-*+]\s+", line):
            items: List[str] = []
            while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(f"<li>{_format_inline_md(re.sub(r'^\s*[-*+]\s+', '', lines[i]))}</li>")
                i += 1
            out.append("<ul style='margin:4px 0;padding-left:18px;'>" + "".join(items) + "</ul>")
            continue

        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(f"<li>{_format_inline_md(re.sub(r'^\s*\d+\.\s+', '', lines[i]))}</li>")
                i += 1
            out.append("<ol style='margin:4px 0;padding-left:18px;'>" + "".join(items) + "</ol>")
            continue

        para: List[str] = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not re.match(r"^```", lines[i])
            and not re.match(r"^#{1,3}\s+", lines[i])
            and not re.match(r"^\s*[-*+]\s+", lines[i])
            and not re.match(r"^\s*\d+\.\s+", lines[i])
        ):
            para.append(_format_inline_md(lines[i]))
            i += 1
        if para:
            out.append("<p style='margin:0 0 6px;'>" + "<br/>".join(para) + "</p>")
        if i == start_i:
            out.append(f"<p style='margin:0 0 6px;'>{_format_inline_md(lines[i])}</p>")
            i += 1

    return "".join(out) or "<i>...</i>"


# ============================================================
# WINDOWS GLOBAL HOTKEY FILTER (Ctrl+Shift+Space)
# ============================================================

class WindowsHotkeyFilter(QtCore.QAbstractNativeEventFilter):
    WM_HOTKEY = 0x0312
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_NOREPEAT = 0x4000
    VK_SPACE = 0x20
    HOTKEY_ID = 0x4C55

    def __init__(self, on_trigger):
        super().__init__()
        self._on_trigger = on_trigger
        self._registered = False

    def register(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            ok = bool(
                ctypes.windll.user32.RegisterHotKey(
                    None,
                    self.HOTKEY_ID,
                    self.MOD_CONTROL | self.MOD_SHIFT | self.MOD_NOREPEAT,
                    self.VK_SPACE,
                )
            )
            self._registered = ok
            return ok
        except Exception:
            return False

    def unregister(self) -> None:
        if self._registered and sys.platform == "win32":
            try:
                ctypes.windll.user32.UnregisterHotKey(None, self.HOTKEY_ID)
            except Exception:
                pass
            self._registered = False

    def nativeEventFilter(self, eventType, message):  # noqa: N802
        if self._registered and sys.platform == "win32":
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == self.WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                    QtCore.QTimer.singleShot(0, self._on_trigger)
                    return True, 0
            except Exception:
                pass
        return False, 0


# ============================================================
# SINGLE-INSTANCE GUARD & WINDOWS STARTUP SHORTCUT HELPERS
# ============================================================

def resolve_pythonw_executable() -> Path:
    """Prefer project .venv pythonw.exe, then sibling pythonw.exe, else sys.executable."""
    project_venv_pyw = Path(__file__).resolve().parent / ".venv" / "Scripts" / "pythonw.exe"
    if project_venv_pyw.is_file():
        return project_venv_pyw
    exe = Path(sys.executable)
    sibling_pyw = exe.with_name("pythonw.exe")
    if sibling_pyw.is_file():
        return sibling_pyw
    return exe


def get_startup_shortcut_path(startup_dir: Optional[Path] = None) -> Path:
    if startup_dir is not None:
        return startup_dir / STARTUP_SHORTCUT_NAME
    appdata = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / STARTUP_SHORTCUT_NAME


def is_startup_enabled(startup_dir: Optional[Path] = None) -> bool:
    return get_startup_shortcut_path(startup_dir).is_file()


def create_windows_shortcut(
    shortcut_path: Path,
    target_exe: Path,
    arguments: str,
    working_dir: Path,
    description: str = "",
    icon_path: Optional[Path] = None,
) -> bool:
    """Create a Windows .lnk shortcut via WScript.Shell without extra packages."""
    if sys.platform != "win32":
        return False
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["_SC_PATH"] = str(shortcut_path)
    env["_SC_TARGET"] = str(target_exe)
    env["_SC_ARGS"] = arguments
    env["_SC_WORKDIR"] = str(working_dir)
    env["_SC_DESC"] = description
    env["_SC_ICON"] = str(icon_path) if icon_path and icon_path.is_file() else ""
    ps_script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$sc = $ws.CreateShortcut($env:_SC_PATH); "
        "$sc.TargetPath = $env:_SC_TARGET; "
        "$sc.Arguments = $env:_SC_ARGS; "
        "$sc.WorkingDirectory = $env:_SC_WORKDIR; "
        "$sc.Description = $env:_SC_DESC; "
        "if ($env:_SC_ICON) { $sc.IconLocation = $env:_SC_ICON }; "
        "$sc.Save()"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            env=env,
            capture_output=True,
            timeout=10,
            check=False,
        )
        return res.returncode == 0 and shortcut_path.is_file()
    except Exception:
        return False


def get_launch_target() -> tuple[Path, str, Path]:
    """Return (target_exe, arguments, working_dir) for Windows shortcuts."""
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        return exe_path, "", exe_path.parent
    script_path = Path(__file__).resolve()
    return resolve_pythonw_executable(), f'"{script_path}"', script_path.parent


def set_startup_enabled(enabled: bool, startup_dir: Optional[Path] = None) -> bool:
    shortcut = get_startup_shortcut_path(startup_dir)
    if not enabled:
        try:
            if shortcut.is_file():
                shortcut.unlink()
            return True
        except Exception:
            return False

    target_exe, arguments, working_dir = get_launch_target()
    bundled_icon = chatbot.get_bundle_dir() / "assets" / "app_icon.ico"
    local_icon = chatbot.get_app_dir() / "assets" / "app_icon.ico"
    icon_path = local_icon if local_icon.is_file() else (bundled_icon if bundled_icon.is_file() else None)
    return create_windows_shortcut(
        shortcut_path=shortcut,
        target_exe=target_exe,
        arguments=arguments,
        working_dir=working_dir,
        description="Always-on-screen Desktop AI Character Companion",
        icon_path=icon_path,
    )


def notify_running_instance(server_name: str = SINGLE_INSTANCE_NAME) -> bool:
    """If an instance is already listening, ask it to show itself and return True."""
    sock = QtNetwork.QLocalSocket()
    sock.connectToServer(server_name)
    if not sock.waitForConnected(250):
        return False
    sock.write(b"SHOW\n")
    sock.flush()
    sock.waitForBytesWritten(200)
    sock.disconnectFromServer()
    return True


class SingleInstanceGuard(QtCore.QObject):
    activated = QtCore.Signal()

    def __init__(self, server_name: str = SINGLE_INSTANCE_NAME):
        super().__init__()
        self._server_name = server_name
        self._server = QtNetwork.QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)

    def start_listening(self) -> bool:
        if not self._server.listen(self._server_name):
            # Remove stale socket from an unclean crash and retry once
            QtNetwork.QLocalServer.removeServer(self._server_name)
            return self._server.listen(self._server_name)
        return True

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            if conn is not None:
                conn.waitForReadyRead(100)
                conn.close()
                conn.deleteLater()
                self.activated.emit()

    def close(self) -> None:
        self._server.close()


# ============================================================
# BACKGROUND STREAM WORKER
# ============================================================

class StreamWorker(QtCore.QObject):
    token_received = QtCore.Signal(str)
    thought_received = QtCore.Signal(str)
    tool_started = QtCore.Signal(str, str)
    tool_finished = QtCore.Signal(str, str)
    error_received = QtCore.Signal(str)
    finished = QtCore.Signal(str)

    def __init__(self, bot: chatbot.Chatbot, lock: threading.Lock, prompt: str):
        super().__init__()
        self._bot = bot
        self._lock = lock
        self._prompt = prompt
        self.cancel_event = threading.Event()

    @QtCore.Slot()
    def run(self) -> None:
        final_text = ""
        with self._lock:
            try:
                for ev in self._bot.stream_turn(self._prompt, cancel_event=self.cancel_event):
                    etype = ev.get("type")
                    if etype == "token":
                        chunk = ev.get("content", "")
                        final_text += chunk
                        self.token_received.emit(chunk)
                    elif etype == "thought":
                        self.thought_received.emit(ev.get("content", ""))
                    elif etype == "tool_start":
                        args_txt = json.dumps(ev.get("args") or {})
                        self.tool_started.emit(ev.get("name", "tool"), args_txt)
                    elif etype == "tool_end":
                        self.tool_finished.emit(ev.get("name", "tool"), ev.get("result", ""))
                    elif etype == "error":
                        self.error_received.emit(ev.get("message", "Unknown error"))
                    elif etype == "done":
                        if ev.get("content"):
                            final_text = ev["content"]
            except Exception as exc:
                self.error_received.emit(str(exc))
        self.finished.emit(final_text)


# ============================================================
# ALWAYS-ON-SCREEN CHARACTER WIDGET
# ============================================================

def draw_pet_pixmap(size: int = 64, sprite_path: str = "") -> QtGui.QPixmap:
    """Create a small avatar pixmap (custom sprite thumbnail or default pet)."""
    if sprite_path and Path(sprite_path).is_file():
        pm = QtGui.QPixmap(sprite_path)
        if not pm.isNull():
            return pm.scaled(
                size,
                size,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )

    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    _paint_cute_pet(p, QtCore.QRectF(4, 4, size - 8, size - 8), phase=0.0, state="idle", blinking=False, look_x=0.0, look_y=0.0)
    p.end()
    return pm


def _paint_cute_pet(
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    phase: float,
    state: str,
    blinking: bool,
    look_x: float,
    look_y: float,
) -> None:
    """Paint the built-in cute animated desktop pet inside `bounds`."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    # Ground shadow
    shadow_scale = 0.75 if state in ("talking", "happy") else 1.0
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(0, 0, 0, 55))
    p.drawEllipse(QtCore.QPointF(cx, bounds.bottom() - h * 0.06), w * 0.31 * shadow_scale, h * 0.07)

    # Body dimensions
    bw = w * 0.68
    bh = h * 0.62
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.04

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.5) * 6.0)
        p.translate(-cx, -cy)

    # Cute cat/spirit ears
    ear_grad = QtGui.QLinearGradient(bx, by - bh * 0.25, bx, by + bh * 0.3)
    ear_grad.setColorAt(0.0, QtGui.QColor("#38bdf8"))
    ear_grad.setColorAt(1.0, QtGui.QColor("#2563eb"))
    p.setBrush(ear_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))

    left_ear = QtGui.QPolygonF([
        QtCore.QPointF(bx + bw * 0.10, by + bh * 0.26),
        QtCore.QPointF(bx + bw * 0.16, by - bh * 0.16),
        QtCore.QPointF(bx + bw * 0.39, by + bh * 0.08),
    ])
    right_ear = QtGui.QPolygonF([
        QtCore.QPointF(bx + bw * 0.90, by + bh * 0.26),
        QtCore.QPointF(bx + bw * 0.84, by - bh * 0.16),
        QtCore.QPointF(bx + bw * 0.61, by + bh * 0.08),
    ])
    p.drawPolygon(left_ear)
    p.drawPolygon(right_ear)

    # Inner pink ears
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#fda4af"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(bx + bw * 0.16, by + bh * 0.20),
        QtCore.QPointF(bx + bw * 0.19, by - bh * 0.06),
        QtCore.QPointF(bx + bw * 0.33, by + bh * 0.09),
    ]))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(bx + bw * 0.84, by + bh * 0.20),
        QtCore.QPointF(bx + bw * 0.81, by - bh * 0.06),
        QtCore.QPointF(bx + bw * 0.67, by + bh * 0.09),
    ]))

    # Main plush rounded body
    body_grad = QtGui.QRadialGradient(cx - bw * 0.16, by + bh * 0.25, bw * 0.72)
    body_grad.setColorAt(0.0, QtGui.QColor("#7dd3fc"))
    body_grad.setColorAt(0.55, QtGui.QColor("#38bdf8"))
    body_grad.setColorAt(1.0, QtGui.QColor("#1d4ed8"))
    p.setBrush(body_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025)))
    p.drawRoundedRect(QtCore.QRectF(bx, by, bw, bh), bw * 0.44, bh * 0.46)

    # Forehead highlight
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(255, 255, 255, 70))
    p.drawEllipse(QtCore.QRectF(bx + bw * 0.22, by + bh * 0.08, bw * 0.38, bh * 0.16))

    # Belly patch
    p.setBrush(QtGui.QColor(240, 249, 255, 210))
    p.drawEllipse(QtCore.QRectF(cx - bw * 0.27, by + bh * 0.56, bw * 0.54, bh * 0.36))

    # Rosy cheeks
    p.setBrush(QtGui.QColor(251, 113, 133, 165))
    p.drawEllipse(QtCore.QPointF(cx - bw * 0.28, by + bh * 0.52), bw * 0.08, bh * 0.055)
    p.drawEllipse(QtCore.QPointF(cx + bw * 0.28, by + bh * 0.52), bw * 0.08, bh * 0.055)

    # Eyes
    eye_y = by + bh * 0.40
    eye_dx = bw * 0.19
    eye_r = bw * 0.075
    ox = look_x * bw * 0.03
    oy = look_y * bh * 0.03

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.024), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r), 0, 180 * 16)
    elif state == "happy":
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.026), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.5, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.5, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + ox
            ey = eye_y + oy
            p.setBrush(QtGui.QColor("#0f172a"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.12)
            # Glossy catchlights
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.32, ey - eye_r * 0.35), eye_r * 0.34, eye_r * 0.34)
            p.drawEllipse(QtCore.QPointF(ex + eye_r * 0.25, ey + eye_r * 0.30), eye_r * 0.16, eye_r * 0.16)

    # Mouth
    mouth_y = by + bh * 0.53
    if state == "talking":
        open_h = bh * (0.06 + 0.045 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(1.8, w * 0.02)))
        p.setBrush(QtGui.QColor("#fb7185"))
        p.drawEllipse(QtCore.QPointF(cx, mouth_y + open_h * 0.25), bw * 0.065, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(cx - bw * 0.08, mouth_y - bh * 0.03, bw * 0.08, bh * 0.08), 190 * 16, 160 * 16)
        p.drawArc(QtCore.QRectF(cx, mouth_y - bh * 0.03, bw * 0.08, bh * 0.08), 190 * 16, 160 * 16)

    # Little paws
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))
    p.setBrush(QtGui.QColor("#bae6fd"))
    paw_wave = math.sin(phase * 10.0) * h * 0.035 if state in ("happy", "talking") else 0.0
    p.drawEllipse(QtCore.QPointF(bx + bw * 0.14, by + bh * 0.78 - paw_wave), bw * 0.09, bh * 0.08)
    p.drawEllipse(QtCore.QPointF(bx + bw * 0.86, by + bh * 0.78 + paw_wave), bw * 0.09, bh * 0.08)

    p.restore()

    # Thinking indicator dots above head
    if state == "thinking":
        for idx in range(3):
            bounce = math.sin(phase * 6.0 - idx * 0.9) * h * 0.025
            dx = cx - w * 0.11 + idx * w * 0.11
            dy = bounds.top() + h * 0.11 + bounce
            p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), 1.5))
            p.setBrush(QtGui.QColor("#fde047"))
            p.drawEllipse(QtCore.QPointF(dx, dy), w * 0.04, w * 0.04)


class CharacterWidget(QtWidgets.QWidget):
    clicked = QtCore.Signal()
    moved = QtCore.Signal(int, int)
    sprite_dropped = QtCore.Signal(str)
    size_change_requested = QtCore.Signal(int)
    open_settings_requested = QtCore.Signal()
    clear_chat_requested = QtCore.Signal()
    provider_change_requested = QtCore.Signal(str)
    system_tools_toggled = QtCore.Signal(bool)
    all_drives_toggled = QtCore.Signal(bool)
    reset_pos_requested = QtCore.Signal()
    hide_requested = QtCore.Signal()
    quit_requested = QtCore.Signal()

    def __init__(self, config: CharacterConfig):
        super().__init__(
            None,
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool,
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        self._config = config
        self._state = "idle"  # idle | hover | thinking | talking | happy
        self._phase = 0.0
        self._blinking = False
        self._next_blink_ticks = 90
        self._happy_ticks = 0
        self._look_x = 0.0
        self._look_y = 0.0
        self._drag_origin: Optional[QtCore.QPoint] = None
        self._press_global: Optional[QtCore.QPoint] = None
        self._dragging = False

        self._pixmap: Optional[QtGui.QPixmap] = None
        self._movie: Optional[QtGui.QMovie] = None
        self._speech_text: str = ""
        self._speech_ticks = 0

        self._anim_timer = QtCore.QTimer(self)
        self._anim_timer.timeout.connect(self._on_tick)
        self._anim_timer.start(33)

        self.apply_config(config)

    def apply_config(self, config: CharacterConfig) -> None:
        self._config = config
        size = max(40, min(260, int(config.character_size)))
        margin = 16
        self.setFixedSize(size + margin, size + margin + 18)
        self.setWindowOpacity(max(0.4, min(1.0, float(config.opacity))))
        self.setToolTip(
            f"{config.character_name} — Click to chat, drag to move, scroll wheel to resize, right-click for menu"
        )
        self._load_sprite(config.sprite_path)
        self.update()

    def _load_sprite(self, path_str: str) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None
        self._pixmap = None

        if not path_str:
            return
        p = Path(path_str)
        if not p.is_file():
            return

        reader = QtGui.QImageReader(str(p))
        if reader.supportsAnimation() and (reader.imageCount() > 1 or p.suffix.lower() == ".gif"):
            movie = QtGui.QMovie(str(p))
            if movie.isValid():
                movie.frameChanged.connect(lambda _: self.update())
                movie.start()
                self._movie = movie
                return

        pm = QtGui.QPixmap(str(p))
        if not pm.isNull():
            self._pixmap = pm

    def set_state(self, state: str) -> None:
        self._state = state
        if state == "happy":
            self._happy_ticks = 32
        self.update()

    def show_speech_bubble(self, text: str, duration_ms: int = 4500) -> None:
        cleaned = " ".join((text or "").split())
        if len(cleaned) > 95:
            cleaned = cleaned[:92] + "..."
        self._speech_text = cleaned
        self._speech_ticks = max(1, duration_ms // 33)
        self.update()

    def _on_tick(self) -> None:
        self._phase += 0.08
        if self._happy_ticks > 0:
            self._happy_ticks -= 1
            if self._happy_ticks == 0 and self._state == "happy":
                self._state = "idle"
        if self._speech_ticks > 0:
            self._speech_ticks -= 1
            if self._speech_ticks == 0:
                self._speech_text = ""

        self._next_blink_ticks -= 1
        if self._next_blink_ticks <= 0:
            if self._blinking:
                self._blinking = False
                self._next_blink_ticks = random.randint(70, 160)
            else:
                self._blinking = True
                self._next_blink_ticks = 4
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        size = max(40, min(260, int(self._config.character_size)))
        amp = max(1.5, size * 0.025)
        bob = math.sin(self._phase * (2.6 if self._state in ("talking", "happy") else 1.1)) * (
            amp * 1.6 if self._state in ("talking", "happy") else amp
        )
        hop = -abs(math.sin(self._phase * 4.5)) * max(4.0, size * 0.08) if self._state == "happy" else 0.0

        top_offset = 14.0 + bob + hop
        char_rect = QtCore.QRectF((w - size) / 2.0, top_offset, size, size)

        if self._movie is not None:
            frame = self._movie.currentPixmap()
            if not frame.isNull():
                scaled = frame.scaled(
                    size,
                    size,
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                x = char_rect.x() + (size - scaled.width()) / 2.0
                y = char_rect.y() + (size - scaled.height()) / 2.0
                p.drawPixmap(QtCore.QPointF(x, y), scaled)
        elif self._pixmap is not None:
            scaled = self._pixmap.scaled(
                size,
                size,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            x = char_rect.x() + (size - scaled.width()) / 2.0
            y = char_rect.y() + (size - scaled.height()) / 2.0
            p.drawPixmap(QtCore.QPointF(x, y), scaled)
        else:
            _paint_cute_pet(
                p,
                char_rect,
                phase=self._phase,
                state=self._state,
                blinking=self._blinking,
                look_x=self._look_x,
                look_y=self._look_y,
            )

        # Mini speech bubble overlay if active (tooltip fallback when character is tiny)
        if self._speech_text and w >= 115:
            font = QtGui.QFont("Segoe UI", 8)
            font.setBold(True)
            p.setFont(font)
            fm = QtGui.QFontMetrics(font)
            text_rect = fm.boundingRect(
                QtCore.QRect(0, 0, w - 16, 48),
                QtCore.Qt.TextFlag.TextWordWrap,
                self._speech_text,
            )
            bw = min(w - 8, text_rect.width() + 16)
            bh = text_rect.height() + 10
            bubble_rect = QtCore.QRectF((w - bw) / 2.0, 2.0, bw, bh)
            p.setPen(QtGui.QPen(QtGui.QColor("#38bdf8"), 1.2))
            p.setBrush(QtGui.QColor(15, 23, 42, 235))
            p.drawRoundedRect(bubble_rect, 8, 8)
            p.setPen(QtGui.QColor("#f8fafc"))
            p.drawText(
                bubble_rect.adjusted(6, 3, -6, -3),
                QtCore.Qt.AlignmentFlag.AlignCenter | QtCore.Qt.TextFlag.TextWordWrap,
                self._speech_text,
            )
        p.end()

    def enterEvent(self, event: QtGui.QEnterEvent) -> None:  # noqa: N802
        if self._state == "idle":
            self._state = "hover"
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:  # noqa: N802
        if self._state == "hover":
            self._state = "idle"
        self._look_x = 0.0
        self._look_y = 0.0
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            gpos = event.globalPosition().toPoint()
            self._press_global = gpos
            self._drag_origin = gpos - self.frameGeometry().topLeft()
            self._dragging = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        center = self.rect().center()
        pos = event.position()
        self._look_x = max(-1.0, min(1.0, (pos.x() - center.x()) / max(1.0, self.width() / 2)))
        self._look_y = max(-1.0, min(1.0, (pos.y() - center.y()) / max(1.0, self.height() / 2)))

        if self._drag_origin is not None and (event.buttons() & QtCore.Qt.MouseButton.LeftButton):
            gpos = event.globalPosition().toPoint()
            if self._press_global is not None and (gpos - self._press_global).manhattanLength() > 6:
                self._dragging = True
            if self._dragging:
                target = gpos - self._drag_origin
                self.move(target)
                self.moved.emit(target.x(), target.y())
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            was_dragging = self._dragging
            self._drag_origin = None
            self._press_global = None
            self._dragging = False
            if not was_dragging:
                self.set_state("happy")
                self.clicked.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: N802
        dy = event.angleDelta().y()
        if dy != 0:
            step = 8 if dy > 0 else -8
            current = max(40, min(260, int(self._config.character_size)))
            new_size = max(40, min(260, current + step))
            if new_size != current:
                self.size_change_requested.emit(new_size)
            event.accept()
            return
        super().wheelEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:  # noqa: N802
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#111827;color:#e5e7eb;border:1px solid #334155;padding:4px;}"
            "QMenu::item{padding:6px 14px;border-radius:4px;}"
            "QMenu::item:selected{background:#2563eb;}"
        )
        act_chat = menu.addAction(f"Chat with {self._config.character_name}")
        act_customize = menu.addAction("Customize Character & Persona...")
        act_sprite = menu.addAction("Choose Sprite Image / GIF...")

        size_menu = menu.addMenu("Character Size")
        for preset_sz, label in [
            (48, "Tiny (48 px)"),
            (72, "Small (72 px)"),
            (104, "Medium (104 px)"),
            (140, "Large (140 px)"),
            (180, "Extra Large (180 px)"),
        ]:
            sa = size_menu.addAction(label)
            sa.setCheckable(True)
            sa.setChecked(abs(int(self._config.character_size) - preset_sz) <= 6)
            sa.triggered.connect(lambda _=False, s=preset_sz: self.size_change_requested.emit(s))

        act_clear_chat = menu.addAction("Clear Conversation")
        act_sys_tools = menu.addAction("PC & File Control Tools")
        act_sys_tools.setCheckable(True)
        act_sys_tools.setChecked(self._config.enable_system_tools)
        act_all_drives = menu.addAction("Control All Drives (Full PC)")
        act_all_drives.setCheckable(True)
        act_all_drives.setChecked(self._config.allow_all_user_folders)
        menu.addSeparator()

        prov_menu = menu.addMenu("Switch Provider")
        for pid, spec in chatbot.PROVIDER_SPECS.items():
            a = prov_menu.addAction(spec["label"])
            a.setCheckable(True)
            a.setChecked(self._config.provider == pid)
            a.triggered.connect(lambda _=False, p=pid: self.provider_change_requested.emit(p))

        act_reset = menu.addAction("Reset Position")
        act_hide = menu.addAction("Hide to Tray")
        menu.addSeparator()
        act_quit = menu.addAction("Quit")

        chosen = menu.exec(event.globalPos())
        if chosen == act_chat:
            self.clicked.emit()
        elif chosen == act_customize:
            self.open_settings_requested.emit()
        elif chosen == act_sprite:
            self._browse_sprite()
        elif chosen == act_clear_chat:
            self.clear_chat_requested.emit()
        elif chosen == act_sys_tools:
            self.system_tools_toggled.emit(act_sys_tools.isChecked())
        elif chosen == act_all_drives:
            self.all_drives_toggled.emit(act_all_drives.isChecked())
        elif chosen == act_reset:
            self.reset_pos_requested.emit()
        elif chosen == act_hide:
            self.hide_requested.emit()
        elif chosen == act_quit:
            self.quit_requested.emit()

    def _browse_sprite(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose Character Image or GIF",
            "",
            "Images (*.png *.gif *.webp *.jpg *.jpeg *.bmp)",
        )
        if file_path:
            self.sprite_dropped.emit(file_path)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in IMAGE_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if url.isLocalFile():
                local = url.toLocalFile()
                if Path(local).suffix.lower() in IMAGE_EXTENSIONS:
                    self.sprite_dropped.emit(local)
                    event.acceptProposedAction()
                    return
        event.ignore()


# ============================================================
# CHAT POPUP DRAWER
# ============================================================

class PromptInputBox(QtWidgets.QPlainTextEdit):
    submit_requested = QtCore.Signal()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            if not (event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier):
                event.accept()
                self.submit_requested.emit()
                return
        super().keyPressEvent(event)


class ChatPopupWindow(QtWidgets.QWidget):
    send_message = QtCore.Signal(str)
    stop_requested = QtCore.Signal()
    clear_requested = QtCore.Signal()
    settings_requested = QtCore.Signal()
    mock_mode_requested = QtCore.Signal()
    provider_switch_requested = QtCore.Signal(str, str)

    def __init__(self, config: CharacterConfig):
        super().__init__(
            None,
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool,
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(410, 520)

        self._config = config
        self._pinned = False
        self._drag_offset: Optional[QtCore.QPoint] = None
        self._streaming_bubble: Optional[QtWidgets.QTextBrowser] = None
        self._streaming_text = ""

        self._build_ui()
        self.apply_config(config)

    def _build_ui(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._frame = QtWidgets.QFrame()
        self._frame.setObjectName("popupFrame")
        self._frame.setStyleSheet(
            """
            #popupFrame {
                background: #0f172a;
                border: 1.5px solid #334155;
                border-radius: 14px;
            }
            QLabel { color: #e2e8f0; }
            QPushButton {
                background: #1e293b;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 7px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover { background: #334155; }
            QPushButton#sendBtn {
                background: #2563eb;
                border: none;
                color: #ffffff;
                padding: 7px 14px;
                font-size: 12px;
            }
            QPushButton#sendBtn:hover { background: #1d4ed8; }
            QPushButton#stopBtn {
                background: #dc2626;
                border: none;
                color: #ffffff;
                padding: 7px 14px;
                font-size: 12px;
            }
            QPlainTextEdit {
                background: #111827;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 8px;
                font-size: 13px;
            }
            QScrollArea { border: none; background: transparent; }
            """
        )
        outer.addWidget(self._frame)

        root = QtWidgets.QVBoxLayout(self._frame)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        # Header
        self._header = QtWidgets.QWidget()
        self._header.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
        hbox = QtWidgets.QHBoxLayout(self._header)
        hbox.setContentsMargins(0, 0, 0, 4)
        hbox.setSpacing(8)

        self._avatar_lbl = QtWidgets.QLabel()
        self._avatar_lbl.setFixedSize(34, 34)
        hbox.addWidget(self._avatar_lbl)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(0)
        self._name_lbl = QtWidgets.QLabel("Lumi")
        self._name_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        self._status_lbl = QtWidgets.QLabel("Ready")
        self._status_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        self._status_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        title_col.addWidget(self._name_lbl)
        title_col.addWidget(self._status_lbl)
        hbox.addLayout(title_col, 1)

        self._pin_btn = QtWidgets.QPushButton("Pin")
        self._pin_btn.setCheckable(True)
        self._pin_btn.setToolTip("Keep window open")
        self._pin_btn.toggled.connect(self._on_pin_toggled)
        hbox.addWidget(self._pin_btn)

        settings_btn = QtWidgets.QPushButton("Edit")
        settings_btn.setToolTip("Customize character name, size & persona")
        settings_btn.clicked.connect(self.settings_requested.emit)
        hbox.addWidget(settings_btn)

        clear_btn = QtWidgets.QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_requested.emit)
        hbox.addWidget(clear_btn)

        close_btn = QtWidgets.QPushButton("×")
        close_btn.setFixedWidth(28)
        close_btn.clicked.connect(self.hide)
        hbox.addWidget(close_btn)
        root.addWidget(self._header)

        # Missing API key banner
        self._key_banner = QtWidgets.QFrame()
        self._key_banner.setStyleSheet(
            "QFrame{background:#451a03;border:1px solid #d97706;border-radius:8px;}"
            "QLabel{color:#fde68a;font-size:11px;border:none;background:transparent;}"
        )
        b_row = QtWidgets.QHBoxLayout(self._key_banner)
        b_row.setContentsMargins(8, 5, 8, 5)
        b_row.setSpacing(6)
        self._key_banner_lbl = QtWidgets.QLabel("API key not set.")
        self._key_banner_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        add_key_btn = QtWidgets.QPushButton("Add Key")
        add_key_btn.clicked.connect(self.settings_requested.emit)
        ollama_btn = QtWidgets.QPushButton("Free Ollama")
        ollama_btn.setToolTip("Use unlimited local Ollama models without any API key")
        ollama_btn.clicked.connect(lambda: self.provider_switch_requested.emit("ollama", ""))
        mock_btn = QtWidgets.QPushButton("Mock")
        mock_btn.clicked.connect(self.mock_mode_requested.emit)
        b_row.addWidget(self._key_banner_lbl, 1)
        b_row.addWidget(add_key_btn)
        b_row.addWidget(ollama_btn)
        b_row.addWidget(mock_btn)
        self._key_banner.setVisible(False)
        root.addWidget(self._key_banner)

        # Free quota / 429 fallback banner
        self._quota_banner = QtWidgets.QFrame()
        self._quota_banner.setStyleSheet(
            "QFrame{background:#172554;border:1px solid #3b82f6;border-radius:8px;}"
            "QLabel{color:#bfdbfe;font-size:11px;border:none;background:transparent;}"
        )
        q_col = QtWidgets.QVBoxLayout(self._quota_banner)
        q_col.setContentsMargins(8, 6, 8, 6)
        q_col.setSpacing(5)
        self._quota_lbl = QtWidgets.QLabel(
            "Rate limit or quota reached. Switch to a free option:"
        )
        q_btn_row = QtWidgets.QHBoxLayout()
        q_btn_row.setSpacing(5)
        q_ollama_btn = QtWidgets.QPushButton("Ollama (Free Local)")
        q_ollama_btn.clicked.connect(lambda: self._switch_from_quota("ollama", ""))
        q_lite_btn = QtWidgets.QPushButton("Flash-Lite (500/day)")
        q_lite_btn.clicked.connect(lambda: self._switch_from_quota("gemini", "gemini-3.5-flash-lite"))
        q_nvidia_btn = QtWidgets.QPushButton("NVIDIA NIM")
        q_nvidia_btn.clicked.connect(lambda: self._switch_from_quota("nvidia", ""))
        q_btn_row.addWidget(q_ollama_btn)
        q_btn_row.addWidget(q_lite_btn)
        q_btn_row.addWidget(q_nvidia_btn)
        q_col.addWidget(self._quota_lbl)
        q_col.addLayout(q_btn_row)
        self._quota_banner.setVisible(False)
        root.addWidget(self._quota_banner)

        # Chat messages scroll area
        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._msg_container = QtWidgets.QWidget()
        self._msg_container.setStyleSheet("background: transparent;")
        self._msg_layout = QtWidgets.QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(2, 4, 2, 4)
        self._msg_layout.setSpacing(8)
        self._msg_layout.addStretch(1)
        self._scroll.setWidget(self._msg_container)
        root.addWidget(self._scroll, 1)

        self._scroll_timer = QtCore.QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(10)
        self._scroll_timer.timeout.connect(self._do_scroll_to_bottom)

        self._render_timer = QtCore.QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(40)
        self._render_timer.timeout.connect(self._flush_streaming_markdown)

        # Quick suggestion chips
        chips_row = QtWidgets.QHBoxLayout()
        chips_row.setSpacing(6)
        self._files_chip: Optional[QtWidgets.QPushButton] = None
        for label, prompt in [
            ("Web Search", "Search the web for the latest tech breakthroughs today."),
            ("Gold Rate", "What is today's gold rate in India?"),
            ("Latest News", "What is the latest tech news?"),
            ("Time", "What date and time is it?"),
            ("Files", "List all my PC drives and allowed folders."),
        ]:
            btn = QtWidgets.QPushButton(label)
            btn.setStyleSheet(
                "QPushButton{background:#162033;color:#93c5fd;border:1px solid #1e3a8a;"
                "border-radius:12px;padding:3px 9px;font-size:11px;}"
                "QPushButton:hover{background:#1e3a8a;color:#fff;}"
            )
            btn.clicked.connect(lambda _=False, p=prompt: self._submit_text(p))
            chips_row.addWidget(btn)
            if label == "Files":
                btn.setVisible(bool(self._config.enable_system_tools))
                self._files_chip = btn
        chips_row.addStretch(1)
        root.addLayout(chips_row)

        # Input row
        input_row = QtWidgets.QHBoxLayout()
        input_row.setSpacing(8)
        self._input = PromptInputBox()
        self._input.setFixedHeight(62)
        self._input.setPlaceholderText("Ask anything... (Enter to send, Shift+Enter newline)")
        self._input.submit_requested.connect(self._on_send_clicked)
        input_row.addWidget(self._input, 1)

        self._send_btn = QtWidgets.QPushButton("Send")
        self._send_btn.setObjectName("sendBtn")
        self._send_btn.clicked.connect(self._on_send_clicked)
        input_row.addWidget(self._send_btn)

        self._stop_btn = QtWidgets.QPushButton("Stop")
        self._stop_btn.setObjectName("stopBtn")
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        input_row.addWidget(self._stop_btn)
        root.addLayout(input_row)

        self.add_system_note("Click the character or press Ctrl+Shift+Space anytime to open this chat.")

    def _on_pin_toggled(self, checked: bool) -> None:
        self._pinned = checked
        self._pin_btn.setText("Pinned" if checked else "Pin")

    def is_pinned(self) -> bool:
        return self._pinned

    def _switch_from_quota(self, provider: str, model: str) -> None:
        self._quota_banner.setVisible(False)
        self.provider_switch_requested.emit(provider, model)

    def apply_config(self, config: CharacterConfig) -> None:
        self._config = config
        self._name_lbl.setText(config.character_name or "Lumi")
        model = config.model_name or chatbot.default_model_for_provider(config.provider)
        if config.enable_system_tools and config.allow_all_user_folders:
            pc_badge = " · PC Control ON · All Drives"
        elif config.enable_system_tools:
            pc_badge = " · PC Control ON"
        else:
            pc_badge = ""
        self._status_lbl.setText(f"{config.provider} · {model}{pc_badge}")
        if self._files_chip is not None:
            self._files_chip.setVisible(bool(config.enable_system_tools))
        self._avatar_lbl.setPixmap(draw_pet_pixmap(34, config.sprite_path))
        needs_key = chatbot.requires_api_key(config.provider) and not chatbot.resolve_api_key(config.provider)
        if needs_key:
            self._key_banner_lbl.setText(f"API key not set for {config.provider}")
        self._key_banner.setVisible(needs_key)
        if config.provider != "gemini":
            self._quota_banner.setVisible(False)

    def set_status(self, text: str) -> None:
        self._status_lbl.setText(text)

    def set_streaming(self, active: bool) -> None:
        self._send_btn.setVisible(not active)
        self._stop_btn.setVisible(active)
        if not active:
            self.apply_config(self._config)

    def focus_input(self) -> None:
        self.raise_()
        self.activateWindow()
        self._input.setFocus()

    def clear_messages(self) -> None:
        self._render_timer.stop()
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._streaming_bubble = None
        self._streaming_text = ""
        self._quota_banner.setVisible(False)

    def add_system_note(self, text: str) -> None:
        lbl = QtWidgets.QLabel(text)
        lbl.setWordWrap(True)
        lbl.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color:#94a3b8;font-size:11px;padding:4px 8px;")
        self._insert_widget(lbl)

    def add_user_message(self, text: str) -> None:
        wrap = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(wrap)
        row.setContentsMargins(36, 0, 0, 0)
        row.addStretch(1)
        lbl = QtWidgets.QLabel(text)
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(310)
        lbl.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setStyleSheet(
            "background:#2563eb;color:#ffffff;padding:8px 12px;"
            "border-radius:12px;font-size:13px;"
        )
        row.addWidget(lbl)
        self._insert_widget(wrap)

    def start_assistant_message(self) -> None:
        self._quota_banner.setVisible(False)
        self._streaming_text = ""
        browser = QtWidgets.QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser.setWordWrapMode(QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        browser.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        browser.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        browser.setStyleSheet(
            "QTextBrowser{background:#1e293b;color:#e2e8f0;border:1px solid #334155;"
            "border-radius:12px;padding:8px 10px;font-size:13px;}"
        )
        browser.setHtml("<i>Thinking...</i>")
        browser.document().setTextWidth(330)
        self._streaming_bubble = browser
        self._insert_widget(browser)
        self._sync_browser_height(browser)

    def _flush_streaming_markdown(self) -> None:
        if self._streaming_bubble is None:
            return
        self._streaming_bubble.setHtml(markdown_to_qt_html(self._streaming_text))
        self._sync_browser_height(self._streaming_bubble)
        self._scroll_to_bottom()

    def append_assistant_token(self, token: str) -> None:
        was_empty = not self._streaming_text
        if self._streaming_bubble is None:
            self.start_assistant_message()
        self._streaming_text += token
        if was_empty:
            self._flush_streaming_markdown()
        elif not self._render_timer.isActive():
            self._render_timer.start()

    def finish_assistant_message(self, final_text: str) -> None:
        self._render_timer.stop()
        if self._streaming_bubble is not None and final_text:
            self._streaming_bubble.setHtml(markdown_to_qt_html(final_text))
            self._sync_browser_height(self._streaming_bubble)
        self._streaming_bubble = None
        self._scroll_to_bottom()

    def show_error(self, message: str) -> None:
        self._render_timer.stop()
        if self._streaming_bubble is not None:
            self._streaming_bubble.setHtml(
                f"<span style='color:#fca5a5;'><b>Error:</b> {html.escape(message)}</span>"
            )
            self._sync_browser_height(self._streaming_bubble)
            self._streaming_bubble = None
        else:
            self.add_system_note(f"Error: {message}")
        low = (message or "").lower()
        if "429" in low or "quota" in low or "rate limit" in low:
            self._quota_banner.setVisible(True)
        self._scroll_to_bottom()

    def _insert_widget(self, w: QtWidgets.QWidget) -> None:
        idx = max(0, self._msg_layout.count() - 1)
        self._msg_layout.insertWidget(idx, w)
        self._scroll_to_bottom()

    def _sync_browser_height(self, browser: QtWidgets.QTextBrowser) -> None:
        browser.document().setTextWidth(max(220, self._scroll.viewport().width() - 28))
        doc_h = int(browser.document().size().height()) + 20
        browser.setFixedHeight(max(38, doc_h))

    def _scroll_to_bottom(self) -> None:
        self._scroll_timer.start()

    def _do_scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_send_clicked(self) -> None:
        txt = self._input.toPlainText().strip()
        if not txt:
            return
        self._input.clear()
        self._submit_text(txt)

    def _submit_text(self, text: str) -> None:
        self.send_message.emit(text)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._header.geometry().contains(event.pos()):
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None and (event.buttons() & QtCore.Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)


# ============================================================
# CUSTOMIZE CHARACTER & PERSONA DIALOG
# ============================================================

class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, config: CharacterConfig, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Customize Desktop Character")
        self.setMinimumSize(540, 460)
        screen = QtGui.QGuiApplication.primaryScreen()
        avail_h = screen.availableGeometry().height() if screen else 800
        self.resize(580, min(680, max(480, avail_h - 80)))
        self.setStyleSheet(
            "QDialog{background:#0f172a;color:#e2e8f0;}"
            "QScrollArea{background:transparent;border:none;}"
            "QLabel,QCheckBox{color:#cbd5e1;font-weight:600;}"
            "QLineEdit,QComboBox,QPlainTextEdit,QSpinBox{background:#1e293b;color:#f8fafc;"
            "border:1px solid #334155;border-radius:7px;padding:6px;}"
            "QPushButton{background:#1e293b;color:#e2e8f0;border:1px solid #334155;"
            "border-radius:7px;padding:6px 12px;font-weight:600;}"
            "QPushButton:hover{background:#334155;}"
        )

        self._config = CharacterConfig(**asdict(config))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        form_host = QtWidgets.QWidget()
        form_host.setStyleSheet("background:transparent;")
        form = QtWidgets.QFormLayout(form_host)
        form.setContentsMargins(4, 4, 10, 4)
        form.setSpacing(9)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._name_edit = QtWidgets.QLineEdit(self._config.character_name)
        form.addRow("Character Name:", self._name_edit)

        self._preset_combo = QtWidgets.QComboBox()
        self._preset_combo.addItem("-- Apply Persona Preset --")
        for key in PERSONA_PRESETS:
            self._preset_combo.addItem(key)
        self._preset_combo.currentTextChanged.connect(self._on_preset_selected)
        form.addRow("Persona Preset:", self._preset_combo)

        self._persona_edit = QtWidgets.QPlainTextEdit(self._config.personality_prompt)
        self._persona_edit.setFixedHeight(78)
        form.addRow("Personality Prompt:", self._persona_edit)

        sprite_row = QtWidgets.QHBoxLayout()
        self._sprite_edit = QtWidgets.QLineEdit(self._config.sprite_path)
        self._sprite_edit.setPlaceholderText("Leave empty for built-in cute animated pet")
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_sprite)
        reset_sprite_btn = QtWidgets.QPushButton("Default Pet")
        reset_sprite_btn.clicked.connect(lambda: self._sprite_edit.setText(""))
        sprite_row.addWidget(self._sprite_edit, 1)
        sprite_row.addWidget(browse_btn)
        sprite_row.addWidget(reset_sprite_btn)
        form.addRow("Custom Image / GIF:", sprite_row)

        size_row = QtWidgets.QHBoxLayout()
        init_size = max(40, min(250, int(self._config.character_size)))
        self._size_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self._size_slider.setRange(40, 250)
        self._size_slider.setValue(init_size)
        self._size_spin = QtWidgets.QSpinBox()
        self._size_spin.setRange(40, 250)
        self._size_spin.setSingleStep(5)
        self._size_spin.setValue(init_size)
        self._size_spin.setSuffix(" px")
        self._size_slider.valueChanged.connect(self._size_spin.setValue)
        self._size_spin.valueChanged.connect(self._size_slider.setValue)
        size_row.addWidget(self._size_slider, 1)
        size_row.addWidget(self._size_spin)
        form.addRow("Character Size:", size_row)

        self._provider_combo = QtWidgets.QComboBox()
        self._provider_combo.addItems(list(chatbot.PROVIDER_SPECS.keys()))
        self._provider_combo.setCurrentText(self._config.provider)
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        form.addRow("AI Provider:", self._provider_combo)

        model_row = QtWidgets.QHBoxLayout()
        self._model_combo = QtWidgets.QComboBox()
        self._model_combo.setEditable(True)
        initial_model = chatbot.normalize_model_for_provider(self._config.provider, self._config.model_name)
        self._populate_models(self._config.provider, selected_model=initial_model, query_live=False)
        refresh_models_btn = QtWidgets.QPushButton("Refresh")
        refresh_models_btn.setToolTip("Fetch currently active models for this provider")
        refresh_models_btn.clicked.connect(self._on_refresh_models)
        model_row.addWidget(self._model_combo, 1)
        model_row.addWidget(refresh_models_btn)
        form.addRow("Model ID:", model_row)

        self._provider_hint_lbl = QtWidgets.QLabel()
        self._provider_hint_lbl.setWordWrap(True)
        self._provider_hint_lbl.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:400;")
        form.addRow("", self._provider_hint_lbl)
        self._refresh_provider_hint(self._config.provider)

        self._thinking_combo = QtWidgets.QComboBox()
        self._thinking_combo.addItems(["LOW", "MEDIUM", "HIGH"])
        self._thinking_combo.setCurrentText(self._config.thinking_level)
        form.addRow("Gemini Thinking:", self._thinking_combo)

        self._tools_chk = QtWidgets.QCheckBox("Enable real-time tools (Tavily Web Search, Gold Rate, News, Time)")
        self._tools_chk.setChecked(self._config.use_tools)
        form.addRow("", self._tools_chk)

        self._sys_tools_chk = QtWidgets.QCheckBox(
            "Enable PC & File Control (search, folder sizes, create, copy/paste, Recycle Bin, open/close apps)"
        )
        self._sys_tools_chk.setChecked(self._config.enable_system_tools)
        form.addRow("", self._sys_tools_chk)

        self._confirm_launch_chk = QtWidgets.QCheckBox(
            "Ask Allow/Deny confirmation before opening apps (Delete & Move always confirm)"
        )
        self._confirm_launch_chk.setChecked(self._config.confirm_app_launch)
        form.addRow("", self._confirm_launch_chk)

        self._all_folders_chk = QtWidgets.QCheckBox(
            "Control All Drives (C:\\, D:\\, K:\\, etc. — disables whitelist; OS & .env/.git stay protected)"
        )
        self._all_folders_chk.setChecked(self._config.allow_all_user_folders)
        form.addRow("", self._all_folders_chk)

        folders_row = QtWidgets.QHBoxLayout()
        self._allowed_dirs_edit = QtWidgets.QPlainTextEdit(
            "\n".join(self._config.allowed_folders or system_tools.default_allowed_dir_strings())
        )
        self._allowed_dirs_edit.setFixedHeight(62)
        self._allowed_dirs_edit.setPlaceholderText("One allowed folder or drive root per line")
        folder_btns = QtWidgets.QVBoxLayout()
        folder_btns.setSpacing(4)
        add_dir_btn = QtWidgets.QPushButton("Add Folder...")
        add_dir_btn.clicked.connect(self._browse_allowed_folder)
        add_drives_btn = QtWidgets.QPushButton("Add All Drives")
        add_drives_btn.setToolTip("Add every ready drive root (C:\\, D:\\, K:\\, etc.) to Allowed Folders")
        add_drives_btn.clicked.connect(self._add_all_drives)
        folder_btns.addWidget(add_dir_btn)
        folder_btns.addWidget(add_drives_btn)
        folders_row.addWidget(self._allowed_dirs_edit, 1)
        folders_row.addLayout(folder_btns)
        form.addRow("Allowed Folders:", folders_row)

        self._gemini_key_edit = QtWidgets.QLineEdit()
        self._gemini_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._gemini_key_edit.setPlaceholderText(
            "Configured (leave blank to keep)"
            if chatbot.resolve_api_key("gemini")
            else "Paste GEMINI_API_KEY (saved to .env)"
        )
        form.addRow("Gemini API Key:", self._gemini_key_edit)

        self._groq_key_edit = QtWidgets.QLineEdit()
        self._groq_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._groq_key_edit.setPlaceholderText(
            "Configured (leave blank to keep)"
            if chatbot.resolve_api_key("groq")
            else "Paste GROQ_API_KEY (gsk_...) — free tier (console.groq.com)"
        )
        form.addRow("Groq API Key:", self._groq_key_edit)

        self._grok_key_edit = QtWidgets.QLineEdit()
        self._grok_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._grok_key_edit.setPlaceholderText(
            "Configured (leave blank to keep)"
            if chatbot.resolve_api_key("grok")
            else "Paste GROK_API_KEY / XAI_API_KEY (xai-..., console.x.ai)"
        )
        form.addRow("Grok (xAI) Key:", self._grok_key_edit)

        self._nvidia_key_edit = QtWidgets.QLineEdit()
        self._nvidia_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._nvidia_key_edit.setPlaceholderText(
            "Configured (leave blank to keep)"
            if chatbot.resolve_api_key("nvidia")
            else "Paste NVIDIA_API_KEY (saved to .env)"
        )
        form.addRow("NVIDIA API Key:", self._nvidia_key_edit)

        self._tavily_key_edit = QtWidgets.QLineEdit()
        self._tavily_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._tavily_key_edit.setPlaceholderText(
            "Configured (leave blank to keep)"
            if os.getenv("TAVILY_API_KEY")
            else "Paste TAVILY_API_KEY (tvly-...) for live web_search (app.tavily.com)"
        )
        form.addRow("Tavily Search Key:", self._tavily_key_edit)

        self._initial_startup = is_startup_enabled()
        self._startup_chk = QtWidgets.QCheckBox("Launch automatically when Windows starts")
        self._startup_chk.setChecked(self._initial_startup)
        if sys.platform != "win32":
            self._startup_chk.setEnabled(False)
        form.addRow("", self._startup_chk)

        scroll.setWidget(form_host)
        layout.addWidget(scroll, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_preset_selected(self, label: str) -> None:
        if label in PERSONA_PRESETS:
            self._persona_edit.setPlainText(PERSONA_PRESETS[label])

    def _refresh_provider_hint(self, provider: str) -> None:
        if provider == "ollama":
            installed = chatbot.list_ollama_models(timeout=0.35)
            if installed:
                self._provider_hint_lbl.setText(
                    f"100% free unlimited local AI · Installed: {', '.join(installed[:4])}"
                )
            else:
                self._provider_hint_lbl.setText(
                    "100% free local AI via Ollama (127.0.0.1:11434) — no API key needed."
                )
        elif provider == "gemini":
            self._provider_hint_lbl.setText(
                "Free tier tips: 'gemini-3.5-flash-lite' or 'gemma-4-31b-it' have higher daily limits than 3.8-flash."
            )
        elif provider == "groq":
            self._provider_hint_lbl.setText(
                "Free cloud tier (no credit card, gsk_... key) at console.groq.com · Models: openai/gpt-oss-120b, openai/gpt-oss-20b, qwen/qwen3.8-27b"
            )
        elif provider == "grok":
            self._provider_hint_lbl.setText(
                "xAI Grok via api.x.ai/v1 (xai-... key, console.x.ai) · Models: grok-4-1-fast, grok-4.7, grok-3"
            )
        elif provider == "nvidia":
            self._provider_hint_lbl.setText(
                "Free developer API tier at build.nvidia.com · Default: meta/muse-glimmer-30b"
            )
        else:
            self._provider_hint_lbl.setText("Offline demo mode (no API key or internet required).")

    def _populate_models(
        self,
        provider: str,
        selected_model: Optional[str] = None,
        query_live: bool = False,
        preloaded_models: Optional[List[str]] = None,
    ) -> None:
        models: List[str] = list(preloaded_models) if preloaded_models else []
        if not models and (query_live or provider == "ollama"):
            models = chatbot.list_provider_models(provider, timeout=0.6 if not query_live else 2.5)
        if not models:
            models = list(chatbot.PROVIDER_SPECS.get(provider, {}).get("models", []))
        chosen = chatbot.normalize_model_for_provider(provider, selected_model)
        if not selected_model and models and chosen not in models:
            chosen = models[0]

        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        for m in models:
            self._model_combo.addItem(m)
        if chosen and chosen not in models:
            self._model_combo.addItem(chosen)
        self._model_combo.setCurrentText(chosen)
        self._model_combo.blockSignals(False)

    def _on_refresh_models(self) -> None:
        provider = self._provider_combo.currentText()
        live = chatbot.list_provider_models(provider, timeout=2.5)
        if live:
            self._populate_models(provider, selected_model=live[0], preloaded_models=live)
            self._provider_hint_lbl.setText(f"Loaded {len(live)} live {provider} model(s): {', '.join(live[:4])}")
        else:
            self._refresh_provider_hint(provider)

    def _on_provider_changed(self, provider: str) -> None:
        self._populate_models(provider, selected_model=None, query_live=False)
        self._refresh_provider_hint(provider)

    def _browse_sprite(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose Character Image or Animated GIF",
            "",
            "Images (*.png *.gif *.webp *.jpg *.jpeg *.bmp)",
        )
        if path:
            self._sprite_edit.setText(path)

    def _browse_allowed_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Allowed Folder")
        if folder:
            existing = [
                ln.strip()
                for ln in self._allowed_dirs_edit.toPlainText().splitlines()
                if ln.strip()
            ]
            if folder not in existing:
                existing.append(folder)
            self._allowed_dirs_edit.setPlainText("\n".join(existing))

    def _add_all_drives(self) -> None:
        existing = [
            ln.strip()
            for ln in self._allowed_dirs_edit.toPlainText().splitlines()
            if ln.strip()
        ]
        seen = {p.lower() for p in existing}
        for info in system_tools.get_available_drives():
            if info.get("ready", True) and info.get("root"):
                root_str = str(info["root"])
                if root_str.lower() not in seen:
                    seen.add(root_str.lower())
                    existing.append(root_str)
        self._allowed_dirs_edit.setPlainText("\n".join(existing))

    def updated_config(self) -> CharacterConfig:
        self._config.character_name = self._name_edit.text().strip() or "Lumi"
        self._config.personality_prompt = (
            self._persona_edit.toPlainText().strip() or PERSONA_PRESETS["Cute Desktop Pet"]
        )
        self._config.sprite_path = self._sprite_edit.text().strip()
        self._config.character_size = int(self._size_spin.value())
        self._config.provider = self._provider_combo.currentText()
        self._config.model_name = chatbot.normalize_model_for_provider(
            self._config.provider,
            self._model_combo.currentText().strip(),
        )
        self._config.thinking_level = self._thinking_combo.currentText()
        self._config.use_tools = self._tools_chk.isChecked()
        self._config.enable_system_tools = self._sys_tools_chk.isChecked()
        self._config.confirm_app_launch = self._confirm_launch_chk.isChecked()
        self._config.allow_all_user_folders = self._all_folders_chk.isChecked()
        self._config.allowed_folders = [
            ln.strip()
            for ln in self._allowed_dirs_edit.toPlainText().splitlines()
            if ln.strip()
        ] or system_tools.default_allowed_dir_strings()
        return self._config

    def apply_system_changes(self, env_path: Optional[Path] = None, startup_dir: Optional[Path] = None) -> bool:
        """Persist any newly entered API keys to .env and update Windows Startup if toggled."""
        keys_changed = False
        for field_edit, env_name in (
            (self._gemini_key_edit, "GEMINI_API_KEY"),
            (self._groq_key_edit, "GROQ_API_KEY"),
            (self._grok_key_edit, "GROK_API_KEY"),
            (self._nvidia_key_edit, "NVIDIA_API_KEY"),
            (self._tavily_key_edit, "TAVILY_API_KEY"),
        ):
            val = field_edit.text().strip()
            if val:
                chatbot.save_env_key(env_name, val, env_path=env_path)
                keys_changed = True

        desired_startup = self._startup_chk.isChecked()
        if desired_startup != self._initial_startup:
            set_startup_enabled(desired_startup, startup_dir=startup_dir)
        return keys_changed


# ============================================================
# CONTROLLER / APPLICATION ORCHESTRATOR
# ============================================================

class DesktopCompanionApp(QtCore.QObject):
    _confirm_requested = QtCore.Signal(str, str, str, object, object)
    _clipboard_requested = QtCore.Signal(str, str, object, object, object)

    def __init__(self, app: QtWidgets.QApplication, config: CharacterConfig):
        super().__init__()
        self._app = app
        self._config = config
        self._bot_lock = threading.Lock()
        self._pending_events_lock = threading.Lock()
        self._pending_events: List[threading.Event] = []
        self._active_confirm_box: Optional[QtWidgets.QMessageBox] = None
        self._worker_thread: Optional[QtCore.QThread] = None
        self._worker: Optional[StreamWorker] = None

        self._confirm_requested.connect(
            self._on_confirm_requested, QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._clipboard_requested.connect(
            self._on_clipboard_requested, QtCore.Qt.ConnectionType.QueuedConnection
        )

        self._bot = chatbot.Chatbot(
            chatbot.ChatbotConfig(
                provider=config.provider,
                model_name=config.model_name,
                thinking_level=config.thinking_level,
                temperature=config.temperature,
                use_tools=config.use_tools,
                enable_system_tools=bool(config.enable_system_tools),
                system_policy=self._build_system_policy(config),
                system_prompt=build_effective_system_prompt(
                    config.character_name,
                    config.personality_prompt,
                    config.use_tools,
                    enable_system_tools=config.enable_system_tools,
                    allow_all_drives=bool(config.allow_all_user_folders),
                ),
            )
        )

        self.character = CharacterWidget(config)
        self.popup = ChatPopupWindow(config)
        self._tray = self._create_tray_icon()

        # Wire character signals
        self.character.clicked.connect(self.toggle_popup)
        self.character.moved.connect(self._on_character_moved)
        self.character.sprite_dropped.connect(self._on_sprite_changed)
        self.character.size_change_requested.connect(self._on_size_changed)
        self.character.open_settings_requested.connect(self.open_settings)
        self.character.clear_chat_requested.connect(self.clear_conversation)
        self.character.system_tools_toggled.connect(self.toggle_system_tools)
        self.character.all_drives_toggled.connect(self.toggle_all_drives)
        self.character.provider_change_requested.connect(self.switch_provider)
        self.character.reset_pos_requested.connect(self.reset_position)
        self.character.hide_requested.connect(self.hide_character)
        self.character.quit_requested.connect(self.quit_app)

        # Wire popup signals
        self.popup.send_message.connect(self.send_user_message)
        self.popup.stop_requested.connect(self.stop_streaming)
        self.popup.clear_requested.connect(self.clear_conversation)
        self.popup.settings_requested.connect(self.open_settings)
        self.popup.mock_mode_requested.connect(lambda: self.switch_provider("mock"))
        self.popup.provider_switch_requested.connect(
            lambda p, m: self.switch_provider(p, m or None)
        )

        # Single-instance listener
        self._instance_guard: Optional[SingleInstanceGuard] = None

        # Global Windows hotkey (Ctrl+Shift+Space)
        self._hotkey_filter = WindowsHotkeyFilter(self.summon_from_hotkey)
        if config.hotkey_enabled and self._hotkey_filter.register():
            self._app.installNativeEventFilter(self._hotkey_filter)

        self._restore_or_default_position()

    def _create_tray_icon(self) -> QtWidgets.QSystemTrayIcon:
        tray = QtWidgets.QSystemTrayIcon(
            QtGui.QIcon(draw_pet_pixmap(64, self._config.sprite_path)),
            self,
        )
        tray.setToolTip(f"{self._config.character_name} Desktop Companion (Ctrl+Shift+Space)")

        menu = QtWidgets.QMenu(self.character)
        menu.addAction("Show / Toggle Chat", self.summon_from_hotkey)
        menu.addAction("Show Character", self.show_character)
        menu.addAction("Customize Character...", self.open_settings)
        menu.addAction("Reset Position", self.reset_position)
        menu.addSeparator()
        menu.addAction("Quit", self.quit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _on_tray_activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QtWidgets.QSystemTrayIcon.ActivationReason.Trigger,
            QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.summon_from_hotkey()

    def start(self) -> None:
        self.character.show()
        self.character.show_speech_bubble(
            f"Hi! I'm {self._config.character_name}. Click me or press Ctrl+Shift+Space!"
        )

    def _restore_or_default_position(self) -> None:
        screen = QtGui.QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1280, 720)
        if self._config.window_pos and len(self._config.window_pos) == 2:
            x, y = int(self._config.window_pos[0]), int(self._config.window_pos[1])
            x = max(geo.left(), min(geo.right() - self.character.width(), x))
            y = max(geo.top(), min(geo.bottom() - self.character.height(), y))
            self.character.move(x, y)
        else:
            self.reset_position()

    def reset_position(self) -> None:
        screen = QtGui.QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1280, 720)
        x = geo.right() - self.character.width() - 24
        y = geo.bottom() - self.character.height() - 18
        self.character.move(x, y)
        self._config.window_pos = [x, y]
        self._config.save()
        if self.popup.isVisible():
            self._position_popup_near_character()

    def _on_character_moved(self, x: int, y: int) -> None:
        self._config.window_pos = [x, y]
        self._config.save()
        if self.popup.isVisible() and not self.popup.is_pinned():
            self._position_popup_near_character()

    def _position_popup_near_character(self) -> None:
        char_geo = self.character.frameGeometry()
        screen = QtGui.QGuiApplication.screenAt(char_geo.center()) or QtGui.QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1280, 720)

        pw, ph = self.popup.width(), self.popup.height()
        # Prefer left side if character is on right half of screen
        if char_geo.center().x() > avail.center().x():
            px = char_geo.left() - pw - 6
        else:
            px = char_geo.right() + 6
        if px < avail.left():
            px = avail.left() + 8
        if px + pw > avail.right():
            px = avail.right() - pw - 8

        py = char_geo.bottom() - ph
        if py < avail.top() + 8:
            py = avail.top() + 8
        if py + ph > avail.bottom() - 8:
            py = avail.bottom() - ph - 8

        self.popup.move(px, py)

    def show_character(self) -> None:
        self.character.show()
        self.character.raise_()

    def hide_character(self) -> None:
        self.popup.hide()
        self.character.hide()
        self._tray.showMessage(
            self._config.character_name,
            "Still running in the tray. Press Ctrl+Shift+Space or click the tray icon anytime.",
            QtWidgets.QSystemTrayIcon.MessageIcon.Information,
            2500,
        )

    def toggle_popup(self) -> None:
        if self.popup.isVisible():
            self.popup.hide()
        else:
            self.show_character()
            self._position_popup_near_character()
            self.popup.show()
            self.popup.focus_input()

    def summon_from_hotkey(self) -> None:
        if not self.character.isVisible():
            self.show_character()
            self._position_popup_near_character()
            self.popup.show()
            self.popup.focus_input()
        else:
            self.toggle_popup()

    def _build_system_policy(self, cfg: CharacterConfig) -> system_tools.SystemToolsPolicy:
        roots = [
            Path(p).expanduser()
            for p in (cfg.allowed_folders or [])
            if str(p).strip()
        ]
        if not roots:
            roots = system_tools.default_allowed_dirs()
        # Use weakref proxies so ChatbotConfig -> SystemToolsPolicy never keeps a
        # strong reference cycle back to DesktopCompanionApp (QObject).
        weak_self = weakref.ref(self)

        def _confirm_proxy(title: str, detail: str, risk: str) -> bool:
            owner = weak_self()
            return owner._confirm_on_ui(title, detail, risk) if owner is not None else False

        def _clipboard_proxy(action: str, text: str, paths: List[str]) -> str:
            owner = weak_self()
            return (
                owner._clipboard_on_ui(action, text, paths)
                if owner is not None
                else "Error: Desktop companion is closed."
            )

        return system_tools.SystemToolsPolicy(
            enabled=bool(cfg.enable_system_tools),
            allowed_roots=roots,
            allow_all_non_system=bool(cfg.allow_all_user_folders),
            confirm_destructive=True,
            confirm_app_launch=bool(cfg.confirm_app_launch),
            confirm_callback=_confirm_proxy,
            clipboard_callback=_clipboard_proxy,
        )

    def _dispatch_ui_sync(
        self,
        direct_fn: Any,
        signal: QtCore.SignalInstance,
        *args: Any,
        default_result: Any = None,
    ) -> Any:
        """Run a UI callback synchronously from either the GUI thread or a worker QThread."""
        if QtCore.QThread.currentThread() == self.thread():
            return direct_fn(*args)
        result_box: Dict[str, Any] = {"value": default_result}
        done = threading.Event()
        with self._pending_events_lock:
            self._pending_events.append(done)
        try:
            signal.emit(*args, result_box, done)
            done.wait(timeout=120.0)
        finally:
            with self._pending_events_lock:
                if done in self._pending_events:
                    self._pending_events.remove(done)
        return result_box["value"]

    def _confirm_on_ui(self, title: str, detail: str, risk: str) -> bool:
        return bool(
            self._dispatch_ui_sync(
                self._prompt_confirm_dialog,
                self._confirm_requested,
                title,
                detail,
                risk,
                default_result=False,
            )
        )

    def _clipboard_on_ui(self, action: str, text: str, paths: List[str]) -> str:
        return str(
            self._dispatch_ui_sync(
                self._exec_clipboard_ui,
                self._clipboard_requested,
                action,
                text,
                paths,
                default_result="Cancelled.",
            )
        )

    @QtCore.Slot(str, str, str, object, object)
    def _on_confirm_requested(
        self,
        title: str,
        detail: str,
        risk: str,
        result_box: Dict[str, Any],
        done: threading.Event,
    ) -> None:
        try:
            if not done.is_set():
                result_box["value"] = self._prompt_confirm_dialog(title, detail, risk)
        finally:
            done.set()

    @QtCore.Slot(str, str, object, object, object)
    def _on_clipboard_requested(
        self,
        action: str,
        text: str,
        paths: Any,
        result_box: Dict[str, Any],
        done: threading.Event,
    ) -> None:
        try:
            if not done.is_set():
                result_box["value"] = self._exec_clipboard_ui(action, text, list(paths or []))
        finally:
            done.set()

    def _prompt_confirm_dialog(self, title: str, detail: str, risk: str) -> bool:
        parent = (
            self.popup
            if self.popup.isVisible()
            else (self.character if self.character.isVisible() else None)
        )
        box = QtWidgets.QMessageBox(parent)
        box.setWindowTitle(f"Allow {self._config.character_name}?")
        if risk in ("destructive", "overwrite"):
            box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        else:
            box.setIcon(QtWidgets.QMessageBox.Icon.Question)
        box.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        box.setText(title)
        box.setInformativeText(detail)
        allow_btn = box.addButton("Allow", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        deny_btn = box.addButton("Deny", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(deny_btn)
        box.setWindowFlags(box.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self._active_confirm_box = box
        try:
            box.exec()
            return box.clickedButton() == allow_btn
        finally:
            if self._active_confirm_box is box:
                self._active_confirm_box = None
            box.deleteLater()

    def _exec_clipboard_ui(self, action: str, text: str, paths: List[str]) -> str:
        cb = QtWidgets.QApplication.clipboard()
        if cb is None:
            return "Error: Clipboard is unavailable."
        if action == "get":
            mime = cb.mimeData()
            if mime is not None and mime.hasUrls():
                urls = [u.toLocalFile() or u.toString() for u in mime.urls()]
                txt = cb.text()
                if urls and not txt:
                    return "Clipboard files:\n" + "\n".join(urls)
                if urls and txt:
                    return f"Clipboard text:\n{txt}\nClipboard files:\n" + "\n".join(urls)
            content = cb.text()
            return content if content else "(Clipboard is empty)"
        if action == "set":
            cb.setText(text)
            return f"Copied {len(text)} character(s) to clipboard."
        if action == "copy_files":
            mime = QtCore.QMimeData()
            mime.setUrls([QtCore.QUrl.fromLocalFile(p) for p in paths])
            cb.setMimeData(mime)
            return (
                f"Copied {len(paths)} file/folder path(s) to Windows clipboard "
                "(ready for Ctrl+V paste)."
            )
        return f"Error: Unsupported clipboard action '{action}'."

    def toggle_system_tools(self, enabled: bool) -> None:
        self._config.enable_system_tools = bool(enabled)
        self._apply_updated_config(self._config)
        state = "enabled" if self._config.enable_system_tools else "disabled"
        self.character.show_speech_bubble(f"PC & File Control {state}!")

    def toggle_all_drives(self, enabled: bool) -> None:
        self._config.allow_all_user_folders = bool(enabled)
        if enabled and not self._config.enable_system_tools:
            self._config.enable_system_tools = True
        self._apply_updated_config(self._config)
        label = (
            "All-Drive Control ON!"
            if self._config.allow_all_user_folders
            else "Restricted to Allowed Folders!"
        )
        self.character.show_speech_bubble(label)

    def _apply_updated_config(self, new_cfg: CharacterConfig, refresh_keys: bool = False) -> None:
        self._config = new_cfg
        self._config.save()
        with self._bot_lock:
            if refresh_keys:
                self._bot.config.api_key = None
            self._bot.reconfigure(
                provider=new_cfg.provider,
                model_name=new_cfg.model_name,
                thinking_level=new_cfg.thinking_level,
                temperature=new_cfg.temperature,
                use_tools=new_cfg.use_tools,
                enable_system_tools=bool(new_cfg.enable_system_tools),
                system_policy=self._build_system_policy(new_cfg),
                system_prompt=build_effective_system_prompt(
                    new_cfg.character_name,
                    new_cfg.personality_prompt,
                    new_cfg.use_tools,
                    enable_system_tools=new_cfg.enable_system_tools,
                    allow_all_drives=bool(new_cfg.allow_all_user_folders),
                ),
            )
        self.character.apply_config(new_cfg)
        self.popup.apply_config(new_cfg)
        self._tray.setIcon(QtGui.QIcon(draw_pet_pixmap(64, new_cfg.sprite_path)))
        self._tray.setToolTip(f"{new_cfg.character_name} Desktop Companion (Ctrl+Shift+Space)")
        if self.popup.isVisible() and not self.popup.is_pinned():
            self._position_popup_near_character()

    def _on_size_changed(self, new_size: int) -> None:
        clamped = max(40, min(260, int(new_size)))
        self._config.character_size = clamped
        self._config.save()
        self.character.apply_config(self._config)
        self.character.show_speech_bubble(f"Size: {clamped}px", duration_ms=1500)
        if self.popup.isVisible() and not self.popup.is_pinned():
            self._position_popup_near_character()

    def _on_sprite_changed(self, path: str) -> None:
        self._config.sprite_path = path
        self._apply_updated_config(self._config)
        self.character.set_state("happy")
        self.character.show_speech_bubble("New look applied!")

    def switch_provider(self, provider: str, model_name: Optional[str] = None) -> None:
        self._config.provider = provider
        chosen_model = (model_name or "").strip() or chatbot.default_model_for_provider(provider)
        if provider == "ollama" and not model_name:
            installed = chatbot.list_ollama_models(timeout=0.35)
            if installed and chosen_model not in installed:
                chosen_model = installed[0]
        self._config.model_name = chosen_model
        self._apply_updated_config(self._config)
        self.character.show_speech_bubble(f"Switched to {provider} ({chosen_model})!")

    def open_settings(self) -> None:
        dlg = SettingsDialog(self._config, self.popup if self.popup.isVisible() else self.character)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            keys_changed = dlg.apply_system_changes()
            self._apply_updated_config(dlg.updated_config(), refresh_keys=keys_changed)
            self.character.set_state("happy")
            self.character.show_speech_bubble(f"Updated! I'm {self._config.character_name}.")

    def clear_conversation(self) -> None:
        if self._worker_thread is not None and self._worker_thread.isRunning():
            return
        with self._bot_lock:
            self._bot.reset_history()
        self.popup.clear_messages()
        self.popup.add_system_note("Conversation cleared.")

    def send_user_message(self, prompt: str) -> None:
        if self._worker_thread is not None and self._worker_thread.isRunning():
            return

        self.popup.add_user_message(prompt)
        self.popup.start_assistant_message()
        self.popup.set_streaming(True)
        self.popup.set_status("Thinking...")
        self.character.set_state("thinking")

        thread = QtCore.QThread(self)
        worker = StreamWorker(self._bot, self._bot_lock, prompt)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.token_received.connect(self._on_worker_token)
        worker.tool_started.connect(self._on_worker_tool_start)
        worker.tool_finished.connect(self._on_worker_tool_end)
        worker.error_received.connect(self._on_worker_error)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        self._worker_thread = thread
        self._worker = worker
        thread.start()

    def stop_streaming(self) -> None:
        if self._worker is not None:
            self._worker.cancel_event.set()
            self.popup.set_status("Stopping...")
        if self._active_confirm_box is not None:
            self._active_confirm_box.reject()
        with self._pending_events_lock:
            for ev in self._pending_events:
                ev.set()

    def _on_worker_token(self, token: str) -> None:
        self.character.set_state("talking")
        self.popup.set_status("Replying...")
        self.popup.append_assistant_token(token)

    def _on_worker_tool_start(self, name: str, args_txt: str) -> None:
        self.character.set_state("thinking")
        self.popup.set_status(f"Running tool: {name}...")
        self.character.show_speech_bubble(f"Checking {name}...")

    def _on_worker_tool_end(self, name: str, result: str) -> None:
        self.popup.set_status(f"Got {name} result, replying...")

    def _on_worker_error(self, message: str) -> None:
        self.character.set_state("idle")
        self.popup.show_error(message)

    def _on_worker_finished(self, final_text: str) -> None:
        self.popup.set_streaming(False)
        self.popup.finish_assistant_message(final_text)
        self.character.set_state("idle")
        if final_text and not self.popup.isVisible():
            self.character.show_speech_bubble(final_text)

    def _on_thread_finished(self) -> None:
        self._worker_thread = None
        self._worker = None

    def activate_from_second_launch(self) -> None:
        self.show_character()
        self._position_popup_near_character()
        self.popup.show()
        self.popup.focus_input()

    def quit_app(self) -> None:
        self.stop_streaming()
        if self._worker_thread is not None and self._worker_thread.isRunning():
            self._worker_thread.wait(1500)
        if self._instance_guard is not None:
            self._instance_guard.close()
        self._hotkey_filter.unregister()
        self._tray.hide()
        self._app.quit()


# ============================================================
# LAUNCHER
# ============================================================

def launch_desktop_companion(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    sprite: Optional[str] = None,
    name: Optional[str] = None,
    single_instance: bool = True,
    instance_name: str = SINGLE_INSTANCE_NAME,
) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Desktop AI Character")

    if single_instance and notify_running_instance(instance_name):
        return 0

    cfg = CharacterConfig.load()
    if provider:
        cfg.provider = provider
        if not model:
            cfg.model_name = chatbot.default_model_for_provider(provider)
    if model:
        cfg.model_name = model
    if sprite:
        cfg.sprite_path = sprite
    if name:
        cfg.character_name = name

    ico_path = chatbot.get_bundle_dir() / "assets" / "app_icon.ico"
    if not cfg.sprite_path and ico_path.is_file():
        app.setWindowIcon(QtGui.QIcon(str(ico_path)))
    else:
        app.setWindowIcon(QtGui.QIcon(draw_pet_pixmap(64, cfg.sprite_path)))

    controller = DesktopCompanionApp(app, cfg)
    if single_instance:
        guard = SingleInstanceGuard(instance_name)
        if guard.start_listening():
            guard.activated.connect(controller.activate_from_second_launch)
            controller._instance_guard = guard
    controller.start()
    return app.exec()


def main() -> None:
    # Windowed PyInstaller .exe launches with sys.stdout / sys.stderr as None
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    parser = argparse.ArgumentParser(description="Always-On-Screen Desktop AI Character Companion")
    parser.add_argument("--provider", choices=list(chatbot.PROVIDER_SPECS.keys()), default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--sprite", default=None, help="Path to custom PNG/GIF/WebP character image")
    parser.add_argument("--name", default=None, help="Custom character name")
    parser.add_argument("--multi", action="store_true", help="Allow running alongside an existing instance")
    parser.add_argument("--instance-name", default=SINGLE_INSTANCE_NAME, help=argparse.SUPPRESS)
    args = parser.parse_args()

    raise SystemExit(
        launch_desktop_companion(
            provider=args.provider,
            model=args.model,
            sprite=args.sprite,
            name=args.name,
            single_instance=not args.multi,
            instance_name=args.instance_name,
        )
    )


if __name__ == "__main__":
    main()
