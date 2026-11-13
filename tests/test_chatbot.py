"""Tests for chatbot.py (Gemini, NVIDIA NIM, Mock, Tools, and FastAPI Web UI)."""

import json
import sys
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chatbot  # noqa: E402


def _make_sse_bytes(events: list[dict | str]) -> bytes:
    lines = []
    for item in events:
        data = item if isinstance(item, str) else json.dumps(item)
        lines.append(f"data: {data}\n\n")
    return "".join(lines).encode("utf-8")


def test_gemini_tool_declarations_omit_empty_parameters():
    decls = chatbot.build_gemini_tools()[0]["functionDeclarations"]
    by_name = {d["name"]: d for d in decls}

    assert "parameters" not in by_name["get_india_gold_price"]
    assert "parameters" not in by_name["get_current_datetime"]
    assert by_name["get_news"]["parameters"]["type"] == "OBJECT"
    assert "keyword" in by_name["get_news"]["parameters"]["properties"]


def test_mock_provider_plain_and_tool_streaming(monkeypatch):
    monkeypatch.setattr(
        chatbot,
        "get_india_gold_price",
        lambda: "Gold (INR/gram): buy INR 8000, sell INR 7800",
    )
    monkeypatch.setitem(chatbot.TOOL_FUNCTIONS, "get_india_gold_price", chatbot.get_india_gold_price)

    bot = chatbot.Chatbot(chatbot.ChatbotConfig(provider="mock"))
    events = list(bot.stream_turn("hello there"))
    types = [e["type"] for e in events]
    assert "token" in types
    assert types[-1] == "done"

    tool_events = list(bot.stream_turn("what is gold price?"))
    assert any(e["type"] == "tool_start" and e["name"] == "get_india_gold_price" for e in tool_events)
    assert any(e["type"] == "tool_end" and "8000" in e["result"] for e in tool_events)
    assert len(bot.history) == 4


def test_gemini_streaming_preserves_thoughts_and_thought_signature(monkeypatch):
    recorded_payloads = []
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        body = json.loads(request.content.decode("utf-8"))
        recorded_payloads.append((str(request.url), dict(request.headers), body))

        if call_count == 1:
            sse = _make_sse_bytes([
                {
                    "candidates": [{
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": "Checking current time first.", "thought": True},
                                {
                                    "functionCall": {"id": "fc_1", "name": "get_current_datetime", "args": {}},
                                    "thoughtSignature": "SIG_TOOL_123",
                                },
                            ],
                        }
                    }]
                }
            ])
            return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

        if call_count == 2:
            sse = _make_sse_bytes([
                {
                    "candidates": [{
                        "content": {
                            "role": "model",
                            "parts": [{"text": "The current ", "thought": False}],
                        }
                    }]
                },
                {
                    "candidates": [{
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": "time is ready.", "thought": False, "thoughtSignature": "SIG_FINAL_456"}
                            ],
                        },
                        "finishReason": "STOP",
                    }]
                },
            ])
            return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

        sse = _make_sse_bytes([
            {
                "candidates": [{
                    "content": {"role": "model", "parts": [{"text": "Follow-up answered."}]},
                    "finishReason": "STOP",
                }]
            }
        ])
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        chatbot.httpx,
        "Client",
        lambda *args, **kwargs: real_client(transport=transport, **kwargs),
    )

    bot = chatbot.Chatbot(
        chatbot.ChatbotConfig(provider="gemini", model_name="gemini-3.8-flash", api_key="fake-gemini-key")
    )
    events = list(bot.stream_turn("What time is it?"))

    thoughts = "".join(e["content"] for e in events if e["type"] == "thought")
    answer = "".join(e["content"] for e in events if e["type"] == "token")
    assert "Checking current time first." in thoughts
    assert answer == "The current time is ready."
    assert any(e["type"] == "tool_end" and e["name"] == "get_current_datetime" for e in events)

    # Verify API key sent in header, not URL
    url_1, headers_1, payload_1 = recorded_payloads[0]
    assert "fake-gemini-key" not in url_1
    assert headers_1.get("x-goog-api-key") == "fake-gemini-key"
    assert payload_1["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "MEDIUM"

    # Verify thoughtSignature and functionCall.id echoed back with role="user"
    _, _, payload_2 = recorded_payloads[1]
    model_parts_in_turn2 = payload_2["contents"][1]["parts"]
    assert any(p.get("thoughtSignature") == "SIG_TOOL_123" for p in model_parts_in_turn2)
    assert payload_2["contents"][2]["role"] == "user"
    assert payload_2["contents"][2]["parts"][0]["functionResponse"]["id"] == "fc_1"

    # Verify multi-turn follow-up also preserves final thoughtSignature
    list(bot.stream_turn("Thanks!"))
    _, _, payload_3 = recorded_payloads[2]
    all_model_parts = [p for c in payload_3["contents"] if c["role"] == "model" for p in c["parts"]]
    assert any(p.get("thoughtSignature") == "SIG_FINAL_456" for p in all_model_parts)


def test_nvidia_openai_streaming_with_tool_calls(monkeypatch):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            sse = _make_sse_bytes([
                {
                    "choices": [{
                        "delta": {
                            "tool_calls": [{
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "get_current_", "arguments": "{"},
                            }]
                        }
                    }]
                },
                {
                    "choices": [{
                        "delta": {
                            "tool_calls": [{
                                "index": 0,
                                "function": {"name": "datetime", "arguments": "}"},
                            }]
                        }
                    }]
                },
                "[DONE]",
            ])
            return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

        sse = _make_sse_bytes([
            {"choices": [{"delta": {"content": "Hello "}}]},
            {"choices": [{"delta": {"content": "world!"}}]},
            "[DONE]",
        ])
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        chatbot.httpx,
        "Client",
        lambda *args, **kwargs: real_client(transport=transport, **kwargs),
    )

    bot = chatbot.Chatbot(
        chatbot.ChatbotConfig(provider="nvidia", model_name="meta/muse-glimmer-30b", api_key="fake-nv")
    )
    events = list(bot.stream_turn("time please"))
    assert "".join(e["content"] for e in events if e["type"] == "token") == "Hello world!"
    assert any(e["type"] == "tool_end" and e["name"] == "get_current_datetime" for e in events)


def test_missing_api_key_returns_clean_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    bot = chatbot.Chatbot(chatbot.ChatbotConfig(provider="gemini", api_key=None))
    events = list(bot.stream_turn("hi"))
    assert events[-1]["type"] == "error"
    assert "GEMINI_API_KEY" in events[-1]["message"]


def test_history_trimming_starts_with_user():
    bot = chatbot.Chatbot(chatbot.ChatbotConfig(provider="mock", max_history_turns=1))
    bot.add_message(chatbot.Message(role="user", content="u1"))
    bot.add_message(chatbot.Message(role="assistant", content="a1"))
    bot.add_message(chatbot.Message(role="user", content="u2"))
    bot.add_message(chatbot.Message(role="assistant", content="a2"))
    assert len(bot.history) == 2
    assert bot.history[0].role == "user"
    assert bot.history[0].content == "u2"


def test_fastapi_endpoints():
    app = chatbot.create_app(chatbot.ChatbotConfig(provider="mock"))
    client = TestClient(app)

    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "Gemini Chatbot" in r_home.text

    r_status = client.get("/api/status")
    assert r_status.status_code == 200
    status_json = r_status.json()
    assert status_json["provider"] == "mock"
    assert "gemini" in status_json["models"]

    r_empty = client.post("/api/chat", json={"message": "   ", "session_id": "t1"})
    assert r_empty.status_code == 400

    r_chat = client.post("/api/chat", json={"message": "hello", "session_id": "t1"})
    assert r_chat.status_code == 200
    assert "Mock Mode" in r_chat.json()["response"]

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "what time is it?", "session_id": "t2"},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
        assert '"type": "tool_start"' in body
        assert '"type": "done"' in body

    r_hist = client.get("/api/history?session_id=t2")
    assert r_hist.status_code == 200
    assert len(r_hist.json()["messages"]) == 2

    r_clear = client.post("/api/clear", json={"session_id": "t2"})
    assert r_clear.status_code == 200
    assert client.get("/api/history?session_id=t2").json()["messages"] == []


def test_save_env_key_creates_and_updates_without_clobbering(monkeypatch, tmp_path):
    monkeypatch.delenv("TEST_CHATBOT_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text('OTHER_KEY="keep_me"\n', encoding="utf-8")

    chatbot.save_env_key("TEST_CHATBOT_KEY", "abc123\n", env_path=env_file)
    text1 = env_file.read_text(encoding="utf-8")
    assert 'OTHER_KEY="keep_me"' in text1
    assert 'TEST_CHATBOT_KEY="abc123"' in text1
    assert chatbot.os.environ["TEST_CHATBOT_KEY"] == "abc123"

    chatbot.save_env_key("TEST_CHATBOT_KEY", "xyz789", env_path=env_file)
    text2 = env_file.read_text(encoding="utf-8")
    assert text2.count("TEST_CHATBOT_KEY=") == 1
    assert 'TEST_CHATBOT_KEY="xyz789"' in text2
    assert 'OTHER_KEY="keep_me"' in text2
    monkeypatch.delenv("TEST_CHATBOT_KEY", raising=False)


def test_frozen_app_and_bundle_dirs(monkeypatch, tmp_path):
    fake_exe = tmp_path / "dist" / "AICompanion.exe"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_bytes(b"")
    fake_meipass = tmp_path / "_MEI123"
    fake_meipass.mkdir()

    monkeypatch.setattr(chatbot.sys, "frozen", True, raising=False)
    monkeypatch.setattr(chatbot.sys, "_MEIPASS", str(fake_meipass), raising=False)
    monkeypatch.setattr(chatbot.sys, "executable", str(fake_exe))

    assert chatbot.get_app_dir() == fake_exe.parent.resolve()
    assert chatbot.get_bundle_dir() == fake_meipass

    # When running from dist/ and parent .env exists, save_env_key updates parent .env
    parent_env = tmp_path / ".env"
    parent_env.write_text('EXISTING="1"\n', encoding="utf-8")
    monkeypatch.delenv("FROZEN_TEST_KEY", raising=False)

    saved_path = chatbot.save_env_key("FROZEN_TEST_KEY", "secret_val")
    assert saved_path == parent_env.resolve()
    assert 'FROZEN_TEST_KEY="secret_val"' in parent_env.read_text(encoding="utf-8")
    monkeypatch.delenv("FROZEN_TEST_KEY", raising=False)


def test_ollama_no_key_and_tool_fallback(monkeypatch):
    seen_payloads = []
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        body = json.loads(request.content.decode("utf-8"))
        seen_payloads.append((str(request.url), dict(request.headers), body))
        if "1234" in str(request.url) and call_count == 2:
            return httpx.Response(
                400,
                json={"error": {"message": "model does not support tools"}},
            )
        sse = _make_sse_bytes([
            {"choices": [{"delta": {"content": "Hi from local Ollama!"}}]},
            "[DONE]",
        ])
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        chatbot.httpx,
        "Client",
        lambda *args, **kwargs: real_client(transport=transport, **kwargs),
    )

    assert chatbot.requires_api_key("ollama") is False
    bot = chatbot.Chatbot(chatbot.ChatbotConfig(provider="ollama", model_name="llama3:8b", use_tools=True))
    events = list(bot.stream_turn("hello locally"))

    answer = "".join(e["content"] for e in events if e["type"] == "token")
    assert answer == "Hi from local Ollama!"
    assert seen_payloads[0][0] == "http://127.0.0.1:11434/v1/chat/completions"
    assert "tools" not in seen_payloads[0][2]

    # OpenAI-compatible servers that reject `tools` with 400 still fall back cleanly
    compat_bot = chatbot.Chatbot(
        chatbot.ChatbotConfig(
            provider="nvidia",
            base_url="http://127.0.0.1:1234/v1",
            api_key="nvapi-test",
            model_name="local-llama",
            use_tools=True,
        )
    )
    events2 = list(compat_bot.stream_turn("hello compat"))
    assert "".join(e["content"] for e in events2 if e["type"] == "token") == "Hi from local Ollama!"
    assert "tools" in seen_payloads[1][2]
    assert "tools" not in seen_payloads[2][2]


def test_groq_provider_config_and_gemma_payload(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_123")
    assert chatbot.requires_api_key("groq") is True
    assert chatbot.resolve_base_url("groq") == "https://api.groq.com/openai/v1"
    assert chatbot.resolve_api_key("groq") == "gsk_test_123"
    assert chatbot.default_model_for_provider("groq") == "openai/gpt-oss-120b"
    assert chatbot.normalize_model_for_provider("groq", "llama-3.3-70b-versatile") == "openai/gpt-oss-120b"

    gemma_bot = chatbot.Chatbot(
        chatbot.ChatbotConfig(provider="gemini", model_name="gemma-4-31b-it", api_key="fake-key")
    )
    payload = gemma_bot._build_gemini_payload([{"role": "user", "parts": [{"text": "hi"}]}], True)
    assert "thinkingConfig" not in payload


def test_openai_404_model_not_found_auto_fallback(monkeypatch):
    seen_models = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and str(request.url) == "https://api.groq.com/openai/v1/models":
            return httpx.Response(
                200,
                json={"data": [{"id": "whisper-large-v3"}, {"id": "openai/gpt-oss-120b"}]},
            )
        body = json.loads(request.content.decode("utf-8"))
        seen_models.append(body["model"])
        if body["model"] == "deprecated-test-model":
            return httpx.Response(
                404,
                json={"error": {"message": "The model `deprecated-test-model` does not exist or you do not have access to it."}},
            )
        sse = _make_sse_bytes([
            {"choices": [{"delta": {"content": "Fallback succeeded!"}}]},
            "[DONE]",
        ])
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        chatbot.httpx,
        "Client",
        lambda *args, **kwargs: real_client(transport=transport, **kwargs),
    )

    bot = chatbot.Chatbot(
        chatbot.ChatbotConfig(provider="groq", model_name="deprecated-test-model", api_key="gsk_test_123")
    )
    events = list(bot.stream_turn("hi"))
    assert "".join(e["content"] for e in events if e["type"] == "token") == "Fallback succeeded!"
    assert seen_models == ["deprecated-test-model", "openai/gpt-oss-120b"]
    assert bot.config.model_name == "openai/gpt-oss-120b"


def test_grok_provider_config_streaming_and_key_mismatch(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("GROK_API_KEY", "xai-test-123")
    assert chatbot.requires_api_key("grok") is True
    assert chatbot.resolve_base_url("grok") == "https://api.x.ai/v1"
    assert chatbot.resolve_api_key("grok") == "xai-test-123"
    assert chatbot.default_model_for_provider("grok") == "grok-4-1-fast"

    monkeypatch.delenv("GROK_API_KEY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-alt-456")
    assert chatbot.resolve_api_key("grok") == "xai-alt-456"

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("authorization")))
        sse = _make_sse_bytes([
            {"choices": [{"delta": {"content": "Hello from xAI Grok!"}}]},
            "[DONE]",
        ])
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        chatbot.httpx,
        "Client",
        lambda *args, **kwargs: real_client(transport=transport, **kwargs),
    )

    bot = chatbot.Chatbot(chatbot.ChatbotConfig(provider="grok", model_name="grok-4-1-fast"))
    events = list(bot.stream_turn("hi grok"))
    assert "".join(e["content"] for e in events if e["type"] == "token") == "Hello from xAI Grok!"
    assert seen == [("https://api.x.ai/v1/chat/completions", "Bearer xai-alt-456")]

    wrong_bot = chatbot.Chatbot(chatbot.ChatbotConfig(provider="grok", api_key="gsk_wrong_provider"))
    err_events = list(wrong_bot.stream_turn("hi"))
    assert err_events[-1]["type"] == "error"
    assert "groq" in err_events[-1]["message"].lower()


def test_tavily_web_search_tool_and_status(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    missing_msg = chatbot.web_search("latest python release")
    assert "TAVILY_API_KEY" in missing_msg

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-999")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "answer": "Python 3.14 is the latest release.",
                "results": [
                    {
                        "title": "Python Releases",
                        "url": "https://www.python.org/downloads/",
                        "content": "Download the latest version for Windows and Linux.",
                        "published_date": "2026-10-01",
                    }
                ],
            },
        )

    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        chatbot.httpx,
        "Client",
        lambda *args, **kwargs: real_client(transport=transport, **kwargs),
    )

    out = chatbot.execute_tool("web_search", {"query": "latest python release", "topic": "general"})
    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["auth"] == "Bearer tvly-test-999"
    assert captured["body"]["include_answer"] is True
    assert "Python 3.14 is the latest release." in out
    assert "https://www.python.org/downloads/" in out

    gem_decls = {d["name"]: d for d in chatbot.build_gemini_tools()[0]["functionDeclarations"]}
    assert "web_search" in gem_decls
    assert gem_decls["web_search"]["parameters"]["properties"]["topic"]["enum"] == [
        "general",
        "news",
        "finance",
    ]

    app = chatbot.create_app(chatbot.ChatbotConfig(provider="mock"))
    status_json = TestClient(app).get("/api/status").json()
    assert status_json["keys_configured"]["tavily"] is True
    assert "grok" in status_json["keys_configured"]
    assert "grok" in status_json["models"]


def test_ollama_text_tool_fallback_executes_tools_and_filters_extra_kwargs(monkeypatch):
    monkeypatch.setattr(
        chatbot,
        "get_india_gold_price",
        lambda: "Gold (INR/gram): buy INR 14631, sell INR 14209",
    )
    monkeypatch.setitem(chatbot.TOOL_FUNCTIONS, "get_india_gold_price", chatbot.get_india_gold_price)

    seen_payloads = []
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        body = json.loads(request.content.decode("utf-8"))
        seen_payloads.append(body)
        if call_count == 1:
            return httpx.Response(
                400,
                json={"error": {"message": "registry.ollama.ai/library/llama3:8b does not support tools"}},
            )
        if call_count == 2:
            # Emulates model with brief preamble before ```tool_call and an extra unexpected kwarg
            sse = _make_sse_bytes([
                {"choices": [{"delta": {"content": "Checking... "}}]},
                {"choices": [{"delta": {"content": '```tool_call\n{"name": "get_india_gold_price", "arguments": {"country": "India"}}'}}]},
                "[DONE]",
            ])
            return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})
        if call_count == 3:
            sse = _make_sse_bytes([
                {"choices": [{"delta": {"content": "Today India gold buy rate is INR 14631/gram."}}]},
                "[DONE]",
            ])
            return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})
        sse = _make_sse_bytes([
            {"choices": [{"delta": {"content": "Second turn direct reply."}}]},
            "[DONE]",
        ])
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        chatbot.httpx,
        "Client",
        lambda *args, **kwargs: real_client(transport=transport, **kwargs),
    )

    bot = chatbot.Chatbot(
        chatbot.ChatbotConfig(
            provider="nvidia",
            base_url="http://127.0.0.1:1234/v1",
            api_key="nvapi-test",
            model_name="llama3:8b",
            use_tools=True,
        )
    )
    events = list(bot.stream_turn("What is today's gold rate in India?"))
    done_ev = [e for e in events if e["type"] == "done"][-1]
    tool_ends = [e for e in events if e["type"] == "tool_end"]

    assert tool_ends and tool_ends[0]["name"] == "get_india_gold_price"
    assert "14631" in tool_ends[0]["result"]
    assert done_ev["content"] == "Today India gold buy rate is INR 14631/gram."
    assert "tool_call" not in done_ev["content"]
    assert "tools" in seen_payloads[0]
    assert "tools" not in seen_payloads[1]
    assert "Tool get_india_gold_price result" in seen_payloads[2]["messages"][-1]["content"]

    # Second turn reuses cached text_tool_mode without triggering another 400
    events2 = list(bot.stream_turn("Say hi"))
    assert len(seen_payloads) == 4
    assert "tools" not in seen_payloads[3]
    assert "".join(e["content"] for e in events2 if e["type"] == "token") == "Second turn direct reply."


def test_text_tool_call_parser_handles_python_style_and_adjacent_blocks():
    allowed = {"get_weather", "get_india_gold_price"}

    # Two-backtick Python dict style emitted by llama3:8b
    c1 = chatbot._extract_text_tool_calls(
        '``get_weather({"city": "Chennai", "units": "metric"})\n``',
        allowed,
    )
    assert c1 is not None and len(c1) == 1
    assert c1[0]["function"]["name"] == "get_weather"
    assert json.loads(c1[0]["function"]["arguments"]) == {"city": "Chennai", "units": "metric"}

    # Zero-arg call followed by {"arguments": {}} line
    c2 = chatbot._extract_text_tool_calls(
        '```get_india_gold_price()\n{"arguments": {}}\n```',
        allowed,
    )
    assert c2 is not None and len(c2) == 1
    assert c2[0]["function"]["name"] == "get_india_gold_price"
    assert json.loads(c2[0]["function"]["arguments"]) == {}

    # Prompt includes actual parameter names for web/API tools (not empty "none")
    prompt = chatbot._build_text_tool_system_prompt(include_web=True, include_system=True)
    assert "get_weather (params: location, days)" in prompt

    # Positional argument call mapped via tool schema param names
    c3 = chatbot._extract_text_tool_calls('get_weather("Chennai")', allowed)
    assert c3 is not None and json.loads(c3[0]["function"]["arguments"]) == {"location": "Chennai"}

    # Early stream stop triggers once closing fence completes a valid call (with or without preamble)
    assert chatbot._should_stop_text_tool_stream(
        '``get_weather({"city": "Chennai"})\n``',
        allowed,
    ) is True
    preamble_fenced = 'Let me check that.\n\n```get_weather\n{"location": "Chennai"}\n```'
    c4 = chatbot._extract_text_tool_calls(preamble_fenced, allowed)
    assert c4 is not None and c4[0]["function"]["name"] == "get_weather"
    assert json.loads(c4[0]["function"]["arguments"]) == {"location": "Chennai"}
    assert chatbot._should_stop_text_tool_stream(preamble_fenced, allowed) is True
    assert chatbot._should_stop_text_tool_stream(
        '```tool_call\n{"name": "get_weather", "arguments": {"city": "Chennai"}}\n',
        allowed,
    ) is False


def test_mock_mode_routes_daily_topics_to_get_news(monkeypatch):
    seen_keywords = []

    def fake_get_news(keyword: str) -> str:
        seen_keywords.append(keyword)
        return f"- Headline for {keyword} [DailyTest]"

    monkeypatch.setattr(chatbot.api_tools, "get_news", fake_get_news)

    bot = chatbot.Chatbot(chatbot.ChatbotConfig(provider="mock", use_tools=True))
    events1 = list(bot.stream_turn("What is happening in cinema and new movie releases today?"))
    events2 = list(bot.stream_turn("What is happening in the tech field today?"))

    assert seen_keywords[0] == "cinema movies box office"
    assert seen_keywords[1] == "technology AI software"
    assert any(e.get("type") == "tool_end" and e.get("name") == "get_news" for e in events1)
    assert any(e.get("type") == "tool_end" and e.get("name") == "get_news" for e in events2)
    assert bot.history[0].role == "user"


def test_openai_and_deepseek_providers_streaming_and_reasoning(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    assert chatbot.resolve_base_url("openai") == "https://api.openai.com/v1"
    assert chatbot.resolve_base_url("deepseek") == "https://api.deepseek.com"
    assert chatbot.default_model_for_provider("openai") == "gpt-4.1-mini"
    assert chatbot.default_model_for_provider("deepseek") == "deepseek-chat"

    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_requests.append((str(request.url), request.headers.get("authorization"), body))
        if "api.openai.com" in str(request.url):
            sse = _make_sse_bytes([
                {"choices": [{"delta": {"content": "OpenAI reply ok!"}}]},
                "[DONE]",
            ])
            return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

        # DeepSeek reasoner round 1 triggers tool call + reasoning_content; round 2 final answer
        if len(body["messages"]) == 2:
            sse = _make_sse_bytes([
                {"choices": [{"delta": {"reasoning_content": "Let me check the clock."}}]},
                {
                    "choices": [{
                        "delta": {
                            "tool_calls": [{
                                "index": 0,
                                "id": "call_ds_1",
                                "function": {"name": "get_current_datetime", "arguments": "{}"},
                            }]
                        }
                    }]
                },
                "[DONE]",
            ])
            return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

        sse = _make_sse_bytes([
            {"choices": [{"delta": {"reasoning_content": "Done."}}]},
            {"choices": [{"delta": {"content": "DeepSeek answer with time!"}}]},
            "[DONE]",
        ])
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        chatbot.httpx,
        "Client",
        lambda *args, **kwargs: real_client(transport=transport, **kwargs),
    )

    # OpenAI gpt-5-mini uses max_completion_tokens and omits temperature
    oa_bot = chatbot.Chatbot(chatbot.ChatbotConfig(provider="openai", model_name="gpt-5-mini"))
    oa_events = list(oa_bot.stream_turn("hi openai"))
    assert "".join(e["content"] for e in oa_events if e["type"] == "token") == "OpenAI reply ok!"
    oa_url, oa_auth, oa_body = seen_requests[0]
    assert oa_url == "https://api.openai.com/v1/chat/completions"
    assert oa_auth == "Bearer sk-openai-test"
    assert oa_body["max_completion_tokens"] == oa_bot.config.max_tokens
    assert "max_tokens" not in oa_body
    assert "temperature" not in oa_body

    # DeepSeek deepseek-reasoner streams thought tokens and preserves reasoning_content on tool follow-up
    ds_bot = chatbot.Chatbot(
        chatbot.ChatbotConfig(provider="deepseek", model_name="deepseek-reasoner", use_tools=True)
    )
    ds_events = list(ds_bot.stream_turn("what time is it?"))
    assert "".join(e["content"] for e in ds_events if e["type"] == "token") == "DeepSeek answer with time!"
    assert any(e["type"] == "thought" and "clock" in e["content"] for e in ds_events)
    ds_round2_messages = seen_requests[2][2]["messages"]
    assert ds_round2_messages[2]["role"] == "assistant"
    assert ds_round2_messages[2]["reasoning_content"] == "Let me check the clock."

    # /api/status exposes both providers
    client = TestClient(chatbot.create_app(chatbot.ChatbotConfig(provider="mock")))
    st = client.get("/api/status").json()
    assert st["keys_configured"]["openai"] is True
    assert st["keys_configured"]["deepseek"] is True
    assert "openai" in st["models"] and "deepseek" in st["models"]
