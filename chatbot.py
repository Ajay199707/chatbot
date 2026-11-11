"""
AI Chatbot with Google Gemini API, NVIDIA NIM, Real-Time Tools, Streaming & FastAPI Web UI.

Features:
- Providers: Google Gemini (default, native REST SSE), NVIDIA NIM (OpenAI-compatible), Mock (offline)
- Real-time streaming WITH function calling / tool execution
- Preserves Gemini thought parts & thoughtSignature across tool loops and multi-turn chats
- Built-in tools: get_india_gold_price(), get_news(keyword), get_current_datetime()
- Modern FastAPI Web UI (SSE streaming, Markdown, session history) + interactive CLI

Setup (PowerShell):
    $env:GEMINI_API_KEY="your-gemini-api-key"
    # Optional (for NVIDIA NIM provider):
    $env:NVIDIA_API_KEY="nvapi-your-key"

Run:
    python chatbot.py --web
    python chatbot.py
    python chatbot.py --provider mock --web
    python chatbot.py --check-config
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
from typing import Any, AsyncIterator, Dict, Generator, List, Optional
import urllib.parse
import xml.etree.ElementTree as ET

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


# ============================================================
# ENVIRONMENT & CONSTANTS
# ============================================================

def get_app_dir() -> Path:
    """Return persistent directory for config and .env (next to .exe when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_bundle_dir() -> Path:
    """Return read-only resource directory (_MEIPASS when PyInstaller-frozen)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _load_env_files() -> None:
    """Load .env from app dir, workspace cwd, or user home if python-dotenv is installed."""
    if load_dotenv is None:
        return
    app_dir = get_app_dir()
    candidates = [app_dir / ".env"]
    if getattr(sys, "frozen", False) and app_dir.name.lower() == "dist":
        candidates.append(app_dir.parent / ".env")
    candidates.extend([Path.cwd() / ".env", Path.home() / ".env"])
    seen: set[Path] = set()
    for env_file in candidates:
        resolved = env_file.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        load_dotenv(dotenv_path=resolved, override=False)


def save_env_key(key_name: str, value: str, env_path: Optional[Path] = None) -> Path:
    """Persist an API key safely to the .env file and update os.environ."""
    clean_key = (key_name or "").strip()
    if not clean_key or not all(ch.isalnum() or ch == "_" for ch in clean_key):
        raise ValueError(f"Invalid environment variable name: {key_name!r}")
    clean_val = (value or "").replace("\r", "").replace("\n", "").strip()
    if env_path is not None:
        target = env_path
    else:
        app_dir = get_app_dir()
        parent_env = app_dir.parent / ".env"
        if (
            getattr(sys, "frozen", False)
            and app_dir.name.lower() == "dist"
            and parent_env.is_file()
            and not (app_dir / ".env").is_file()
        ):
            target = parent_env
        else:
            target = app_dir / ".env"

    lines: List[str] = []
    if target.is_file():
        lines = target.read_text(encoding="utf-8").splitlines()

    prefix = f"{clean_key}="
    new_line = f'{clean_key}="{clean_val.replace(chr(34), "")}"'
    updated = False
    new_lines: List[str] = []
    for line in lines:
        if line.lstrip().startswith(prefix):
            if not updated:
                new_lines.append(new_line)
                updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(new_line)

    target.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ[clean_key] = clean_val
    return target


_load_env_files()

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_DEFAULT_MODEL = "gemini-3.8-flash"
GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemma-4-31b-it",
    "gemma-4-26b-a4b-it",
    "gemini-4-argon",
    "gemini-4-carbon",
]

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_DEFAULT_MODEL = "meta/muse-glimmer-30b"
NVIDIA_MODELS = [
    "meta/muse-glimmer-30b",
]

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]
RETIRED_PROVIDER_MODELS: Dict[str, Tuple[str, ...]] = {
    "groq": ("llama-3.3-70b-versatile", "llama-3.1-8b-instant"),
}

XAI_BASE_URL = "https://api.x.ai/v1"
XAI_DEFAULT_MODEL = "grok-4-1-fast"
XAI_MODELS = [
    "grok-4-1-fast",
    "grok-4.7",
    "grok-3",
]

OLLAMA_DEFAULT_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
OLLAMA_DEFAULT_MODEL = "llama3:8b"
OLLAMA_MODELS = [
    "llama3:8b",
    "qwen2.5vl:7b",
    "gemma3:4b",
    "Mistral:latest",
]

PROVIDER_SPECS: Dict[str, Dict[str, Any]] = {
    "gemini": {
        "label": "Google Gemini (Free / Paid)",
        "protocol": "gemini",
        "default_model": GEMINI_DEFAULT_MODEL,
        "models": GEMINI_MODELS,
        "base_url": GEMINI_BASE_URL,
        "env_keys": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "requires_key": True,
    },
    "ollama": {
        "label": "Ollama (Local Free · Unlimited)",
        "protocol": "openai",
        "default_model": OLLAMA_DEFAULT_MODEL,
        "models": OLLAMA_MODELS,
        "base_url": OLLAMA_DEFAULT_BASE_URL,
        "env_keys": (),
        "requires_key": False,
    },
    "groq": {
        "label": "Groq Cloud (Free API · No Card)",
        "protocol": "openai",
        "default_model": GROQ_DEFAULT_MODEL,
        "models": GROQ_MODELS,
        "base_url": GROQ_BASE_URL,
        "env_keys": ("GROQ_API_KEY",),
        "requires_key": True,
    },
    "grok": {
        "label": "xAI Grok (Grok API Key)",
        "protocol": "openai",
        "default_model": XAI_DEFAULT_MODEL,
        "models": XAI_MODELS,
        "base_url": XAI_BASE_URL,
        "env_keys": ("GROK_API_KEY", "XAI_API_KEY"),
        "requires_key": True,
    },
    "nvidia": {
        "label": "NVIDIA NIM (Free API)",
        "protocol": "openai",
        "default_model": NVIDIA_DEFAULT_MODEL,
        "models": NVIDIA_MODELS,
        "base_url": NVIDIA_BASE_URL,
        "env_keys": ("NVIDIA_API_KEY",),
        "requires_key": True,
    },
    "mock": {
        "label": "Mock (Offline Demo)",
        "protocol": "mock",
        "default_model": "mock-assistant",
        "models": ["mock-assistant"],
        "base_url": None,
        "env_keys": (),
        "requires_key": False,
    },
}

VALID_THINKING_LEVELS = ("LOW", "MEDIUM", "HIGH")

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, accurate AI assistant. Format responses cleanly in Markdown when useful. "
    "When the user asks about live web information, gold/silver rates in India, current news, "
    "or the current date/time, use the available tools to fetch real-time data before answering "
    "and cite the sources or results honestly."
)


# ============================================================
# TOOLS & SCHEMAS
# ============================================================

def get_india_gold_price() -> str:
    """Fetch live Indian gold and silver prices from OroPocket public API."""
    url = "https://api.oropocket.com/public/prices"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers={"User-Agent": "chatbot/2.0"})
            resp.raise_for_status()
            data = resp.json()

        payload = data.get("data", data)
        gold = payload.get("gold", {})
        silver = payload.get("silver", {})
        lines = []
        if gold:
            lines.append(
                f"Gold (INR/gram): buy INR {gold.get('buy')}, sell INR {gold.get('sell')}, "
                f"GST INR {gold.get('gst')}, 24h change {gold.get('change24h')}"
            )
        if silver:
            lines.append(
                f"Silver (INR/gram): buy INR {silver.get('buy')}, sell INR {silver.get('sell')}, "
                f"GST INR {silver.get('gst')}, 24h change {silver.get('change24h')}"
            )
        if not lines:
            return json.dumps({"error": "No gold/silver data in response", "raw": data})
        lines.append(f"Timestamp: {payload.get('timestamp', 'unknown')}")
        lines.append("Note: This is a tradeable buy/sell quote, not a spot benchmark.")
        return "\n".join(lines)
    except Exception as exc:
        return json.dumps({"error": f"Failed to fetch gold price: {exc}"})


def get_news(keyword: str) -> str:
    """Fetch latest news headlines via Google News RSS."""
    cleaned = (keyword or "").strip()
    if not cleaned:
        return json.dumps({"error": "Missing 'keyword' argument"})

    q = urllib.parse.quote(cleaned)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "chatbot/2.0"})
            resp.raise_for_status()
            xml_bytes = resp.content

        root = ET.fromstring(xml_bytes)
        items = root.findall(".//item")[:5]
        if not items:
            return json.dumps({"error": f"No news found for '{cleaned}'"})
        out = []
        for item in items:
            title = item.findtext("title", default="(no title)")
            pub = item.findtext("pubDate", default="")
            source = item.findtext("source", default="")
            link = item.findtext("link", default="")
            entry = f"- {title}"
            if source:
                entry += f" [{source}]"
            if pub:
                entry += f" ({pub})"
            if link:
                entry += f"\n  Link: {link}"
            out.append(entry)
        return "\n".join(out)
    except Exception as exc:
        return json.dumps({"error": f"Failed to fetch news: {exc}"})


def get_current_datetime() -> str:
    """Return the current local and UTC date/time."""
    local_now = datetime.now().astimezone()
    utc_now = datetime.now(timezone.utc)
    return (
        f"Local time: {local_now.strftime('%Y-%m-%d %H:%M:%S %Z (%A)')}\n"
        f"UTC time: {utc_now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )


def web_search(
    query: str,
    topic: str = "general",
    search_depth: str = "basic",
    max_results: int = 5,
) -> str:
    """Search the live web using the Tavily Search REST API."""
    clean_query = (query or "").strip()
    if not clean_query:
        return "Error: Search query must not be empty."

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return (
            "Error: TAVILY_API_KEY is not configured. Add TAVILY_API_KEY in Settings or .env "
            "(https://app.tavily.com) to enable live web search."
        )

    clean_topic = topic if topic in ("general", "news", "finance") else "general"
    clean_depth = search_depth if search_depth in ("basic", "advanced") else "basic"
    try:
        clamped_max = max(1, min(10, int(max_results)))
    except (TypeError, ValueError):
        clamped_max = 5

    payload = {
        "query": clean_query,
        "topic": clean_topic,
        "search_depth": clean_depth,
        "max_results": clamped_max,
        "include_answer": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post("https://api.tavily.com/search", headers=headers, json=payload)
            if resp.status_code != 200:
                return f"Error performing Tavily search (HTTP {resp.status_code}): {resp.text[:300]}"
            data = resp.json()
    except Exception as exc:
        return f"Error performing Tavily search: {exc}"

    lines: List[str] = []
    answer = (data.get("answer") or "").strip()
    if answer:
        lines.append(f"Summary: {answer}")

    results = data.get("results") or []
    if results:
        lines.append("Sources:")
        for idx, item in enumerate(results[:clamped_max], 1):
            title = (item.get("title") or "Untitled").strip()
            url_str = (item.get("url") or "").strip()
            snippet = " ".join((item.get("content") or "").split())[:320]
            pub = (item.get("published_date") or "").strip()
            meta = f" ({pub})" if pub else ""
            lines.append(f"{idx}. {title}{meta}\n   URL: {url_str}\n   {snippet}")

    return "\n".join(lines) if lines else f"No Tavily search results found for '{clean_query}'."


TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "get_india_gold_price",
        "description": (
            "Get the current live gold and silver buy/sell price in India in INR per gram. "
            "Use this whenever the user asks about gold rate, silver rate, bullion prices, "
            "or today's gold price in India."
        ),
        "properties": {},
        "required": [],
        "fn": get_india_gold_price,
    },
    {
        "name": "get_news",
        "description": (
            "Search for the latest news headlines on a given topic. Use this whenever the "
            "user asks for current news, recent headlines, or what is happening with a topic."
        ),
        "properties": {
            "keyword": {
                "type": "string",
                "description": "The search keyword, e.g. 'India economy', 'AI technology', 'cricket'.",
            }
        },
        "required": ["keyword"],
        "fn": get_news,
    },
    {
        "name": "web_search",
        "description": (
            "Search the live web using Tavily for up-to-date facts, documentation, current events, "
            "prices, weather, sports, or any question needing current internet information."
        ),
        "properties": {
            "query": {
                "type": "string",
                "description": "The web search query.",
            },
            "topic": {
                "type": "string",
                "description": "Search focus category: 'general', 'news', or 'finance'.",
                "enum": ["general", "news", "finance"],
            },
            "search_depth": {
                "type": "string",
                "description": "Search depth: 'basic' (fast) or 'advanced' (deeper).",
                "enum": ["basic", "advanced"],
            },
        },
        "required": ["query"],
        "fn": web_search,
    },
    {
        "name": "get_current_datetime",
        "description": (
            "Get the current local and UTC date, time, and day of the week. "
            "Use this when the user asks what day or time it is."
        ),
        "properties": {},
        "required": [],
        "fn": get_current_datetime,
    },
]

TOOL_FUNCTIONS = {spec["name"]: spec["fn"] for spec in TOOL_SPECS}


def build_openai_tools() -> List[Dict[str, Any]]:
    """Build OpenAI/NVIDIA-compatible tool declarations."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": {
                    "type": "object",
                    "properties": spec["properties"],
                    "required": spec["required"],
                },
            },
        }
        for spec in TOOL_SPECS
    ]


def build_gemini_tools() -> List[Dict[str, Any]]:
    """Build Gemini REST API functionDeclarations (omits parameters if none exist)."""
    declarations: List[Dict[str, Any]] = []
    for spec in TOOL_SPECS:
        decl: Dict[str, Any] = {
            "name": spec["name"],
            "description": spec["description"],
        }
        if spec["properties"]:
            gemini_props: Dict[str, Any] = {}
            for k, v in spec["properties"].items():
                prop_schema: Dict[str, Any] = {
                    "type": v["type"].upper(),
                    "description": v.get("description", ""),
                }
                if "enum" in v:
                    prop_schema["enum"] = list(v["enum"])
                gemini_props[k] = prop_schema
            decl["parameters"] = {
                "type": "OBJECT",
                "properties": gemini_props,
                "required": spec["required"],
            }
        declarations.append(decl)
    return [{"functionDeclarations": declarations}]


TOOLS = build_openai_tools()
GEMINI_TOOLS = build_gemini_tools()


def execute_tool(name: str, args: Any) -> str:
    """Safely execute a registered tool with validated arguments."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid JSON arguments for {name}: {exc}"})
    if not isinstance(args, dict):
        args = {}
    try:
        return str(fn(**args))
    except TypeError as exc:
        return json.dumps({"error": f"Invalid arguments for {name}: {exc}"})
    except Exception as exc:
        return json.dumps({"error": f"Tool {name} failed: {exc}"})


# ============================================================
# MESSAGE & CONFIG
# ============================================================

@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str
    thoughts: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    raw_model_parts: Optional[List[Dict[str, Any]]] = None
    gemini_tool_exchange: Optional[List[Dict[str, Any]]] = None


@dataclass
class ChatbotConfig:
    provider: str = "gemini"
    model_name: str = ""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    temperature: float = 0.7
    max_tokens: int = 4096
    max_history_turns: int = 20
    thinking_level: str = "MEDIUM"
    use_tools: bool = True
    max_tool_rounds: int = 5


def requires_api_key(provider: str) -> bool:
    spec = PROVIDER_SPECS.get(provider)
    return bool(spec.get("requires_key", True)) if spec else True


def default_model_for_provider(provider: str) -> str:
    spec = PROVIDER_SPECS.get(provider)
    return str(spec["default_model"]) if spec else "mock-assistant"


def _validate_provider_key(provider: str, api_key: Optional[str]) -> Optional[str]:
    """Return a clear error message when a key prefix clearly belongs to another provider."""
    if not api_key:
        return None
    if provider == "grok" and api_key.startswith("gsk_"):
        return (
            "Configured key starts with 'gsk_' (Groq Cloud, console.groq.com), not xAI Grok ('xai-...'). "
            "Switch provider to 'groq' or enter an xAI API key for Grok."
        )
    if provider == "groq" and api_key.startswith("xai-"):
        return (
            "Configured key starts with 'xai-' (xAI Grok, console.x.ai), not Groq Cloud ('gsk_...'). "
            "Switch provider to 'grok' or enter a Groq Cloud API key."
        )
    return None


def resolve_api_key(provider: str, explicit_key: Optional[str] = None) -> Optional[str]:
    if explicit_key:
        return explicit_key
    spec = PROVIDER_SPECS.get(provider)
    if not spec:
        return None
    for env_name in spec.get("env_keys", ()):
        val = os.getenv(env_name)
        if val:
            return val
    return None


def resolve_base_url(provider: str, explicit_url: Optional[str] = None) -> Optional[str]:
    if explicit_url:
        return explicit_url
    if provider == "ollama":
        return os.getenv("OLLAMA_BASE_URL") or OLLAMA_DEFAULT_BASE_URL
    spec = PROVIDER_SPECS.get(provider)
    return spec.get("base_url") if spec else None


_NON_CHAT_MODEL_HINTS = ("whisper", "orpheus", "prompt-guard", "safeguard", "embed", "tts")


def normalize_model_for_provider(provider: str, model_name: Optional[str]) -> str:
    """Return a valid model ID, migrating known retired defaults cleanly."""
    clean = (model_name or "").strip()
    if not clean or clean in RETIRED_PROVIDER_MODELS.get(provider, ()):
        return default_model_for_provider(provider)
    return clean


def list_ollama_models(base_url: Optional[str] = None, timeout: float = 1.2) -> List[str]:
    """Discover locally installed Ollama models via /api/tags without failing."""
    raw = (base_url or resolve_base_url("ollama") or OLLAMA_DEFAULT_BASE_URL).rstrip("/")
    tags_base = raw[:-3] if raw.endswith("/v1") else raw
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{tags_base}/api/tags")
            if resp.status_code != 200:
                return []
            data = resp.json()
        names = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        return names
    except Exception:
        return []


def list_provider_models(
    provider: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 1.2,
) -> List[str]:
    """Query active chat models from Ollama or OpenAI-compatible /models endpoints."""
    if provider == "ollama":
        return list_ollama_models(base_url=base_url, timeout=timeout)
    spec = PROVIDER_SPECS.get(provider)
    if not spec or spec.get("protocol") != "openai":
        return list(spec.get("models", [])) if spec else []

    resolved_key = resolve_api_key(provider, api_key)
    if not resolved_key:
        return []
    base = (base_url or resolve_base_url(provider) or "").rstrip("/")
    if not base:
        return []

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{base}/models", headers={"Authorization": f"Bearer {resolved_key}"})
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception:
        return []

    raw_ids = [
        str(m.get("id", "")).strip()
        for m in data.get("data", [])
        if m.get("id") and not any(h in str(m.get("id", "")).lower() for h in _NON_CHAT_MODEL_HINTS)
    ]
    if not raw_ids:
        return []

    preferred = [m for m in spec.get("models", []) if m in raw_ids]
    others = sorted(m for m in raw_ids if m not in preferred)
    return preferred + others


def _pick_fallback_model(
    provider: str,
    failed_model: str,
    base_url: Optional[str],
    api_key: Optional[str],
) -> Optional[str]:
    """Pick an alternate model ID when a configured model returns HTTP 404."""
    candidates = list_provider_models(provider, base_url=base_url, api_key=api_key, timeout=2.0)
    candidates.extend(PROVIDER_SPECS.get(provider, {}).get("models", []))
    for candidate in candidates:
        if candidate and candidate != failed_model:
            return candidate
    return None


# ============================================================
# SSE & PAYLOAD HELPERS
# ============================================================

def _iter_sse_events(resp: httpx.Response) -> Generator[str, None, None]:
    """Yield complete SSE `data` payloads from an httpx streaming response."""
    data_lines: List[str] = []
    for line in resp.iter_lines():
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
    if data_lines:
        yield "\n".join(data_lines)


def _merge_gemini_part(parts: List[Dict[str, Any]], part: Dict[str, Any]) -> None:
    """Append a Gemini response part while compacting plain text and keeping signatures intact."""
    if "functionCall" in part or "thoughtSignature" in part:
        parts.append(dict(part))
        return
    if "text" in part:
        is_thought = bool(part.get("thought", False))
        if (
            parts
            and "text" in parts[-1]
            and "functionCall" not in parts[-1]
            and "thoughtSignature" not in parts[-1]
            and bool(parts[-1].get("thought", False)) == is_thought
        ):
            parts[-1]["text"] += part["text"]
        else:
            parts.append(dict(part))
        return
    parts.append(dict(part))


def _format_http_error(resp: httpx.Response) -> str:
    """Extract a clean human-readable error message from a failed HTTP response."""
    try:
        raw = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        raw = ""
    if raw:
        try:
            data = json.loads(raw)
            err = data.get("error")
            if isinstance(err, dict) and err.get("message"):
                return f"HTTP {resp.status_code}: {err['message']}"
            if isinstance(err, str):
                return f"HTTP {resp.status_code}: {err}"
        except json.JSONDecodeError:
            pass
    return f"HTTP {resp.status_code}: {raw[:300] or resp.reason_phrase}"


# ============================================================
# CHATBOT CORE
# ============================================================

class Chatbot:
    def __init__(self, config: Optional[ChatbotConfig] = None):
        self.config = config or ChatbotConfig()
        self.history: List[Message] = []
        self._resolve_provider()

    def _resolve_provider(self) -> None:
        provider = (self.config.provider or "gemini").lower()
        if provider not in PROVIDER_SPECS:
            provider = "gemini"
        self.config.provider = provider
        self.config.model_name = normalize_model_for_provider(provider, self.config.model_name)
        self.config.base_url = resolve_base_url(provider, self.config.base_url)
        self.config.api_key = resolve_api_key(provider, self.config.api_key)
        level = (self.config.thinking_level or "MEDIUM").upper()
        self.config.thinking_level = level if level in VALID_THINKING_LEVELS else "MEDIUM"

    def reconfigure(
        self,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        thinking_level: Optional[str] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        use_tools: Optional[bool] = None,
    ) -> None:
        """Update runtime configuration without losing conversation history."""
        if provider is not None and provider != self.config.provider:
            self.config.provider = provider
            self.config.base_url = None
            self.config.api_key = None
            if not model_name:
                self.config.model_name = ""
        if model_name is not None:
            self.config.model_name = model_name.strip()
        if thinking_level is not None:
            self.config.thinking_level = thinking_level
        if temperature is not None:
            self.config.temperature = max(0.0, min(2.0, float(temperature)))
        if system_prompt is not None:
            self.config.system_prompt = system_prompt
        if use_tools is not None:
            self.config.use_tools = bool(use_tools)
        self._resolve_provider()

    def reset_history(self) -> None:
        self.history.clear()

    def add_message(self, message: Message) -> None:
        self.history.append(message)
        max_messages = self.config.max_history_turns * 2
        if len(self.history) > max_messages:
            trimmed = self.history[-max_messages:]
            while trimmed and trimmed[0].role != "user":
                trimmed.pop(0)
            self.history = trimmed

    def get_public_history(self) -> List[Dict[str, Any]]:
        return [
            {
                "role": m.role,
                "content": m.content,
                "thoughts": m.thoughts,
                "tool_calls": m.tool_calls,
            }
            for m in self.history
        ]

    # --------------------------------------------------------
    # Backwards-compatible synchronous / plain-text wrappers
    # --------------------------------------------------------
    def stream_chat(self, user_input: str) -> Generator[str, None, None]:
        """Yield plain text chunks (disables tools for raw streaming compatibility)."""
        for event in self.stream_turn(user_input, use_tools=False):
            if event["type"] == "token":
                yield event["content"]
            elif event["type"] == "error":
                yield f"\n[Error: {event['message']}]"

    def chat_with_tools(self, user_input: str) -> str:
        """Run a full tool-enabled turn and return the final text response."""
        chunks: List[str] = []
        for event in self.stream_turn(user_input, use_tools=self.config.use_tools):
            if event["type"] == "token":
                chunks.append(event["content"])
            elif event["type"] == "error":
                return f"[Error: {event['message']}]"
        return "".join(chunks)

    # --------------------------------------------------------
    # Unified streaming turn (text + thoughts + tool calls)
    # --------------------------------------------------------
    def stream_turn(
        self,
        user_input: str,
        use_tools: Optional[bool] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Stream structured events for one user turn across the active provider."""
        text = (user_input or "").strip()
        if not text:
            yield {"type": "error", "message": "Empty message."}
            return

        tools_enabled = self.config.use_tools if use_tools is None else bool(use_tools)
        self.add_message(Message(role="user", content=text))

        try:
            protocol = PROVIDER_SPECS.get(self.config.provider, {}).get("protocol", "mock")
            if protocol == "gemini":
                gen = self._stream_gemini_turn(tools_enabled, cancel_event)
            elif protocol == "openai":
                gen = self._stream_openai_turn(tools_enabled, cancel_event)
            else:
                gen = self._stream_mock_turn(text, tools_enabled, cancel_event)

            for event in gen:
                yield event
        except Exception as exc:
            msg = f"Unexpected error: {exc}"
            self.add_message(Message(role="assistant", content=f"[Error: {msg}]"))
            yield {"type": "error", "message": msg}

    # --------------------------------------------------------
    # Google Gemini native REST API (:streamGenerateContent?alt=sse)
    # --------------------------------------------------------
    def _build_gemini_contents(self) -> List[Dict[str, Any]]:
        contents: List[Dict[str, Any]] = []
        for msg in self.history:
            if msg.role == "user":
                contents.append({"role": "user", "parts": [{"text": msg.content}]})
                continue
            if msg.gemini_tool_exchange:
                contents.extend(msg.gemini_tool_exchange)
            if msg.raw_model_parts:
                valid_parts = [
                    p for p in msg.raw_model_parts
                    if p.get("text") or "functionCall" in p or "thoughtSignature" in p
                ]
                if valid_parts:
                    contents.append({"role": "model", "parts": valid_parts})
                    continue
            contents.append({"role": "model", "parts": [{"text": msg.content or " "}]})
        return contents

    def _build_gemini_payload(self, contents: List[Dict[str, Any]], tools_enabled: bool) -> Dict[str, Any]:
        generation_config: Dict[str, Any] = {
            "temperature": self.config.temperature,
            "maxOutputTokens": self.config.max_tokens,
        }
        model_lower = self.config.model_name.lower()
        if not model_lower.startswith("gemma"):
            if "gemini-3" in model_lower or "gemini-4" in model_lower:
                generation_config["thinkingConfig"] = {
                    "thinkingLevel": self.config.thinking_level,
                    "includeThoughts": True,
                }
            elif "2.5" in model_lower:
                generation_config["thinkingConfig"] = {"includeThoughts": True}

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if self.config.system_prompt:
            payload["system_instruction"] = {
                "parts": [{"text": self.config.system_prompt}]
            }
        if tools_enabled:
            payload["tools"] = GEMINI_TOOLS
        return payload

    def _stream_gemini_turn(
        self,
        tools_enabled: bool,
        cancel_event: Optional[threading.Event] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        api_key = resolve_api_key("gemini", self.config.api_key)
        if not api_key:
            err = (
                "GEMINI_API_KEY is not set. Set $env:GEMINI_API_KEY='...' in PowerShell "
                "or add GEMINI_API_KEY=... to .env (or switch to Mock Demo mode)."
            )
            self.add_message(Message(role="assistant", content=f"[Error: {err}]"))
            yield {"type": "error", "message": err}
            return

        base = (self.config.base_url or GEMINI_BASE_URL).rstrip("/")
        url = f"{base}/models/{urllib.parse.quote(self.config.model_name, safe='')}:streamGenerateContent?alt=sse"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }

        contents = self._build_gemini_contents()
        tool_exchange: List[Dict[str, Any]] = []
        recorded_tools: List[Dict[str, Any]] = []
        answer_chunks: List[str] = []
        thought_chunks: List[str] = []
        final_model_parts: List[Dict[str, Any]] = []

        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            round_idx = 0
            while round_idx <= self.config.max_tool_rounds:
                if cancel_event and cancel_event.is_set():
                    break

                payload = self._build_gemini_payload(contents, tools_enabled)
                round_parts: List[Dict[str, Any]] = []
                function_calls: List[Dict[str, Any]] = []
                finish_reason: Optional[str] = None

                with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        err = _format_http_error(resp)
                        if (
                            resp.status_code == 400
                            and tools_enabled
                            and ("tool" in err.lower() or "function" in err.lower())
                        ):
                            tools_enabled = False
                            continue
                        self.add_message(Message(role="assistant", content=f"[Error: {err}]"))
                        yield {"type": "error", "message": err}
                        return

                    for raw_data in _iter_sse_events(resp):
                        if cancel_event and cancel_event.is_set():
                            break
                        if not raw_data or raw_data == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(raw_data)
                        except json.JSONDecodeError:
                            continue

                        if "error" in chunk:
                            err = chunk["error"].get("message", str(chunk["error"]))
                            self.add_message(Message(role="assistant", content=f"[Error: {err}]"))
                            yield {"type": "error", "message": err}
                            return

                        candidates = chunk.get("candidates") or []
                        if not candidates:
                            continue
                        cand = candidates[0]
                        if cand.get("finishReason"):
                            finish_reason = cand["finishReason"]

                        parts = cand.get("content", {}).get("parts") or []
                        for part in parts:
                            _merge_gemini_part(round_parts, part)
                            if "functionCall" in part:
                                function_calls.append(part["functionCall"])
                            elif "text" in part and part["text"]:
                                if part.get("thought"):
                                    thought_chunks.append(part["text"])
                                    yield {"type": "thought", "content": part["text"]}
                                else:
                                    answer_chunks.append(part["text"])
                                    yield {"type": "token", "content": part["text"]}

                if cancel_event and cancel_event.is_set():
                    break

                if function_calls and tools_enabled:
                    model_turn = {"role": "model", "parts": round_parts}
                    func_parts: List[Dict[str, Any]] = []

                    for fc in function_calls:
                        fn_name = fc.get("name", "")
                        fn_args = fc.get("args") or {}
                        yield {"type": "tool_start", "name": fn_name, "args": fn_args}
                        result_str = execute_tool(fn_name, fn_args)
                        yield {"type": "tool_end", "name": fn_name, "result": result_str}
                        recorded_tools.append(
                            {"name": fn_name, "args": fn_args, "result": result_str}
                        )
                        resp_obj: Dict[str, Any] = {
                            "name": fn_name,
                            "response": {"result": result_str},
                        }
                        if fc.get("id"):
                            resp_obj["id"] = fc["id"]
                        func_parts.append({"functionResponse": resp_obj})

                    func_turn = {"role": "user", "parts": func_parts}
                    contents.extend([model_turn, func_turn])
                    tool_exchange.extend([model_turn, func_turn])
                    round_idx += 1
                    continue

                final_model_parts = round_parts
                if not answer_chunks and finish_reason and finish_reason not in ("STOP", "MAX_TOKENS"):
                    note = f"[Response stopped: {finish_reason}]"
                    answer_chunks.append(note)
                    yield {"type": "token", "content": note}
                break
            else:
                note = "\n[Max tool call limit reached]"
                answer_chunks.append(note)
                yield {"type": "token", "content": note}

        full_text = "".join(answer_chunks)
        if not full_text and cancel_event and cancel_event.is_set():
            full_text = "[Stopped]"
        full_thoughts = "".join(thought_chunks)
        self.add_message(
            Message(
                role="assistant",
                content=full_text,
                thoughts=full_thoughts,
                tool_calls=recorded_tools,
                raw_model_parts=final_model_parts or None,
                gemini_tool_exchange=tool_exchange or None,
            )
        )
        yield {
            "type": "done",
            "content": full_text,
            "thoughts": full_thoughts,
            "tool_calls": recorded_tools,
        }

    # --------------------------------------------------------
    # NVIDIA NIM / OpenAI-compatible streaming + tools
    # --------------------------------------------------------
    def _build_openai_messages(self) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        if self.config.system_prompt:
            messages.append({"role": "system", "content": self.config.system_prompt})
        for msg in self.history:
            messages.append({"role": msg.role, "content": msg.content})
        return messages

    def _stream_openai_turn(
        self,
        tools_enabled: bool,
        cancel_event: Optional[threading.Event] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        provider = self.config.provider
        api_key = resolve_api_key(provider, self.config.api_key)
        if requires_api_key(provider) and not api_key:
            env_hint = (PROVIDER_SPECS.get(provider, {}).get("env_keys") or ("API_KEY",))[0]
            err = (
                f"{env_hint} is not set. Add it in Settings or .env, "
                "or switch to Local Ollama (Free) / Mock mode."
            )
            self.add_message(Message(role="assistant", content=f"[Error: {err}]"))
            yield {"type": "error", "message": err}
            return

        mismatch_err = _validate_provider_key(provider, api_key)
        if mismatch_err:
            self.add_message(Message(role="assistant", content=f"[Error: {mismatch_err}]"))
            yield {"type": "error", "message": mismatch_err}
            return

        base = (self.config.base_url or resolve_base_url(provider) or NVIDIA_BASE_URL).rstrip("/")
        url = f"{base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        messages = self._build_openai_messages()
        recorded_tools: List[Dict[str, Any]] = []
        answer_chunks: List[str] = []

        try:
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
                round_idx = 0
                retried_model = False
                while round_idx <= self.config.max_tool_rounds:
                    if cancel_event and cancel_event.is_set():
                        break

                    payload: Dict[str, Any] = {
                        "model": self.config.model_name,
                        "messages": messages,
                        "temperature": self.config.temperature,
                        "max_tokens": self.config.max_tokens,
                        "stream": True,
                    }
                    if tools_enabled:
                        payload["tools"] = TOOLS
                        payload["tool_choice"] = "auto"

                    round_text_parts: List[str] = []
                    tool_calls_by_idx: Dict[int, Dict[str, Any]] = {}

                    with client.stream("POST", url, headers=headers, json=payload) as resp:
                        if resp.status_code != 200:
                            err = _format_http_error(resp)
                            if (
                                resp.status_code == 400
                                and tools_enabled
                                and ("tool" in err.lower() or "function" in err.lower())
                            ):
                                tools_enabled = False
                                continue
                            if resp.status_code == 404 and not retried_model:
                                low = err.lower()
                                if "model" in low and any(
                                    tok in low
                                    for tok in ("does not exist", "not found", "decommissioned", "not have access")
                                ):
                                    fallback = _pick_fallback_model(provider, self.config.model_name, base, api_key)
                                    if fallback:
                                        self.config.model_name = fallback
                                        retried_model = True
                                        continue
                            self.add_message(Message(role="assistant", content=f"[Error: {err}]"))
                            yield {"type": "error", "message": err}
                            return

                        for raw_data in _iter_sse_events(resp):
                            if cancel_event and cancel_event.is_set():
                                break
                            if not raw_data or raw_data == "[DONE]":
                                continue
                            try:
                                chunk = json.loads(raw_data)
                            except json.JSONDecodeError:
                                continue

                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta") or {}

                            content_piece = delta.get("content")
                            if content_piece:
                                round_text_parts.append(content_piece)
                                answer_chunks.append(content_piece)
                                yield {"type": "token", "content": content_piece}

                            for tc_delta in delta.get("tool_calls") or []:
                                idx = tc_delta.get("index", 0)
                                entry = tool_calls_by_idx.setdefault(
                                    idx,
                                    {
                                        "id": tc_delta.get("id") or f"call_{idx}",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    },
                                )
                                if tc_delta.get("id"):
                                    entry["id"] = tc_delta["id"]
                                fn_delta = tc_delta.get("function") or {}
                                if fn_delta.get("name"):
                                    entry["function"]["name"] += fn_delta["name"]
                                if fn_delta.get("arguments"):
                                    entry["function"]["arguments"] += fn_delta["arguments"]

                    if cancel_event and cancel_event.is_set():
                        break

                    if tool_calls_by_idx and tools_enabled:
                        ordered_calls = [tool_calls_by_idx[k] for k in sorted(tool_calls_by_idx)]
                        messages.append(
                            {
                                "role": "assistant",
                                "content": "".join(round_text_parts) or None,
                                "tool_calls": ordered_calls,
                            }
                        )
                        for tc in ordered_calls:
                            fn_name = tc["function"]["name"]
                            raw_args = tc["function"]["arguments"]
                            try:
                                parsed_args = json.loads(raw_args) if raw_args.strip() else {}
                            except json.JSONDecodeError:
                                parsed_args = {}

                            yield {"type": "tool_start", "name": fn_name, "args": parsed_args}
                            result_str = execute_tool(fn_name, raw_args)
                            yield {"type": "tool_end", "name": fn_name, "result": result_str}
                            recorded_tools.append(
                                {"name": fn_name, "args": parsed_args, "result": result_str}
                            )
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc["id"],
                                    "name": fn_name,
                                    "content": result_str,
                                }
                            )
                        round_idx += 1
                        continue
                    break
                else:
                    note = "\n[Max tool call limit reached]"
                    answer_chunks.append(note)
                    yield {"type": "token", "content": note}
        except httpx.ConnectError:
            hint = (
                f"Cannot connect to local Ollama at {base}. Make sure Ollama is running (e.g. 'ollama serve')."
                if provider == "ollama"
                else f"Cannot connect to {provider} API at {base}."
            )
            self.add_message(Message(role="assistant", content=f"[Error: {hint}]"))
            yield {"type": "error", "message": hint}
            return

        full_text = "".join(answer_chunks)
        if not full_text and cancel_event and cancel_event.is_set():
            full_text = "[Stopped]"
        self.add_message(
            Message(role="assistant", content=full_text, tool_calls=recorded_tools)
        )
        yield {
            "type": "done",
            "content": full_text,
            "thoughts": "",
            "tool_calls": recorded_tools,
        }

    # --------------------------------------------------------
    # Mock provider (offline testing & live demo)
    # --------------------------------------------------------
    def _stream_mock_turn(
        self,
        user_input: str,
        tools_enabled: bool,
        cancel_event: Optional[threading.Event] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        lower = user_input.lower()
        recorded_tools: List[Dict[str, Any]] = []

        thought = "Analyzing user prompt in offline mock mode..."
        yield {"type": "thought", "content": thought}

        tool_plan: Optional[tuple[str, Dict[str, Any]]] = None
        if tools_enabled:
            if "gold" in lower or "silver" in lower:
                tool_plan = ("get_india_gold_price", {})
            elif "news" in lower:
                topic = user_input.replace("news", "").strip(" ?.:") or "India"
                tool_plan = ("get_news", {"keyword": topic})
            elif "time" in lower or "date" in lower or "day" in lower:
                tool_plan = ("get_current_datetime", {})

        if tool_plan:
            fn_name, fn_args = tool_plan
            yield {"type": "tool_start", "name": fn_name, "args": fn_args}
            result_str = execute_tool(fn_name, fn_args)
            yield {"type": "tool_end", "name": fn_name, "result": result_str}
            recorded_tools.append({"name": fn_name, "args": fn_args, "result": result_str})
            reply = f"### Mock Tool Result (`{fn_name}`)\n\n{result_str}"
        else:
            reply = (
                f"**[Mock Mode]** You asked: _{user_input}_\n\n"
                "To chat with **Google Gemini**, set `GEMINI_API_KEY` and select **Google Gemini** "
                "in the sidebar."
            )

        for token in reply.split(" "):
            if cancel_event and cancel_event.is_set():
                break
            chunk = token + " "
            yield {"type": "token", "content": chunk}
            time.sleep(0.015)

        self.add_message(
            Message(
                role="assistant",
                content=reply,
                thoughts=thought,
                tool_calls=recorded_tools,
            )
        )
        yield {
            "type": "done",
            "content": reply,
            "thoughts": thought,
            "tool_calls": recorded_tools,
        }


# ============================================================
# SESSION STORE & FASTAPI WEB SERVER
# ============================================================

class SessionEntry:
    def __init__(self, bot: Chatbot):
        self.bot = bot
        self.lock = threading.Lock()


class SessionManager:
    def __init__(self, base_config: ChatbotConfig):
        self.base_config = base_config
        self._sessions: Dict[str, SessionEntry] = {}
        self._guard = threading.Lock()

    def get_or_create(self, session_id: str) -> SessionEntry:
        sid = (session_id or "default").strip() or "default"
        with self._guard:
            entry = self._sessions.get(sid)
            if entry is None:
                cfg = ChatbotConfig(
                    provider=self.base_config.provider,
                    model_name=self.base_config.model_name,
                    api_key=self.base_config.api_key,
                    base_url=self.base_config.base_url,
                    system_prompt=self.base_config.system_prompt,
                    temperature=self.base_config.temperature,
                    max_tokens=self.base_config.max_tokens,
                    max_history_turns=self.base_config.max_history_turns,
                    thinking_level=self.base_config.thinking_level,
                    use_tools=self.base_config.use_tools,
                    max_tool_rounds=self.base_config.max_tool_rounds,
                )
                entry = SessionEntry(Chatbot(cfg))
                self._sessions[sid] = entry
            return entry


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    provider: Optional[str] = None
    model: Optional[str] = None
    thinking_level: Optional[str] = None
    temperature: Optional[float] = None
    system_prompt: Optional[str] = None
    use_tools: Optional[bool] = None


class ClearRequest(BaseModel):
    session_id: str = "default"


def _apply_request_config(bot: Chatbot, req: ChatRequest) -> None:
    bot.reconfigure(
        provider=req.provider,
        model_name=req.model,
        thinking_level=req.thinking_level,
        temperature=req.temperature,
        system_prompt=req.system_prompt,
        use_tools=req.use_tools,
    )


def create_app(base_config: Optional[ChatbotConfig] = None) -> FastAPI:
    cfg = base_config or ChatbotConfig()
    # Ensure defaults are resolved once
    probe = Chatbot(cfg)
    sessions = SessionManager(probe.config)
    static_index = get_bundle_dir() / "static" / "index.html"

    app = FastAPI(title="Gemini AI Chatbot", version="2.0.0")
    app.state.sessions = sessions

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        if static_index.is_file():
            return HTMLResponse(static_index.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Chatbot UI missing</h1><p>Expected static/index.html.</p>", status_code=500)

    @app.get("/api/status")
    async def status() -> JSONResponse:
        ollama_models = list_ollama_models() or OLLAMA_MODELS
        return JSONResponse(
            {
                "provider": probe.config.provider,
                "model": probe.config.model_name,
                "thinking_level": probe.config.thinking_level,
                "temperature": probe.config.temperature,
                "use_tools": probe.config.use_tools,
                "system_prompt": probe.config.system_prompt,
                "keys_configured": {
                    "gemini": bool(resolve_api_key("gemini", probe.config.api_key if probe.config.provider == "gemini" else None)),
                    "ollama": True,
                    "groq": bool(resolve_api_key("groq", probe.config.api_key if probe.config.provider == "groq" else None)),
                    "grok": bool(resolve_api_key("grok", probe.config.api_key if probe.config.provider == "grok" else None)),
                    "nvidia": bool(resolve_api_key("nvidia", probe.config.api_key if probe.config.provider == "nvidia" else None)),
                    "mock": True,
                    "tavily": bool(os.getenv("TAVILY_API_KEY")),
                },
                "models": {
                    "gemini": GEMINI_MODELS,
                    "ollama": ollama_models,
                    "groq": GROQ_MODELS,
                    "grok": XAI_MODELS,
                    "nvidia": NVIDIA_MODELS,
                    "mock": ["mock-assistant"],
                },
                "tools": [
                    {"name": s["name"], "description": s["description"]}
                    for s in TOOL_SPECS
                ],
            }
        )

    @app.get("/api/history")
    async def history(session_id: str = "default") -> JSONResponse:
        entry = sessions.get_or_create(session_id)
        with entry.lock:
            return JSONResponse(
                {
                    "session_id": session_id,
                    "provider": entry.bot.config.provider,
                    "model": entry.bot.config.model_name,
                    "messages": entry.bot.get_public_history(),
                }
            )

    @app.post("/api/clear")
    async def clear(req: ClearRequest) -> JSONResponse:
        entry = sessions.get_or_create(req.session_id)
        with entry.lock:
            entry.bot.reset_history()
        return JSONResponse({"ok": True, "session_id": req.session_id})

    @app.post("/api/chat")
    async def chat_sync(req: ChatRequest) -> JSONResponse:
        msg = (req.message or "").strip()
        if not msg:
            raise HTTPException(status_code=400, detail="Empty message")

        entry = sessions.get_or_create(req.session_id)

        def _run() -> Dict[str, Any]:
            with entry.lock:
                _apply_request_config(entry.bot, req)
                chunks: List[str] = []
                thoughts: List[str] = []
                tools_used: List[Dict[str, Any]] = []
                for ev in entry.bot.stream_turn(msg):
                    if ev["type"] == "token":
                        chunks.append(ev["content"])
                    elif ev["type"] == "thought":
                        thoughts.append(ev["content"])
                    elif ev["type"] == "done":
                        tools_used = ev.get("tool_calls", [])
                    elif ev["type"] == "error":
                        return {"response": f"[Error: {ev['message']}]", "error": ev["message"]}
                return {
                    "response": "".join(chunks),
                    "thoughts": "".join(thoughts),
                    "tool_calls": tools_used,
                    "provider": entry.bot.config.provider,
                    "model": entry.bot.config.model_name,
                }

        result = await asyncio.to_thread(_run)
        return JSONResponse(result)

    @app.post("/api/chat/stream")
    async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
        msg = (req.message or "").strip()
        if not msg:
            raise HTTPException(status_code=400, detail="Empty message")

        entry = sessions.get_or_create(req.session_id)
        cancel_event = threading.Event()
        event_queue: queue.Queue[Optional[Dict[str, Any]]] = queue.Queue()

        def worker() -> None:
            with entry.lock:
                _apply_request_config(entry.bot, req)
                try:
                    for ev in entry.bot.stream_turn(msg, cancel_event=cancel_event):
                        event_queue.put(ev)
                except Exception as exc:
                    event_queue.put({"type": "error", "message": str(exc)})
                finally:
                    event_queue.put(None)

        threading.Thread(target=worker, daemon=True).start()

        async def sse_generator() -> AsyncIterator[str]:
            try:
                while True:
                    if await request.is_disconnected():
                        cancel_event.set()
                        break
                    try:
                        ev = event_queue.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.015)
                        continue
                    if ev is None:
                        break
                    yield f"data: {json.dumps(ev)}\n\n"
            finally:
                cancel_event.set()

        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


def start_web_server(config: ChatbotConfig, host: str = "127.0.0.1", port: int = 8000) -> None:
    app = create_app(config)
    print(f"\nWeb UI running at: http://{host}:{port}")
    print(f"Provider: {config.provider} | Model: {config.model_name}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


# ============================================================
# CLI
# ============================================================

def start_cli(bot: Chatbot) -> None:
    print("=" * 65)
    print(f" AI Chatbot Active ({bot.config.provider} / {bot.config.model_name})")
    print(f" Commands: /clear, /provider <{'|'.join(PROVIDER_SPECS)}>, /model <name>,")
    print("           /thinking <low|medium|high>, /tools <on|off>, /exit")
    print(" Try: 'gold rate in India', 'latest news on AI', 'what time is it?'")
    print("=" * 65 + "\n")

    while True:
        try:
            user = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break
        if not user:
            continue
        lower = user.lower()
        if lower in ("/exit", "/quit"):
            break
        if lower == "/clear":
            bot.reset_history()
            print("[History cleared]\n")
            continue
        if lower.startswith("/provider "):
            bot.reconfigure(provider=user.split(None, 1)[1].strip())
            print(f"[Provider switched to {bot.config.provider} / {bot.config.model_name}]\n")
            continue
        if lower.startswith("/model "):
            bot.reconfigure(model_name=user.split(None, 1)[1].strip())
            print(f"[Model switched to {bot.config.model_name}]\n")
            continue
        if lower.startswith("/thinking "):
            bot.reconfigure(thinking_level=user.split(None, 1)[1].strip())
            print(f"[Thinking level: {bot.config.thinking_level}]\n")
            continue
        if lower in ("/tools on", "/tools off"):
            bot.reconfigure(use_tools=lower.endswith("on"))
            print(f"[Tools {'enabled' if bot.config.use_tools else 'disabled'}]\n")
            continue

        print("Assistant: ", end="", flush=True)
        for ev in bot.stream_turn(user):
            if ev["type"] == "tool_start":
                print(f"\n  [Running tool: {ev['name']}({ev['args']})]", flush=True)
                print("Assistant: ", end="", flush=True)
            elif ev["type"] == "token":
                print(ev["content"], end="", flush=True)
            elif ev["type"] == "error":
                print(f"\n[Error: {ev['message']}]", flush=True)
        print("\n")


# ============================================================
# CONFIG CHECK & MAIN
# ============================================================

def print_config(bot: Chatbot) -> None:
    print("\n" + "=" * 65)
    print(" CONFIG")
    print("=" * 65)
    print(f" Provider : {bot.config.provider}")
    print(f" Model    : {bot.config.model_name}")
    print(f" Base URL : {bot.config.base_url}")
    print(f" Thinking : {bot.config.thinking_level}")
    print(f" Tools    : {'enabled' if bot.config.use_tools else 'disabled'}")
    key = bot.config.api_key
    if not requires_api_key(bot.config.provider):
        print(f" API Key  : not required ({bot.config.provider} mode)")
    else:
        print(f" API Key  : {'CONFIGURED' if key else 'NOT SET'}")
    print("=" * 65)
    print(" Tools available:")
    for spec in TOOL_SPECS:
        print(f"   - {spec['name']}: {spec['description'][:60]}...")
    print("=" * 65 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Chatbot (Gemini / Ollama / Groq / NVIDIA / Mock) with Streaming & Web UI")
    parser.add_argument("--provider", choices=list(PROVIDER_SPECS.keys()), default=None)
    parser.add_argument("--model", default="", help="Model name (defaults to provider recommended model)")
    parser.add_argument("--thinking", choices=["low", "medium", "high", "LOW", "MEDIUM", "HIGH"], default="MEDIUM")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--no-tools", action="store_true", help="Disable real-time function calling tools")
    parser.add_argument("--web", action="store_true", help="Launch FastAPI Web UI")
    parser.add_argument("--desktop", action="store_true", help="Launch always-on-screen desktop character companion")
    parser.add_argument("--sprite", default=None, help="Custom PNG/GIF/WebP character image for --desktop")
    parser.add_argument("--name", default=None, help="Custom character name for --desktop")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()

    if args.desktop:
        from desktop_companion import launch_desktop_companion

        raise SystemExit(
            launch_desktop_companion(
                provider=args.provider,
                model=args.model or None,
                sprite=args.sprite,
                name=args.name,
            )
        )

    config = ChatbotConfig(
        provider=args.provider or "gemini",
        model_name=args.model,
        api_key=args.api_key,
        base_url=args.base_url,
        thinking_level=args.thinking.upper(),
        use_tools=not args.no_tools,
    )
    bot = Chatbot(config)

    if args.check_config:
        print_config(bot)
        return

    if args.web:
        start_web_server(bot.config, host=args.host, port=args.port)
    else:
        start_cli(bot)


if __name__ == "__main__":
    main()
