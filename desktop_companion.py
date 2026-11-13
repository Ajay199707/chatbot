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
import base64
import copy
import ctypes
import ctypes.wintypes
from dataclasses import asdict, dataclass, field
from datetime import datetime
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
import time
from typing import Any, Dict, List, Optional, Tuple
import weakref

from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets

import api_tools
import chatbot
import character_painters
from character_painters import (
    CHARACTER_PRESETS,
    CharacterPreset,
    draw_character_pixmap,
    get_character_preset,
    list_character_categories,
    paint_animated_character,
)
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

TOPIC_KINDS: Tuple[str, ...] = ("news", "gold", "weather", "web_search", "custom_prompt")


def default_custom_topics() -> List[Dict[str, Any]]:
    """Return a fresh starter list of customizable wake-up & daily briefing topics."""
    return [
        {
            "id": "tech",
            "label": "Tech Field",
            "kind": "news",
            "query": "technology AI software",
            "prompt": "What is happening in the tech field today? Give the top highlights.",
            "enabled": True,
        },
        {
            "id": "cinema",
            "label": "Cinema",
            "kind": "news",
            "query": "cinema movies box office",
            "prompt": "What is happening in cinema and new movie releases today?",
            "enabled": True,
        },
        {
            "id": "gold",
            "label": "Gold Rate",
            "kind": "gold",
            "query": "india gold rate",
            "prompt": "What is today's gold rate and silver rate in India?",
            "enabled": True,
        },
        {
            "id": "weather",
            "label": "Weather",
            "kind": "weather",
            "query": "",
            "prompt": "",
            "enabled": True,
        },
        {
            "id": "news",
            "label": "Top News",
            "kind": "news",
            "query": "latest top news",
            "prompt": "What are today's latest top news headlines?",
            "enabled": True,
        },
    ]


def _normalize_topic_entry(entry: Any, index: int = 0) -> Optional[Dict[str, Any]]:
    """Validate and normalize a single custom topic dictionary."""
    if not isinstance(entry, dict):
        return None
    label = str(entry.get("label") or "").strip()
    if not label:
        return None
    kind = str(entry.get("kind") or "custom_prompt").strip().lower()
    if kind not in TOPIC_KINDS:
        kind = "custom_prompt"
    raw_id = str(entry.get("id") or "").strip()
    if not raw_id:
        slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        raw_id = slug or f"topic_{index + 1}"
    return {
        "id": raw_id,
        "label": label[:40],
        "kind": kind,
        "query": str(entry.get("query") or "").strip(),
        "prompt": str(entry.get("prompt") or "").strip(),
        "enabled": bool(entry.get("enabled", True)),
    }


def _resolved_topics(topics: Any) -> List[Dict[str, Any]]:
    """Return normalized topic dicts, falling back to defaults only when unset/invalid."""
    if not isinstance(topics, list):
        return default_custom_topics()
    cleaned: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(topics):
        norm = _normalize_topic_entry(item, index=idx)
        if norm is None:
            continue
        base_id = norm["id"]
        candidate = base_id
        suffix = 2
        while candidate in seen_ids:
            candidate = f"{base_id}_{suffix}"
            suffix += 1
        norm["id"] = candidate
        seen_ids.add(candidate)
        cleaned.append(norm)
    return cleaned


@dataclass
class CharacterConfig:
    character_name: str = "Lumi"
    character_id: str = "lumi"
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
    wake_greeting_enabled: bool = True
    wake_open_chat: bool = True
    wake_on_system_resume: bool = True
    wake_resume_cooldown_minutes: int = 120
    wake_auto_fetch_briefing: bool = False
    wake_user_name: str = ""
    wake_weather_city: str = "Chennai"
    custom_topics: List[Dict[str, Any]] = field(default_factory=default_custom_topics)
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
            cfg.custom_topics = _resolved_topics(cfg.custom_topics)
            clean_cid = str(getattr(cfg, "character_id", "") or "lumi").strip().lower()
            if clean_cid not in CHARACTER_PRESETS:
                clean_cid = "lumi"
            cfg.character_id = clean_cid
            try:
                cfg.wake_resume_cooldown_minutes = max(1, min(1440, int(cfg.wake_resume_cooldown_minutes)))
            except (TypeError, ValueError):
                cfg.wake_resume_cooldown_minutes = 120
            cfg.wake_user_name = (cfg.wake_user_name or "").strip()
            cfg.wake_weather_city = (cfg.wake_weather_city or "Chennai").strip() or "Chennai"
            return cfg
        except Exception:
            return cls()

    def save(self, path: Path = CONFIG_FILE) -> None:
        try:
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except Exception:
            pass


def topic_prompt_for_config(topic: Dict[str, Any], cfg: CharacterConfig) -> str:
    """Resolve the clickable chat prompt for a topic using current config settings."""
    city = (cfg.wake_weather_city or "Chennai").strip() or "Chennai"
    raw_prompt = str(topic.get("prompt") or "").strip()
    if raw_prompt:
        return raw_prompt.replace("{city}", city)
    kind = str(topic.get("kind") or "custom_prompt")
    raw_query = str(topic.get("query") or "").strip()
    label = str(topic.get("label") or "Updates").strip()
    query = raw_query or label
    if kind == "weather":
        target_city = raw_query or city
        return f"What is today's weather in {target_city}?"
    if kind == "gold":
        return "What is today's gold rate and silver rate in India?"
    if kind == "news":
        return f"What is the latest news in {query or label}?"
    if kind == "web_search":
        return f"Search the web for latest updates on {query or label}."
    return f"Give me today's update on {query or label}."


def time_of_day_greeting(now: Optional[datetime] = None, user_name: str = "") -> str:
    """Return a warm time-aware greeting such as 'Good morning, Alex!'."""
    dt = now or datetime.now()
    hour = dt.hour
    if 5 <= hour < 12:
        salutation = "Good morning"
    elif 12 <= hour < 17:
        salutation = "Good afternoon"
    elif 17 <= hour < 22:
        salutation = "Good evening"
    else:
        salutation = "Hello"
    clean_user = (user_name or "").strip()
    if clean_user:
        return f"{salutation}, {clean_user}!"
    return f"{salutation}!"


def build_wake_greeting_data(
    cfg: CharacterConfig,
    now: Optional[datetime] = None,
    system_resume: bool = False,
) -> Dict[str, Any]:
    """Build structured wake-up greeting copy and resolved enabled topics."""
    greeting = time_of_day_greeting(now=now, user_name=cfg.wake_user_name)
    topics: List[Dict[str, str]] = []
    for t in _resolved_topics(cfg.custom_topics):
        if not t.get("enabled", True):
            continue
        topics.append(
            {
                "id": str(t["id"]),
                "label": str(t["label"]),
                "kind": str(t["kind"]),
                "query": str(t.get("query") or ""),
                "prompt": topic_prompt_for_config(t, cfg),
            }
        )

    labels = [t["label"] for t in topics]
    if labels:
        preview = ", ".join(labels[:3]) if len(labels) <= 3 else ", ".join(labels[:3]) + f", and {labels[3]}"
        question = f"Do you want to know what is happening in {preview}?"
        bubble_tail = f"Ask about {', '.join(labels[:3])}!"
    else:
        question = "Ask me anything, check your PC files, or add custom topics in Settings."
        bubble_tail = "How can I assist you?"

    welcome_prefix = "Welcome back! " if system_resume else ""
    bubble_text = f"{greeting} {welcome_prefix}How can I assist you? {bubble_tail}".strip()
    if len(bubble_text) > 135:
        bubble_text = bubble_text[:132].rstrip() + "..."

    return {
        "greeting": greeting,
        "welcome_prefix": welcome_prefix,
        "headline": f"{greeting} {welcome_prefix}How can I assist you?".strip(),
        "question": question,
        "bubble_text": bubble_text,
        "topics": topics,
    }


def _summarize_briefing_lines(raw: str, max_items: int = 2) -> str:
    """Extract clean, single-line bullet text from a tool response string."""
    txt = (raw or "").strip()
    if not txt:
        return "No updates available."
    if txt.startswith("{"):
        try:
            obj = json.loads(txt)
            if isinstance(obj, dict) and obj.get("error"):
                return f"Unavailable ({obj['error']})"
        except Exception:
            pass
    if txt.startswith("Error:"):
        return txt

    picks: List[str] = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s or s.startswith("Link:") or s.startswith("Note:") or s.startswith("http"):
            continue
        s = re.sub(r"\s+", " ", s).lstrip("-*• ").strip()
        if len(s) > 120:
            s = s[:117].rstrip() + "..."
        picks.append(s)
        if len(picks) >= max_items:
            break
    return " · ".join(picks) if picks else "No updates available."


def _fetch_single_topic_summary(topic: Dict[str, Any], cfg: CharacterConfig) -> str:
    """Fetch a compact 1-2 item live summary for a single enabled topic."""
    kind = str(topic.get("kind") or "custom_prompt")
    raw_query = str(topic.get("query") or "").strip()
    query = raw_query or str(topic.get("label") or "").strip()
    city = (cfg.wake_weather_city or "Chennai").strip() or "Chennai"

    if kind == "gold":
        return _summarize_briefing_lines(chatbot.get_india_gold_price(), max_items=2)
    if kind == "weather":
        return _summarize_briefing_lines(api_tools.get_weather(raw_query or city, days=1), max_items=2)
    if kind == "news":
        return _summarize_briefing_lines(api_tools.get_news(query or "latest news"), max_items=2)
    if kind == "web_search":
        return _summarize_briefing_lines(api_tools.web_search(query, max_results=3), max_items=2)
    search_target = query or topic_prompt_for_config(topic, cfg)
    return _summarize_briefing_lines(api_tools.web_search(search_target, max_results=3), max_items=2)


def fetch_live_briefing_markdown(cfg: CharacterConfig, max_topics: int = 4) -> str:
    """Fetch a compact live Markdown daily briefing for enabled wake-up topics."""
    enabled_topics = [t for t in _resolved_topics(cfg.custom_topics) if t.get("enabled", True)]
    if not enabled_topics:
        return "_No daily topics are enabled. Open **Edit -> Wake-Up & Topics** to add some._"

    lines: List[str] = ["**Today's Live Briefing**"]
    for topic in enabled_topics[:max_topics]:
        label = topic["label"]
        try:
            summary = _fetch_single_topic_summary(topic, cfg)
        except Exception as exc:
            summary = f"Unavailable ({exc})"
        lines.append(f"- **{label}:** {summary}")
    return "\n".join(lines)


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
            "When the user asks about live weather (use get_weather), web information (web_search), "
            "gold/silver prices in India (get_india_gold_price), latest news (get_news), current date/time "
            "(get_current_datetime), maps/places/directions (maps_lookup), databases (database_query), "
            "email (email_action), calendar events (calendar_action), payments (payment_action), "
            "or custom/company internal APIs (list_custom_apis / call_custom_api), call your available tools first "
            "and report the real-time result honestly."
        )
        custom_summary = api_tools.custom_apis_prompt_summary()
        if custom_summary:
            parts.append(custom_summary)
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
            raw_lang = fence.group(1).strip()
            lang = raw_lang.upper() if raw_lang else "CODE"
            raw_code_lines: List[str] = []
            escaped_code_lines: List[str] = []
            i += 1
            while i < len(lines) and not re.match(r"^```\s*$", lines[i]):
                raw_code_lines.append(lines[i])
                escaped_code_lines.append(html.escape(lines[i]))
                i += 1
            if i < len(lines):
                i += 1
            raw_code = "\n".join(raw_code_lines)
            encoded_code = base64.b64encode(raw_code.encode("utf-8")).decode("ascii")
            code_html = "\n".join(escaped_code_lines)
            out.append(
                f"<div style='margin:8px 0;background:#090d16;border:1px solid #1e293b;border-radius:8px;'>"
                f"<table width='100%' cellpadding='4' cellspacing='0' style='background:#111827;border-bottom:1px solid #1e293b;border-top-left-radius:8px;border-top-right-radius:8px;'>"
                f"<tr>"
                f"<td align='left' style='color:#94a3b8;font-size:10px;font-weight:bold;font-family:Segoe UI,sans-serif;'>&nbsp;{lang}</td>"
                f"<td align='right' style='font-size:11px;'><a href='copy:{encoded_code}' style='color:#38bdf8;text-decoration:none;font-weight:bold;font-family:Segoe UI,sans-serif;'>📋 Copy&nbsp;</a></td>"
                f"</tr>"
                f"</table>"
                f"<pre style='color:#e2e8f0;padding:8px 10px;font-family:Consolas,Courier New,monospace;font-size:12px;white-space:pre-wrap;margin:0;'>{code_html}</pre>"
                f"</div>"
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
# WINDOWS GLOBAL HOTKEY & POWER RESUME FILTER
# ============================================================

class WindowsHotkeyFilter(QtCore.QAbstractNativeEventFilter):
    WM_HOTKEY = 0x0312
    WM_POWERBROADCAST = 0x0218
    PBT_APMRESUMESUSPEND = 0x0007
    PBT_APMRESUMEAUTOMATIC = 0x0012
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_NOREPEAT = 0x4000
    VK_SPACE = 0x20
    HOTKEY_ID = 0x4C55

    def __init__(self, on_trigger, on_system_resume=None):
        super().__init__()
        self._on_trigger = on_trigger
        self._on_system_resume = on_system_resume
        self._registered = False
        self._last_resume_monotonic = -10.0

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

    def _process_win32_msg(self, msg_id: int, wparam: int) -> Tuple[bool, int]:
        if self._registered and msg_id == self.WM_HOTKEY and wparam == self.HOTKEY_ID:
            QtCore.QTimer.singleShot(0, self._on_trigger)
            return True, 0
        if (
            self._on_system_resume is not None
            and msg_id == self.WM_POWERBROADCAST
            and wparam in (self.PBT_APMRESUMESUSPEND, self.PBT_APMRESUMEAUTOMATIC)
        ):
            now_m = time.monotonic()
            if now_m - self._last_resume_monotonic >= 5.0:
                self._last_resume_monotonic = now_m
                QtCore.QTimer.singleShot(0, self._on_system_resume)
        return False, 0

    def nativeEventFilter(self, eventType, message):  # noqa: N802
        if sys.platform == "win32":
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                return self._process_win32_msg(int(msg.message), int(msg.wParam))
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


def get_launch_target(startup_mode: bool = False) -> Tuple[Path, str, Path]:
    """Return (target_exe, arguments, working_dir) for Windows shortcuts."""
    extra = " --startup" if startup_mode else ""
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        return exe_path, ("--startup" if startup_mode else ""), exe_path.parent
    script_path = Path(__file__).resolve()
    return resolve_pythonw_executable(), f'"{script_path}"{extra}', script_path.parent


def set_startup_enabled(
    enabled: bool,
    startup_dir: Optional[Path] = None,
    include_startup_flag: bool = True,
) -> bool:
    shortcut = get_startup_shortcut_path(startup_dir)
    if not enabled:
        try:
            if shortcut.is_file():
                shortcut.unlink()
            return True
        except Exception:
            return False

    target_exe, arguments, working_dir = get_launch_target(startup_mode=include_startup_flag)
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


class WakeBriefingWorker(QtCore.QObject):
    """Fetch a compact live daily briefing in a background thread without blocking chat."""

    briefing_ready = QtCore.Signal(str)
    finished = QtCore.Signal()

    def __init__(self, config: CharacterConfig):
        super().__init__()
        self._config = CharacterConfig(**asdict(config))

    @QtCore.Slot()
    def run(self) -> None:
        try:
            md = fetch_live_briefing_markdown(self._config)
            self.briefing_ready.emit(md)
        except Exception as exc:
            self.briefing_ready.emit(f"_Live briefing unavailable: {exc}_")
        finally:
            self.finished.emit()


# ============================================================
# ALWAYS-ON-SCREEN CHARACTER WIDGET
# ============================================================

def draw_pet_pixmap(size: int = 64, sprite_path: str = "", character_id: str = "lumi") -> QtGui.QPixmap:
    """Create a small avatar pixmap (custom sprite thumbnail or animated character)."""
    return draw_character_pixmap(size=size, character_id=character_id, sprite_path=sprite_path)


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
    greet_requested = QtCore.Signal()
    moved = QtCore.Signal(int, int)
    sprite_dropped = QtCore.Signal(str)
    size_change_requested = QtCore.Signal(int)
    open_settings_requested = QtCore.Signal()
    avatar_gallery_requested = QtCore.Signal()
    avatar_preset_requested = QtCore.Signal(str)
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

        self._particles: List[Dict[str, float]] = [
            {
                "x": random.uniform(0.15, 0.85),
                "y": random.uniform(0.15, 0.90),
                "speed": random.uniform(0.006, 0.016),
                "size": random.uniform(2.0, 4.2),
                "phase_offset": random.uniform(0.0, 6.28),
            }
            for _ in range(6)
        ]

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

        for pt in self._particles:
            pt["y"] -= pt["speed"]
            if pt["y"] < 0.05:
                pt["y"] = 0.95
                pt["x"] = random.uniform(0.15, 0.85)

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

        # Ambient Neon Halo & Particles
        preset = get_character_preset(self._config.character_id)
        accent_color = QtGui.QColor(preset.accent_color)

        glow_rad = size * 0.52
        center_pt = char_rect.center()
        pulse = 0.5 + 0.5 * math.sin(self._phase * 1.6)
        glow_alpha = int(28 + 22 * pulse)
        if self._state in ("talking", "happy"):
            glow_alpha = int(glow_alpha * 1.5)

        halo_grad = QtGui.QRadialGradient(center_pt, glow_rad)
        c0 = QtGui.QColor(accent_color)
        c0.setAlpha(glow_alpha)
        c1 = QtGui.QColor(accent_color)
        c1.setAlpha(glow_alpha // 2)
        c2 = QtGui.QColor(accent_color)
        c2.setAlpha(0)
        halo_grad.setColorAt(0.0, c0)
        halo_grad.setColorAt(0.65, c1)
        halo_grad.setColorAt(1.0, c2)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(halo_grad)
        p.drawEllipse(center_pt, glow_rad, glow_rad)

        for part in self._particles:
            part_x = char_rect.left() + part["x"] * size + math.sin(self._phase * 2.0 + part["phase_offset"]) * 6.0
            part_y = char_rect.top() + part["y"] * size
            part_sz = part["size"] * (0.8 + 0.4 * math.sin(self._phase * 3.0 + part["phase_offset"]))
            part_alpha = int(120 + 90 * math.sin(self._phase * 2.5 + part["phase_offset"]))
            c_part = QtGui.QColor(accent_color)
            c_part.setAlpha(max(20, min(240, part_alpha)))
            p.setBrush(c_part)
            p.drawEllipse(QtCore.QPointF(part_x, part_y), part_sz, part_sz)

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
            paint_animated_character(
                self._config.character_id,
                p,
                char_rect,
                phase=self._phase,
                state=self._state,
                blinking=self._blinking,
                look_x=self._look_x,
                look_y=self._look_y,
            )

        # Comic speech bubble overlay with pointer tail
        if self._speech_text and w >= 100:
            font = QtGui.QFont("Segoe UI", 8, QtGui.QFont.Weight.DemiBold)
            p.setFont(font)
            fm = QtGui.QFontMetrics(font)
            text_rect = fm.boundingRect(
                QtCore.QRect(0, 0, w - 18, 54),
                QtCore.Qt.TextFlag.TextWordWrap,
                self._speech_text,
            )
            bw = min(w - 8, max(64.0, float(text_rect.width() + 18)))
            bh = float(text_rect.height() + 12)
            bx = (w - bw) / 2.0
            by = 2.0

            tail_w = 8.0
            tail_h = 5.0
            tail_cx = w / 2.0

            bubble_path = QtGui.QPainterPath()
            bubble_path.addRoundedRect(QtCore.QRectF(bx, by, bw, bh), 9.0, 9.0)

            tail_path = QtGui.QPainterPath()
            tail_path.moveTo(tail_cx - tail_w / 2.0, by + bh - 0.5)
            tail_path.lineTo(tail_cx, by + bh + tail_h)
            tail_path.lineTo(tail_cx + tail_w / 2.0, by + bh - 0.5)
            tail_path.closeSubpath()

            unified_path = bubble_path.united(tail_path)

            # Drop shadow
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 70))
            p.drawPath(unified_path.translated(0, 2.0))

            # Bubble background & accent colored border
            p.setPen(QtGui.QPen(accent_color, 1.5))
            p.setBrush(QtGui.QColor(15, 23, 42, 245))
            p.drawPath(unified_path)

            # Text inside
            p.setPen(QtGui.QColor("#f8fafc"))
            p.drawText(
                QtCore.QRectF(bx + 6, by + 4, bw - 12, bh - 8),
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
        act_greet = menu.addAction("Greet Me / Daily Topics")
        act_customize = menu.addAction("Customize Character & Persona...")
        act_gallery = menu.addAction("Choose Character Avatar (Gallery)...")

        avatar_menu = menu.addMenu("Switch Character Avatar")
        for pid, preset in CHARACTER_PRESETS.items():
            pa = avatar_menu.addAction(f"{preset.name} ({preset.category})")
            pa.setCheckable(True)
            pa.setChecked(self._config.character_id == pid and not self._config.sprite_path)
            pa.triggered.connect(lambda _=False, p_id=pid: self.avatar_preset_requested.emit(p_id))

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
        elif chosen == act_greet:
            self.greet_requested.emit()
        elif chosen == act_customize:
            self.open_settings_requested.emit()
        elif chosen == act_gallery:
            self.avatar_gallery_requested.emit()
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
# FLOW LAYOUT & FLOATING WAKE-UP GREETING BUBBLE
# ============================================================

class FlowLayout(QtWidgets.QLayout):
    """Wrapping horizontal layout so topic pills never overflow narrow drawers."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None, margin: int = 0, h_spacing: int = 6, v_spacing: int = 5):
        super().__init__(parent)
        self._items: List[QtWidgets.QLayoutItem] = []
        self._h_space = h_spacing
        self._v_space = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self) -> None:
        while self._items:
            self.takeAt(0)

    def addItem(self, item: QtWidgets.QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QtWidgets.QLayoutItem]:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> Optional[QtWidgets.QLayoutItem]:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> QtCore.Qt.Orientation:  # noqa: N802
        return QtCore.Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QtCore.QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QtCore.QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QtCore.QSize:  # noqa: N802
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QtCore.QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def clear_widgets(self) -> None:
        while self._items:
            item = self.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()

    def _do_layout(self, rect: QtCore.QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = eff.x()
        y = eff.y()
        line_h = 0
        for item in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_space
            if line_h > 0 and next_x - self._h_space > eff.right():
                x = eff.x()
                y += line_h + self._v_space
                next_x = x + hint.width() + self._h_space
                line_h = 0
            if not test_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        return (y + line_h - rect.y()) + m.bottom()


class WakeupBubbleWidget(QtWidgets.QWidget):
    """Frameless floating wake-up bubble visible even when the pet sprite is small (< 115px)."""

    chat_requested = QtCore.Signal()
    dismissed = QtCore.Signal()

    def __init__(self, character_name: str = "Lumi"):
        super().__init__(
            None,
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool,
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._card = QtWidgets.QFrame()
        self._card.setObjectName("wakeupBubbleCard")
        self._card.setStyleSheet(
            """
            #wakeupBubbleCard {
                background: #0f172a;
                border: 1.5px solid #38bdf8;
                border-radius: 12px;
            }
            QLabel { color: #e2e8f0; background: transparent; border: none; }
            QPushButton#bubbleCloseBtn {
                background: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 9px;
                font-size: 11px;
                font-weight: 700;
                padding: 0px;
            }
            QPushButton#bubbleCloseBtn:hover { background: #334155; color: #f8fafc; }
            """
        )
        self._card.setMaximumWidth(270)
        outer.addWidget(self._card)

        col = QtWidgets.QVBoxLayout(self._card)
        col.setContentsMargins(10, 8, 10, 8)
        col.setSpacing(4)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(6)
        self._title_lbl = QtWidgets.QLabel(f"{character_name or 'Lumi'} · Ready")
        self._title_lbl.setStyleSheet("color:#38bdf8;font-size:11px;font-weight:700;")
        close_btn = QtWidgets.QPushButton("×")
        close_btn.setObjectName("bubbleCloseBtn")
        close_btn.setFixedSize(18, 18)
        close_btn.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        close_btn.clicked.connect(self.dismiss_bubble)
        top.addWidget(self._title_lbl, 1)
        top.addWidget(close_btn)
        col.addLayout(top)

        self._msg_lbl = QtWidgets.QLabel("")
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setMaximumWidth(246)
        self._msg_lbl.setStyleSheet("color:#f8fafc;font-size:12px;line-height:1.35;")
        col.addWidget(self._msg_lbl)

        self._hint_lbl = QtWidgets.QLabel("Click to open chat & daily topics")
        self._hint_lbl.setStyleSheet("color:#93c5fd;font-size:10px;")
        col.addWidget(self._hint_lbl)

        self._hide_timer = QtCore.QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.dismiss_bubble)

    def set_character_name(self, name: str) -> None:
        self._title_lbl.setText(f"{(name or 'Lumi').strip() or 'Lumi'} · Ready")

    def show_for_character(self, char_geo: QtCore.QRect, text: str, duration_ms: int = 12000) -> None:
        self._msg_lbl.setText((text or "").strip())
        self.adjustSize()
        self.reposition_near(char_geo)
        self.show()
        self.raise_()
        self._hide_timer.start(max(1500, int(duration_ms)))

    def reposition_near(self, char_geo: QtCore.QRect) -> None:
        screen = QtGui.QGuiApplication.screenAt(char_geo.center()) or QtGui.QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1280, 720)
        bw, bh = max(self.width(), self.sizeHint().width()), max(self.height(), self.sizeHint().height())
        if char_geo.center().x() > avail.center().x():
            bx = char_geo.left() - bw - 8
        else:
            bx = char_geo.right() + 8
        bx = max(avail.left() + 8, min(avail.right() - bw - 8, bx))
        by = max(avail.top() + 8, min(avail.bottom() - bh - 8, char_geo.center().y() - bh // 2))
        self.move(bx, by)

    def dismiss_bubble(self) -> None:
        self._hide_timer.stop()
        self.hide()
        self.dismissed.emit()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._hide_timer.stop()
            self.hide()
            self.chat_requested.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


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
    enable_web_tools_requested = QtCore.Signal()
    briefing_requested = QtCore.Signal()

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
        self._wake_card: Optional[QtWidgets.QFrame] = None
        self._wake_briefing_browser: Optional[QtWidgets.QTextBrowser] = None
        self._files_chip: Optional[QtWidgets.QPushButton] = None

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
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(15, 23, 42, 0.96), stop:1 rgba(10, 15, 30, 0.98));
                border: 1.5px solid rgba(56, 189, 248, 0.35);
                border-radius: 18px;
            }
            QLabel { color: #e2e8f0; }
            QPushButton {
                background: rgba(30, 41, 59, 0.75);
                color: #e2e8f0;
                border: 1px solid rgba(51, 65, 85, 0.8);
                border-radius: 8px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover { background: rgba(51, 65, 85, 0.95); border-color: #38bdf8; }
            QPushButton#sendBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #38bdf8);
                border: none;
                color: #ffffff;
                padding: 7px 16px;
                border-radius: 9px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton#sendBtn:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4ed8, stop:1 #0284c7); }
            QPushButton#stopBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #dc2626, stop:1 #f87171);
                border: none;
                color: #ffffff;
                padding: 7px 16px;
                border-radius: 9px;
                font-size: 12px;
                font-weight: bold;
            }
            QPlainTextEdit {
                background: rgba(11, 17, 32, 0.85);
                color: #f8fafc;
                border: 1.5px solid #334155;
                border-radius: 12px;
                padding: 10px 12px;
                font-size: 13px;
            }
            QPlainTextEdit:focus {
                border: 1.5px solid #38bdf8;
            }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(148, 163, 184, 0.35);
                border-radius: 3px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(56, 189, 248, 0.65);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
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
        hbox.setSpacing(6)

        self._avatar_lbl = QtWidgets.QLabel()
        self._avatar_lbl.setFixedSize(36, 36)
        self._avatar_lbl.setStyleSheet("border-radius:18px;border:1.5px solid #38bdf8;padding:1px;background:#111827;")
        hbox.addWidget(self._avatar_lbl)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(1)
        self._name_lbl = QtWidgets.QLabel("Lumi")
        self._name_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")

        status_row = QtWidgets.QHBoxLayout()
        status_row.setSpacing(5)
        self._status_dot = QtWidgets.QLabel()
        self._status_dot.setFixedSize(8, 8)
        self._status_dot.setStyleSheet("border-radius:4px;background:#22c55e;")
        status_row.addWidget(self._status_dot)

        self._status_lbl = QtWidgets.QLabel("Ready")
        self._status_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        status_row.addWidget(self._status_lbl, 1)
        title_col.addWidget(self._name_lbl)
        title_col.addLayout(status_row)
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
        close_btn.setFixedWidth(24)
        close_btn.clicked.connect(self.hide_animated)
        hbox.addWidget(close_btn)
        root.addWidget(self._header)

        # Floating toast notification (e.g. "Code copied!")
        self._toast_lbl = QtWidgets.QLabel()
        self._toast_lbl.setStyleSheet(
            "background:rgba(37,99,235,0.94);color:#ffffff;font-size:11px;font-weight:bold;"
            "padding:4px 10px;border-radius:6px;border:1px solid #60a5fa;"
        )
        self._toast_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._toast_lbl.setVisible(False)
        self._toast_timer = QtCore.QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(lambda: self._toast_lbl.setVisible(False))
        root.addWidget(self._toast_lbl)

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

        # Disabled Web & API tools reminder banner
        self._tools_off_banner = QtWidgets.QFrame()
        self._tools_off_banner.setStyleSheet(
            "QFrame{background:#1e1b4b;border:1px solid #6366f1;border-radius:8px;}"
            "QLabel{color:#c7d2fe;font-size:11px;border:none;background:transparent;}"
        )
        t_row = QtWidgets.QHBoxLayout(self._tools_off_banner)
        t_row.setContentsMargins(8, 5, 8, 5)
        t_row.setSpacing(6)
        tools_off_lbl = QtWidgets.QLabel(
            "Web & API tools are OFF (Weather, Gold, News, Search)."
        )
        tools_off_lbl.setWordWrap(True)
        tools_off_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        turn_on_btn = QtWidgets.QPushButton("Turn On")
        turn_on_btn.clicked.connect(self.enable_web_tools_requested.emit)
        t_row.addWidget(tools_off_lbl, 1)
        t_row.addWidget(turn_on_btn)
        self._tools_off_banner.setVisible(False)
        root.addWidget(self._tools_off_banner)

        # Chat messages scroll area (wheel/auto-scroll active, scrollbars hidden)
        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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

        # Quick suggestion chips (wrapping FlowLayout backed by custom_topics + Files)
        self._chips_host = QtWidgets.QWidget()
        self._chips_host.setStyleSheet("background: transparent;")
        self._chips_layout = FlowLayout(self._chips_host, margin=0, h_spacing=6, v_spacing=5)
        self._rebuild_topic_chips(self._config)
        root.addWidget(self._chips_host)

        # Input row
        input_row = QtWidgets.QHBoxLayout()
        input_row.setSpacing(8)
        self._input = PromptInputBox()
        self._input.setFixedHeight(62)
        self._input.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._input.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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

    @staticmethod
    def _make_topic_pill(label: str, prompt: str, on_click, accent: bool = False) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(label)
        if accent:
            btn.setStyleSheet(
                "QPushButton{background:#1d4ed8;color:#f8fafc;border:1px solid #3b82f6;"
                "border-radius:12px;padding:3px 10px;font-size:11px;font-weight:700;}"
                "QPushButton:hover{background:#2563eb;color:#ffffff;}"
            )
        else:
            btn.setStyleSheet(
                "QPushButton{background:#162033;color:#93c5fd;border:1px solid #1e3a8a;"
                "border-radius:12px;padding:3px 9px;font-size:11px;}"
                "QPushButton:hover{background:#1e3a8a;color:#fff;}"
            )
        btn.clicked.connect(lambda _=False, p=prompt: on_click(p))
        return btn

    def _rebuild_topic_chips(self, config: CharacterConfig, force: bool = False) -> None:
        greeting_data = build_wake_greeting_data(config)
        sig = (
            tuple((t["label"], t["prompt"]) for t in greeting_data["topics"]),
            bool(config.enable_system_tools),
        )
        if not force and getattr(self, "_chips_signature", None) == sig and self._files_chip is not None:
            self._files_chip.setVisible(bool(config.enable_system_tools))
            return
        self._chips_signature = sig
        self._chips_layout.clear_widgets()
        self._files_chip = None
        for topic in greeting_data["topics"]:
            self._chips_layout.addWidget(
                self._make_topic_pill(topic["label"], topic["prompt"], self._submit_text)
            )
        files_btn = self._make_topic_pill(
            "Files",
            "List all my PC drives and allowed folders.",
            self._submit_text,
        )
        files_btn.setVisible(bool(config.enable_system_tools))
        self._files_chip = files_btn
        self._chips_layout.addWidget(files_btn)
        self._chips_host.updateGeometry()

    def apply_config(self, config: CharacterConfig) -> None:
        self._config = config
        self._name_lbl.setText(config.character_name or "Lumi")
        model = config.model_name or chatbot.default_model_for_provider(config.provider)
        web_badge = "" if config.use_tools else " · Web/API OFF"
        if config.enable_system_tools and config.allow_all_user_folders:
            pc_badge = " · PC Control ON · All Drives"
        elif config.enable_system_tools:
            pc_badge = " · PC Control ON"
        else:
            pc_badge = ""
        self._status_lbl.setText(f"{config.provider} · {model}{web_badge}{pc_badge}")
        self._tools_off_banner.setVisible(not bool(config.use_tools))
        self._rebuild_topic_chips(config)
        self._avatar_lbl.setPixmap(draw_pet_pixmap(34, config.sprite_path, config.character_id))
        preset = get_character_preset(config.character_id)
        self._avatar_lbl.setStyleSheet(f"border-radius:18px;border:1.5px solid {preset.accent_color};padding:1px;background:#111827;")
        needs_key = chatbot.requires_api_key(config.provider) and not chatbot.resolve_api_key(config.provider)
        if hasattr(self, "_status_dot"):
            if needs_key:
                self._status_dot.setStyleSheet("border-radius:4px;background:#f59e0b;")
            else:
                self._status_dot.setStyleSheet("border-radius:4px;background:#22c55e;")
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
        if hasattr(self, "_status_dot"):
            if active:
                self._status_dot.setStyleSheet("border-radius:4px;background:#38bdf8;")
            else:
                needs_key = chatbot.requires_api_key(self._config.provider) and not chatbot.resolve_api_key(self._config.provider)
                if needs_key:
                    self._status_dot.setStyleSheet("border-radius:4px;background:#f59e0b;")
                else:
                    self._status_dot.setStyleSheet("border-radius:4px;background:#22c55e;")
        if not active:
            self.apply_config(self._config)

    def show_animated(self) -> None:
        """Show with smooth fade-in animation."""
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.show()
        self.raise_()
        self.activateWindow()
        self.focus_input()
        if not hasattr(self, "_opacity_effect") or self._opacity_effect is None:
            self._opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self._opacity_effect)
        self._anim = QtCore.QPropertyAnimation(self._opacity_effect, b"opacity")
        self._anim.setDuration(160)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._anim.start()

    def hide_animated(self) -> None:
        """Hide with smooth fade-out animation."""
        if not self.isVisible():
            return
        if not hasattr(self, "_opacity_effect") or self._opacity_effect is None:
            self._opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self._opacity_effect)
        self._anim = QtCore.QPropertyAnimation(self._opacity_effect, b"opacity")
        self._anim.setDuration(130)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.InQuad)
        self._anim.finished.connect(
            lambda: self.hide() if (hasattr(self, "_opacity_effect") and self._opacity_effect.opacity() == 0.0) else None
        )
        self._anim.start()

    def show_passive(self) -> None:
        """Show the chat popup on startup/resume without stealing keyboard focus."""
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.show()
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, False)

    def focus_input(self) -> None:
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.raise_()
        self.activateWindow()
        self._input.setFocus()

    def _remove_wake_card(self) -> None:
        if self._wake_card is not None:
            self._msg_layout.removeWidget(self._wake_card)
            self._wake_card.deleteLater()
            self._wake_card = None
        self._wake_briefing_browser = None

    def show_wake_greeting(
        self,
        greeting_data: Dict[str, Any],
        include_briefing_placeholder: bool = False,
    ) -> None:
        """Render or refresh the interactive visual wake-up greeting card without altering LLM history."""
        self._remove_wake_card()

        card = QtWidgets.QFrame()
        card.setObjectName("wakeGreetingCard")
        card.setStyleSheet(
            "#wakeGreetingCard{background:#111c33;border:1.5px solid #2563eb;"
            "border-radius:12px;}"
        )
        col = QtWidgets.QVBoxLayout(card)
        col.setContentsMargins(11, 9, 11, 9)
        col.setSpacing(6)

        title_lbl = QtWidgets.QLabel(str(greeting_data.get("headline") or "Hello! How can I assist you?"))
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet("color:#f8fafc;font-size:13px;font-weight:700;background:transparent;")
        col.addWidget(title_lbl)

        sub_lbl = QtWidgets.QLabel(str(greeting_data.get("question") or "Pick a topic or ask anything below:"))
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet("color:#cbd5e1;font-size:12px;background:transparent;")
        col.addWidget(sub_lbl)

        pills_host = QtWidgets.QWidget()
        pills_host.setStyleSheet("background: transparent;")
        pills_flow = FlowLayout(pills_host, margin=0, h_spacing=6, v_spacing=5)
        for topic in greeting_data.get("topics") or []:
            pills_flow.addWidget(
                self._make_topic_pill(str(topic["label"]), str(topic["prompt"]), self._submit_text)
            )
        if self._config.enable_system_tools:
            pills_flow.addWidget(
                self._make_topic_pill(
                    "My Drives & Files",
                    "List all my PC drives and summarize my folders.",
                    self._submit_text,
                )
            )
        briefing_btn = QtWidgets.QPushButton("Get Live Briefing")
        briefing_btn.setStyleSheet(
            "QPushButton{background:#0f766e;color:#f0fdfa;border:1px solid #14b8a6;"
            "border-radius:12px;padding:3px 10px;font-size:11px;font-weight:700;}"
            "QPushButton:hover{background:#0d9488;color:#ffffff;}"
        )
        briefing_btn.clicked.connect(self.briefing_requested.emit)
        pills_flow.addWidget(briefing_btn)
        col.addWidget(pills_host)

        briefing_browser = QtWidgets.QTextBrowser()
        briefing_browser.setOpenExternalLinks(True)
        briefing_browser.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        briefing_browser.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        briefing_browser.setWordWrapMode(QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        briefing_browser.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        briefing_browser.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        briefing_browser.setStyleSheet(
            "QTextBrowser{background:#0f172a;color:#e2e8f0;border:1px solid #334155;"
            "border-radius:8px;padding:6px 8px;font-size:12px;}"
        )
        briefing_browser.setVisible(False)
        col.addWidget(briefing_browser)

        self._wake_card = card
        self._wake_briefing_browser = briefing_browser
        self._insert_widget(card)
        if include_briefing_placeholder:
            self.set_wake_briefing_loading()

    def set_wake_briefing_loading(self) -> None:
        if self._wake_briefing_browser is None:
            return
        self._wake_briefing_browser.setVisible(True)
        self._wake_briefing_browser.setHtml("<i>Fetching today's live briefing across your topics...</i>")
        self._sync_browser_height(self._wake_briefing_browser)
        self._scroll_to_bottom()

    def set_wake_briefing_markdown(self, markdown_text: str) -> None:
        if self._wake_briefing_browser is None:
            return
        self._wake_briefing_browser.setVisible(True)
        self._wake_briefing_browser.setHtml(markdown_to_qt_html(markdown_text))
        self._sync_browser_height(self._wake_briefing_browser)
        self._scroll_to_bottom()

    def clear_messages(self) -> None:
        self._render_timer.stop()
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._wake_card = None
        self._wake_briefing_browser = None
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
        lbl.setMaximumWidth(332)
        lbl.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2563eb, stop:1 #1d4ed8);"
            "color: #ffffff; padding: 9px 13px; border-radius: 14px;"
            "border-bottom-right-radius: 3px; font-size: 13px;"
            "border: 1px solid rgba(255, 255, 255, 0.12);"
        )
        row.addWidget(lbl)
        self._insert_widget(wrap)

    def start_assistant_message(self) -> None:
        self._quota_banner.setVisible(False)
        self._streaming_text = ""
        browser = QtWidgets.QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.anchorClicked.connect(self._on_browser_anchor_clicked)
        browser.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser.setWordWrapMode(QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        browser.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        browser.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        browser.setStyleSheet(
            "QTextBrowser{background:rgba(30, 41, 59, 0.88);color:#f1f5f9;border:1px solid rgba(51, 65, 85, 0.7);"
            "border-radius:14px;border-bottom-left-radius:3px;padding:9px 12px;font-size:13px;}"
        )
        preset = get_character_preset(self._config.character_id)
        accent = preset.accent_color
        browser.setHtml(
            f"<span style='color:{accent};font-size:14px;'>●</span> "
            f"<span style='color:{accent};font-size:14px;'>●</span> "
            f"<span style='color:{accent};font-size:14px;'>●</span> "
            f"<i style='color:#94a3b8;margin-left:6px;font-size:12px;'>Thinking...</i>"
        )
        browser.document().setTextWidth(330)
        self._streaming_bubble = browser
        self._insert_widget(browser)
        self._sync_browser_height(browser)

    def _on_browser_anchor_clicked(self, url: QtCore.QUrl) -> None:
        url_str = url.toString()
        if url_str.startswith("copy:"):
            encoded = url_str[5:]
            try:
                raw = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
                QtGui.QGuiApplication.clipboard().setText(raw)
                self.show_toast("Code copied to clipboard!")
            except Exception:
                pass
            return
        QtGui.QDesktopServices.openUrl(url)

    def show_toast(self, text: str, duration_ms: int = 2200) -> None:
        if hasattr(self, "_toast_lbl"):
            self._toast_lbl.setText(text)
            self._toast_lbl.setVisible(True)
            self._toast_timer.start(duration_ms)

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

    def reset_streaming_preview(self, status_html: str = "<i>Working...</i>") -> None:
        self._render_timer.stop()
        self._streaming_text = ""
        if self._streaming_bubble is not None:
            self._streaming_bubble.setHtml(status_html)
            self._sync_browser_height(self._streaming_bubble)
            self._scroll_to_bottom()

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
        browser.document().setTextWidth(max(220, self._scroll.viewport().width() - 24))
        doc_h = int(browser.document().size().height()) + 20
        browser.setFixedHeight(max(38, doc_h))

    def _scroll_to_bottom(self) -> None:
        self._scroll_timer.start()

    def _do_scroll_to_bottom(self) -> None:
        self._msg_layout.activate()
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

_DARK_DIALOG_QSS = (
    "QDialog{background:#0f172a;color:#e2e8f0;font-size:12px;}"
    "QLabel,QCheckBox{color:#cbd5e1;font-weight:600;}"
    "QCheckBox{spacing:8px;}"
    "QGroupBox{background:#111c33;border:1px solid #293548;border-radius:10px;"
    "margin-top:10px;padding:12px 12px 8px 12px;font-weight:700;color:#93c5fd;}"
    "QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 6px;}"
    "QTabWidget::pane{border:1px solid #293548;border-radius:10px;background:#0f172a;top:-1px;}"
    "QTabBar::tab{background:#1e293b;color:#94a3b8;border:1px solid #293548;"
    "border-bottom:none;border-top-left-radius:8px;border-top-right-radius:8px;"
    "padding:7px 14px;margin-right:4px;font-weight:600;}"
    "QTabBar::tab:selected{background:#2563eb;color:#ffffff;border-color:#2563eb;}"
    "QTabBar::tab:hover:!selected{background:#293548;color:#e2e8f0;}"
    "QLineEdit,QComboBox,QPlainTextEdit,QSpinBox,QListWidget{background:#1e293b;color:#f8fafc;"
    "border:1px solid #334155;border-radius:7px;padding:4px 8px;}"
    "QListWidget::item{padding:5px 6px;border-radius:5px;}"
    "QListWidget::item:selected{background:#1d4ed8;color:#ffffff;}"
    "QLineEdit:focus,QComboBox:focus,QPlainTextEdit:focus,QSpinBox:focus,QListWidget:focus{border-color:#38bdf8;}"
    "QPushButton{background:#1e293b;color:#e2e8f0;border:1px solid #334155;"
    "border-radius:7px;padding:5px 12px;font-weight:600;}"
    "QPushButton:hover{background:#334155;}"
    "QPushButton#primaryBtn{background:#2563eb;color:#ffffff;border-color:#2563eb;}"
    "QPushButton#primaryBtn:hover{background:#1d4ed8;}"
)


_BUILTIN_API_FIELD_TABS: Tuple[Tuple[str, Tuple[Tuple[str, str, bool, str], ...]], ...] = (
    (
        "Weather, Maps && DB",
        (
            ("OPENWEATHER_API_KEY", "OpenWeather Key:", True, "Optional (free Open-Meteo works with no key)"),
            ("NEWSAPI_KEY", "NewsAPI.org Key:", True, "Optional (free Google News RSS works with no key)"),
            ("GOOGLE_MAPS_API_KEY", "Google Maps Key:", True, "Optional (Nominatim works with no key)"),
            ("SQLITE_DB_PATH", "SQLite DB Path:", False, "Path to local .db file (optional)"),
            ("DATABASE_API_URL", "Database REST URL:", False, "e.g. https://project.supabase.co/rest/v1"),
            ("DATABASE_API_KEY", "Database API Key:", True, "Bearer / apikey token for Database REST API"),
        ),
    ),
    (
        "Email && Calendar",
        (
            ("EMAIL_USER", "Email Address:", False, "e.g. your.name@gmail.com"),
            ("EMAIL_PASSWORD", "Email App Password:", True, "SMTP / IMAP password or Gmail App Password"),
            ("SMTP_HOST", "SMTP Host:", False, "Auto-detected for Gmail, or e.g. smtp.office365.com"),
            ("SMTP_PORT", "SMTP Port:", False, "Default 587 (or 465 for SSL)"),
            ("IMAP_HOST", "IMAP Host:", False, "Auto-detected for Gmail, or e.g. outlook.office365.com"),
            ("GOOGLE_CALENDAR_TOKEN", "Google Cal Token:", True, "OAuth Bearer token for Google Calendar API"),
            ("CALENDAR_ICS_URL", "Calendar .ics URL:", False, "Optional private iCal feed URL (read-only)"),
            ("CALENDAR_ICS_PATH", "Local .ics File:", False, "Optional path to local .ics calendar file"),
        ),
    ),
    (
        "Payments",
        (
            ("STRIPE_API_KEY", "Stripe Secret Key:", True, "sk_test_... or sk_live_..."),
            ("RAZORPAY_KEY_ID", "Razorpay Key ID:", True, "rzp_test_... or rzp_live_..."),
            ("RAZORPAY_KEY_SECRET", "Razorpay Secret:", True, "Razorpay API key secret"),
        ),
    ),
)


class BuiltInApisDialog(QtWidgets.QDialog):
    """Compact tabbed dialog for saving Weather/Maps/DB/Email/Calendar/Payment keys to .env."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Configure Built-in API Credentials (.env)")
        self.setMinimumSize(620, 420)
        self.resize(650, 460)
        self.setStyleSheet(_DARK_DIALOG_QSS)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        note = QtWidgets.QLabel(
            "Leave already configured password fields blank to keep existing keys. "
            "Secrets are saved locally to .env (never in JSON config files)."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:400;")
        layout.addWidget(note)

        self._edits: Dict[str, Tuple[QtWidgets.QLineEdit, bool]] = {}
        tabs = QtWidgets.QTabWidget()
        for tab_title, rows in _BUILTIN_API_FIELD_TABS:
            page = QtWidgets.QWidget()
            form = QtWidgets.QFormLayout(page)
            form.setContentsMargins(12, 12, 12, 10)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(7)
            form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            for env_key, label, is_secret, hint in rows:
                edit = QtWidgets.QLineEdit()
                existing = os.getenv(env_key, "").strip()
                if is_secret:
                    edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
                    edit.setPlaceholderText("Configured (leave blank to keep)" if existing else hint)
                else:
                    edit.setText(existing)
                    edit.setPlaceholderText(hint)
                self._edits[env_key] = (edit, is_secret)
                if env_key == "SQLITE_DB_PATH":
                    row_box = QtWidgets.QHBoxLayout()
                    row_box.setSpacing(6)
                    browse_btn = QtWidgets.QPushButton("Browse...")
                    browse_btn.clicked.connect(lambda _=False, e=edit: self._pick_db_file(e))
                    row_box.addWidget(edit, 1)
                    row_box.addWidget(browse_btn)
                    form.addRow(label, row_box)
                else:
                    form.addRow(label, edit)
            tabs.addTab(page, tab_title)
        layout.addWidget(tabs, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setObjectName("primaryBtn")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick_db_file(self, target_edit: QtWidgets.QLineEdit) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select SQLite Database", "", "SQLite Databases (*.db *.sqlite *.sqlite3);;All Files (*.*)"
        )
        if path:
            target_edit.setText(path)

    def save_to_env(self, env_path: Optional[Path] = None) -> int:
        saved = 0
        for env_key, (edit, is_secret) in self._edits.items():
            val = edit.text().strip()
            if val:
                if val != os.getenv(env_key, "").strip() or is_secret:
                    chatbot.save_env_key(env_key, val, env_path=env_path)
                    saved += 1
        return saved


class CustomApiEditorDialog(QtWidgets.QDialog):
    """Add or edit a user-registered custom / company internal REST API endpoint."""

    def __init__(
        self,
        endpoint: Optional[api_tools.CustomApiEndpoint] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Add / Edit Custom or Company Internal API")
        self.setMinimumSize(620, 500)
        self.resize(650, 540)
        self.setStyleSheet(_DARK_DIALOG_QSS)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(7)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._template_combo = QtWidgets.QComboBox()
        self._template_combo.addItem("-- Load Quick Template (Optional) --")
        for key in api_tools.PRESET_TEMPLATES:
            self._template_combo.addItem(key)
        self._template_combo.currentTextChanged.connect(self._on_template_chosen)
        form.addRow("Quick Template:", self._template_combo)

        self._name_edit = QtWidgets.QLineEdit(endpoint.name if endpoint else "")
        self._name_edit.setPlaceholderText("e.g. Company HR Service")
        form.addRow("Display Name:", self._name_edit)

        self._id_edit = QtWidgets.QLineEdit(endpoint.id if endpoint else "")
        self._id_edit.setPlaceholderText("Unique ID e.g. company_hr (auto-generated if blank)")
        form.addRow("API ID:", self._id_edit)

        cat_method_row = QtWidgets.QHBoxLayout()
        cat_method_row.setSpacing(8)
        self._cat_combo = QtWidgets.QComboBox()
        self._cat_combo.addItems(list(api_tools.CUSTOM_API_CATEGORIES))
        if endpoint and endpoint.category in api_tools.CUSTOM_API_CATEGORIES:
            self._cat_combo.setCurrentText(endpoint.category)
        self._method_combo = QtWidgets.QComboBox()
        self._method_combo.addItems(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
        if endpoint:
            self._method_combo.setCurrentText(endpoint.method)
        cat_method_row.addWidget(self._cat_combo, 2)
        cat_method_row.addWidget(QtWidgets.QLabel("Method:"))
        cat_method_row.addWidget(self._method_combo, 1)
        form.addRow("Category:", cat_method_row)

        self._base_url_edit = QtWidgets.QLineEdit(endpoint.base_url if endpoint else "")
        self._base_url_edit.setPlaceholderText("https://api.yourcompany.com/v1")
        form.addRow("Base URL:", self._base_url_edit)

        self._path_edit = QtWidgets.QLineEdit(endpoint.default_path if endpoint else "")
        self._path_edit.setPlaceholderText("/employees (optional default endpoint path)")
        form.addRow("Default Path:", self._path_edit)

        auth_row = QtWidgets.QHBoxLayout()
        auth_row.setSpacing(8)
        self._auth_combo = QtWidgets.QComboBox()
        self._auth_combo.addItems(list(api_tools.AUTH_TYPES))
        if endpoint:
            self._auth_combo.setCurrentText(endpoint.auth_type)
        self._auth_param_edit = QtWidgets.QLineEdit(endpoint.auth_param if endpoint else "")
        self._auth_param_edit.setPlaceholderText("Header/param e.g. Authorization or X-API-Key")
        auth_row.addWidget(self._auth_combo, 1)
        auth_row.addWidget(self._auth_param_edit, 2)
        form.addRow("Auth Type / Param:", auth_row)

        secret_row = QtWidgets.QHBoxLayout()
        secret_row.setSpacing(8)
        self._secret_name_edit = QtWidgets.QLineEdit(endpoint.env_secret_name if endpoint else "")
        self._secret_name_edit.setPlaceholderText(".env key name e.g. COMPANY_API_TOKEN")
        self._secret_val_edit = QtWidgets.QLineEdit()
        self._secret_val_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        existing_secret = bool(endpoint and endpoint.env_secret_name and os.getenv(endpoint.env_secret_name))
        self._secret_val_edit.setPlaceholderText(
            "Configured in .env (blank keeps)" if existing_secret else "Paste token/key (optional)"
        )
        secret_row.addWidget(self._secret_name_edit, 1)
        secret_row.addWidget(self._secret_val_edit, 1)
        form.addRow(".env Key / Secret:", secret_row)

        self._confirm_combo = QtWidgets.QComboBox()
        self._confirm_combo.addItems(list(api_tools.CONFIRMATION_MODES))
        if endpoint:
            self._confirm_combo.setCurrentText(endpoint.confirmation_mode)
        form.addRow("Allow/Deny Rule:", self._confirm_combo)

        self._desc_edit = QtWidgets.QPlainTextEdit(endpoint.description if endpoint else "")
        self._desc_edit.setFixedHeight(74)
        self._desc_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._desc_edit.setPlaceholderText(
            "Tell the AI what this API does, expected endpoint paths, query params, or JSON body fields."
        )
        form.addRow("AI Description:", self._desc_edit)

        self._enabled_chk = QtWidgets.QCheckBox("Enable this API endpoint for AI tool calls")
        self._enabled_chk.setChecked(endpoint.enabled if endpoint else True)
        form.addRow("", self._enabled_chk)
        layout.addLayout(form, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setObjectName("primaryBtn")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_template_chosen(self, label: str) -> None:
        tpl = api_tools.PRESET_TEMPLATES.get(label)
        if not tpl:
            return
        self._id_edit.setText(tpl.get("id", ""))
        self._name_edit.setText(tpl.get("name", ""))
        self._cat_combo.setCurrentText(tpl.get("category", "Custom"))
        self._method_combo.setCurrentText(tpl.get("method", "GET"))
        self._base_url_edit.setText(tpl.get("base_url", ""))
        self._path_edit.setText(tpl.get("default_path", ""))
        self._auth_combo.setCurrentText(tpl.get("auth_type", "none"))
        self._auth_param_edit.setText(tpl.get("auth_param", ""))
        self._secret_name_edit.setText(tpl.get("env_secret_name", ""))
        self._confirm_combo.setCurrentText(tpl.get("confirmation_mode", "auto"))
        self._desc_edit.setPlainText(tpl.get("description", ""))

    def _validate_and_accept(self) -> None:
        base_url = self._base_url_edit.text().strip()
        if not base_url.startswith(("http://", "https://")):
            QtWidgets.QMessageBox.warning(self, "Invalid URL", "Base URL must start with http:// or https://.")
            return
        if not self._name_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Missing Name", "Please enter a display name for this API.")
            return
        self.accept()

    def build_endpoint(self) -> api_tools.CustomApiEndpoint:
        return api_tools.CustomApiEndpoint(
            id=self._id_edit.text().strip() or self._name_edit.text().strip(),
            name=self._name_edit.text().strip(),
            category=self._cat_combo.currentText(),
            description=self._desc_edit.toPlainText().strip(),
            base_url=self._base_url_edit.text().strip(),
            default_path=self._path_edit.text().strip(),
            method=self._method_combo.currentText(),
            auth_type=self._auth_combo.currentText(),
            auth_param=self._auth_param_edit.text().strip(),
            env_secret_name=self._secret_name_edit.text().strip(),
            confirmation_mode=self._confirm_combo.currentText(),
            enabled=self._enabled_chk.isChecked(),
        ).normalized()

    def save_secret_if_entered(self, env_path: Optional[Path] = None) -> bool:
        sec_name = self._secret_name_edit.text().strip()
        sec_val = self._secret_val_edit.text().strip()
        if sec_name and sec_val:
            chatbot.save_env_key(sec_name, sec_val, env_path=env_path)
            return True
        return False


class TopicEditorDialog(QtWidgets.QDialog):
    """Modal editor to add or customize a daily wake-up & quick-chip topic."""

    _KIND_CHOICES: Tuple[Tuple[str, str], ...] = (
        ("news", "News Headlines (Google News RSS / NewsAPI)"),
        ("gold", "India Gold & Silver Rate"),
        ("weather", "Live Weather Forecast"),
        ("web_search", "Web Search (Tavily / DuckDuckGo)"),
        ("custom_prompt", "Custom AI Prompt"),
    )

    def __init__(
        self,
        topic: Optional[Dict[str, Any]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit Topic" if topic else "Add Custom Topic")
        self.setMinimumWidth(440)
        self.setStyleSheet(_DARK_DIALOG_QSS)
        self._existing_id = str((topic or {}).get("id") or "").strip()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._label_edit = QtWidgets.QLineEdit(str((topic or {}).get("label") or ""))
        self._label_edit.setPlaceholderText("e.g., Tech Field, Cinema, Cricket, Stocks")
        form.addRow("Topic Label:", self._label_edit)

        self._kind_combo = QtWidgets.QComboBox()
        for kind_id, kind_label in self._KIND_CHOICES:
            self._kind_combo.addItem(kind_label, kind_id)
        cur_kind = str((topic or {}).get("kind") or "news")
        idx = self._kind_combo.findData(cur_kind)
        if idx >= 0:
            self._kind_combo.setCurrentIndex(idx)
        self._kind_combo.currentIndexChanged.connect(self._update_query_placeholder)
        form.addRow("Source / Type:", self._kind_combo)

        self._query_edit = QtWidgets.QLineEdit(str((topic or {}).get("query") or ""))
        form.addRow("Keyword / City:", self._query_edit)

        self._prompt_edit = QtWidgets.QPlainTextEdit(str((topic or {}).get("prompt") or ""))
        self._prompt_edit.setFixedHeight(72)
        self._prompt_edit.setPlaceholderText(
            "Optional custom question sent when clicked (supports {city}). Leave empty to auto-generate."
        )
        form.addRow("Click Prompt:", self._prompt_edit)

        self._enabled_chk = QtWidgets.QCheckBox("Show in wake-up greeting & quick chat chips")
        self._enabled_chk.setChecked(bool((topic or {}).get("enabled", True)))
        form.addRow("", self._enabled_chk)

        layout.addLayout(form)
        self._update_query_placeholder()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setObjectName("primaryBtn")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_query_placeholder(self) -> None:
        kind = str(self._kind_combo.currentData() or "news")
        placeholders = {
            "news": "e.g., technology AI software, cinema movies, cricket",
            "gold": "Optional note (uses live India gold & silver rates)",
            "weather": "Optional city override (blank = use default Weather City)",
            "web_search": "e.g., ISRO latest launch, Nifty 50 market today",
            "custom_prompt": "Optional keyword for live briefing web search",
        }
        self._query_edit.setPlaceholderText(placeholders.get(kind, "Keyword or query"))

    def _on_accept(self) -> None:
        if not self._label_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Missing Label", "Please enter a topic label.")
            self._label_edit.setFocus()
            return
        self.accept()

    def build_topic(self) -> Dict[str, Any]:
        raw = {
            "id": self._existing_id,
            "label": self._label_edit.text().strip(),
            "kind": str(self._kind_combo.currentData() or "custom_prompt"),
            "query": self._query_edit.text().strip(),
            "prompt": self._prompt_edit.toPlainText().strip(),
            "enabled": self._enabled_chk.isChecked(),
        }
        return _normalize_topic_entry(raw) or {
            "id": "custom",
            "label": "Custom Topic",
            "kind": "custom_prompt",
            "query": "",
            "prompt": "",
            "enabled": True,
        }


class CharacterPreviewWidget(QtWidgets.QWidget):
    """Mini animated character preview that renders the live character at 30 FPS."""

    def __init__(self, character_id: str, size: int = 76, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._character_id = character_id
        self._size = size
        self.setFixedSize(size, size)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._phase = 0.0
        self._blinking = False
        self._blink_ticks = random.randint(30, 90)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(33)

    def _on_tick(self) -> None:
        self._phase += 0.08
        self._blink_ticks -= 1
        if self._blink_ticks <= 0:
            if self._blinking:
                self._blinking = False
                self._blink_ticks = random.randint(60, 150)
            else:
                self._blinking = True
                self._blink_ticks = 4
        self.update()

    def set_character_id(self, character_id: str) -> None:
        self._character_id = character_id
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        rect = QtCore.QRectF(2, 2, self._size - 4, self._size - 4)
        paint_animated_character(
            self._character_id,
            p,
            rect,
            phase=self._phase,
            state="idle",
            blinking=self._blinking,
            look_x=0.0,
            look_y=0.0,
        )
        p.end()


class AvatarGalleryDialog(QtWidgets.QDialog):
    """Visual gallery dialog for choosing animated character presets."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        current_character_id: str = "lumi",
    ):
        super().__init__(parent)
        self.setWindowTitle("Choose Animated Character Avatar")
        self.setMinimumSize(720, 520)
        self.resize(760, 560)
        self.setStyleSheet(
            "QDialog{background:#0b1120;color:#f8fafc;}"
            "QLabel{color:#f8fafc;}"
            "QPushButton{background:#1e293b;color:#f8fafc;border:1px solid #334155;border-radius:6px;padding:6px 14px;font-size:12px;}"
            "QPushButton:hover{background:#334155;border-color:#38bdf8;}"
            "QPushButton:checked{background:#2563eb;border-color:#60a5fa;font-weight:bold;}"
            "QScrollArea{background:transparent;border:none;}"
        )

        self._selected_id = current_character_id if current_character_id in CHARACTER_PRESETS else "lumi"
        self._cards: Dict[str, QtWidgets.QFrame] = {}
        self._category_buttons: Dict[str, QtWidgets.QPushButton] = {}
        self._current_category = "All"

        vbox = QtWidgets.QVBoxLayout(self)
        vbox.setContentsMargins(16, 14, 16, 14)
        vbox.setSpacing(12)

        # Header title
        header = QtWidgets.QHBoxLayout()
        title_lbl = QtWidgets.QLabel("Animated Character Avatar Gallery")
        title_lbl.setStyleSheet("font-size:16px;font-weight:bold;color:#38bdf8;")
        header.addWidget(title_lbl)
        header.addStretch(1)
        sub_lbl = QtWidgets.QLabel("Live interactive characters with animations, expressions & catchphrases")
        sub_lbl.setStyleSheet("font-size:12px;color:#94a3b8;")
        header.addWidget(sub_lbl)
        vbox.addLayout(header)

        # Category filter bar
        cat_bar = QtWidgets.QHBoxLayout()
        cat_bar.setSpacing(8)
        cat_bar.addWidget(QtWidgets.QLabel("Category:"))
        self._cat_btn_group = QtWidgets.QButtonGroup(self)
        for cat in list_character_categories():
            btn = QtWidgets.QPushButton(cat)
            btn.setCheckable(True)
            if cat == "All":
                btn.setChecked(True)
            btn.clicked.connect(lambda _=False, c=cat: self._filter_category(c))
            self._cat_btn_group.addButton(btn)
            self._category_buttons[cat] = btn
            cat_bar.addWidget(btn)
        cat_bar.addStretch(1)
        vbox.addLayout(cat_bar)

        # Scrollable grid of character cards
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        self._grid = QtWidgets.QGridLayout(container)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(10)

        self._build_cards()
        scroll.setWidget(container)
        vbox.addWidget(scroll, 1)

        # Footer selection details & actions
        footer = QtWidgets.QHBoxLayout()
        footer.setSpacing(12)

        self._status_lbl = QtWidgets.QLabel()
        self._status_lbl.setStyleSheet("font-size:12px;color:#cbd5e1;")
        footer.addWidget(self._status_lbl, 1)

        self._persona_chk = QtWidgets.QCheckBox("Sync AI Persona to character personality")
        self._persona_chk.setChecked(True)
        self._persona_chk.setStyleSheet("color:#e2e8f0;font-size:12px;")
        footer.addWidget(self._persona_chk)

        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)

        apply_btn = QtWidgets.QPushButton("Apply Character Avatar")
        apply_btn.setStyleSheet("background:#2563eb;color:#ffffff;font-weight:bold;padding:7px 18px;")
        apply_btn.clicked.connect(self.accept)
        footer.addWidget(apply_btn)

        vbox.addLayout(footer)
        self._update_selection_ui()

    def _build_cards(self) -> None:
        for c in self._cards.values():
            c.setParent(None)
            c.deleteLater()
        self._cards.clear()

        row = 0
        col = 0
        max_cols = 3

        for pid, preset in CHARACTER_PRESETS.items():
            if self._current_category != "All" and preset.category != self._current_category:
                continue

            card = QtWidgets.QFrame()
            card.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            card.setFixedSize(225, 175)
            card.setObjectName(f"card_{pid}")

            cvbox = QtWidgets.QVBoxLayout(card)
            cvbox.setContentsMargins(10, 10, 10, 10)
            cvbox.setSpacing(6)

            top_h = QtWidgets.QHBoxLayout()
            top_h.setSpacing(8)
            preview = CharacterPreviewWidget(pid, size=58, parent=card)
            top_h.addWidget(preview)

            meta_vbox = QtWidgets.QVBoxLayout()
            meta_vbox.setSpacing(2)
            name_lbl = QtWidgets.QLabel(preset.name)
            name_lbl.setStyleSheet(f"font-size:13px;font-weight:bold;color:{preset.accent_color};")
            meta_vbox.addWidget(name_lbl)

            cat_pill = QtWidgets.QLabel(preset.category)
            cat_pill.setStyleSheet("font-size:10px;color:#94a3b8;background:#1e293b;padding:2px 6px;border-radius:4px;")
            meta_vbox.addWidget(cat_pill)
            top_h.addLayout(meta_vbox, 1)
            cvbox.addLayout(top_h)

            if preset.theme_quote:
                quote_lbl = QtWidgets.QLabel(f'"{preset.theme_quote}"')
                quote_lbl.setWordWrap(True)
                quote_lbl.setStyleSheet("font-size:11px;font-style:italic;color:#38bdf8;")
                cvbox.addWidget(quote_lbl)

            desc_lbl = QtWidgets.QLabel(preset.description)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("font-size:10px;color:#94a3b8;")
            cvbox.addWidget(desc_lbl, 1)

            card.mousePressEvent = lambda e, p_id=pid: self._on_card_clicked(p_id)

            self._grid.addWidget(card, row, col)
            self._cards[pid] = card

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

    def _filter_category(self, cat: str) -> None:
        self._current_category = cat
        self._build_cards()
        self._update_selection_ui()

    def _on_card_clicked(self, pid: str) -> None:
        self._selected_id = pid
        self._update_selection_ui()

    def _update_selection_ui(self) -> None:
        selected_preset = get_character_preset(self._selected_id)
        for pid, card in self._cards.items():
            if pid == self._selected_id:
                card.setStyleSheet(
                    f"QFrame#card_{pid}{{background:#1e293b;border:2px solid {selected_preset.accent_color};border-radius:8px;}}"
                )
            else:
                card.setStyleSheet(
                    f"QFrame#card_{pid}{{background:#111827;border:1px solid #1f2937;border-radius:8px;}}"
                    f"QFrame#card_{pid}:hover{{background:#1e293b;border-color:#475569;}}"
                )

        self._status_lbl.setText(
            f"Selected: <b><font color='{selected_preset.accent_color}'>{selected_preset.name}</font></b> — {selected_preset.category}"
        )

    def get_selected_preset(self) -> Tuple[CharacterPreset, bool]:
        """Return (selected_preset, sync_persona)."""
        preset = get_character_preset(self._selected_id)
        sync_persona = self._persona_chk.isChecked()
        return preset, sync_persona


class SettingsDialog(QtWidgets.QDialog):
    preview_wake_requested = QtCore.Signal()

    def __init__(self, config: CharacterConfig, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Customize Desktop Character")
        self.setMinimumSize(640, 540)
        screen = QtGui.QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1280, 800)
        target_w = min(700, max(640, avail.width() - 80))
        target_h = min(600, max(540, avail.height() - 60))
        self.resize(target_w, target_h)
        self.setStyleSheet(_DARK_DIALOG_QSS)

        self._config = CharacterConfig(**asdict(config))
        self._selected_character_id = self._config.character_id
        self._topics_draft: List[Dict[str, Any]] = _resolved_topics(copy.deepcopy(self._config.custom_topics))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        self._tabs = QtWidgets.QTabWidget()
        self._tabs.addTab(self._build_character_tab(), "Character")
        self._tabs.addTab(self._build_ai_keys_tab(), "AI && API Keys")
        self._tabs.addTab(self._build_pc_files_tab(), "PC && Files")
        self._tabs.addTab(self._build_apis_tab(), "APIs && Tools")
        self._tabs.addTab(self._build_wake_topics_tab(), "Wake-Up && Topics")
        layout.addWidget(self._tabs, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setObjectName("primaryBtn")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _create_form_card(title: str, vertical_spacing: int = 6) -> tuple[QtWidgets.QGroupBox, QtWidgets.QFormLayout]:
        box = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(box)
        form.setContentsMargins(6, 4, 6, 4)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(vertical_spacing)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        return box, form

    @staticmethod
    def _add_option_with_hint(
        parent_layout: QtWidgets.QVBoxLayout,
        checkbox: QtWidgets.QCheckBox,
        hint_text: str,
    ) -> None:
        parent_layout.addWidget(checkbox)
        hint = QtWidgets.QLabel(hint_text)
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:400;margin-left:22px;margin-bottom:2px;")
        parent_layout.addWidget(hint)

    def _build_character_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(tab)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(10)

        persona_box, persona_form = self._create_form_card("Persona && Behavior")
        self._name_edit = QtWidgets.QLineEdit(self._config.character_name)
        persona_form.addRow("Character Name:", self._name_edit)

        self._preset_combo = QtWidgets.QComboBox()
        self._preset_combo.addItem("-- Apply Persona Preset --")
        for key in PERSONA_PRESETS:
            self._preset_combo.addItem(key)
        self._preset_combo.currentTextChanged.connect(self._on_preset_selected)
        persona_form.addRow("Persona Preset:", self._preset_combo)

        self._persona_edit = QtWidgets.QPlainTextEdit(self._config.personality_prompt)
        self._persona_edit.setFixedHeight(96)
        self._persona_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        persona_form.addRow("Personality Prompt:", self._persona_edit)
        vbox.addWidget(persona_box)

        look_box, look_form = self._create_form_card("Appearance && Startup")
        char_row = QtWidgets.QHBoxLayout()
        char_row.setSpacing(8)
        self._current_char_lbl = QtWidgets.QLabel()
        self._update_char_preset_label()
        gallery_btn = QtWidgets.QPushButton("Choose Character Avatar (Gallery)...")
        gallery_btn.setStyleSheet("background:#2563eb;color:#ffffff;font-weight:bold;padding:5px 12px;")
        gallery_btn.clicked.connect(self._open_avatar_gallery)
        char_row.addWidget(self._current_char_lbl, 1)
        char_row.addWidget(gallery_btn)
        look_form.addRow("Character Avatar:", char_row)

        sprite_row = QtWidgets.QHBoxLayout()
        sprite_row.setSpacing(6)
        self._sprite_edit = QtWidgets.QLineEdit(self._config.sprite_path)
        self._sprite_edit.setPlaceholderText("Leave empty for built-in cute animated pet")
        self._sprite_edit.textChanged.connect(lambda _: self._update_char_preset_label())
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_sprite)
        reset_sprite_btn = QtWidgets.QPushButton("Default Pet")
        reset_sprite_btn.clicked.connect(lambda: self._sprite_edit.setText(""))
        sprite_row.addWidget(self._sprite_edit, 1)
        sprite_row.addWidget(browse_btn)
        sprite_row.addWidget(reset_sprite_btn)
        look_form.addRow("Custom Image / GIF:", sprite_row)

        size_row = QtWidgets.QHBoxLayout()
        size_row.setSpacing(8)
        init_size = max(40, min(250, int(self._config.character_size)))
        self._size_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self._size_slider.setRange(40, 250)
        self._size_slider.setValue(init_size)
        self._size_spin = QtWidgets.QSpinBox()
        self._size_spin.setRange(40, 250)
        self._size_spin.setSingleStep(5)
        self._size_spin.setValue(init_size)
        self._size_spin.setSuffix(" px")
        self._size_spin.setMinimumWidth(82)
        self._size_slider.valueChanged.connect(self._size_spin.setValue)
        self._size_spin.valueChanged.connect(self._size_slider.setValue)
        size_row.addWidget(self._size_slider, 1)
        size_row.addWidget(self._size_spin)
        look_form.addRow("Character Size:", size_row)

        self._initial_startup = is_startup_enabled()
        self._startup_chk = QtWidgets.QCheckBox("Launch automatically when Windows starts")
        self._startup_chk.setChecked(self._initial_startup)
        if sys.platform != "win32":
            self._startup_chk.setEnabled(False)
        look_form.addRow("", self._startup_chk)
        vbox.addWidget(look_box)
        vbox.addStretch(1)
        return tab

    def _build_ai_keys_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(tab)
        vbox.setContentsMargins(12, 8, 12, 8)
        vbox.setSpacing(8)

        ai_box, ai_form = self._create_form_card("AI Provider && Model", vertical_spacing=6)
        self._provider_combo = QtWidgets.QComboBox()
        self._provider_combo.addItems(list(chatbot.PROVIDER_SPECS.keys()))
        self._provider_combo.setCurrentText(self._config.provider)
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        ai_form.addRow("AI Provider:", self._provider_combo)

        model_row = QtWidgets.QHBoxLayout()
        model_row.setSpacing(6)
        self._model_combo = QtWidgets.QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._model_combo.setMinimumContentsLength(18)
        initial_model = chatbot.normalize_model_for_provider(self._config.provider, self._config.model_name)
        self._populate_models(self._config.provider, selected_model=initial_model, query_live=False)
        refresh_models_btn = QtWidgets.QPushButton("Refresh")
        refresh_models_btn.setToolTip("Fetch currently active models for this provider")
        refresh_models_btn.clicked.connect(self._on_refresh_models)
        model_row.addWidget(self._model_combo, 1)
        model_row.addWidget(refresh_models_btn)
        ai_form.addRow("Model ID:", model_row)

        self._provider_hint_lbl = QtWidgets.QLabel()
        self._provider_hint_lbl.setWordWrap(True)
        self._provider_hint_lbl.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.MinimumExpanding,
        )
        self._provider_hint_lbl.setMinimumHeight(34)
        self._provider_hint_lbl.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:400;padding:2px 0;")
        ai_form.addRow("", self._provider_hint_lbl)
        self._refresh_provider_hint(self._config.provider)

        self._thinking_combo = QtWidgets.QComboBox()
        self._thinking_combo.addItems(["LOW", "MEDIUM", "HIGH"])
        self._thinking_combo.setCurrentText(self._config.thinking_level)
        ai_form.addRow("Gemini Thinking:", self._thinking_combo)

        self._tools_chk = QtWidgets.QCheckBox("Enable Web && API Tools (Live Weather, Gold, News, Search, APIs)")
        self._tools_chk.setChecked(self._config.use_tools)
        ai_form.addRow("", self._tools_chk)
        vbox.addWidget(ai_box)

        keys_box = QtWidgets.QGroupBox("API Keys (saved locally to .env)")
        keys_grid = QtWidgets.QGridLayout(keys_box)
        keys_grid.setContentsMargins(8, 6, 8, 6)
        keys_grid.setHorizontalSpacing(10)
        keys_grid.setVerticalSpacing(5)
        keys_grid.setColumnStretch(1, 1)
        keys_grid.setColumnStretch(3, 1)
        key_specs = (
            ("_gemini_key_edit", "Gemini Key:", chatbot.resolve_api_key("gemini"), "GEMINI_API_KEY"),
            ("_openai_key_edit", "OpenAI Key:", chatbot.resolve_api_key("openai"), "OPENAI_API_KEY (sk-...)"),
            ("_deepseek_key_edit", "DeepSeek Key:", chatbot.resolve_api_key("deepseek"), "DEEPSEEK_API_KEY (sk-...)"),
            ("_groq_key_edit", "Groq Key:", chatbot.resolve_api_key("groq"), "GROQ_API_KEY (gsk_...)"),
            ("_grok_key_edit", "Grok (xAI):", chatbot.resolve_api_key("grok"), "GROK_API_KEY (xai-...)"),
            ("_nvidia_key_edit", "NVIDIA Key:", chatbot.resolve_api_key("nvidia"), "NVIDIA_API_KEY"),
            ("_tavily_key_edit", "Tavily Key:", os.getenv("TAVILY_API_KEY"), "TAVILY_API_KEY (tvly-...)"),
        )
        for idx, (attr_name, label, existing_val, empty_hint) in enumerate(key_specs):
            edit = QtWidgets.QLineEdit()
            edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
            edit.setMinimumWidth(135)
            edit.setPlaceholderText("Configured (blank = keep)" if existing_val else empty_hint)
            setattr(self, attr_name, edit)
            r, col_pair = divmod(idx, 2)
            lbl = QtWidgets.QLabel(label)
            keys_grid.addWidget(lbl, r, col_pair * 2)
            keys_grid.addWidget(edit, r, col_pair * 2 + 1)
        saved_hint = QtWidgets.QLabel("Masked locally · only entered keys are updated")
        saved_hint.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:400;")
        keys_grid.addWidget(saved_hint, 3, 2, 1, 2)
        vbox.addWidget(keys_box)
        vbox.addStretch(1)
        return tab

    def _build_pc_files_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(tab)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(10)

        perm_box = QtWidgets.QGroupBox("Permissions && Safety")
        perm_layout = QtWidgets.QVBoxLayout(perm_box)
        perm_layout.setContentsMargins(8, 6, 8, 6)
        perm_layout.setSpacing(6)

        self._sys_tools_chk = QtWidgets.QCheckBox("Enable PC && File Control Tools")
        self._sys_tools_chk.setChecked(self._config.enable_system_tools)
        self._add_option_with_hint(
            perm_layout,
            self._sys_tools_chk,
            "Search files, check folder sizes, read/create/copy/move items, inspect Recycle Bin, "
            "clipboard actions, and open or close running apps.",
        )

        self._confirm_launch_chk = QtWidgets.QCheckBox("Ask Allow/Deny confirmation before opening apps")
        self._confirm_launch_chk.setChecked(self._config.confirm_app_launch)
        self._add_option_with_hint(
            perm_layout,
            self._confirm_launch_chk,
            "Recycle Bin deletes, moves/renames, overwrites, and closing running apps always ask Allow / Deny.",
        )

        self._all_folders_chk = QtWidgets.QCheckBox("Control All Drives (Full PC Access)")
        self._all_folders_chk.setChecked(self._config.allow_all_user_folders)
        self._add_option_with_hint(
            perm_layout,
            self._all_folders_chk,
            "Access C:\\, D:\\, K:\\, etc. beyond Allowed Folders. Windows OS dirs, protected apps, "
            "and .env / .git folders stay blocked.",
        )
        vbox.addWidget(perm_box)

        folders_box = QtWidgets.QGroupBox("Allowed Folders Whitelist")
        folders_layout = QtWidgets.QVBoxLayout(folders_box)
        folders_layout.setContentsMargins(8, 6, 8, 6)
        folders_layout.setSpacing(6)

        folders_hint = QtWidgets.QLabel(
            "Active when Control All Drives is unchecked (one folder path or drive root per line):"
        )
        folders_hint.setWordWrap(True)
        folders_hint.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:400;")
        folders_layout.addWidget(folders_hint)

        self._allowed_dirs_edit = QtWidgets.QPlainTextEdit(
            "\n".join(self._config.allowed_folders or system_tools.default_allowed_dir_strings())
        )
        self._allowed_dirs_edit.setMinimumHeight(104)
        self._allowed_dirs_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._allowed_dirs_edit.setPlaceholderText("One allowed folder or drive root per line")
        folders_layout.addWidget(self._allowed_dirs_edit, 1)

        folder_btns = QtWidgets.QHBoxLayout()
        folder_btns.setSpacing(8)
        add_dir_btn = QtWidgets.QPushButton("Add Folder...")
        add_dir_btn.clicked.connect(self._browse_allowed_folder)
        add_drives_btn = QtWidgets.QPushButton("Add All Drives")
        add_drives_btn.setToolTip("Add every ready drive root (C:\\, D:\\, K:\\, etc.) to Allowed Folders")
        add_drives_btn.clicked.connect(self._add_all_drives)
        folder_btns.addWidget(add_dir_btn)
        folder_btns.addWidget(add_drives_btn)
        folder_btns.addStretch(1)
        folders_layout.addLayout(folder_btns)
        vbox.addWidget(folders_box, 1)
        return tab

    def _sync_tools_checkboxes(self, source: QtWidgets.QCheckBox, checked: bool) -> None:
        other = self._apis_tools_chk if source is self._tools_chk else self._tools_chk
        if other.isChecked() != checked:
            other.blockSignals(True)
            other.setChecked(checked)
            other.blockSignals(False)

    def _build_apis_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(tab)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(10)

        self._apis_tools_chk = QtWidgets.QCheckBox(
            "Enable Web && API Tools (Weather, Search, Gold, News, Maps, DB, Custom APIs)"
        )
        self._apis_tools_chk.setChecked(self._tools_chk.isChecked())
        self._tools_chk.toggled.connect(lambda c: self._sync_tools_checkboxes(self._tools_chk, c))
        self._apis_tools_chk.toggled.connect(lambda c: self._sync_tools_checkboxes(self._apis_tools_chk, c))
        vbox.addWidget(self._apis_tools_chk)

        custom_box = QtWidgets.QGroupBox("Custom && Company Internal APIs (custom_apis.json)")
        custom_layout = QtWidgets.QVBoxLayout(custom_box)
        custom_layout.setContentsMargins(8, 6, 8, 6)
        custom_layout.setSpacing(6)

        custom_hint = QtWidgets.QLabel(
            "Register any internal company endpoint, webhook, or third-party REST API. "
            "Read-only GET calls run automatically; POST/PUT/DELETE ask Allow / Deny."
        )
        custom_hint.setWordWrap(True)
        custom_hint.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:400;")
        custom_layout.addWidget(custom_hint)

        self._custom_apis_list = QtWidgets.QListWidget()
        self._custom_apis_list.setMinimumHeight(145)
        self._custom_apis_list.itemDoubleClicked.connect(lambda _item: self._edit_custom_api())
        custom_layout.addWidget(self._custom_apis_list, 1)

        api_btns = QtWidgets.QHBoxLayout()
        api_btns.setSpacing(6)
        add_btn = QtWidgets.QPushButton("Add Custom API...")
        add_btn.clicked.connect(self._add_custom_api)
        edit_btn = QtWidgets.QPushButton("Edit...")
        edit_btn.clicked.connect(self._edit_custom_api)
        del_btn = QtWidgets.QPushButton("Remove")
        del_btn.clicked.connect(self._delete_custom_api)
        test_btn = QtWidgets.QPushButton("Test Call")
        test_btn.clicked.connect(self._test_custom_api)
        api_btns.addWidget(add_btn)
        api_btns.addWidget(edit_btn)
        api_btns.addWidget(del_btn)
        api_btns.addWidget(test_btn)
        api_btns.addStretch(1)
        custom_layout.addLayout(api_btns)
        vbox.addWidget(custom_box, 1)

        builtin_box = QtWidgets.QGroupBox("Built-in Service Connectors")
        builtin_layout = QtWidgets.QVBoxLayout(builtin_box)
        builtin_layout.setContentsMargins(8, 6, 8, 6)
        builtin_layout.setSpacing(6)

        free_lbl = QtWidgets.QLabel(
            "Work free with zero keys: Live Weather (Open-Meteo), Web Search fallback (DuckDuckGo), "
            "Latest News (RSS), Places/Geocode (OpenStreetMap), and local SQLite."
        )
        free_lbl.setWordWrap(True)
        free_lbl.setStyleSheet("color:#94a3b8;font-size:11px;font-weight:400;")
        builtin_layout.addWidget(free_lbl)

        self._builtin_status_lbl = QtWidgets.QLabel()
        self._builtin_status_lbl.setWordWrap(True)
        self._builtin_status_lbl.setStyleSheet("color:#cbd5e1;font-size:11px;font-weight:600;")
        builtin_layout.addWidget(self._builtin_status_lbl)

        cred_row = QtWidgets.QHBoxLayout()
        cred_btn = QtWidgets.QPushButton("Configure API Credentials (Maps, DB, Email, Calendar, Payments)...")
        cred_btn.clicked.connect(self._open_builtin_credentials)
        cred_row.addWidget(cred_btn)
        cred_row.addStretch(1)
        builtin_layout.addLayout(cred_row)
        vbox.addWidget(builtin_box)

        self._refresh_custom_apis_list()
        self._refresh_builtin_status()
        return tab

    def _build_wake_topics_tab(self) -> QtWidgets.QWidget:
        tab = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(tab)
        vbox.setContentsMargins(12, 8, 12, 8)
        vbox.setSpacing(8)

        wake_box = QtWidgets.QGroupBox("Wake-Up Greeting && Schedule")
        wake_layout = QtWidgets.QVBoxLayout(wake_box)
        wake_layout.setContentsMargins(8, 6, 8, 6)
        wake_layout.setSpacing(5)

        self._wake_enabled_chk = QtWidgets.QCheckBox("Greet me automatically when Lumi starts or wakes up")
        self._wake_enabled_chk.setChecked(bool(self._config.wake_greeting_enabled))
        wake_layout.addWidget(self._wake_enabled_chk)

        self._wake_open_chat_chk = QtWidgets.QCheckBox(
            "Also open interactive Chat Popup on startup (without stealing focus)"
        )
        self._wake_open_chat_chk.setChecked(bool(self._config.wake_open_chat))
        wake_layout.addWidget(self._wake_open_chat_chk)

        self._wake_resume_chk = QtWidgets.QCheckBox(
            "Greet me again when Windows wakes from Sleep / Hibernate"
        )
        self._wake_resume_chk.setChecked(bool(self._config.wake_on_system_resume))
        wake_layout.addWidget(self._wake_resume_chk)

        self._wake_briefing_chk = QtWidgets.QCheckBox(
            "Auto-fetch live headlines, weather & gold rate at wake-up (runs in background)"
        )
        self._wake_briefing_chk.setChecked(bool(self._config.wake_auto_fetch_briefing))
        wake_layout.addWidget(self._wake_briefing_chk)

        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QtWidgets.QLabel("Your Name:"))
        self._wake_user_edit = QtWidgets.QLineEdit(self._config.wake_user_name)
        self._wake_user_edit.setPlaceholderText("Optional (e.g., Alex)")
        row1.addWidget(self._wake_user_edit, 1)

        row1.addWidget(QtWidgets.QLabel("Weather City:"))
        self._wake_city_edit = QtWidgets.QLineEdit(self._config.wake_weather_city)
        self._wake_city_edit.setPlaceholderText("e.g., Chennai")
        row1.addWidget(self._wake_city_edit, 1)
        wake_layout.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QtWidgets.QLabel("Resume Cooldown:"))
        self._wake_cooldown_spin = QtWidgets.QSpinBox()
        self._wake_cooldown_spin.setRange(1, 1440)
        self._wake_cooldown_spin.setValue(int(self._config.wake_resume_cooldown_minutes))
        self._wake_cooldown_spin.setSuffix(" min")
        row2.addWidget(self._wake_cooldown_spin)
        row2.addStretch(1)

        preview_btn = QtWidgets.QPushButton("Preview Wake-Up Now")
        preview_btn.setToolTip("Show the floating bubble and chat wake greeting right now")
        preview_btn.clicked.connect(self.preview_wake_requested.emit)
        row2.addWidget(preview_btn)
        wake_layout.addLayout(row2)
        vbox.addWidget(wake_box)

        topics_box = QtWidgets.QGroupBox("Customizable Daily Topics (Shown in Greeting && Quick Chips)")
        topics_layout = QtWidgets.QVBoxLayout(topics_box)
        topics_layout.setContentsMargins(8, 6, 8, 6)
        topics_layout.setSpacing(6)

        self._topics_list = QtWidgets.QListWidget()
        self._topics_list.setMinimumHeight(115)
        self._topics_list.itemDoubleClicked.connect(lambda _item: self._edit_topic())
        topics_layout.addWidget(self._topics_list, 1)

        topic_btns = QtWidgets.QHBoxLayout()
        topic_btns.setSpacing(5)
        for caption, handler in (
            ("Add...", self._add_topic),
            ("Edit...", self._edit_topic),
            ("Toggle ON/OFF", self._toggle_topic),
            ("Remove", self._remove_topic),
            ("Up", lambda: self._move_topic(-1)),
            ("Down", lambda: self._move_topic(1)),
            ("Reset Defaults", self._reset_default_topics),
        ):
            btn = QtWidgets.QPushButton(caption)
            btn.clicked.connect(handler)
            topic_btns.addWidget(btn)
        topic_btns.addStretch(1)
        topics_layout.addLayout(topic_btns)
        vbox.addWidget(topics_box, 1)

        self._refresh_topics_list()
        return tab

    def _refresh_topics_list(self, select_row: Optional[int] = None) -> None:
        self._topics_list.clear()
        for t in self._topics_draft:
            tag = "ON" if t.get("enabled", True) else "OFF"
            kind = str(t.get("kind") or "custom_prompt")
            detail = str(t.get("query") or t.get("prompt") or "").strip()
            suffix = f" — {detail[:48]}" if detail else ""
            item = QtWidgets.QListWidgetItem(f"[{tag}] {t['label']} ({kind}){suffix}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, t["id"])
            self._topics_list.addItem(item)
        if select_row is not None and 0 <= select_row < self._topics_list.count():
            self._topics_list.setCurrentRow(select_row)

    def _add_topic(self) -> None:
        dlg = TopicEditorDialog(parent=self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            topic = dlg.build_topic()
            self._topics_draft.append(topic)
            self._topics_draft = _resolved_topics(self._topics_draft)
            self._refresh_topics_list(select_row=len(self._topics_draft) - 1)

    def _edit_topic(self) -> None:
        row = self._topics_list.currentRow()
        if row < 0 or row >= len(self._topics_draft):
            return
        dlg = TopicEditorDialog(topic=self._topics_draft[row], parent=self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self._topics_draft[row] = dlg.build_topic()
            self._topics_draft = _resolved_topics(self._topics_draft)
            self._refresh_topics_list(select_row=min(row, len(self._topics_draft) - 1))

    def _toggle_topic(self) -> None:
        row = self._topics_list.currentRow()
        if row < 0 or row >= len(self._topics_draft):
            return
        self._topics_draft[row]["enabled"] = not bool(self._topics_draft[row].get("enabled", True))
        self._refresh_topics_list(select_row=row)

    def _remove_topic(self) -> None:
        row = self._topics_list.currentRow()
        if row < 0 or row >= len(self._topics_draft):
            return
        self._topics_draft.pop(row)
        self._refresh_topics_list(select_row=min(row, len(self._topics_draft) - 1))

    def _move_topic(self, delta: int) -> None:
        row = self._topics_list.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= len(self._topics_draft):
            return
        self._topics_draft[row], self._topics_draft[target] = (
            self._topics_draft[target],
            self._topics_draft[row],
        )
        self._refresh_topics_list(select_row=target)

    def _reset_default_topics(self) -> None:
        self._topics_draft = default_custom_topics()
        self._refresh_topics_list(select_row=0 if self._topics_draft else None)

    def _refresh_custom_apis_list(self) -> None:
        self._custom_apis_list.clear()
        for ep in api_tools.load_custom_apis():
            tag = "ON" if ep.enabled else "OFF"
            text = f"[{tag}] {ep.name} ({ep.category}) — {ep.method} {ep.base_url}{ep.default_path}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, ep.id)
            self._custom_apis_list.addItem(item)

    def _refresh_builtin_status(self) -> None:
        checks = [
            ("OpenWeather", bool(os.getenv("OPENWEATHER_API_KEY"))),
            ("NewsAPI", bool(os.getenv("NEWSAPI_KEY"))),
            ("Google Maps", bool(os.getenv("GOOGLE_MAPS_API_KEY"))),
            ("Database", bool(os.getenv("SQLITE_DB_PATH") or os.getenv("DATABASE_API_URL"))),
            ("Email", bool(os.getenv("EMAIL_USER") and os.getenv("EMAIL_PASSWORD"))),
            ("Calendar", bool(os.getenv("GOOGLE_CALENDAR_TOKEN") or os.getenv("CALENDAR_ICS_URL") or os.getenv("CALENDAR_ICS_PATH"))),
            ("Payments", bool(os.getenv("STRIPE_API_KEY") or (os.getenv("RAZORPAY_KEY_ID") and os.getenv("RAZORPAY_KEY_SECRET")))),
        ]
        summary = " · ".join(f"{name}: {'Configured' if ok else 'Not set'}" for name, ok in checks)
        self._builtin_status_lbl.setText(f"Optional/Pro Keys: {summary}")

    def _selected_custom_api(self) -> Optional[api_tools.CustomApiEndpoint]:
        item = self._custom_apis_list.currentItem()
        if item is None:
            return None
        api_id = str(item.data(QtCore.Qt.ItemDataRole.UserRole) or "")
        for ep in api_tools.load_custom_apis():
            if ep.id == api_id:
                return ep
        return None

    def _add_custom_api(self) -> None:
        dlg = CustomApiEditorDialog(parent=self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            api_tools.upsert_custom_api(dlg.build_endpoint())
            dlg.save_secret_if_entered()
            self._refresh_custom_apis_list()

    def _edit_custom_api(self) -> None:
        ep = self._selected_custom_api()
        if ep is None:
            return
        dlg = CustomApiEditorDialog(endpoint=ep, parent=self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            api_tools.upsert_custom_api(dlg.build_endpoint())
            dlg.save_secret_if_entered()
            self._refresh_custom_apis_list()

    def _delete_custom_api(self) -> None:
        ep = self._selected_custom_api()
        if ep is None:
            return
        api_tools.delete_custom_api(ep.id)
        self._refresh_custom_apis_list()

    def _test_custom_api(self) -> None:
        ep = self._selected_custom_api()
        if ep is None:
            return

        def _confirm_test(title: str, detail: str, _risk: str) -> bool:
            res = QtWidgets.QMessageBox.question(
                self,
                title,
                detail,
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            )
            return res == QtWidgets.QMessageBox.StandardButton.Yes

        policy = api_tools.ApiToolsPolicy(confirm_callback=_confirm_test)
        out = api_tools.call_custom_api(ep.id, policy=policy)
        QtWidgets.QMessageBox.information(self, f"Test Result: {ep.name}", out[:1200])

    def _open_builtin_credentials(self) -> None:
        dlg = BuiltInApisDialog(parent=self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            dlg.save_to_env()
            self._refresh_builtin_status()

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
        elif provider == "openai":
            self._provider_hint_lbl.setText(
                "OpenAI (api.openai.com, sk-... key at platform.openai.com) · Models: gpt-4.1-mini, gpt-4.1, gpt-5-mini, gpt-4o, o4-mini"
            )
        elif provider == "deepseek":
            self._provider_hint_lbl.setText(
                "DeepSeek (api.deepseek.com, sk-... key at platform.deepseek.com) · Models: deepseek-chat (V3), deepseek-reasoner (R1)"
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

    def _open_avatar_gallery(self) -> None:
        dlg = AvatarGalleryDialog(self, current_character_id=self._selected_character_id)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            preset, sync_persona = dlg.get_selected_preset()
            self._selected_character_id = preset.id
            self._name_edit.setText(preset.name)
            self._sprite_edit.setText("")
            if sync_persona and preset.personality_prompt:
                self._persona_edit.setPlainText(preset.personality_prompt)
            self._update_char_preset_label()

    def _update_char_preset_label(self) -> None:
        preset = get_character_preset(self._selected_character_id)
        sprite_val = self._sprite_edit.text().strip() if hasattr(self, "_sprite_edit") else ""
        if sprite_val:
            self._current_char_lbl.setText(f"Custom Sprite ({Path(sprite_val).name})")
        else:
            self._current_char_lbl.setText(
                f"<b><font color='{preset.accent_color}'>{preset.name}</font></b> ({preset.category})"
            )

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
        self._config.character_id = self._selected_character_id
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
        self._config.wake_greeting_enabled = self._wake_enabled_chk.isChecked()
        self._config.wake_open_chat = self._wake_open_chat_chk.isChecked()
        self._config.wake_on_system_resume = self._wake_resume_chk.isChecked()
        self._config.wake_auto_fetch_briefing = self._wake_briefing_chk.isChecked()
        self._config.wake_user_name = self._wake_user_edit.text().strip()
        self._config.wake_weather_city = self._wake_city_edit.text().strip() or "Chennai"
        self._config.wake_resume_cooldown_minutes = int(self._wake_cooldown_spin.value())
        self._config.custom_topics = _resolved_topics(copy.deepcopy(self._topics_draft))
        return self._config

    def apply_system_changes(self, env_path: Optional[Path] = None, startup_dir: Optional[Path] = None) -> bool:
        """Persist any newly entered API keys to .env and update Windows Startup if toggled."""
        keys_changed = False
        for field_edit, env_name in (
            (self._gemini_key_edit, "GEMINI_API_KEY"),
            (self._openai_key_edit, "OPENAI_API_KEY"),
            (self._deepseek_key_edit, "DEEPSEEK_API_KEY"),
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
        if desired_startup != self._initial_startup or (desired_startup and startup_dir is None):
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
        self._briefing_thread: Optional[QtCore.QThread] = None
        self._briefing_worker: Optional[WakeBriefingWorker] = None
        self._startup_wake_timer: Optional[QtCore.QTimer] = None
        self._last_wake_monotonic = -1e9

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
                api_policy=self._build_api_policy(config),
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
        self.wakeup_bubble = WakeupBubbleWidget(config.character_name)
        self.popup = ChatPopupWindow(config)
        self._tray = self._create_tray_icon()

        # Wire character signals
        self.character.clicked.connect(self.toggle_popup)
        self.character.greet_requested.connect(self.greet_now)
        self.character.moved.connect(self._on_character_moved)
        self.character.sprite_dropped.connect(self._on_sprite_changed)
        self.character.size_change_requested.connect(self._on_size_changed)
        self.character.open_settings_requested.connect(self.open_settings)
        self.character.avatar_gallery_requested.connect(self.open_avatar_gallery)
        self.character.avatar_preset_requested.connect(self.switch_character_preset)
        self.character.clear_chat_requested.connect(self.clear_conversation)
        self.character.system_tools_toggled.connect(self.toggle_system_tools)
        self.character.all_drives_toggled.connect(self.toggle_all_drives)
        self.character.provider_change_requested.connect(self.switch_provider)
        self.character.reset_pos_requested.connect(self.reset_position)
        self.character.hide_requested.connect(self.hide_character)
        self.character.quit_requested.connect(self.quit_app)
        self.wakeup_bubble.chat_requested.connect(self._on_wakeup_bubble_clicked)

        # Wire popup signals
        self.popup.send_message.connect(self.send_user_message)
        self.popup.stop_requested.connect(self.stop_streaming)
        self.popup.clear_requested.connect(self.clear_conversation)
        self.popup.settings_requested.connect(self.open_settings)
        self.popup.briefing_requested.connect(self.fetch_live_briefing)
        self.popup.mock_mode_requested.connect(lambda: self.switch_provider("mock"))
        self.popup.provider_switch_requested.connect(
            lambda p, m: self.switch_provider(p, m or None)
        )
        self.popup.enable_web_tools_requested.connect(lambda: self.toggle_web_tools(True))

        # Single-instance listener
        self._instance_guard: Optional[SingleInstanceGuard] = None

        # Global Windows hotkey (Ctrl+Shift+Space) + Windows power resume wake-up hook
        self._hotkey_filter = WindowsHotkeyFilter(
            self.summon_from_hotkey,
            on_system_resume=self._on_system_resume,
        )
        if config.hotkey_enabled:
            self._hotkey_filter.register()
        if sys.platform == "win32":
            self._app.installNativeEventFilter(self._hotkey_filter)

        self._restore_or_default_position()

    def _create_tray_icon(self) -> QtWidgets.QSystemTrayIcon:
        tray = QtWidgets.QSystemTrayIcon(
            QtGui.QIcon(draw_pet_pixmap(64, self._config.sprite_path, self._config.character_id)),
            self,
        )
        tray.setToolTip(f"{self._config.character_name} Desktop Companion (Ctrl+Shift+Space)")

        menu = QtWidgets.QMenu(self.character)
        menu.addAction("Show / Toggle Chat", self.summon_from_hotkey)
        menu.addAction("Greet Me / Daily Topics", self.greet_now)
        menu.addAction("Show Character", self.show_character)
        menu.addAction("Customize Character...", self.open_settings)
        menu.addAction("Choose Character Avatar (Gallery)...", self.open_avatar_gallery)

        avatar_menu = menu.addMenu("Switch Character Avatar")
        for pid, preset in CHARACTER_PRESETS.items():
            pa = avatar_menu.addAction(f"{preset.name} ({preset.category})")
            pa.setCheckable(True)
            pa.setChecked(self._config.character_id == pid and not self._config.sprite_path)
            pa.triggered.connect(lambda _=False, p_id=pid: self.switch_character_preset(p_id))

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

    def start(self, startup_launch: bool = False) -> None:
        self.character.show()
        if self._config.wake_greeting_enabled:
            delay_ms = 2500 if startup_launch else 150
            self._startup_wake_timer = QtCore.QTimer(self)
            self._startup_wake_timer.setSingleShot(True)
            self._startup_wake_timer.timeout.connect(
                lambda: self.trigger_wake_greeting(open_chat=self._config.wake_open_chat, system_resume=False)
            )
            self._startup_wake_timer.start(delay_ms)
        else:
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
        if self.wakeup_bubble.isVisible():
            self.wakeup_bubble.reposition_near(self.character.frameGeometry())

    def _on_character_moved(self, x: int, y: int) -> None:
        self._config.window_pos = [x, y]
        self._config.save()
        if self.popup.isVisible() and not self.popup.is_pinned():
            self._position_popup_near_character()
        if self.wakeup_bubble.isVisible():
            self.wakeup_bubble.reposition_near(self.character.frameGeometry())

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
        self.wakeup_bubble.hide()
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
            self.popup.hide_animated()
        else:
            self.wakeup_bubble.hide()
            self.show_character()
            self._position_popup_near_character()
            self.popup.show_animated()

    def summon_from_hotkey(self) -> None:
        if not self.character.isVisible():
            self.wakeup_bubble.hide()
            self.show_character()
            self._position_popup_near_character()
            self.popup.show_animated()
        else:
            self.toggle_popup()

    def trigger_wake_greeting(
        self,
        open_chat: Optional[bool] = None,
        system_resume: bool = False,
        override_config: Optional[CharacterConfig] = None,
        force_briefing: bool = False,
    ) -> None:
        """Display Lumi's wake-up greeting bubble and interactive daily-topic card."""
        cfg = override_config or self._config
        self._last_wake_monotonic = time.monotonic()
        self.show_character()
        self.character.set_state("happy")

        data = build_wake_greeting_data(cfg, system_resume=system_resume)
        self.character.show_speech_bubble(data["bubble_text"], duration_ms=10000)
        self.wakeup_bubble.set_character_name(cfg.character_name)
        self.wakeup_bubble.show_for_character(
            self.character.frameGeometry(),
            data["bubble_text"],
            duration_ms=12000,
        )

        self.popup.show_wake_greeting(data, include_briefing_placeholder=False)
        should_open = cfg.wake_open_chat if open_chat is None else bool(open_chat)
        if should_open:
            self._position_popup_near_character()
            self.popup.show_passive()

        if force_briefing or (cfg.wake_auto_fetch_briefing and cfg.use_tools):
            self.fetch_live_briefing(override_config=cfg)

    def greet_now(self) -> None:
        """Manual trigger (context menu / tray) to greet and open daily topics immediately."""
        self.trigger_wake_greeting(open_chat=True, system_resume=False)
        self.popup.focus_input()

    def _on_wakeup_bubble_clicked(self) -> None:
        self.show_character()
        self._position_popup_near_character()
        self.popup.show()
        self.popup.focus_input()

    def _on_system_resume(self) -> None:
        """Respond to Windows Sleep/Hibernate resume subject to cooldown."""
        if not self._config.wake_greeting_enabled or not self._config.wake_on_system_resume:
            return
        cooldown_sec = max(60, int(self._config.wake_resume_cooldown_minutes) * 60)
        if (time.monotonic() - self._last_wake_monotonic) < cooldown_sec:
            return
        self.trigger_wake_greeting(open_chat=self._config.wake_open_chat, system_resume=True)

    def fetch_live_briefing(self, override_config: Optional[CharacterConfig] = None) -> None:
        """Fetch live summaries for enabled daily topics on a background thread."""
        if self._briefing_thread is not None and self._briefing_thread.isRunning():
            return
        cfg = override_config or self._config
        if self.popup._wake_briefing_browser is None:
            self.popup.show_wake_greeting(build_wake_greeting_data(cfg), include_briefing_placeholder=True)
        else:
            self.popup.set_wake_briefing_loading()

        thread = QtCore.QThread(self)
        worker = WakeBriefingWorker(cfg)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.briefing_ready.connect(self.popup.set_wake_briefing_markdown)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_briefing_thread_finished)

        self._briefing_thread = thread
        self._briefing_worker = worker
        thread.start()

    def _on_briefing_thread_finished(self) -> None:
        self._briefing_thread = None
        self._briefing_worker = None

    def _resolved_allowed_roots(self, cfg: CharacterConfig) -> List[Path]:
        roots = [
            Path(p).expanduser()
            for p in (cfg.allowed_folders or [])
            if str(p).strip()
        ]
        return roots or system_tools.default_allowed_dirs()

    def _confirm_proxy_fn(self) -> Any:
        weak_self = weakref.ref(self)

        def _confirm_proxy(title: str, detail: str, risk: str) -> bool:
            owner = weak_self()
            return owner._confirm_on_ui(title, detail, risk) if owner is not None else False

        return _confirm_proxy

    def _build_api_policy(self, cfg: CharacterConfig) -> api_tools.ApiToolsPolicy:
        return api_tools.ApiToolsPolicy(
            confirm_callback=self._confirm_proxy_fn(),
            allowed_roots=self._resolved_allowed_roots(cfg),
            allow_all_non_system=bool(cfg.allow_all_user_folders),
        )

    def _build_system_policy(self, cfg: CharacterConfig) -> system_tools.SystemToolsPolicy:
        roots = self._resolved_allowed_roots(cfg)
        # Use weakref proxies so ChatbotConfig -> policy never keeps a
        # strong reference cycle back to DesktopCompanionApp (QObject).
        weak_self = weakref.ref(self)

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
            confirm_callback=self._confirm_proxy_fn(),
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
        QtWidgets.QApplication.processEvents()
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
            QtWidgets.QApplication.processEvents()
            return f"Copied {len(text)} character(s) to clipboard."
        if action == "copy_files":
            mime = QtCore.QMimeData()
            mime.setUrls([QtCore.QUrl.fromLocalFile(p) for p in paths])
            mime.setText("\n".join(paths))
            cb.setMimeData(mime)
            QtWidgets.QApplication.processEvents()
            return (
                f"Copied {len(paths)} file/folder path(s) to Windows clipboard "
                "(ready for Ctrl+V paste)."
            )
        return f"Error: Unsupported clipboard action '{action}'."

    def toggle_web_tools(self, enabled: bool) -> None:
        self._config.use_tools = bool(enabled)
        self._apply_updated_config(self._config)
        state = "enabled" if self._config.use_tools else "disabled"
        self.character.show_speech_bubble(f"Web & API Tools {state}!")

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
                api_policy=self._build_api_policy(new_cfg),
                system_prompt=build_effective_system_prompt(
                    new_cfg.character_name,
                    new_cfg.personality_prompt,
                    new_cfg.use_tools,
                    enable_system_tools=new_cfg.enable_system_tools,
                    allow_all_drives=bool(new_cfg.allow_all_user_folders),
                ),
            )
        self.character.apply_config(new_cfg)
        self.wakeup_bubble.set_character_name(new_cfg.character_name)
        self.popup.apply_config(new_cfg)
        self._tray.setIcon(QtGui.QIcon(draw_pet_pixmap(64, new_cfg.sprite_path, new_cfg.character_id)))
        self._tray.setToolTip(f"{new_cfg.character_name} Desktop Companion (Ctrl+Shift+Space)")
        if self.popup.isVisible() and not self.popup.is_pinned():
            self._position_popup_near_character()
        if self.wakeup_bubble.isVisible():
            self.wakeup_bubble.reposition_near(self.character.frameGeometry())

    def _on_size_changed(self, new_size: int) -> None:
        clamped = max(40, min(260, int(new_size)))
        self._config.character_size = clamped
        self._config.save()
        self.character.apply_config(self._config)
        self.character.show_speech_bubble(f"Size: {clamped}px", duration_ms=1500)
        if self.popup.isVisible() and not self.popup.is_pinned():
            self._position_popup_near_character()
        if self.wakeup_bubble.isVisible():
            self.wakeup_bubble.reposition_near(self.character.frameGeometry())

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

    def open_avatar_gallery(self) -> None:
        dlg = AvatarGalleryDialog(
            self.popup if self.popup.isVisible() else self.character,
            current_character_id=self._config.character_id,
        )
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            preset, sync_persona = dlg.get_selected_preset()
            self.switch_character_preset(preset.id, update_persona=sync_persona)

    def switch_character_preset(self, preset_id: str, update_persona: bool = True) -> None:
        preset = get_character_preset(preset_id)
        self._config.character_id = preset.id
        self._config.sprite_path = ""
        self._config.character_name = preset.name
        if update_persona and preset.personality_prompt:
            self._config.personality_prompt = preset.personality_prompt
        self._apply_updated_config(self._config)
        self.character.set_state("happy")
        quote = preset.theme_quote or f"I am {preset.name}!"
        self.character.show_speech_bubble(quote, duration_ms=3500)

    def open_settings(self) -> None:
        dlg = SettingsDialog(self._config, self.popup if self.popup.isVisible() else self.character)
        dlg.preview_wake_requested.connect(
            lambda: self.trigger_wake_greeting(open_chat=True, override_config=dlg.updated_config())
        )
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
        self.popup.reset_streaming_preview(f"<i>Checking {html.escape(name)}...</i>")
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
        if self._startup_wake_timer is not None:
            self._startup_wake_timer.stop()
        self.wakeup_bubble._hide_timer.stop()
        self.wakeup_bubble.close()
        self.stop_streaming()
        if self._worker_thread is not None and self._worker_thread.isRunning():
            self._worker_thread.wait(1500)
        if self._briefing_thread is not None and self._briefing_thread.isRunning():
            self._briefing_thread.quit()
            self._briefing_thread.wait(1500)
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
    startup: bool = False,
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
        app.setWindowIcon(QtGui.QIcon(draw_pet_pixmap(64, cfg.sprite_path, cfg.character_id)))

    controller = DesktopCompanionApp(app, cfg)
    if single_instance:
        guard = SingleInstanceGuard(instance_name)
        if guard.start_listening():
            guard.activated.connect(controller.activate_from_second_launch)
            controller._instance_guard = guard
    controller.start(startup_launch=startup)
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
    parser.add_argument("--startup", action="store_true", help="Launched at Windows Startup with gentle wake-up greeting")
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
            startup=args.startup,
        )
    )


if __name__ == "__main__":
    main()
