"""
Extensible API & Integration tools for the AI Chatbot and Desktop Companion.

Provides:
- Built-in free / keyed connectors:
  * Weather (`get_weather`: OpenWeatherMap if key set, free Open-Meteo primary/fallback)
  * Web Search (`web_search`: Tavily if key set, free DuckDuckGo fallback)
  * News (`get_news`: NewsAPI if key set, free Google News RSS fallback)
  * Maps (`maps_lookup`: Google Maps API if key set, free OpenStreetMap Nominatim fallback)
  * Database (`database_query`: local SQLite read/write + Database REST APIs)
  * Email (`email_action`: IMAP read inbox + SMTP send email)
  * Calendar (`calendar_action`: Google Calendar API + iCal .ics feed/local file)
  * Payment (`payment_action`: Stripe & Razorpay read + payment links)
- Dynamic Custom / Company Internal API Registry (`custom_apis.json`):
  * Register any internal company API or third-party REST endpoint with env-backed
    secrets (stored safely in `.env`, never plaintext in JSON)
  * Configurable confirmation policy (`auto` = read-only GET runs automatically while
    write methods ask Allow/Deny, `always`, or `never`)
"""

from __future__ import annotations

import base64
import email
import html
import imaplib
import json
import math
import os
import re
import smtplib
import sqlite3
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

import system_tools

ConfirmCallback = Callable[[str, str, str], bool]

MAX_RESPONSE_CHARS = 4000
MAX_DB_ROWS = 50
HTTP_TIMEOUT = 15.0

CUSTOM_API_CATEGORIES: Tuple[str, ...] = (
    "Company Internal",
    "Weather",
    "News",
    "Maps",
    "Database",
    "Payment",
    "Email",
    "Calendar",
    "Web Search",
    "Custom",
)

AUTH_TYPES: Tuple[str, ...] = (
    "none",
    "bearer",
    "api_key_header",
    "api_key_query",
    "basic",
)

CONFIRMATION_MODES: Tuple[str, ...] = ("auto", "always", "never")
ALLOWED_HTTP_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}

_WMO_WEATHER_CODES: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

PRESET_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "Company Internal REST API": {
        "id": "company_internal",
        "name": "Company Internal API",
        "category": "Company Internal",
        "description": "Query or update internal company service endpoints (employees, tickets, inventory, reports).",
        "base_url": "https://api.company.internal/v1",
        "default_path": "/health",
        "method": "GET",
        "auth_type": "bearer",
        "auth_param": "Authorization",
        "env_secret_name": "COMPANY_API_TOKEN",
        "confirmation_mode": "auto",
    },
    "Weather (OpenWeatherMap)": {
        "id": "openweather",
        "name": "OpenWeatherMap",
        "category": "Weather",
        "description": "Current weather endpoint on api.openweathermap.org (pass query_params={'q': 'Chennai', 'units': 'metric'}).",
        "base_url": "https://api.openweathermap.org/data/2.5",
        "default_path": "/weather",
        "method": "GET",
        "auth_type": "api_key_query",
        "auth_param": "appid",
        "env_secret_name": "OPENWEATHER_API_KEY",
        "confirmation_mode": "auto",
    },
    "News API (newsapi.org)": {
        "id": "newsapi_org",
        "name": "NewsAPI.org",
        "category": "News",
        "description": "Search global articles on newsapi.org (pass query_params={'q': 'AI', 'pageSize': '5'}).",
        "base_url": "https://newsapi.org/v2",
        "default_path": "/everything",
        "method": "GET",
        "auth_type": "api_key_header",
        "auth_param": "X-Api-Key",
        "env_secret_name": "NEWSAPI_KEY",
        "confirmation_mode": "auto",
    },
    "Google Maps REST API": {
        "id": "google_maps",
        "name": "Google Maps Geocoding",
        "category": "Maps",
        "description": "Geocode addresses via Google Maps (pass query_params={'address': 'Chennai, India'}).",
        "base_url": "https://maps.googleapis.com/maps/api",
        "default_path": "/geocode/json",
        "method": "GET",
        "auth_type": "api_key_query",
        "auth_param": "key",
        "env_secret_name": "GOOGLE_MAPS_API_KEY",
        "confirmation_mode": "auto",
    },
    "Database REST (PostgREST / Supabase)": {
        "id": "database_rest",
        "name": "Database REST API",
        "category": "Database",
        "description": "Query or update database tables via REST (pass endpoint_path='/your_table' and query_params).",
        "base_url": "https://your-project.supabase.co/rest/v1",
        "default_path": "/",
        "method": "GET",
        "auth_type": "api_key_header",
        "auth_param": "apikey",
        "env_secret_name": "DATABASE_API_KEY",
        "confirmation_mode": "auto",
    },
    "Payment API (Stripe REST)": {
        "id": "stripe_rest",
        "name": "Stripe Payments REST",
        "category": "Payment",
        "description": "Inspect Stripe charges/customers or create payment resources via Stripe REST API.",
        "base_url": "https://api.stripe.com/v1",
        "default_path": "/payment_intents",
        "method": "GET",
        "auth_type": "bearer",
        "auth_param": "Authorization",
        "env_secret_name": "STRIPE_API_KEY",
        "confirmation_mode": "auto",
    },
    "Email Webhook / Resend API": {
        "id": "resend_email",
        "name": "Resend Email API",
        "category": "Email",
        "description": "Send transactional emails via Resend POST /emails with JSON body.",
        "base_url": "https://api.resend.com",
        "default_path": "/emails",
        "method": "POST",
        "auth_type": "bearer",
        "auth_param": "Authorization",
        "env_secret_name": "RESEND_API_KEY",
        "confirmation_mode": "always",
    },
    "Google Calendar REST API": {
        "id": "google_calendar_rest",
        "name": "Google Calendar API",
        "category": "Calendar",
        "description": "List or create Google Calendar events on /calendars/primary/events.",
        "base_url": "https://www.googleapis.com/calendar/v3",
        "default_path": "/calendars/primary/events",
        "method": "GET",
        "auth_type": "bearer",
        "auth_param": "Authorization",
        "env_secret_name": "GOOGLE_CALENDAR_TOKEN",
        "confirmation_mode": "auto",
    },
    "Generic Webhook / Custom REST": {
        "id": "custom_webhook",
        "name": "Custom Webhook",
        "category": "Custom",
        "description": "Call a custom webhook or third-party REST service.",
        "base_url": "https://example.com/api",
        "default_path": "/status",
        "method": "GET",
        "auth_type": "none",
        "auth_param": "",
        "env_secret_name": "",
        "confirmation_mode": "auto",
    },
}


@dataclass
class ApiToolsPolicy:
    """Runtime policy & UI confirmation hook for external/internal API calls."""

    confirm_callback: Optional[ConfirmCallback] = None
    allow_sensitive_without_confirm: bool = False
    allowed_roots: List[Path] = field(default_factory=system_tools.default_allowed_dirs)
    allow_all_non_system: bool = False


@dataclass
class CustomApiEndpoint:
    """Definition of a user-registered REST / company internal API endpoint."""

    id: str
    name: str
    category: str = "Company Internal"
    description: str = ""
    base_url: str = ""
    default_path: str = ""
    method: str = "GET"
    auth_type: str = "none"
    auth_param: str = ""
    env_secret_name: str = ""
    default_headers: Dict[str, str] = field(default_factory=dict)
    confirmation_mode: str = "auto"
    enabled: bool = True

    def normalized(self) -> "CustomApiEndpoint":
        clean_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", (self.id or "").strip()).strip("_").lower()
        if not clean_id:
            clean_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", (self.name or "custom_api").strip()).strip("_").lower() or "custom_api"
        method = (self.method or "GET").strip().upper()
        if method not in ALLOWED_HTTP_METHODS:
            method = "GET"
        auth_type = (self.auth_type or "none").strip().lower()
        if auth_type not in AUTH_TYPES:
            auth_type = "none"
        confirm_mode = (self.confirmation_mode or "auto").strip().lower()
        if confirm_mode not in CONFIRMATION_MODES:
            confirm_mode = "auto"
        return CustomApiEndpoint(
            id=clean_id,
            name=(self.name or clean_id).strip(),
            category=(self.category or "Custom").strip(),
            description=(self.description or "").strip(),
            base_url=(self.base_url or "").strip().rstrip("/"),
            default_path=(self.default_path or "").strip(),
            method=method,
            auth_type=auth_type,
            auth_param=(self.auth_param or "").strip(),
            env_secret_name=(self.env_secret_name or "").strip(),
            default_headers={str(k): str(v) for k, v in (self.default_headers or {}).items() if str(k).strip()},
            confirmation_mode=confirm_mode,
            enabled=bool(self.enabled),
        )


def _get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resolve_custom_apis_file(app_dir: Optional[Path] = None) -> Path:
    """Resolve `custom_apis.json` next to the app or in parent dir when running from dist/."""
    base = app_dir or _get_app_dir()
    primary = base / "custom_apis.json"
    if (
        not primary.exists()
        and app_dir is None
        and getattr(sys, "frozen", False)
        and base.name.lower() == "dist"
        and (base.parent / "custom_apis.json").is_file()
    ):
        return base.parent / "custom_apis.json"
    return primary


def load_custom_apis(path: Optional[Path] = None) -> List[CustomApiEndpoint]:
    target = path or resolve_custom_apis_file()
    if not target.is_file():
        return []
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        valid_fields = {f.name for f in CustomApiEndpoint.__dataclass_fields__.values()}
        items: List[CustomApiEndpoint] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            filtered = {k: v for k, v in entry.items() if k in valid_fields}
            if not filtered.get("id") and not filtered.get("name"):
                continue
            items.append(CustomApiEndpoint(**filtered).normalized())
        return items
    except Exception:
        return []


def save_custom_apis(endpoints: List[CustomApiEndpoint], path: Optional[Path] = None) -> Path:
    target = path or resolve_custom_apis_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = [asdict(ep.normalized()) for ep in endpoints]
    target.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
    return target


def upsert_custom_api(endpoint: CustomApiEndpoint, path: Optional[Path] = None) -> List[CustomApiEndpoint]:
    norm = endpoint.normalized()
    existing = load_custom_apis(path)
    replaced = False
    for idx, item in enumerate(existing):
        if item.id.lower() == norm.id.lower():
            existing[idx] = norm
            replaced = True
            break
    if not replaced:
        existing.append(norm)
    save_custom_apis(existing, path)
    return existing


def delete_custom_api(api_id: str, path: Optional[Path] = None) -> List[CustomApiEndpoint]:
    target_id = (api_id or "").strip().lower()
    remaining = [ep for ep in load_custom_apis(path) if ep.id.lower() != target_id]
    save_custom_apis(remaining, path)
    return remaining


def custom_apis_prompt_summary(path: Optional[Path] = None) -> str:
    """Short summary of enabled user-registered APIs for AI system prompts."""
    enabled = [ep for ep in load_custom_apis(path) if ep.enabled]
    if not enabled:
        return ""
    lines = ["User-registered Custom & Company Internal APIs (call via `call_custom_api`):"]
    for ep in enabled[:12]:
        desc = f" — {ep.description}" if ep.description else ""
        lines.append(f"- api_id='{ep.id}' [{ep.category}] ({ep.method} {ep.base_url}{ep.default_path}){desc}")
    return "\n".join(lines)


def _require_confirmation(
    policy: Optional[ApiToolsPolicy],
    title: str,
    detail: str,
    risk: str = "destructive",
) -> Optional[str]:
    """Enforce interactive Allow/Deny confirmation before sensitive API actions."""
    if policy is None:
        return "Error: Sensitive API actions require Desktop companion confirmation."
    if policy.confirm_callback is not None:
        approved = bool(policy.confirm_callback(title, detail, risk))
        if not approved:
            return f"Cancelled by user: {title}."
        return None
    if policy.allow_sensitive_without_confirm:
        return None
    return "Error: Confirmation callback is not available in this session; sensitive API action blocked."


def _truncate_text(text: str, limit: int = MAX_RESPONSE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


# ============================================================
# 1. WEATHER API (OpenWeatherMap optional + free Open-Meteo)
# ============================================================

def get_weather(location: str, days: int = 3) -> str:
    """Fetch current weather and forecast using OpenWeatherMap (if configured) or free Open-Meteo."""
    city = (location or "").strip()
    if not city:
        return "Error: Please provide a city or location name (e.g. 'Chennai')."
    try:
        forecast_days = max(1, min(7, int(days)))
    except (TypeError, ValueError):
        forecast_days = 3

    owm_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
    if owm_key:
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                resp = client.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"q": city, "appid": owm_key, "units": "metric"},
                )
            if resp.status_code == 200:
                d = resp.json()
                main = d.get("main") or {}
                wind = d.get("wind") or {}
                desc = ((d.get("weather") or [{}])[0].get("description") or "").title()
                place = d.get("name") or city
                country = (d.get("sys") or {}).get("country") or ""
                loc_label = f"{place}, {country}".strip(", ")
                return (
                    f"Weather for {loc_label} (OpenWeatherMap):\n"
                    f"- Condition: {desc or 'N/A'}\n"
                    f"- Temperature: {main.get('temp')}°C (Feels like {main.get('feels_like')}°C)\n"
                    f"- Min / Max: {main.get('temp_min')}°C / {main.get('temp_max')}°C\n"
                    f"- Humidity: {main.get('humidity')}%\n"
                    f"- Wind: {wind.get('speed')} m/s"
                )
        except Exception:
            pass  # fall back seamlessly to free Open-Meteo

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            geo = client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "en", "format": "json"},
            )
            geo.raise_for_status()
            geo_data = geo.json()
            results = geo_data.get("results") or []
            if results:
                top = results[0]
                lat, lon = top["latitude"], top["longitude"]
                place_parts = [top.get("name"), top.get("admin1"), top.get("country")]
                place_label = ", ".join(p for p in place_parts if p)
            else:
                nom = _nominatim_search(city, limit=1)
                if not nom:
                    return f"Could not find location '{city}' for weather lookup."
                top = nom[0]
                lat, lon = float(top["lat"]), float(top["lon"])
                place_label = str(top.get("display_name") or city)

            fc = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "forecast_days": forecast_days,
                    "timezone": "auto",
                },
            )
            fc.raise_for_status()
            wdata = fc.json()
    except Exception as exc:
        return f"Error fetching live weather for '{city}': {exc}"

    cur = wdata.get("current") or {}
    code = cur.get("weather_code")
    cond = _WMO_WEATHER_CODES.get(code, f"Weather code {code}")
    lines = [
        f"Weather for {place_label} (Open-Meteo, local {wdata.get('timezone', 'local')}):",
        f"- Current: {cond}, {cur.get('temperature_2m')}°C (Feels like {cur.get('apparent_temperature')}°C)",
        f"- Humidity: {cur.get('relative_humidity_2m')}% · Wind: {cur.get('wind_speed_10m')} km/h",
    ]
    daily = wdata.get("daily") or {}
    dates = daily.get("time") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    dcodes = daily.get("weather_code") or []
    rain = daily.get("precipitation_probability_max") or []
    if dates:
        lines.append("Forecast:")
        for idx, day_str in enumerate(dates[:forecast_days]):
            hi = tmax[idx] if idx < len(tmax) else "?"
            lo = tmin[idx] if idx < len(tmin) else "?"
            dc = _WMO_WEATHER_CODES.get(dcodes[idx] if idx < len(dcodes) else None, "")
            pr = f", Rain chance: {rain[idx]}%" if idx < len(rain) and rain[idx] is not None else ""
            lines.append(f"  - {day_str}: {lo}°C to {hi}°C ({dc}{pr})")
    return "\n".join(lines)


# ============================================================
# 2. WEB SEARCH (Tavily primary + free DuckDuckGo fallback)
# ============================================================

class _DDGHtmlParser(HTMLParser):
    """Lightweight stdlib HTML parser for DuckDuckGo HTML search results."""

    def __init__(self) -> None:
        super().__init__()
        self.results: List[Dict[str, str]] = []
        self._in_title = False
        self._in_snippet = False
        self._cur_title: List[str] = []
        self._cur_snippet: List[str] = []
        self._cur_href: str = ""

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attr_map = dict(attrs)
        cls = (attr_map.get("class") or "").split()
        if tag == "a" and "result__a" in cls:
            self._in_title = True
            self._cur_title = []
            self._cur_href = attr_map.get("href") or ""
        elif "result__snippet" in cls:
            self._in_snippet = True
            self._cur_snippet = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        elif self._in_snippet and tag in ("a", "div", "span"):
            self._in_snippet = False
            title = " ".join("".join(self._cur_title).split())
            snippet = " ".join("".join(self._cur_snippet).split())
            href = _unwrap_ddg_href(self._cur_href)
            if title or snippet:
                self.results.append({"title": title, "url": href, "snippet": snippet})
            self._cur_title = []
            self._cur_snippet = []
            self._cur_href = ""

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._cur_title.append(html.unescape(data))
        elif self._in_snippet:
            self._cur_snippet.append(html.unescape(data))


def _unwrap_ddg_href(href: str) -> str:
    if "uddg=" in href:
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        if qs.get("uddg"):
            return qs["uddg"][0]
    if href.startswith("//"):
        return "https:" + href
    return href


def _duckduckgo_fallback_search(query: str, max_results: int = 5, reason: str = "") -> str:
    """Free keyless DuckDuckGo HTML + Instant Answer fallback search."""
    items: List[Dict[str, str]] = []
    abstract = ""

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            html_resp = client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"},
            )
            if html_resp.status_code == 200 and html_resp.text:
                parser = _DDGHtmlParser()
                parser.feed(html_resp.text)
                items.extend(parser.results[:max_results])

            if not items:
                ia_resp = client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
                    headers={"User-Agent": "AICompanion/1.0"},
                )
                if ia_resp.text.lstrip().startswith("{"):
                    ia = ia_resp.json()
                    abstract = (ia.get("AbstractText") or ia.get("Abstract") or "").strip()
                    for rel in (ia.get("RelatedTopics") or [])[:max_results]:
                        if isinstance(rel, dict) and rel.get("Text"):
                            items.append({
                                "title": rel.get("Text", "")[:100],
                                "url": rel.get("FirstURL", ""),
                                "snippet": rel.get("Text", ""),
                            })
    except Exception as exc:
        prefix = f"[{reason} — using free DuckDuckGo search]\n" if reason else ""
        return f"{prefix}Web search error (DuckDuckGo fallback failed): {exc}"

    lines: List[str] = []
    if reason:
        lines.append(f"[{reason} — using free DuckDuckGo search]")
    if abstract:
        lines.append(f"Summary: {abstract}")
    if items:
        lines.append("Sources:")
        for idx, it in enumerate(items[:max_results], 1):
            lines.append(f"{idx}. {it.get('title') or 'Result'}\n   URL: {it.get('url', '')}\n   {it.get('snippet', '')[:320]}")
    if not (abstract or items):
        lines.append(f"No free web search results found for '{query}'.")
    return "\n".join(lines)


def web_search(
    query: str,
    topic: str = "general",
    search_depth: str = "basic",
    max_results: int = 5,
) -> str:
    """Search the live web using Tavily (primary if configured) with automatic free DuckDuckGo fallback."""
    clean_query = (query or "").strip()
    if not clean_query:
        return "Error: Search query must not be empty."

    clean_topic = topic if topic in ("general", "news", "finance") else "general"
    clean_depth = search_depth if search_depth in ("basic", "advanced") else "basic"
    try:
        clamped_max = max(1, min(10, int(max_results)))
    except (TypeError, ValueError):
        clamped_max = 5

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return _duckduckgo_fallback_search(clean_query, clamped_max, reason="TAVILY_API_KEY not set")

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
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.post("https://api.tavily.com/search", headers=headers, json=payload)
            if resp.status_code != 200:
                return _duckduckgo_fallback_search(
                    clean_query,
                    clamped_max,
                    reason=f"Tavily HTTP {resp.status_code}",
                )
            data = resp.json()
    except Exception as exc:
        return _duckduckgo_fallback_search(clean_query, clamped_max, reason=f"Tavily error ({exc})")

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


# ============================================================
# 3. NEWS API (NewsAPI optional + Google News RSS fallback)
# ============================================================

def get_news(keyword: str) -> str:
    """Fetch latest news via NewsAPI.org (if NEWSAPI_KEY set) or free Google News RSS."""
    cleaned = (keyword or "").strip()
    if not cleaned:
        return json.dumps({"error": "Missing 'keyword' argument"})

    news_key = os.getenv("NEWSAPI_KEY", "").strip()
    if news_key:
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                resp = client.get(
                    "https://newsapi.org/v2/everything",
                    params={"q": cleaned, "pageSize": 5, "sortBy": "publishedAt"},
                    headers={"X-Api-Key": news_key},
                )
            if resp.status_code == 200:
                articles = (resp.json().get("articles") or [])[:5]
                if articles:
                    out = []
                    for art in articles:
                        title = art.get("title") or "(no title)"
                        src = ((art.get("source") or {}).get("name") or "").strip()
                        pub = art.get("publishedAt") or ""
                        link = art.get("url") or ""
                        entry = f"- {title}"
                        if src:
                            entry += f" [{src}]"
                        if pub:
                            entry += f" ({pub})"
                        if link:
                            entry += f"\n  Link: {link}"
                        out.append(entry)
                    return "\n".join(out)
        except Exception:
            pass

    q = urllib.parse.quote(cleaned)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
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


# ============================================================
# 4. MAPS API (Google Maps if key set + OpenStreetMap fallback)
# ============================================================

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _nominatim_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": limit},
            headers={"User-Agent": "AICompanion/1.0 (desktop-assistant)"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []


def maps_lookup(
    action: str = "places",
    query: str = "",
    origin: str = "",
    destination: str = "",
    mode: str = "driving",
) -> str:
    """Geocode addresses, search places, or get directions (Google Maps API or free OpenStreetMap fallback)."""
    act = (action or "places").strip().lower()
    gmaps_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()

    if act == "directions":
        orig = (origin or "").strip()
        dest = (destination or "").strip()
        if not orig or not dest:
            return "Error: 'origin' and 'destination' are required for maps directions."
        travel_mode = mode if mode in ("driving", "walking", "bicycling", "transit") else "driving"
        if gmaps_key:
            try:
                with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                    r = client.get(
                        "https://maps.googleapis.com/maps/api/directions/json",
                        params={"origin": orig, "destination": dest, "mode": travel_mode, "key": gmaps_key},
                    )
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") == "OK" and data.get("routes"):
                        leg = data["routes"][0]["legs"][0]
                        steps = [
                            re.sub(r"<[^>]+>", "", s.get("html_instructions", ""))
                            + f" ({s.get('distance', {}).get('text', '')})"
                            for s in (leg.get("steps") or [])[:8]
                        ]
                        return (
                            f"Google Maps Directions ({travel_mode}):\n"
                            f"- From: {leg.get('start_address')}\n"
                            f"- To: {leg.get('end_address')}\n"
                            f"- Distance: {leg.get('distance', {}).get('text')} · Duration: {leg.get('duration', {}).get('text')}\n"
                            + ("Steps:\n  " + "\n  ".join(steps) if steps else "")
                        )
            except Exception:
                pass
        try:
            o_res = _nominatim_search(orig, limit=1)
            d_res = _nominatim_search(dest, limit=1)
            if o_res and d_res:
                km = _haversine_km(
                    float(o_res[0]["lat"]),
                    float(o_res[0]["lon"]),
                    float(d_res[0]["lat"]),
                    float(d_res[0]["lon"]),
                )
                return (
                    f"Distance estimate via OpenStreetMap (add GOOGLE_MAPS_API_KEY for full turn-by-turn routes):\n"
                    f"- Origin: {o_res[0].get('display_name')}\n"
                    f"- Destination: {d_res[0].get('display_name')}\n"
                    f"- Straight-line distance: {km:.2f} km"
                )
        except Exception as exc:
            return f"Error looking up directions: {exc}"
        return "Could not resolve origin or destination for directions."

    clean_q = (query or "").strip()
    if not clean_q:
        return "Error: 'query' is required for maps geocode/places lookup."

    if gmaps_key:
        try:
            endpoint = (
                "https://maps.googleapis.com/maps/api/geocode/json"
                if act == "geocode"
                else "https://maps.googleapis.com/maps/api/place/textsearch/json"
            )
            param_key = "address" if act == "geocode" else "query"
            with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                r = client.get(endpoint, params={param_key: clean_q, "key": gmaps_key})
            if r.status_code == 200:
                data = r.json()
                results = (data.get("results") or [])[:5]
                if data.get("status") == "OK" and results:
                    lines = [f"Google Maps ({act}) for '{clean_q}':"]
                    for item in results:
                        name = item.get("name") or item.get("formatted_address")
                        addr = item.get("formatted_address", "")
                        loc = (item.get("geometry") or {}).get("location") or {}
                        rating = f" · Rating: {item['rating']}" if item.get("rating") else ""
                        lines.append(f"- {name} ({addr}) [{loc.get('lat')}, {loc.get('lng')}]{rating}")
                    return "\n".join(lines)
        except Exception:
            pass

    try:
        osm_items = _nominatim_search(clean_q, limit=5)
        if not osm_items:
            return f"No map locations found for '{clean_q}'."
        lines = [f"OpenStreetMap results for '{clean_q}':"]
        for item in osm_items:
            lines.append(
                f"- {item.get('display_name')} "
                f"(type: {item.get('type', 'place')}, lat: {item.get('lat')}, lon: {item.get('lon')})"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"Error querying Maps: {exc}"


# ============================================================
# 5. DATABASE API (SQLite local + Database REST API)
# ============================================================

_WRITE_SQL_WORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|vacuum|reindex)\b",
    re.IGNORECASE,
)


def _strip_sql_comments(sql: str) -> str:
    no_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    no_line = re.sub(r"--[^\r\n]*", " ", no_block)
    return no_line.strip()


def _is_readonly_sql(sql: str) -> bool:
    cleaned = _strip_sql_comments(sql).rstrip(";").strip()
    if not cleaned or ";" in cleaned:
        return False
    first = cleaned.split(None, 1)[0].lower()
    if first not in ("select", "pragma", "explain", "with"):
        return False
    if _WRITE_SQL_WORDS.search(cleaned):
        return False
    return True


def _validate_sqlite_path(raw_path: str, policy: Optional[ApiToolsPolicy]) -> Tuple[Optional[Path], Optional[str]]:
    candidate_str = (raw_path or os.getenv("SQLITE_DB_PATH") or os.getenv("DATABASE_PATH") or "").strip()
    if not candidate_str:
        return None, "Please pass db_path (or set SQLITE_DB_PATH in .env)."
    sys_policy = system_tools.SystemToolsPolicy(
        enabled=True,
        allowed_roots=(policy.allowed_roots if policy else system_tools.default_allowed_dirs()),
        allow_all_non_system=(policy.allow_all_non_system if policy else False),
    )
    return system_tools._validate_path(candidate_str, sys_policy)


def database_query(
    action: str = "query",
    sql: str = "",
    db_path: str = "",
    connection_url: str = "",
    *,
    policy: Optional[ApiToolsPolicy] = None,
) -> str:
    """Inspect tables/schemas or run SQL against local SQLite or a Database REST endpoint."""
    act = (action or "query").strip().lower()
    rest_url = (connection_url or os.getenv("DATABASE_API_URL") or "").strip()
    if rest_url and not db_path.strip():
        return _database_rest_query(rest_url, sql_or_endpoint=sql or act, policy=policy)

    resolved_db, err = _validate_sqlite_path(db_path, policy)
    if err or resolved_db is None:
        return f"Error: {err or 'Invalid SQLite database path.'}"
    if not resolved_db.is_file():
        return f"Error: SQLite database file does not exist: {resolved_db}"

    if act == "tables":
        query_sql = "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name"
    elif act == "schema":
        query_sql = "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
    else:
        query_sql = (sql or "").strip()
        if not query_sql:
            return "Error: 'sql' query is required."

    readonly = (act in ("tables", "schema")) or (act != "execute" and _is_readonly_sql(query_sql))
    if not readonly:
        deny_msg = _require_confirmation(
            policy,
            "Execute Database Write",
            f"Database: {resolved_db}\nSQL:\n{query_sql[:400]}",
            risk="destructive",
        )
        if deny_msg:
            return deny_msg

    try:
        uri = f"file:{resolved_db}?mode=ro" if readonly else str(resolved_db)
        conn = sqlite3.connect(uri, uri=readonly, timeout=10.0)
        try:
            cur = conn.cursor()
            if readonly:
                cur.execute(query_sql)
                rows = cur.fetchmany(MAX_DB_ROWS + 1)
                cols = [d[0] for d in cur.description] if cur.description else []
                more = len(rows) > MAX_DB_ROWS
                rows = rows[:MAX_DB_ROWS]
                payload = {
                    "database": str(resolved_db),
                    "columns": cols,
                    "row_count": len(rows),
                    "truncated": more,
                    "rows": [dict(zip(cols, r)) if cols else list(r) for r in rows],
                }
                return _truncate_text(json.dumps(payload, indent=2, default=str))
            cur.executescript(query_sql) if ";" in _strip_sql_comments(query_sql).rstrip(";") else cur.execute(query_sql)
            conn.commit()
            return f"SQL executed successfully on {resolved_db}. Rows affected: {cur.rowcount}."
        finally:
            conn.close()
    except Exception as exc:
        return f"Database error: {exc}"


def _database_rest_query(base_url: str, sql_or_endpoint: str, policy: Optional[ApiToolsPolicy]) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        return "Error: Database REST URL must use http:// or https://."
    db_key = os.getenv("DATABASE_API_KEY", "").strip()
    headers = {"Accept": "application/json"}
    if db_key:
        headers["apikey"] = db_key
        headers["Authorization"] = f"Bearer {db_key}"

    target = base_url.rstrip("/")
    rel = (sql_or_endpoint or "").strip()
    if rel and "://" not in rel and not rel.lower().startswith(("select ", "insert ", "update ", "delete ")):
        target = f"{target}/{rel.lstrip('/')}"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            if rel.lower().startswith(("select ", "with ")) or not rel.lower().startswith(("insert ", "update ", "delete ")):
                resp = client.get(target, headers=headers)
            else:
                deny_msg = _require_confirmation(
                    policy,
                    "Database REST Write",
                    f"Target: {target}\nPayload: {rel[:300]}",
                    risk="destructive",
                )
                if deny_msg:
                    return deny_msg
                resp = client.post(target, headers=headers, json={"query": rel})
        return _truncate_text(f"HTTP {resp.status_code}\n{resp.text}")
    except Exception as exc:
        return f"Database REST error: {exc}"


# ============================================================
# 6. EMAIL API (IMAP list inbox + SMTP send with confirmation)
# ============================================================

def _decode_mime_words(value: str) -> str:
    parts = []
    for chunk, charset in decode_header(value or ""):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


def email_action(
    action: str = "list_inbox",
    to: str = "",
    subject: str = "",
    body: str = "",
    limit: int = 5,
    *,
    policy: Optional[ApiToolsPolicy] = None,
) -> str:
    """Read inbox messages via IMAP or send an email via SMTP (with confirmation popup)."""
    user = os.getenv("EMAIL_USER", "").strip()
    password = os.getenv("EMAIL_PASSWORD", "").strip()
    if not user or not password:
        return (
            "Error: EMAIL_USER / EMAIL_PASSWORD not configured. Set them in "
            "Settings -> APIs & Tools -> Configure API Credentials (or .env)."
        )

    act = (action or "list_inbox").strip().lower()
    is_gmail = user.lower().endswith("@gmail.com")

    if act == "list_inbox":
        imap_host = os.getenv("IMAP_HOST", "").strip() or ("imap.gmail.com" if is_gmail else "")
        if not imap_host:
            return "Error: IMAP_HOST is not configured in Settings / .env."
        imap_port = int(os.getenv("IMAP_PORT", "993") or 993)
        try:
            cap = max(1, min(15, int(limit)))
        except (TypeError, ValueError):
            cap = 5

        try:
            with imaplib.IMAP4_SSL(imap_host, imap_port) as mail:
                mail.login(user, password)
                mail.select("INBOX", readonly=True)
                _, data = mail.search(None, "ALL")
                ids = (data[0] or b"").split()
                if not ids:
                    return "Inbox is empty."
                lines = [f"Latest {min(cap, len(ids))} email(s) for {user}:"]
                for msg_id in reversed(ids[-cap:]):
                    _, msg_data = mail.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                    raw_hdr = msg_data[0][1] if msg_data and isinstance(msg_data[0], tuple) else b""
                    msg = email.message_from_bytes(raw_hdr)
                    subj = _decode_mime_words(msg.get("Subject", "(no subject)"))
                    frm = _decode_mime_words(msg.get("From", ""))
                    dt = msg.get("Date", "")
                    lines.append(f"- {subj}\n  From: {frm} ({dt})")
                return "\n".join(lines)
        except Exception as exc:
            return f"Email IMAP error: {exc}"

    if act == "send_email":
        clean_to = (to or "").strip()
        clean_subj = (subject or "").strip()
        if not clean_to or "@" not in clean_to:
            return "Error: A valid recipient email address ('to') is required."
        if not clean_subj:
            return "Error: Email 'subject' is required."

        smtp_host = os.getenv("SMTP_HOST", "").strip() or ("smtp.gmail.com" if is_gmail else "")
        if not smtp_host:
            return "Error: SMTP_HOST is not configured in Settings / .env."
        smtp_port = int(os.getenv("SMTP_PORT", "587") or 587)

        deny_msg = _require_confirmation(
            policy,
            "Send Email",
            f"From: {user}\nTo: {clean_to}\nSubject: {clean_subj}\n\n{(body or '')[:350]}",
            risk="destructive",
        )
        if deny_msg:
            return deny_msg

        msg = EmailMessage()
        msg["From"] = user
        msg["To"] = clean_to
        msg["Subject"] = clean_subj
        msg.set_content(body or "")

        try:
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15) as srv:
                    srv.login(user, password)
                    srv.send_message(msg)
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as srv:
                    srv.starttls()
                    srv.login(user, password)
                    srv.send_message(msg)
            return f"Email sent cleanly to {clean_to} with subject '{clean_subj}'."
        except Exception as exc:
            return f"Email SMTP error: {exc}"

    return f"Error: Unsupported email action '{act}'. Use 'list_inbox' or 'send_email'."


# ============================================================
# 7. CALENDAR API (Google Calendar REST + .ics URL / local file)
# ============================================================

def _parse_ics_events(ics_text: str, limit: int = 10) -> List[Dict[str, str]]:
    events: List[Dict[str, str]] = []
    cur: Optional[Dict[str, str]] = None
    unfolded = re.sub(r"\r?\n[ \t]", "", ics_text or "")
    for raw_line in unfolded.splitlines():
        line = raw_line.strip()
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            events.append(cur)
            cur = None
            if len(events) >= limit:
                break
        elif cur is not None and ":" in line:
            key_part, val = line.split(":", 1)
            key = key_part.split(";", 1)[0].upper()
            if key in ("SUMMARY", "DTSTART", "DTEND", "LOCATION"):
                cur[key.lower()] = val
    return events


def calendar_action(
    action: str = "list_events",
    days: int = 7,
    title: str = "",
    start_iso: str = "",
    end_iso: str = "",
    description: str = "",
    location: str = "",
    *,
    policy: Optional[ApiToolsPolicy] = None,
) -> str:
    """List upcoming events or create events (Google Calendar REST API or iCal .ics feed/file)."""
    act = (action or "list_events").strip().lower()
    gcal_token = os.getenv("GOOGLE_CALENDAR_TOKEN", "").strip()
    ics_url = os.getenv("CALENDAR_ICS_URL", "").strip()
    ics_path_env = os.getenv("CALENDAR_ICS_PATH", "").strip()

    if act == "list_events":
        try:
            lookahead = max(1, min(60, int(days)))
        except (TypeError, ValueError):
            lookahead = 7

        if gcal_token:
            now = datetime.now(timezone.utc)
            end = now + timedelta(days=lookahead)
            try:
                with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                    resp = client.get(
                        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                        params={
                            "timeMin": now.isoformat(),
                            "timeMax": end.isoformat(),
                            "singleEvents": "true",
                            "orderBy": "startTime",
                            "maxResults": 15,
                        },
                        headers={"Authorization": f"Bearer {gcal_token}"},
                    )
                if resp.status_code != 200:
                    return f"Google Calendar error (HTTP {resp.status_code}): {resp.text[:300]}"
                items = resp.json().get("items") or []
                if not items:
                    return f"No Google Calendar events in the next {lookahead} day(s)."
                lines = [f"Upcoming Google Calendar events (next {lookahead} days):"]
                for ev in items:
                    st = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date") or ""
                    lines.append(f"- {ev.get('summary', '(No title)')} · {st}" + (f" ({ev['location']})" if ev.get("location") else ""))
                return "\n".join(lines)
            except Exception as exc:
                return f"Google Calendar request failed: {exc}"

        if ics_url:
            try:
                with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
                    resp = client.get(ics_url)
                    resp.raise_for_status()
                events = _parse_ics_events(resp.text)
                if not events:
                    return "No VEVENT entries found in CALENDAR_ICS_URL."
                return "Calendar events (.ics feed):\n" + "\n".join(
                    f"- {ev.get('summary', '(No title)')} · {ev.get('dtstart', '')}" for ev in events
                )
            except Exception as exc:
                return f"Failed to read CALENDAR_ICS_URL: {exc}"

        if ics_path_env:
            sys_policy = system_tools.SystemToolsPolicy(
                enabled=True,
                allowed_roots=(policy.allowed_roots if policy else system_tools.default_allowed_dirs()),
                allow_all_non_system=(policy.allow_all_non_system if policy else False),
            )
            p, err = system_tools._validate_path(ics_path_env, sys_policy)
            if err or p is None:
                return f"Error: {err}"
            if p.is_file():
                events = _parse_ics_events(p.read_text(encoding="utf-8", errors="ignore"))
                if not events:
                    return f"No events found in {p}."
                return f"Calendar events ({p.name}):\n" + "\n".join(
                    f"- {ev.get('summary', '(No title)')} · {ev.get('dtstart', '')}" for ev in events
                )

        return (
            "Error: Calendar is not configured. Add GOOGLE_CALENDAR_TOKEN, CALENDAR_ICS_URL, "
            "or CALENDAR_ICS_PATH in Settings -> APIs & Tools (or .env)."
        )

    if act == "create_event":
        clean_title = (title or "").strip()
        clean_start = (start_iso or "").strip()
        if not clean_title or not clean_start:
            return "Error: 'title' and 'start_iso' (e.g. '2026-11-12T10:00:00+05:30') are required."
        clean_end = (end_iso or "").strip() or clean_start

        if not gcal_token:
            return "Error: GOOGLE_CALENDAR_TOKEN must be set in Settings / .env to create calendar events."

        deny_msg = _require_confirmation(
            policy,
            "Create Calendar Event",
            f"Title: {clean_title}\nStart: {clean_start}\nEnd: {clean_end}"
            + (f"\nLocation: {location}" if location else ""),
            risk="destructive",
        )
        if deny_msg:
            return deny_msg

        body: Dict[str, Any] = {
            "summary": clean_title,
            "start": {"dateTime": clean_start} if "T" in clean_start else {"date": clean_start},
            "end": {"dateTime": clean_end} if "T" in clean_end else {"date": clean_end},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location

        try:
            with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                resp = client.post(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                    headers={"Authorization": f"Bearer {gcal_token}", "Content-Type": "application/json"},
                    json=body,
                )
            if resp.status_code not in (200, 201):
                return f"Google Calendar create failed (HTTP {resp.status_code}): {resp.text[:300]}"
            created = resp.json()
            return f"Created calendar event '{clean_title}' (ID: {created.get('id', '')}). Link: {created.get('htmlLink', '')}"
        except Exception as exc:
            return f"Google Calendar create error: {exc}"

    return f"Error: Unsupported calendar action '{act}'. Use 'list_events' or 'create_event'."


# ============================================================
# 8. PAYMENT API (Stripe & Razorpay — read & payment links)
# ============================================================

def payment_action(
    action: str = "list_payments",
    provider: str = "",
    amount: Any = "",
    currency: str = "INR",
    description: str = "",
    payment_id: str = "",
    *,
    policy: Optional[ApiToolsPolicy] = None,
) -> str:
    """Inspect Stripe / Razorpay payments or create a payment link (always confirms first)."""
    act = (action or "list_payments").strip().lower()
    stripe_key = os.getenv("STRIPE_API_KEY", "").strip()
    rzp_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    rzp_sec = os.getenv("RAZORPAY_KEY_SECRET", "").strip()

    chosen = (provider or "").strip().lower()
    if not chosen:
        if rzp_id and rzp_sec:
            chosen = "razorpay"
        elif stripe_key:
            chosen = "stripe"

    if not chosen:
        return (
            "Error: No payment credentials configured. Add STRIPE_API_KEY or "
            "RAZORPAY_KEY_ID + RAZORPAY_KEY_SECRET in Settings -> APIs & Tools (or .env)."
        )

    if chosen == "stripe":
        if not stripe_key:
            return "Error: STRIPE_API_KEY is not configured."
        headers = {"Authorization": f"Bearer {stripe_key}"}
        if act == "list_payments":
            try:
                with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                    r = client.get("https://api.stripe.com/v1/payment_intents", params={"limit": 5}, headers=headers)
                if r.status_code != 200:
                    return f"Stripe error (HTTP {r.status_code}): {r.text[:300]}"
                items = r.json().get("data") or []
                if not items:
                    return "No recent Stripe payments found."
                return "Recent Stripe Payment Intents:\n" + "\n".join(
                    f"- {p.get('id')}: {p.get('amount')} {str(p.get('currency', '')).upper()} [{p.get('status')}]"
                    for p in items
                )
            except Exception as exc:
                return f"Stripe error: {exc}"
        if act == "get_payment_status":
            if not payment_id.strip():
                return "Error: 'payment_id' is required."
            try:
                with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                    r = client.get(f"https://api.stripe.com/v1/payment_intents/{urllib.parse.quote(payment_id.strip())}", headers=headers)
                return _truncate_text(f"HTTP {r.status_code}\n{r.text}")
            except Exception as exc:
                return f"Stripe error: {exc}"
        if act == "create_payment_link":
            return (
                "Info: Creating Stripe Payment Links requires an existing Stripe Price ID (`line_items[0][price]`). "
                "You can register a custom Stripe endpoint or pass a Razorpay payment link request."
            )
        return f"Error: Unsupported Stripe action '{act}'."

    if chosen == "razorpay":
        if not (rzp_id and rzp_sec):
            return "Error: RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must both be set."
        auth = (rzp_id, rzp_sec)
        if act == "list_payments":
            try:
                with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                    r = client.get("https://api.razorpay.com/v1/payments", params={"count": 5}, auth=auth)
                if r.status_code != 200:
                    return f"Razorpay error (HTTP {r.status_code}): {r.text[:300]}"
                items = r.json().get("items") or []
                if not items:
                    return "No recent Razorpay payments found."
                return "Recent Razorpay Payments:\n" + "\n".join(
                    f"- {p.get('id')}: {int(p.get('amount', 0)) / 100:.2f} {p.get('currency', '')} [{p.get('status')}]"
                    for p in items
                )
            except Exception as exc:
                return f"Razorpay error: {exc}"
        if act == "get_payment_status":
            if not payment_id.strip():
                return "Error: 'payment_id' is required."
            try:
                with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                    r = client.get(f"https://api.razorpay.com/v1/payments/{urllib.parse.quote(payment_id.strip())}", auth=auth)
                return _truncate_text(f"HTTP {r.status_code}\n{r.text}")
            except Exception as exc:
                return f"Razorpay error: {exc}"
        if act == "create_payment_link":
            try:
                major_amount = float(str(amount).strip())
                if major_amount <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return "Error: A positive numeric 'amount' (e.g. 500) is required."
            cur_code = (currency or "INR").strip().upper()
            desc = (description or "Payment Link").strip()
            deny_msg = _require_confirmation(
                policy,
                "Create Razorpay Payment Link",
                f"Amount: {major_amount:.2f} {cur_code}\nDescription: {desc}",
                risk="destructive",
            )
            if deny_msg:
                return deny_msg
            try:
                with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                    r = client.post(
                        "https://api.razorpay.com/v1/payment_links",
                        auth=auth,
                        json={
                            "amount": int(round(major_amount * 100)),
                            "currency": cur_code,
                            "description": desc,
                        },
                    )
                return _truncate_text(f"HTTP {r.status_code}\n{r.text}")
            except Exception as exc:
                return f"Razorpay link creation error: {exc}"
        return f"Error: Unsupported Razorpay action '{act}'."

    return f"Error: Unsupported payment provider '{chosen}'. Use 'stripe' or 'razorpay'."


# ============================================================
# 9. DYNAMIC CUSTOM / COMPANY INTERNAL API CONNECTOR
# ============================================================

def list_custom_apis(custom_apis_path: Optional[Path] = None) -> str:
    """List user-registered Custom & Company Internal APIs without exposing secrets."""
    endpoints = load_custom_apis(custom_apis_path)
    if not endpoints:
        return (
            "No custom or company internal APIs registered yet. "
            "Open Settings -> APIs & Tools to add one."
        )
    lines = [f"Registered Custom APIs ({len(endpoints)}):"]
    for ep in endpoints:
        state = "ON" if ep.enabled else "OFF"
        secret_status = (
            f"key:{ep.env_secret_name} ({'set' if os.getenv(ep.env_secret_name) else 'unset'})"
            if ep.env_secret_name
            else f"auth:{ep.auth_type}"
        )
        lines.append(
            f"- [{state}] api_id='{ep.id}' | {ep.name} ({ep.category}) | "
            f"{ep.method} {ep.base_url}{ep.default_path} | {secret_status} | confirm:{ep.confirmation_mode}"
            + (f"\n  Note: {ep.description}" if ep.description else "")
        )
    return "\n".join(lines)


def _join_base_and_relative_path(base_url: str, rel_path: str) -> Tuple[Optional[str], Optional[str]]:
    base = (base_url or "").strip().rstrip("/")
    parsed_base = urllib.parse.urlparse(base)
    if parsed_base.scheme not in ("http", "https") or not parsed_base.netloc:
        return None, f"Invalid base_url '{base}'. Must start with http:// or https://."

    rel = (rel_path or "").strip()
    if not rel:
        return base, None
    if "://" in rel or rel.startswith("//"):
        return None, "Security block: endpoint_path must be a relative path, not a full URL."
    return f"{base}/{rel.lstrip('/')}", None


def _coerce_optional_json_dict(value: Any, field_name: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if value is None or value == "":
        return None, None
    if isinstance(value, dict):
        return dict(value), None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None, None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            return None, f"Invalid JSON in '{field_name}': {exc}"
        if not isinstance(parsed, dict):
            return None, f"'{field_name}' must be a JSON object."
        return parsed, None
    return None, f"'{field_name}' must be an object or JSON object string."


def call_custom_api(
    api_id: str,
    endpoint_path: str = "",
    method: str = "",
    query_params: Optional[Any] = None,
    json_body: Optional[Any] = None,
    *,
    policy: Optional[ApiToolsPolicy] = None,
    custom_apis_path: Optional[Path] = None,
) -> str:
    """Invoke a registered custom or company internal REST API safely."""
    target_id = (api_id or "").strip().lower()
    if not target_id:
        return "Error: 'api_id' is required. Call list_custom_apis to see registered IDs."

    parsed_query, q_err = _coerce_optional_json_dict(query_params, "query_params")
    if q_err:
        return f"Error: {q_err}"
    parsed_body, b_err = _coerce_optional_json_dict(json_body, "json_body")
    if b_err:
        return f"Error: {b_err}"

    match: Optional[CustomApiEndpoint] = None
    for ep in load_custom_apis(custom_apis_path):
        if ep.id.lower() == target_id:
            match = ep
            break
    if match is None:
        return f"Error: Custom API '{api_id}' not found. Call list_custom_apis to view registered APIs."
    if not match.enabled:
        return f"Error: Custom API '{match.id}' is currently disabled in Settings."

    rel_path = endpoint_path.strip() if endpoint_path and endpoint_path.strip() else match.default_path
    full_url, url_err = _join_base_and_relative_path(match.base_url, rel_path)
    if url_err or not full_url:
        return f"Error: {url_err}"

    http_method = (method or match.method or "GET").strip().upper()
    if http_method not in ALLOWED_HTTP_METHODS:
        return f"Error: HTTP method '{http_method}' is not allowed."

    q_params: Dict[str, Any] = dict(parsed_query) if parsed_query else {}
    headers: Dict[str, str] = {"Accept": "application/json", **match.default_headers}
    secret = os.getenv(match.env_secret_name, "").strip() if match.env_secret_name else ""

    if match.auth_type != "none" and match.env_secret_name and not secret:
        return (
            f"Error: Secret '{match.env_secret_name}' for API '{match.name}' is not set in .env / Settings."
        )

    if secret:
        if match.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {secret}"
        elif match.auth_type == "api_key_header":
            hdr_name = match.auth_param or "X-API-Key"
            headers[hdr_name] = secret
        elif match.auth_type == "api_key_query":
            p_name = match.auth_param or "api_key"
            q_params[p_name] = secret
        elif match.auth_type == "basic":
            encoded = base64.b64encode(secret.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {encoded}"

    needs_confirm = (
        match.confirmation_mode == "always"
        or (match.confirmation_mode != "never" and http_method not in ("GET", "HEAD"))
    )
    if needs_confirm:
        preview_parts = [f"API: {match.name} ({match.category})", f"{http_method} {full_url}"]
        if parsed_query:
            preview_parts.append(f"Query: {json.dumps(parsed_query)[:200]}")
        if parsed_body is not None:
            preview_parts.append(f"Body: {json.dumps(parsed_body)[:300]}")
        deny_msg = _require_confirmation(
            policy,
            f"Call API: {match.name}",
            "\n".join(preview_parts),
            risk="destructive" if http_method not in ("GET", "HEAD") else "launch",
        )
        if deny_msg:
            return deny_msg

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            resp = client.request(
                http_method,
                full_url,
                headers=headers,
                params=q_params or None,
                json=parsed_body if http_method in ("POST", "PUT", "PATCH", "DELETE") else None,
            )
        body_text = resp.text
        try:
            body_text = json.dumps(resp.json(), indent=2)
        except Exception:
            pass
        return _truncate_text(f"HTTP {resp.status_code} ({http_method} {full_url})\n{body_text}")
    except Exception as exc:
        return f"Custom API '{match.id}' request error: {exc}"


# ============================================================
# TOOL SCHEMAS & DISPATCH
# ============================================================

def get_api_tool_specs(custom_apis_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Build tool specifications for built-in APIs and dynamically registered custom APIs."""
    enabled_custom = [ep for ep in load_custom_apis(custom_apis_path) if ep.enabled]
    if enabled_custom:
        custom_hint = " Available api_id values: " + "; ".join(
            f"'{ep.id}' ({ep.name}, {ep.method} {ep.base_url}{ep.default_path}"
            + (f" — {ep.description[:90]}" if ep.description else "")
            + ")"
            for ep in enabled_custom[:8]
        )
    else:
        custom_hint = " Call list_custom_apis first to see if any custom endpoints are configured."

    return [
        {
            "name": "get_weather",
            "description": (
                "Get current live weather and multi-day forecast (temperature, feels-like, humidity, "
                "wind, precipitation probability) for any city or location. Works free with no API key."
            ),
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City or place name, e.g. 'Chennai', 'Mumbai', 'London'.",
                },
                "days": {
                    "type": "integer",
                    "description": "Forecast days (1 to 7, default 3).",
                },
            },
            "required": ["location"],
        },
        {
            "name": "maps_lookup",
            "description": (
                "Look up places, geocode addresses/coordinates, or get directions/distances using "
                "Google Maps API (or free OpenStreetMap Nominatim fallback)."
            ),
            "properties": {
                "action": {
                    "type": "string",
                    "description": "'places', 'geocode', or 'directions'.",
                    "enum": ["places", "geocode", "directions"],
                },
                "query": {
                    "type": "string",
                    "description": "Place or address query for 'places' or 'geocode'.",
                },
                "origin": {
                    "type": "string",
                    "description": "Starting address/city for 'directions'.",
                },
                "destination": {
                    "type": "string",
                    "description": "Ending address/city for 'directions'.",
                },
                "mode": {
                    "type": "string",
                    "description": "Travel mode for 'directions'.",
                    "enum": ["driving", "walking", "bicycling", "transit"],
                },
            },
            "required": ["action"],
        },
        {
            "name": "database_query",
            "description": (
                "Query a local SQLite database or configured Database REST endpoint. "
                "Use action='tables', 'schema', or 'query' for read-only SELECT queries; "
                "writes ask Allow/Deny confirmation."
            ),
            "properties": {
                "action": {
                    "type": "string",
                    "description": "'tables', 'schema', 'query' (SELECT), or 'execute' (write).",
                    "enum": ["tables", "schema", "query", "execute"],
                },
                "sql": {
                    "type": "string",
                    "description": "SQL query or REST path.",
                },
                "db_path": {
                    "type": "string",
                    "description": "Path to local SQLite .db file (optional if SQLITE_DB_PATH is configured).",
                },
                "connection_url": {
                    "type": "string",
                    "description": "Optional Database REST endpoint URL.",
                },
            },
            "required": ["action"],
        },
        {
            "name": "email_action",
            "description": (
                "Check recent inbox emails (action='list_inbox') or send an email (action='send_email'; "
                "always asks Allow/Deny confirmation before sending)."
            ),
            "properties": {
                "action": {
                    "type": "string",
                    "description": "'list_inbox' or 'send_email'.",
                    "enum": ["list_inbox", "send_email"],
                },
                "to": {"type": "string", "description": "Recipient email address (for send_email)."},
                "subject": {"type": "string", "description": "Email subject (for send_email)."},
                "body": {"type": "string", "description": "Plain-text email body (for send_email)."},
                "limit": {"type": "integer", "description": "Number of inbox messages to fetch (1-15)."},
            },
            "required": ["action"],
        },
        {
            "name": "calendar_action",
            "description": (
                "List upcoming calendar events (action='list_events') or create an event "
                "(action='create_event'; always asks Allow/Deny confirmation)."
            ),
            "properties": {
                "action": {
                    "type": "string",
                    "description": "'list_events' or 'create_event'.",
                    "enum": ["list_events", "create_event"],
                },
                "days": {"type": "integer", "description": "Lookahead days for list_events (default 7)."},
                "title": {"type": "string", "description": "Event title (for create_event)."},
                "start_iso": {"type": "string", "description": "Start ISO timestamp e.g. '2026-11-12T10:00:00+05:30'."},
                "end_iso": {"type": "string", "description": "End ISO timestamp."},
                "description": {"type": "string", "description": "Event description."},
                "location": {"type": "string", "description": "Event location."},
            },
            "required": ["action"],
        },
        {
            "name": "payment_action",
            "description": (
                "Inspect recent Stripe/Razorpay payments (action='list_payments' or 'get_payment_status') "
                "or create a payment link (action='create_payment_link'; always asks Allow/Deny confirmation)."
            ),
            "properties": {
                "action": {
                    "type": "string",
                    "description": "'list_payments', 'get_payment_status', or 'create_payment_link'.",
                    "enum": ["list_payments", "get_payment_status", "create_payment_link"],
                },
                "provider": {"type": "string", "description": "'stripe' or 'razorpay' (auto-detected if omitted)."},
                "amount": {"type": "number", "description": "Major currency amount e.g. 500 (for payment link)."},
                "currency": {"type": "string", "description": "3-letter currency code e.g. 'INR' or 'USD'."},
                "description": {"type": "string", "description": "Payment description."},
                "payment_id": {"type": "string", "description": "Payment ID for get_payment_status."},
            },
            "required": ["action"],
        },
        {
            "name": "list_custom_apis",
            "description": (
                "List all user-registered custom, third-party, and company internal REST APIs with their api_id and description."
            ),
            "properties": {},
            "required": [],
        },
        {
            "name": "call_custom_api",
            "description": (
                "Call a registered custom or company internal REST API by api_id." + custom_hint
            ),
            "properties": {
                "api_id": {
                    "type": "string",
                    "description": "Registered api_id from custom_apis.json (see list_custom_apis).",
                },
                "endpoint_path": {
                    "type": "string",
                    "description": "Relative endpoint path appended to the API's base_url (optional; uses default_path if empty).",
                },
                "method": {
                    "type": "string",
                    "description": "Optional HTTP method override: GET, POST, PUT, PATCH, DELETE.",
                    "enum": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
                },
                "query_params": {
                    "type": "object",
                    "description": "Optional URL query parameters as JSON object.",
                },
                "json_body": {
                    "type": "object",
                    "description": "Optional JSON request body for POST/PUT/PATCH.",
                },
            },
            "required": ["api_id"],
        },
    ]


API_TOOL_NAMES = {
    "get_weather",
    "maps_lookup",
    "database_query",
    "email_action",
    "calendar_action",
    "payment_action",
    "list_custom_apis",
    "call_custom_api",
}


def execute_api_tool(
    name: str,
    args: Dict[str, Any],
    policy: Optional[ApiToolsPolicy] = None,
    *,
    custom_apis_path: Optional[Path] = None,
) -> Optional[str]:
    """Dispatch an extended API tool call if `name` is handled by `api_tools`."""
    if name == "get_weather":
        return get_weather(
            location=str(args.get("location", "")),
            days=args.get("days", 3),
        )
    if name == "maps_lookup":
        return maps_lookup(
            action=str(args.get("action", "places")),
            query=str(args.get("query", "")),
            origin=str(args.get("origin", "")),
            destination=str(args.get("destination", "")),
            mode=str(args.get("mode", "driving")),
        )
    if name == "database_query":
        return database_query(
            action=str(args.get("action", "query")),
            sql=str(args.get("sql", "")),
            db_path=str(args.get("db_path", "")),
            connection_url=str(args.get("connection_url", "")),
            policy=policy,
        )
    if name == "email_action":
        return email_action(
            action=str(args.get("action", "list_inbox")),
            to=str(args.get("to", "")),
            subject=str(args.get("subject", "")),
            body=str(args.get("body", "")),
            limit=args.get("limit", 5),
            policy=policy,
        )
    if name == "calendar_action":
        return calendar_action(
            action=str(args.get("action", "list_events")),
            days=args.get("days", 7),
            title=str(args.get("title", "")),
            start_iso=str(args.get("start_iso", "")),
            end_iso=str(args.get("end_iso", "")),
            description=str(args.get("description", "")),
            location=str(args.get("location", "")),
            policy=policy,
        )
    if name == "payment_action":
        return payment_action(
            action=str(args.get("action", "list_payments")),
            provider=str(args.get("provider", "")),
            amount=args.get("amount", ""),
            currency=str(args.get("currency", "INR")),
            description=str(args.get("description", "")),
            payment_id=str(args.get("payment_id", "")),
            policy=policy,
        )
    if name == "list_custom_apis":
        return list_custom_apis(custom_apis_path=custom_apis_path)
    if name == "call_custom_api":
        return call_custom_api(
            api_id=str(args.get("api_id", "")),
            endpoint_path=str(args.get("endpoint_path", "")),
            method=str(args.get("method", "")),
            query_params=args.get("query_params"),
            json_body=args.get("json_body"),
            policy=policy,
            custom_apis_path=custom_apis_path,
        )
    return None
