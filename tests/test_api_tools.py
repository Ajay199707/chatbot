"""Unit tests for built-in API connectors, custom API registry, and routing."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
import pytest

import api_tools
import chatbot


class _HttpRecorder:
    """Flexible httpx mock intercepting httpx.get/post/request and httpx.Client."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []

    def handle(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append((method.upper(), str(url), kwargs))
        return self.handler(method.upper(), str(url), kwargs)


def _install_http_mock(monkeypatch: pytest.MonkeyPatch, handler) -> _HttpRecorder:
    recorder = _HttpRecorder(handler)

    def _request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return recorder.handle(method, url, **kwargs)

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            return recorder.handle(method, url, **kwargs)

        def get(self, url: str, **kwargs: Any) -> httpx.Response:
            return recorder.handle("GET", url, **kwargs)

        def post(self, url: str, **kwargs: Any) -> httpx.Response:
            return recorder.handle("POST", url, **kwargs)

        def put(self, url: str, **kwargs: Any) -> httpx.Response:
            return recorder.handle("PUT", url, **kwargs)

        def patch(self, url: str, **kwargs: Any) -> httpx.Response:
            return recorder.handle("PATCH", url, **kwargs)

        def delete(self, url: str, **kwargs: Any) -> httpx.Response:
            return recorder.handle("DELETE", url, **kwargs)

    monkeypatch.setattr(api_tools.httpx, "Client", _FakeClient)
    monkeypatch.setattr(api_tools.httpx, "request", _request)
    monkeypatch.setattr(api_tools.httpx, "get", lambda url, **kw: _request("GET", url, **kw))
    monkeypatch.setattr(api_tools.httpx, "post", lambda url, **kw: _request("POST", url, **kw))
    return recorder


def _json_response(url: str, payload: Any, method: str = "GET", status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request(method, url),
    )


def _text_response(url: str, text: str, method: str = "GET", status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        text=text,
        request=httpx.Request(method, url),
    )


def test_get_weather_open_meteo_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)

    def handler(method: str, url: str, kw: Dict[str, Any]) -> httpx.Response:
        if "geocoding-api.open-meteo.com" in url:
            return _json_response(
                url,
                {
                    "results": [
                        {
                            "name": "Chennai",
                            "country": "India",
                            "latitude": 13.08784,
                            "longitude": 80.27847,
                            "timezone": "Asia/Kolkata",
                        }
                    ]
                },
            )
        if "api.open-meteo.com" in url:
            return _json_response(
                url,
                {
                    "current": {
                        "temperature_2m": 31.4,
                        "apparent_temperature": 35.1,
                        "relative_humidity_2m": 66,
                        "wind_speed_10m": 12.5,
                        "weather_code": 1,
                    },
                    "daily": {
                        "time": ["2026-11-11", "2026-11-12"],
                        "temperature_2m_max": [33.0, 32.0],
                        "temperature_2m_min": [25.0, 24.5],
                        "weather_code": [1, 3],
                        "precipitation_probability_max": [10, 45],
                    },
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")

    _install_http_mock(monkeypatch, handler)
    out = api_tools.get_weather("Chennai", days=2)
    assert "Chennai" in out
    assert "31.4" in out
    assert "2026-11-11" in out


def test_get_weather_falls_back_to_nominatim_when_open_meteo_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)

    def handler(method: str, url: str, kw: Dict[str, Any]) -> httpx.Response:
        if "geocoding-api.open-meteo.com" in url:
            return _json_response(url, {"generationtime_ms": 0.1})
        if "nominatim.openstreetmap.org/search" in url:
            return _json_response(
                url,
                [
                    {
                        "display_name": "Kanyakumari, Tamil Nadu, India",
                        "lat": "8.0792520",
                        "lon": "77.5499338",
                    }
                ],
            )
        if "api.open-meteo.com" in url:
            return _json_response(
                url,
                {
                    "timezone": "Asia/Kolkata",
                    "current": {
                        "temperature_2m": 29.2,
                        "apparent_temperature": 32.0,
                        "relative_humidity_2m": 78,
                        "wind_speed_10m": 18.0,
                        "weather_code": 2,
                    },
                    "daily": {
                        "time": ["2026-11-11"],
                        "temperature_2m_max": [30.5],
                        "temperature_2m_min": [25.0],
                        "weather_code": [2],
                        "precipitation_probability_max": [20],
                    },
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")

    _install_http_mock(monkeypatch, handler)
    out = api_tools.get_weather("Kanyakumari", days=1)
    assert "Kanyakumari" in out
    assert "29.2" in out


def test_get_weather_openweathermap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENWEATHER_API_KEY", "owm-key-123")

    def handler(method: str, url: str, kw: Dict[str, Any]) -> httpx.Response:
        if "api.openweathermap.org/data/2.5/weather" in url:
            return _json_response(
                url,
                {
                    "name": "Chennai",
                    "sys": {"country": "IN"},
                    "main": {"temp": 30.8, "feels_like": 34.2, "humidity": 72},
                    "wind": {"speed": 4.1},
                    "weather": [{"description": "partly cloudy"}],
                },
            )
        if "api.openweathermap.org/data/2.5/forecast" in url:
            return _json_response(
                url,
                {
                    "list": [
                        {
                            "dt_txt": "2026-11-11 12:00:00",
                            "main": {"temp": 31.0, "temp_min": 29.0, "temp_max": 32.0},
                            "weather": [{"description": "clear sky"}],
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")

    _install_http_mock(monkeypatch, handler)
    out = api_tools.get_weather("Chennai", days=2)
    assert "Chennai" in out
    assert "30.8" in out
    assert "partly cloudy" in out.lower()


def test_web_search_duckduckgo_fallback_when_tavily_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    def handler(method: str, url: str, kw: Dict[str, Any]) -> httpx.Response:
        if "html.duckduckgo.com" in url:
            html = (
                '<html><body>'
                '<div class="result"><a class="result__a" href="https://python.org/downloads/">'
                'Download Python 3.13</a>'
                '<a class="result__snippet">Latest Python release notes and installers.</a></div>'
                '</body></html>'
            )
            return _text_response(url, html)
        if "api.duckduckgo.com" in url:
            return _json_response(
                url,
                {
                    "Heading": "Python",
                    "AbstractText": "Python programming language",
                    "AbstractURL": "https://python.org",
                    "RelatedTopics": [],
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")

    _install_http_mock(monkeypatch, handler)
    out = api_tools.web_search("latest python release")
    assert "TAVILY_API_KEY" in out
    assert "Download Python 3.13" in out or "Python" in out


def test_maps_lookup_nominatim_and_google_maps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    def nom_handler(method: str, url: str, kw: Dict[str, Any]) -> httpx.Response:
        if "nominatim.openstreetmap.org" in url:
            return _json_response(
                url,
                [
                    {
                        "display_name": "Marina Beach, Chennai, Tamil Nadu, India",
                        "lat": "13.0500",
                        "lon": "80.2824",
                        "type": "beach",
                    }
                ],
            )
        if "router.project-osrm.org" in url:
            return _json_response(
                url,
                {"code": "Ok", "routes": [{"distance": 12400.0, "duration": 1620.0}]},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    _install_http_mock(monkeypatch, nom_handler)
    nom_out = api_tools.maps_lookup(action="places", query="Marina Beach, Chennai")
    assert "Marina Beach" in nom_out
    assert "13.0500" in nom_out

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "gmaps-test")

    def gmaps_handler(method: str, url: str, kw: Dict[str, Any]) -> httpx.Response:
        if "maps.googleapis.com/maps/api/place/textsearch" in url:
            return _json_response(
                url,
                {
                    "status": "OK",
                    "results": [
                        {
                            "name": "Chennai Central",
                            "formatted_address": "Kannappar Thidal, Chennai",
                            "rating": 4.4,
                            "geometry": {"location": {"lat": 13.0827, "lng": 80.2707}},
                        }
                    ],
                },
            )
        if "maps.googleapis.com/maps/api/directions" in url:
            return _json_response(
                url,
                {
                    "status": "OK",
                    "routes": [
                        {
                            "summary": "Anna Salai",
                            "legs": [
                                {
                                    "distance": {"text": "6.5 km"},
                                    "duration": {"text": "18 mins"},
                                    "start_address": "A",
                                    "end_address": "B",
                                    "steps": [{"html_instructions": "Head <b>south</b>"}],
                                }
                            ],
                        }
                    ],
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")

    _install_http_mock(monkeypatch, gmaps_handler)
    places_out = api_tools.maps_lookup(action="places", query="Chennai Central")
    assert "Chennai Central" in places_out
    dir_out = api_tools.maps_lookup(
        action="directions", origin="Chennai Central", destination="Marina Beach"
    )
    assert "6.5 km" in dir_out


def test_database_query_sqlite_readonly_write_confirm_and_stacked_guard(tmp_path: Path) -> None:
    db_file = tmp_path / "sample.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO items (name) VALUES ('Widget')")
    conn.commit()
    conn.close()

    def _never_confirm(title: str, detail: str, risk: str = "destructive") -> bool:
        raise AssertionError(f"Unexpected confirm prompt: {title}: {detail}")

    ro_policy = api_tools.ApiToolsPolicy(
        confirm_callback=_never_confirm,
        allowed_roots=[tmp_path],
    )
    tables_out = api_tools.database_query(action="tables", db_path=str(db_file), policy=ro_policy)
    assert "items" in tables_out
    select_out = api_tools.database_query(
        action="query", sql="SELECT id, name FROM items", db_path=str(db_file), policy=ro_policy
    )
    assert "Widget" in select_out

    # Deny write
    deny_policy = api_tools.ApiToolsPolicy(
        confirm_callback=lambda _t, _d, _r="destructive": False,
        allowed_roots=[tmp_path],
    )
    denied = api_tools.database_query(
        action="query",
        sql="INSERT INTO items (name) VALUES ('DeniedGadget')",
        db_path=str(db_file),
        policy=deny_policy,
    )
    assert "denied" in denied.lower() or "cancelled" in denied.lower()

    # Allow write
    allow_calls: List[str] = []

    def _allow(title: str, detail: str, risk: str = "destructive") -> bool:
        allow_calls.append(title)
        return True

    allow_policy = api_tools.ApiToolsPolicy(
        confirm_callback=_allow,
        allowed_roots=[tmp_path],
    )
    inserted = api_tools.database_query(
        action="query",
        sql="INSERT INTO items (name) VALUES ('AllowedGadget')",
        db_path=str(db_file),
        policy=allow_policy,
    )
    assert len(allow_calls) == 1
    assert "error" not in inserted.lower()
    after = api_tools.database_query(
        action="query", sql="SELECT name FROM items", db_path=str(db_file), policy=ro_policy
    )
    assert "AllowedGadget" in after
    assert "DeniedGadget" not in after

    # Stacked SQL guard: query starting with SELECT plus `; DROP TABLE` must NOT
    # be treated as read-only and must trigger destructive Allow/Deny confirmation.
    stacked_prompts: List[Tuple[str, str]] = []

    def _deny_and_record(title: str, detail: str, risk: str = "destructive") -> bool:
        stacked_prompts.append((title, risk))
        return False

    stacked_deny_policy = api_tools.ApiToolsPolicy(
        confirm_callback=_deny_and_record,
        allowed_roots=[tmp_path],
    )
    stacked = api_tools.database_query(
        action="query",
        sql="SELECT * FROM items; DROP TABLE items;",
        db_path=str(db_file),
        policy=stacked_deny_policy,
    )
    assert stacked_prompts and stacked_prompts[0][1] == "destructive"
    assert "denied" in stacked.lower() or "cancelled" in stacked.lower()
    check_tables = api_tools.database_query(action="tables", db_path=str(db_file), policy=ro_policy)
    assert "items" in check_tables


def test_email_action_smtp_allow_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("EMAIL_USER", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-password")
    sent_messages: List[Any] = []

    class _FakeSMTP:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "_FakeSMTP":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, user: str, pwd: str) -> None:
            return None

        def send_message(self, msg: Any) -> None:
            sent_messages.append(msg)

        def sendmail(self, from_addr: str, to_addrs: Any, msg: Any) -> None:
            sent_messages.append(msg)

    monkeypatch.setattr(api_tools.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(api_tools.smtplib, "SMTP_SSL", _FakeSMTP)

    deny_policy = api_tools.ApiToolsPolicy(confirm_callback=lambda _t, _d, _r="destructive": False)
    denied = api_tools.email_action(
        action="send_email",
        to="friend@example.com",
        subject="Hello",
        body="Body text",
        policy=deny_policy,
    )
    assert "denied" in denied.lower() or "cancelled" in denied.lower()
    assert sent_messages == []

    allow_policy = api_tools.ApiToolsPolicy(confirm_callback=lambda _t, _d, _r="destructive": True)
    allowed = api_tools.email_action(
        action="send_email",
        to="friend@example.com",
        subject="Hello",
        body="Body text",
        policy=allow_policy,
    )
    assert "sent" in allowed.lower()
    assert len(sent_messages) == 1


def test_calendar_action_ics_and_google_create_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    ics_text = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "SUMMARY:Team Standup\r\n"
        "DTSTART:20261112T090000Z\r\n"
        "DTEND:20261112T093000Z\r\n"
        "LOCATION:Room 42\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    monkeypatch.setenv("CALENDAR_ICS_URL", "https://calendar.example.com/feed.ics")
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN", "gcal-token-xyz")
    created_events: List[Dict[str, Any]] = []

    def handler(method: str, url: str, kw: Dict[str, Any]) -> httpx.Response:
        if url.endswith("feed.ics"):
            return _text_response(url, ics_text)
        if "www.googleapis.com/calendar/v3/calendars" in url and method == "POST":
            created_events.append(kw.get("json") or {})
            return _json_response(
                url,
                {
                    "id": "evt_1",
                    "summary": (kw.get("json") or {}).get("summary", "Sync"),
                    "htmlLink": "https://calendar.google.com/event?eid=evt_1",
                },
                method="POST",
            )
        if "www.googleapis.com/calendar/v3/calendars" in url and method == "GET":
            return _json_response(url, {"items": []})
        raise AssertionError(f"Unexpected URL: {method} {url}")

    _install_http_mock(monkeypatch, handler)
    # Note: test .ics feed with GOOGLE_CALENDAR_TOKEN unset first so list_events reads ICS
    monkeypatch.delenv("GOOGLE_CALENDAR_TOKEN", raising=False)
    ro_policy = api_tools.ApiToolsPolicy(confirm_callback=lambda _t, _d, _r="destructive": False)
    ics_out = api_tools.calendar_action(action="list_events", days=365, policy=ro_policy)
    assert "Team Standup" in ics_out

    # Now enable token and test create_event confirmation gate
    monkeypatch.setenv("GOOGLE_CALENDAR_TOKEN", "gcal-token-xyz")
    denied = api_tools.calendar_action(
        action="create_event",
        title="Design Review",
        start_iso="2026-11-12T10:00:00Z",
        end_iso="2026-11-12T11:00:00Z",
        policy=ro_policy,
    )
    assert "denied" in denied.lower() or "cancelled" in denied.lower()
    assert created_events == []

    allow_policy = api_tools.ApiToolsPolicy(confirm_callback=lambda _t, _d, _r="destructive": True)
    created = api_tools.calendar_action(
        action="create_event",
        title="Design Review",
        start_iso="2026-11-12T10:00:00Z",
        end_iso="2026-11-12T11:00:00Z",
        policy=allow_policy,
    )
    assert "Design Review" in created
    assert len(created_events) == 1


def test_payment_action_razorpay_list_and_create_link_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_key")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "rzp_test_secret")
    posted_links: List[Any] = []

    def handler(method: str, url: str, kw: Dict[str, Any]) -> httpx.Response:
        if "api.razorpay.com/v1/payments" in url and method == "GET":
            return _json_response(
                url,
                {
                    "items": [
                        {
                            "id": "pay_001",
                            "amount": 50000,
                            "currency": "INR",
                            "status": "captured",
                            "description": "Invoice #101",
                        }
                    ]
                },
            )
        if "api.razorpay.com/v1/payment_links" in url and method == "POST":
            posted_links.append(kw.get("json") or kw.get("data"))
            return _json_response(
                url,
                {
                    "id": "plink_123",
                    "short_url": "https://rzp.io/i/plink_123",
                    "amount": 25000,
                    "currency": "INR",
                    "status": "created",
                },
                method="POST",
            )
        raise AssertionError(f"Unexpected URL: {method} {url}")

    _install_http_mock(monkeypatch, handler)

    # list_payments is read-only and should not prompt
    ro_policy = api_tools.ApiToolsPolicy(
        confirm_callback=lambda _t, _d, _r="destructive": (_ for _ in ()).throw(
            AssertionError("Should not confirm")
        )
    )
    listed = api_tools.payment_action(action="list_payments", provider="razorpay", policy=ro_policy)
    assert "pay_001" in listed

    deny_policy = api_tools.ApiToolsPolicy(confirm_callback=lambda _t, _d, _r="destructive": False)
    denied = api_tools.payment_action(
        action="create_payment_link",
        provider="razorpay",
        amount=250,
        currency="INR",
        description="Consulting",
        policy=deny_policy,
    )
    assert "denied" in denied.lower() or "cancelled" in denied.lower()
    assert posted_links == []

    allow_policy = api_tools.ApiToolsPolicy(confirm_callback=lambda _t, _d, _r="destructive": True)
    created = api_tools.payment_action(
        action="create_payment_link",
        provider="razorpay",
        amount=250,
        currency="INR",
        description="Consulting",
        policy=allow_policy,
    )
    assert "plink_123" in created or "https://rzp.io/i/plink_123" in created
    assert len(posted_links) == 1


def test_custom_api_crud_auth_ssrf_guard_and_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_path = tmp_path / "custom_apis.json"
    ep = api_tools.CustomApiEndpoint(
        id="internal_crm",
        name="Internal CRM",
        category="Company Internal",
        description="Company customer lookup",
        base_url="https://crm.internal.example.com/api",
        default_path="/v1/customers",
        method="GET",
        auth_type="bearer",
        env_secret_name="CRM_API_TOKEN",
        confirmation_mode="auto",
        enabled=True,
    )
    api_tools.upsert_custom_api(ep, path=cfg_path)
    loaded = api_tools.load_custom_apis(path=cfg_path)
    assert len(loaded) == 1
    assert loaded[0].id == "internal_crm"
    assert "internal_crm" in api_tools.custom_apis_prompt_summary(path=cfg_path)
    assert "Internal CRM" in api_tools.list_custom_apis(custom_apis_path=cfg_path)

    monkeypatch.setenv("CRM_API_TOKEN", "super-secret-crm-token")

    def handler(method: str, url: str, kw: Dict[str, Any]) -> httpx.Response:
        headers = kw.get("headers") or {}
        assert headers.get("Authorization") == "Bearer super-secret-crm-token"
        return _json_response(url, {"method": method, "url": url, "ok": True}, method=method)

    recorder = _install_http_mock(monkeypatch, handler)

    # SSRF guard: absolute URL or scheme-relative override in endpoint_path must be blocked
    for bad_path in ("https://evil.example.com/steal", "http://169.254.169.254/latest", "//evil.example.com/x"):
        blocked = api_tools.call_custom_api(
            "internal_crm",
            endpoint_path=bad_path,
            custom_apis_path=cfg_path,
        )
        assert "blocked" in blocked.lower() or "relative" in blocked.lower() or "invalid" in blocked.lower()
    assert recorder.calls == []

    # GET under confirmation_mode="auto" executes without confirmation
    get_out = api_tools.call_custom_api(
        "internal_crm",
        method="GET",
        query_params='{"q": "acme"}',
        policy=api_tools.ApiToolsPolicy(confirm_callback=lambda _t, _d, _r="destructive": False),
        custom_apis_path=cfg_path,
    )
    assert '"ok": true' in get_out.lower() or "ok" in get_out.lower()
    assert len(recorder.calls) == 1

    # POST under confirmation_mode="auto" requires Allow/Deny
    denied_post = api_tools.call_custom_api(
        "internal_crm",
        method="POST",
        json_body='{"name": "Acme"}',
        policy=api_tools.ApiToolsPolicy(confirm_callback=lambda _t, _d, _r="destructive": False),
        custom_apis_path=cfg_path,
    )
    assert "denied" in denied_post.lower() or "cancelled" in denied_post.lower()
    assert len(recorder.calls) == 1

    allowed_post = api_tools.call_custom_api(
        "internal_crm",
        method="POST",
        json_body='{"name": "Acme"}',
        policy=api_tools.ApiToolsPolicy(confirm_callback=lambda _t, _d, _r="destructive": True),
        custom_apis_path=cfg_path,
    )
    assert "ok" in allowed_post.lower()
    assert len(recorder.calls) == 2

    remaining = api_tools.delete_custom_api("internal_crm", path=cfg_path)
    assert remaining == []
    assert api_tools.load_custom_apis(path=cfg_path) == []


def test_build_gemini_tools_schema_has_no_empty_object_properties() -> None:
    tools = chatbot.build_gemini_tools(include_system=False, include_web=True)
    assert len(tools) == 1
    decls = tools[0]["functionDeclarations"]
    names = {d["name"] for d in decls}
    assert {
        "get_weather",
        "maps_lookup",
        "database_query",
        "email_action",
        "calendar_action",
        "payment_action",
        "list_custom_apis",
        "call_custom_api",
    }.issubset(names)
    for decl in decls:
        props = (decl.get("parameters") or {}).get("properties") or {}
        for pname, pspec in props.items():
            if pspec.get("type") == "OBJECT":
                assert pspec.get("properties"), f"{decl['name']}.{pname} has empty OBJECT properties"


def test_stream_mock_turn_routes_weather_and_find_folder_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import system_tools

    monkeypatch.setattr(api_tools, "get_weather", lambda location, days=3: f"Sunny 31C in {location}")

    bot_weather = chatbot.Chatbot(
        chatbot.ChatbotConfig(provider="mock", use_tools=True, enable_system_tools=False)
    )
    events_w = list(bot_weather.stream_turn("What is today's weather in Chennai?"))
    assert any(e["type"] == "tool_start" and e["name"] == "get_weather" for e in events_w)
    assert any(e["type"] == "tool_end" and "Chennai" in e["result"] for e in events_w)

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    sys_policy = system_tools.SystemToolsPolicy(enabled=True, allowed_roots=[tmp_path])
    bot_files = chatbot.Chatbot(
        chatbot.ChatbotConfig(
            provider="mock",
            use_tools=False,
            enable_system_tools=True,
            system_policy=sys_policy,
        )
    )
    events_f = list(bot_files.stream_turn("find the folder name project"))
    tool_ends = [e for e in events_f if e["type"] == "tool_end"]
    assert tool_ends and tool_ends[0]["name"] == "search_files"
    assert str(project_dir) in tool_ends[0]["result"] or "project" in tool_ends[0]["result"].lower()
