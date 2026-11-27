"""Tests for desktop_companion.py (config, Markdown rendering, sprite loading, PySide6 UI)."""

import json
import os
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import desktop_companion as dc  # noqa: E402

_QAPP = None


def _get_qapp() -> QtWidgets.QApplication:
    global _QAPP
    if _QAPP is None:
        _QAPP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return _QAPP


def test_character_config_roundtrip(tmp_path):
    cfg_path = tmp_path / "character_config.json"
    cfg = dc.CharacterConfig(
        character_name="Mochi",
        personality_prompt="Playful pixel companion.",
        sprite_path="custom.gif",
        character_size=160,
        provider="nvidia",
        use_tools=False,
        window_pos=[100, 200],
    )
    cfg.save(cfg_path)

    loaded = dc.CharacterConfig.load(cfg_path)
    assert loaded.character_name == "Mochi"
    assert loaded.personality_prompt == "Playful pixel companion."
    assert loaded.sprite_path == "custom.gif"
    assert loaded.character_size == 160
    assert loaded.provider == "nvidia"
    assert loaded.use_tools is False
    assert loaded.window_pos == [100, 200]


def test_effective_system_prompt():
    with_tools = dc.build_effective_system_prompt("Mochi", "Be cheerful.", use_tools=True)
    assert "Mochi" in with_tools
    assert "Be cheerful." in with_tools
    assert "tools" in with_tools.lower()

    without_tools = dc.build_effective_system_prompt("Mochi", "Be cheerful.", use_tools=False)
    assert "Mochi" in without_tools
    assert "tools" not in without_tools.lower()


def test_markdown_to_qt_html_escapes_script_and_formats_elements():
    md = (
        "# Title\n"
        "Hello **world** and `code` <script>alert(1)</script>\n\n"
        "- item one\n"
        "- [link](https://example.com)\n\n"
        "```python\nprint('hi')\n```"
    )
    rendered = dc.markdown_to_qt_html(md)
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<b>world</b>" in rendered
    assert "<pre" in rendered and "print(&#x27;hi&#x27;)" in rendered
    assert "https://example.com" in rendered

    # Partial streaming headings or fences with extra args must terminate without hanging
    for partial in ("### ", "## ", "# ", "```python extra info\ncode\n```"):
        partial_html = dc.markdown_to_qt_html(partial)
        assert isinstance(partial_html, str) and len(partial_html) > 0


def test_character_widget_renders_default_and_custom_png(tmp_path):
    _get_qapp()
    cfg = dc.CharacterConfig(character_name="Lumi", character_size=120)
    widget = dc.CharacterWidget(cfg)

    # Render built-in pet to pixmap
    pm = widget.grab()
    assert not pm.isNull()
    assert pm.width() > 100

    # Create a custom PNG sprite and verify loading
    sprite_file = tmp_path / "pet.png"
    img = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_ARGB32)
    img.fill(QtGui.QColor("#38bdf8"))
    assert img.save(str(sprite_file))

    cfg.sprite_path = str(sprite_file)
    widget.apply_config(cfg)
    assert widget._pixmap is not None
    pm2 = widget.grab()
    assert not pm2.isNull()

    widget.set_state("thinking")
    widget.set_state("talking")
    widget.set_state("happy")
    widget.show_speech_bubble("Hello!")
    widget.close()
    widget.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    QtWidgets.QApplication.processEvents()


def _cleanup_controller(app, controller) -> None:
    if getattr(controller, "_startup_wake_timer", None) is not None:
        controller._startup_wake_timer.stop()
    if controller._worker_thread is not None:
        controller._worker_thread.quit()
        controller._worker_thread.wait(2000)
    if getattr(controller, "_briefing_thread", None) is not None:
        controller._briefing_thread.quit()
        controller._briefing_thread.wait(2000)
    controller.character._anim_timer.stop()
    controller._hotkey_filter.unregister()
    app.removeNativeEventFilter(controller._hotkey_filter)
    if getattr(controller, "wakeup_bubble", None) is not None:
        controller.wakeup_bubble._hide_timer.stop()
        controller.wakeup_bubble.close()
        controller.wakeup_bubble.deleteLater()
    controller.popup.close()
    controller.popup.deleteLater()
    controller.character.close()
    controller.character.deleteLater()
    controller._tray.hide()
    controller.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()


def test_desktop_companion_app_streams_mock_reply(monkeypatch, tmp_path):
    app = _get_qapp()
    monkeypatch.setattr(dc, "CONFIG_FILE", tmp_path / "character_config.json")
    monkeypatch.setattr(dc.CharacterConfig, "save", lambda self, path=None: None)

    cfg = dc.CharacterConfig(
        character_name="Lumi",
        provider="mock",
        hotkey_enabled=False,
    )
    controller = dc.DesktopCompanionApp(app, cfg)
    try:
        controller.toggle_popup()
        assert controller.popup.isVisible()

        finished_texts = []
        loop = QtCore.QEventLoop(controller)

        timer = QtCore.QTimer(loop)
        timer.timeout.connect(lambda: loop.quit() if controller._worker_thread is None and finished_texts else None)

        controller.send_user_message("hello buddy")
        assert controller._worker is not None
        controller._worker.finished.connect(lambda txt: finished_texts.append(txt))
        timer.start(25)
        stopper = QtCore.QTimer(loop)
        stopper.setSingleShot(True)
        stopper.timeout.connect(loop.quit)
        stopper.start(4000)
        loop.exec()
        timer.stop()
        stopper.stop()

        assert finished_texts
        assert "Mock Mode" in finished_texts[-1]
        assert controller._worker_thread is None
    finally:
        _cleanup_controller(app, controller)


def test_character_resize_down_to_tiny_and_popup_width(monkeypatch, tmp_path):
    app = _get_qapp()
    monkeypatch.setattr(dc, "CONFIG_FILE", tmp_path / "character_config.json")
    monkeypatch.setattr(dc.CharacterConfig, "save", lambda self, path=None: None)

    cfg = dc.CharacterConfig(character_name="Lumi", character_size=140, provider="mock", hotkey_enabled=False)
    controller = dc.DesktopCompanionApp(app, cfg)
    try:
        assert controller.character.width() == 156  # 140 + 16 margin
        controller._on_size_changed(48)
        assert controller._config.character_size == 48
        assert controller.character.width() == 64  # 48 + 16 margin

        dlg = dc.SettingsDialog(controller._config)
        dlg._size_slider.setValue(60)
        assert dlg._size_spin.value() == 60
        updated = dlg.updated_config()
        assert updated.character_size == 60
        dlg.close()
        dlg.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        app.processEvents()

        assert controller.popup.width() == 410
    finally:
        _cleanup_controller(app, controller)


def test_single_instance_guard_signals_running_instance():
    app = _get_qapp()
    server_name = f"test_companion_guard_{QtCore.QCoreApplication.applicationPid()}"
    guard = dc.SingleInstanceGuard(server_name)
    assert guard.start_listening()
    activated = []
    guard.activated.connect(lambda: activated.append(True))

    try:
        assert dc.notify_running_instance(server_name) is True
        for _ in range(10):
            app.processEvents()
            if activated:
                break
        assert activated == [True]
    finally:
        guard.close()


def test_windows_startup_shortcut_toggle(tmp_path):
    assert dc.is_startup_enabled(startup_dir=tmp_path) is False
    ok_enable = dc.set_startup_enabled(True, startup_dir=tmp_path)
    assert ok_enable is True
    assert dc.is_startup_enabled(startup_dir=tmp_path) is True
    assert dc.get_startup_shortcut_path(tmp_path).is_file()

    ok_disable = dc.set_startup_enabled(False, startup_dir=tmp_path)
    assert ok_disable is True
    assert dc.is_startup_enabled(startup_dir=tmp_path) is False


def test_popup_missing_key_banner_toggles(monkeypatch):
    _get_qapp()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    popup = dc.ChatPopupWindow(dc.CharacterConfig(provider="gemini"))
    assert popup._key_banner.isHidden() is False

    popup.apply_config(dc.CharacterConfig(provider="mock"))
    assert popup._key_banner.isHidden() is True
    popup.close()
    popup.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    QtWidgets.QApplication.processEvents()


def test_get_launch_target_frozen_vs_script(monkeypatch, tmp_path):
    fake_exe = tmp_path / "AICompanion.exe"
    fake_exe.write_bytes(b"")

    with monkeypatch.context() as m:
        m.setattr(dc.sys, "frozen", True, raising=False)
        m.setattr(dc.sys, "executable", str(fake_exe))
        target, args, workdir = dc.get_launch_target()
        assert target == fake_exe.resolve()
        assert args == ""
        assert workdir == fake_exe.resolve().parent

    target2, args2, _ = dc.get_launch_target()
    assert target2.name.lower() in {"pythonw.exe", "python.exe"}
    assert "desktop_companion.py" in args2


def test_generate_app_icon_creates_valid_ico(tmp_path):
    from PIL import Image
    from scripts.generate_icon import generate_app_icon

    _get_qapp()
    ico_path = tmp_path / "test_icon.ico"
    generate_app_icon(ico_path)
    assert ico_path.is_file()
    assert ico_path.stat().st_size > 1000
    with Image.open(ico_path) as img:
        assert img.format == "ICO"


def test_popup_quota_banner_and_ollama_no_key_banner():
    _get_qapp()
    popup = dc.ChatPopupWindow(dc.CharacterConfig(provider="ollama", model_name="llama3:8b"))
    assert popup._key_banner.isHidden() is True
    assert popup._quota_banner.isHidden() is True

    switched = []
    popup.provider_switch_requested.connect(lambda p, m: switched.append((p, m)))

    popup.show_error("HTTP 429: You exceeded your current quota")
    assert popup._quota_banner.isHidden() is False

    popup._switch_from_quota("ollama", "")
    assert popup._quota_banner.isHidden() is True
    assert switched == [("ollama", "")]
    popup.close()
    popup.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    QtWidgets.QApplication.processEvents()


def test_settings_dialog_saves_grok_and_tavily_keys(tmp_path, monkeypatch):
    _get_qapp()
    monkeypatch.setitem(os.environ, "GROK_API_KEY", "")
    monkeypatch.setitem(os.environ, "TAVILY_API_KEY", "")
    dlg = dc.SettingsDialog(dc.CharacterConfig(provider="groq", model_name="llama-3.3-70b-versatile"))
    providers = [dlg._provider_combo.itemText(i) for i in range(dlg._provider_combo.count())]
    assert "grok" in providers
    assert dlg.minimumWidth() >= 540
    assert dlg._model_combo.currentText() == "openai/gpt-oss-120b"

    dlg._grok_key_edit.setText("xai-unit-test-123")
    dlg._tavily_key_edit.setText("tvly-unit-test-456")

    env_file = tmp_path / ".env"
    changed = dlg.apply_system_changes(env_path=env_file, startup_dir=tmp_path)
    assert changed is True
    content = env_file.read_text(encoding="utf-8")
    assert "GROK_API_KEY=" in content
    assert "TAVILY_API_KEY=" in content
    assert os.getenv("GROK_API_KEY") == "xai-unit-test-123"
    assert os.getenv("TAVILY_API_KEY") == "tvly-unit-test-456"
    dlg.close()
    dlg.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    QtWidgets.QApplication.processEvents()


def test_settings_dialog_system_tools_roundtrip(tmp_path):
    _get_qapp()
    custom_dir = tmp_path / "work"
    custom_dir.mkdir()
    cfg = dc.CharacterConfig(
        enable_system_tools=False,
        confirm_app_launch=True,
        allow_all_user_folders=False,
        allowed_folders=[str(tmp_path)],
    )
    dlg = dc.SettingsDialog(cfg)
    dlg._sys_tools_chk.setChecked(True)
    dlg._confirm_launch_chk.setChecked(False)
    dlg._all_folders_chk.setChecked(True)
    dlg._allowed_dirs_edit.setPlainText(f"{tmp_path}\n{custom_dir}")

    updated = dlg.updated_config()
    assert updated.enable_system_tools is True
    assert updated.confirm_app_launch is False
    assert updated.allow_all_user_folders is True
    assert updated.allowed_folders == [str(tmp_path), str(custom_dir)]
    dlg.close()
    dlg.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    QtWidgets.QApplication.processEvents()

    cfg_path = tmp_path / "character_config.json"
    updated.save(cfg_path)
    reloaded = dc.CharacterConfig.load(cfg_path)
    assert reloaded.enable_system_tools is True
    assert reloaded.confirm_app_launch is False
    assert reloaded.allow_all_user_folders is True
    assert reloaded.allowed_folders == [str(tmp_path), str(custom_dir)]


def test_companion_system_tools_toggle_clipboard_and_confirm(monkeypatch, tmp_path):
    import threading

    app = _get_qapp()
    monkeypatch.setattr(dc, "CONFIG_FILE", tmp_path / "character_config.json")
    monkeypatch.setattr(dc.CharacterConfig, "save", lambda self, path=None: None)

    cfg = dc.CharacterConfig(
        character_name="Lumi",
        provider="mock",
        use_tools=True,
        enable_system_tools=False,
        allowed_folders=[str(tmp_path)],
        hotkey_enabled=False,
    )
    controller = dc.DesktopCompanionApp(app, cfg)
    try:
        assert controller.popup._files_chip is not None
        assert controller.popup._files_chip.isHidden() is True
        assert controller._bot.config.enable_system_tools is False

        controller.toggle_system_tools(True)
        assert controller._config.enable_system_tools is True
        assert controller._bot.config.enable_system_tools is True
        assert controller._bot.config.system_policy.enabled is True
        assert controller.popup._files_chip.isHidden() is False
        assert "PC Control ON" in controller.popup._status_lbl.text()

        # Clipboard set / get / copy_files
        set_msg = controller._exec_clipboard_ui("set", "hello clip", [])
        assert "10 character" in set_msg
        assert controller._exec_clipboard_ui("get", "", []) == "hello clip"

        sample = tmp_path / "paste_me.txt"
        sample.write_text("hi", encoding="utf-8")
        copy_msg = controller._exec_clipboard_ui("copy_files", "", [str(sample)])
        assert "Copied 1 file/folder" in copy_msg
        assert "paste_me.txt" in controller._exec_clipboard_ui("get", "", [])

        # Confirm dialog requested off GUI thread -> Allow button clicked on UI thread
        results = []

        def worker_call():
            results.append(
                controller._confirm_on_ui(
                    "Move to Recycle Bin",
                    f"Send to Windows Recycle Bin:\n{sample}",
                    "destructive",
                )
            )

        t = threading.Thread(target=worker_call, daemon=True)
        t.start()

        deadline_loop = QtCore.QEventLoop(controller)
        poll = QtCore.QTimer(deadline_loop)

        def check_dialog():
            box = controller._active_confirm_box
            if box is not None:
                for btn in box.buttons():
                    if btn.text() == "Allow":
                        btn.click()
                        break
                else:
                    box.reject()
            if not t.is_alive():
                deadline_loop.quit()

        poll.timeout.connect(check_dialog)
        poll.start(20)
        stopper = QtCore.QTimer(deadline_loop)
        stopper.setSingleShot(True)
        stopper.timeout.connect(deadline_loop.quit)
        stopper.start(3000)
        deadline_loop.exec()
        poll.stop()
        stopper.stop()
        if controller._active_confirm_box is not None:
            controller._active_confirm_box.reject()
        t.join(timeout=1.0)
        assert results == [True]

        controller.toggle_system_tools(False)
        assert controller._bot.config.enable_system_tools is False
        assert controller.popup._files_chip.isHidden() is True
    finally:
        _cleanup_controller(app, controller)


def test_pc_control_badge_visible_when_web_tools_disabled(monkeypatch, tmp_path):
    app = _get_qapp()
    monkeypatch.setattr(dc, "CONFIG_FILE", tmp_path / "character_config.json")
    monkeypatch.setattr(dc.CharacterConfig, "save", lambda self, path=None: None)

    cfg = dc.CharacterConfig(
        character_name="Lumi",
        provider="mock",
        use_tools=False,
        enable_system_tools=True,
        allow_all_user_folders=False,
        allowed_folders=[str(tmp_path)],
        hotkey_enabled=False,
    )
    controller = dc.DesktopCompanionApp(app, cfg)
    try:
        assert controller._bot.config.enable_system_tools is True
        assert controller._bot.config.system_policy.enabled is True
        assert controller._bot.config.system_policy.allow_all_non_system is False
        assert controller.popup._files_chip is not None
        assert controller.popup._files_chip.isHidden() is False
        assert "PC Control ON" in controller.popup._status_lbl.text()

        # Toggling All-Drive Control updates policy, system prompt, and status badge
        controller.toggle_all_drives(True)
        assert controller._config.allow_all_user_folders is True
        assert controller._bot.config.system_policy.allow_all_non_system is True
        assert "All Drives" in controller.popup._status_lbl.text()
        assert "list_drives" in controller._bot.config.system_prompt
    finally:
        _cleanup_controller(app, controller)


def test_settings_dialog_uses_tabs_without_scrollarea_or_clipping():
    app = _get_qapp()
    cfg = dc.CharacterConfig(
        character_name="Lumi",
        provider="groq",
        enable_system_tools=True,
        allow_all_user_folders=True,
    )
    dlg = dc.SettingsDialog(cfg)
    try:
        assert dlg.findChildren(QtWidgets.QScrollArea) == []
        assert dlg._tabs.count() == 6
        tab_labels = [dlg._tabs.tabText(i).replace("&&", "&") for i in range(dlg._tabs.count())]
        assert tab_labels == ["Character", "AI & API Keys", "PC & Files", "APIs & Tools", "Wake-Up & Topics", "🧠 Memory"]
        dlg.show()
        for idx in range(dlg._tabs.count()):
            dlg._tabs.setCurrentIndex(idx)
            app.processEvents()
            page = dlg._tabs.widget(idx)
            assert page.minimumSizeHint().width() <= dlg._tabs.width()
        assert dlg.minimumSizeHint().width() <= dlg.width()
    finally:
        dlg.close()
        dlg.deleteLater()
        QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        QtWidgets.QApplication.processEvents()


def test_builtin_apis_dialog_smoke_and_save_env(tmp_path, monkeypatch):
    app = _get_qapp()
    monkeypatch.setenv("OPENWEATHER_API_KEY", "test-owm-key")
    dlg = dc.BuiltInApisDialog()
    env_file = tmp_path / ".env"
    try:
        assert dlg.findChildren(QtWidgets.QScrollArea) == []
        dlg.show()
        app.processEvents()
        assert dlg.minimumSizeHint().width() <= dlg.width()
        edits = dlg.findChildren(QtWidgets.QLineEdit)
        assert edits, "BuiltInApisDialog should contain input fields"
        edits[0].setText("edited-test-secret-123")
        dlg.save_to_env(env_path=env_file)
        assert env_file.exists()
        assert "edited-test-secret-123" in env_file.read_text(encoding="utf-8")
    finally:
        dlg.close()
        dlg.deleteLater()
        QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        QtWidgets.QApplication.processEvents()


def test_custom_api_editor_dialog_preset_templates_and_build(tmp_path):
    import api_tools

    app = _get_qapp()
    dlg = dc.CustomApiEditorDialog()
    try:
        assert dlg.findChildren(QtWidgets.QScrollArea) == []
        dlg.show()
        app.processEvents()
        assert dlg.minimumSizeHint().width() <= dlg.width()
        assert dlg._template_combo.count() >= len(api_tools.PRESET_TEMPLATES) + 1
        dlg._template_combo.setCurrentIndex(1)
        app.processEvents()
        ep = dlg.build_endpoint()
        assert isinstance(ep, api_tools.CustomApiEndpoint)
        assert ep.base_url.startswith("http")
        assert ep.name.strip() != ""
        env_file = tmp_path / ".env"
        dlg.save_secret_if_entered(env_path=env_file)
    finally:
        dlg.close()
        dlg.deleteLater()
        QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        QtWidgets.QApplication.processEvents()


def test_chat_area_hides_scrollbars_and_shows_tools_off_banner(monkeypatch, tmp_path):
    app = _get_qapp()
    monkeypatch.setattr(dc, "CONFIG_FILE", tmp_path / "character_config.json")
    monkeypatch.setattr(dc.CharacterConfig, "save", lambda self, path=None: None)

    cfg = dc.CharacterConfig(
        character_name="Lumi",
        provider="mock",
        use_tools=False,
        enable_system_tools=True,
        allowed_folders=[str(tmp_path)],
        hotkey_enabled=False,
    )
    controller = dc.DesktopCompanionApp(app, cfg)
    try:
        popup = controller.popup
        popup.show()
        app.processEvents()
        assert popup._scroll.verticalScrollBarPolicy() == QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert popup._scroll.horizontalScrollBarPolicy() == QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert popup._input.verticalScrollBarPolicy() == QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert popup._input.horizontalScrollBarPolicy() == QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff

        # Tools-OFF banner and status badge appear when use_tools=False
        assert popup._tools_off_banner.isHidden() is False
        assert "Web/API OFF" in popup._status_lbl.text()

        # Fill chat beyond viewport height; scrollbars remain hidden while scrolling still works
        for i in range(12):
            popup.add_user_message(f"Message {i}: testing overflow height cleanly")
            popup.start_assistant_message()
            popup.finish_assistant_message(f"Reply {i}: testing response wrapping without scrollbars.")
        app.processEvents()
        popup._msg_layout.activate()
        app.processEvents()
        popup._do_scroll_to_bottom()
        bar = popup._scroll.verticalScrollBar()
        assert bar.isVisible() is False
        assert popup._scroll.horizontalScrollBar().isVisible() is False
        assert bar.maximum() > 0
        assert bar.value() == bar.maximum()

        # Toggling web tools ON hides banner and removes Web/API OFF badge
        controller.toggle_web_tools(True)
        assert controller._config.use_tools is True
        assert controller._bot.config.use_tools is True
        assert popup._tools_off_banner.isHidden() is True
        assert "Web/API OFF" not in popup._status_lbl.text()

        # SettingsDialog keeps Tab 1 & Tab 3 web tools checkboxes synced
        dlg = dc.SettingsDialog(controller._config)
        try:
            assert dlg._tools_chk.isChecked() is True
            assert dlg._apis_tools_chk.isChecked() is True
            dlg._apis_tools_chk.setChecked(False)
            assert dlg._tools_chk.isChecked() is False
            assert dlg.updated_config().use_tools is False
        finally:
            dlg.close()
            dlg.deleteLater()
            QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            QtWidgets.QApplication.processEvents()
    finally:
        _cleanup_controller(app, controller)


def test_character_config_wake_and_topics_roundtrip(tmp_path):
    cfg_path = tmp_path / "character_config.json"
    cfg = dc.CharacterConfig(
        wake_greeting_enabled=True,
        wake_open_chat=False,
        wake_on_system_resume=True,
        wake_resume_cooldown_minutes=45,
        wake_auto_fetch_briefing=True,
        wake_user_name="Sam",
        wake_weather_city="Bengaluru",
        custom_topics=[
            {
                "id": "tech",
                "label": "Tech Field",
                "kind": "news",
                "query": "AI chips",
                "prompt": "What happened in AI chips today?",
                "enabled": True,
            },
            {
                "id": "cricket",
                "label": "Cricket",
                "kind": "web_search",
                "query": "India cricket match score",
                "prompt": "",
                "enabled": False,
            },
        ],
    )
    cfg.save(cfg_path)
    loaded = dc.CharacterConfig.load(cfg_path)
    assert loaded.wake_greeting_enabled is True
    assert loaded.wake_open_chat is False
    assert loaded.wake_resume_cooldown_minutes == 45
    assert loaded.wake_auto_fetch_briefing is True
    assert loaded.wake_user_name == "Sam"
    assert loaded.wake_weather_city == "Bengaluru"
    assert [t["id"] for t in loaded.custom_topics] == ["tech", "cricket"]
    assert loaded.custom_topics[1]["enabled"] is False


def test_time_of_day_greeting_and_wake_greeting_data():
    from datetime import datetime

    assert dc.time_of_day_greeting(datetime(2026, 11, 12, 8, 30), "Alex") == "Good morning, Alex!"
    assert dc.time_of_day_greeting(datetime(2026, 11, 12, 14, 0), "") == "Good afternoon!"
    assert dc.time_of_day_greeting(datetime(2026, 11, 12, 19, 15), "Sam") == "Good evening, Sam!"
    assert dc.time_of_day_greeting(datetime(2026, 11, 12, 2, 10), "") == "Hello!"

    cfg = dc.CharacterConfig(wake_user_name="Alex", wake_weather_city="Hyderabad")
    data = dc.build_wake_greeting_data(cfg, now=datetime(2026, 11, 12, 9, 0), system_resume=True)
    assert "Good morning, Alex!" in data["headline"]
    assert "Welcome back!" in data["headline"]
    assert "How can I assist you?" in data["headline"]
    labels = [t["label"] for t in data["topics"]]
    assert labels == ["Tech Field", "Cinema", "Gold Rate", "Weather", "Cricket", "Top News"]
    weather_topic = next(t for t in data["topics"] if t["id"] == "weather")
    assert "Hyderabad" in weather_topic["prompt"]


def test_wakeup_bubble_visible_at_small_character_size(monkeypatch, tmp_path):
    app = _get_qapp()
    monkeypatch.setattr(dc, "CONFIG_FILE", tmp_path / "character_config.json")
    monkeypatch.setattr(dc.CharacterConfig, "save", lambda self, path=None: None)

    cfg = dc.CharacterConfig(
        character_name="Lumi",
        character_size=72,
        provider="mock",
        enable_system_tools=True,
        hotkey_enabled=False,
        wake_greeting_enabled=True,
        wake_open_chat=True,
        wake_auto_fetch_briefing=False,
    )
    controller = dc.DesktopCompanionApp(app, cfg)
    try:
        assert controller.character.width() == 88  # < 115px where built-in inline paint stops
        controller.trigger_wake_greeting(open_chat=True)
        app.processEvents()

        assert controller.character.isVisible() is True
        assert controller.wakeup_bubble.isVisible() is True
        assert "How can I assist you?" in controller.wakeup_bubble._msg_lbl.text()
        assert controller.popup.isVisible() is True
        assert controller.popup._wake_card is not None
        assert controller._bot.history == []

        # Dismissing the wakeup bubble stops its timer and hides it
        controller.wakeup_bubble.dismiss_bubble()
        assert controller.wakeup_bubble.isVisible() is False
    finally:
        _cleanup_controller(app, controller)


def test_dynamic_topic_chips_and_settings_roundtrip(tmp_path):
    app = _get_qapp()
    cfg = dc.CharacterConfig(
        provider="mock",
        enable_system_tools=False,
        wake_user_name="Maya",
        wake_weather_city="Coimbatore",
    )
    dlg = dc.SettingsDialog(cfg)
    try:
        editor = dc.TopicEditorDialog(parent=dlg)
        editor._label_edit.setText("ISRO Space")
        idx = editor._kind_combo.findData("web_search")
        editor._kind_combo.setCurrentIndex(idx)
        editor._query_edit.setText("ISRO latest launch")
        topic = editor.build_topic()
        editor.close()
        editor.deleteLater()

        dlg._topics_draft.append(topic)
        dlg._wake_user_edit.setText("Maya K")
        dlg._wake_city_edit.setText("Madurai")
        dlg._wake_cooldown_spin.setValue(90)
        dlg._wake_briefing_chk.setChecked(True)
        updated = dlg.updated_config()

        assert updated.wake_user_name == "Maya K"
        assert updated.wake_weather_city == "Madurai"
        assert updated.wake_resume_cooldown_minutes == 90
        assert updated.wake_auto_fetch_briefing is True
        assert any(t["label"] == "ISRO Space" for t in updated.custom_topics)

        popup = dc.ChatPopupWindow(updated)
        try:
            chip_texts = [
                popup._chips_layout.itemAt(i).widget().text()
                for i in range(popup._chips_layout.count())
                if popup._chips_layout.itemAt(i).widget() is not None
            ]
            assert "ISRO Space" in chip_texts
            assert "Files" in chip_texts
            assert popup._files_chip is not None and popup._files_chip.isHidden() is True
        finally:
            popup.close()
            popup.deleteLater()
            QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
            QtWidgets.QApplication.processEvents()
    finally:
        dlg.close()
        dlg.deleteLater()
        QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        QtWidgets.QApplication.processEvents()


def test_startup_flag_and_power_resume_debounce_cooldown(monkeypatch, tmp_path):
    app = _get_qapp()
    monkeypatch.setattr(dc, "CONFIG_FILE", tmp_path / "character_config.json")
    monkeypatch.setattr(dc.CharacterConfig, "save", lambda self, path=None: None)

    fake_exe = tmp_path / "AICompanion.exe"
    fake_exe.write_bytes(b"")
    with monkeypatch.context() as m:
        m.setattr(dc.sys, "frozen", True, raising=False)
        m.setattr(dc.sys, "executable", str(fake_exe))
        _, args_startup, _ = dc.get_launch_target(startup_mode=True)
        assert args_startup == "--startup"

    _, py_args_startup, _ = dc.get_launch_target(startup_mode=True)
    assert "--startup" in py_args_startup
    assert dc.set_startup_enabled(True, startup_dir=tmp_path, include_startup_flag=True) is True
    assert dc.get_startup_shortcut_path(tmp_path).is_file()

    # Power broadcast debouncing inside WindowsHotkeyFilter
    resumed = []
    flt = dc.WindowsHotkeyFilter(lambda: None, on_system_resume=lambda: resumed.append(True))
    now_clock = [100.0]
    monkeypatch.setattr(dc.time, "monotonic", lambda: now_clock[0])
    flt._process_win32_msg(flt.WM_POWERBROADCAST, flt.PBT_APMRESUMEAUTOMATIC)
    flt._process_win32_msg(flt.WM_POWERBROADCAST, flt.PBT_APMRESUMESUSPEND)
    app.processEvents()
    assert len(resumed) == 1

    now_clock[0] = 106.0
    flt._process_win32_msg(flt.WM_POWERBROADCAST, flt.PBT_APMRESUMESUSPEND)
    app.processEvents()
    assert len(resumed) == 2

    # Controller cooldown check on _on_system_resume
    cfg = dc.CharacterConfig(
        provider="mock",
        hotkey_enabled=False,
        wake_greeting_enabled=True,
        wake_on_system_resume=True,
        wake_resume_cooldown_minutes=60,
        wake_open_chat=False,
    )
    controller = dc.DesktopCompanionApp(app, cfg)
    try:
        triggers = []
        monkeypatch.setattr(controller, "trigger_wake_greeting", lambda **kw: triggers.append(kw))
        controller._last_wake_monotonic = 100.0
        now_clock[0] = 200.0  # < 60 min
        controller._on_system_resume()
        assert triggers == []

        now_clock[0] = 100.0 + 3601.0  # >= 60 min
        controller._on_system_resume()
        assert len(triggers) == 1 and triggers[0]["system_resume"] is True
    finally:
        _cleanup_controller(app, controller)


def test_fetch_live_briefing_markdown_and_worker(monkeypatch, tmp_path):
    app = _get_qapp()
    monkeypatch.setattr(dc, "CONFIG_FILE", tmp_path / "character_config.json")
    monkeypatch.setattr(dc.CharacterConfig, "save", lambda self, path=None: None)

    monkeypatch.setattr(dc.chatbot, "get_india_gold_price", lambda: "Gold (INR/gram): buy INR 15000")
    monkeypatch.setattr(dc.api_tools, "get_weather", lambda city, days=1: f"{city}: 31C Sunny")
    monkeypatch.setattr(dc.api_tools, "get_news", lambda kw: f"- Top story about {kw} [Test]")
    monkeypatch.setattr(dc.api_tools, "web_search", lambda q, max_results=3: f"Result for {q}")

    cfg = dc.CharacterConfig(
        provider="mock",
        wake_weather_city="Chennai",
        hotkey_enabled=False,
        wake_auto_fetch_briefing=False,
    )
    md = dc.fetch_live_briefing_markdown(cfg, max_topics=4)
    assert "**Tech Field:**" in md
    assert "**Cinema:**" in md
    assert "**Gold Rate:**" in md and "15000" in md
    assert "**Weather:**" in md and "31C Sunny" in md

    controller = dc.DesktopCompanionApp(app, cfg)
    try:
        controller.trigger_wake_greeting(open_chat=True)
        controller.fetch_live_briefing()
        loop = QtCore.QEventLoop(controller)
        timer = QtCore.QTimer(loop)
        timer.timeout.connect(lambda: loop.quit() if controller._briefing_thread is None else None)
        stopper = QtCore.QTimer(loop)
        stopper.setSingleShot(True)
        stopper.timeout.connect(loop.quit)
        timer.start(20)
        stopper.start(3000)
        loop.exec()
        timer.stop()
        stopper.stop()

        assert controller._briefing_thread is None
        assert controller.popup._wake_briefing_browser is not None
        assert controller.popup._wake_briefing_browser.isHidden() is False
        assert "15000" in controller.popup._wake_briefing_browser.toPlainText()
    finally:
        _cleanup_controller(app, controller)


def test_settings_dialog_saves_openai_and_deepseek_keys(tmp_path, monkeypatch):
    _get_qapp()
    monkeypatch.setitem(os.environ, "OPENAI_API_KEY", "")
    monkeypatch.setitem(os.environ, "DEEPSEEK_API_KEY", "")
    dlg = dc.SettingsDialog(dc.CharacterConfig(provider="openai"))
    try:
        providers = [dlg._provider_combo.itemText(i) for i in range(dlg._provider_combo.count())]
        assert "openai" in providers
        assert "deepseek" in providers
        assert dlg._model_combo.currentText() == "gpt-4.1-mini"

        dlg.show()
        QtWidgets.QApplication.processEvents()
        assert dlg.minimumSizeHint().width() <= dlg.width()
        assert dlg.minimumSizeHint().height() <= dlg.height()

        dlg._openai_key_edit.setText("sk-openai-unit-test")
        dlg._deepseek_key_edit.setText("sk-deepseek-unit-test")
        env_file = tmp_path / ".env"
        changed = dlg.apply_system_changes(env_path=env_file, startup_dir=tmp_path)
        assert changed is True
        content = env_file.read_text(encoding="utf-8")
        assert "OPENAI_API_KEY=" in content
        assert "DEEPSEEK_API_KEY=" in content
        assert os.getenv("OPENAI_API_KEY") == "sk-openai-unit-test"
        assert os.getenv("DEEPSEEK_API_KEY") == "sk-deepseek-unit-test"
    finally:
        dlg.close()
        dlg.deleteLater()
        QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        QtWidgets.QApplication.processEvents()


def test_markdown_code_block_copy_link_generation():
    raw_md = "Here is the code:\n```python\nprint('Hero Time!')\nx = 10\n```\nDone."
    html_out = dc.markdown_to_qt_html(raw_md)
    assert "PYTHON" in html_out
    assert "href='copy:" in html_out
    assert "Hero Time!" in html_out


def test_chat_popup_code_copy_and_animation():
    _get_qapp()
    cfg = dc.CharacterConfig(character_id="ben_tennyson")
    popup = dc.ChatPopupWindow(cfg)
    try:
        popup.show()
        QtWidgets.QApplication.processEvents()

        raw_code = "print('Heatblast blast!')"
        encoded = dc.base64.b64encode(raw_code.encode("utf-8")).decode("ascii")
        copy_url = QtCore.QUrl(f"copy:{encoded}")

        # Trigger copy click handler
        popup._on_browser_anchor_clicked(copy_url)
        assert QtGui.QGuiApplication.clipboard().text() == raw_code
        assert not popup._toast_lbl.isHidden()
        assert "copied" in popup._toast_lbl.text().lower()

        # Test show_animated & hide_animated
        popup.show_animated()
        QtWidgets.QApplication.processEvents()
        assert popup.isVisible()

        popup.hide_animated()
        QtWidgets.QApplication.processEvents()
    finally:
        popup.close()
        popup.deleteLater()
        QtWidgets.QApplication.processEvents()


def test_character_widget_ambient_halo_and_comic_bubble():
    _get_qapp()
    cfg = dc.CharacterConfig(character_id="heatblast", character_size=120)
    w = dc.CharacterWidget(cfg)
    try:
        w.show_speech_bubble("Testing fiery comic speech bubble!")
        w._on_tick()
        assert len(w._particles) == 6

        pm = QtGui.QPixmap(140, 160)
        p = QtGui.QPainter(pm)
        w.paintEvent(QtGui.QPaintEvent(QtCore.QRect(0, 0, 140, 160)))
        p.end()
        assert not pm.isNull()
    finally:
        w.deleteLater()


def test_tasks_dialog_and_alert_popup(tmp_path, monkeypatch):
    import task_manager
    _get_qapp()
    test_db = tmp_path / "gui_tasks.json"
    tm = task_manager.TaskManager(str(test_db))
    monkeypatch.setattr(task_manager, "get_task_manager", lambda: tm)

    cfg = dc.CharacterConfig(character_name="Ben", character_id="ben_tennyson")
    dlg = dc.TasksDialog(config=cfg)
    try:
        # Add a task
        dlg._new_todo_input.setText("Test companion task")
        dlg._on_add_todo()
        assert len(tm.get_todos("pending")) == 1
        assert tm.get_todos("pending")[0].title == "Test companion task"

        # Toggle task complete
        t_id = tm.get_todos("pending")[0].id
        dlg._on_toggle_todo(t_id, True)
        assert len(tm.get_todos("pending")) == 0
        assert len(tm.get_todos("completed")) == 1

        # Add alarm
        dlg._alm_time_input.setText("08:30")
        dlg._alm_label_input.setText("Workout Alarm")
        dlg._on_add_alarm()
        assert len(tm.get_alarms()) == 1
        alm = tm.get_alarms()[0]
        assert alm.time_str == "08:30"

        # Test slider & typing synchronization
        dlg._hour_slider.setValue(14)
        dlg._min_slider.setValue(45)
        assert dlg._alm_time_input.text() == "14:45"
        assert "02 PM" in dlg._hour_slider_lbl.text()
        assert "45" in dlg._min_slider_lbl.text()

        # Type time back
        dlg._alm_time_input.setText("07:15")
        assert dlg._hour_slider.value() == 7
        assert dlg._min_slider.value() == 15

        # Test alarm deletion
        dlg._on_delete_alarm(alm.id)
        assert len(tm.get_alarms()) == 0

        # Add reminder
        dlg._rem_msg_input.setText("Stretch break")
        dlg._rem_time_input.setText("in 15m")
        dlg._on_add_reminder()
        assert len(tm.get_reminders("pending")) == 1
        rem = tm.get_reminders("pending")[0]

        # Test reminder deletion
        dlg._on_delete_reminder(rem.id)
        assert len(tm.get_reminders("pending")) == 0

        # Add reminder with natural embedded time in note and blank When input
        dlg._rem_msg_input.setText("dont forget to update teh work at 5:40 p.m")
        dlg._rem_time_input.clear()
        dlg._on_add_reminder()
        assert len(tm.get_reminders("pending")) == 1
        rem2 = tm.get_reminders("pending")[0]
        assert "dont forget to update" in rem2.message
        dlg._on_delete_reminder(rem2.id)

        # Test quick preset time button
        dlg._set_reminder_time_preset("in 30m")
        assert dlg._rem_time_input.text() == "in 30m"

        # Verify bright text color styling on input fields
        assert "#ffffff" in dlg._new_todo_input.styleSheet()
        assert "#ffffff" in dlg._rem_msg_input.styleSheet()
        assert "#ffffff" in dlg._rem_time_input.styleSheet()

        # Test AlertNotificationPopup
        done_called = False
        snooze_called = False

        def on_done():
            nonlocal done_called
            done_called = True

        def on_snooze(mins):
            nonlocal snooze_called
            snooze_called = True

        popup = dc.AlertNotificationPopup(
            title="⏰ Reminder",
            message="Stretch break",
            target_id="rem_123",
            on_done=on_done,
            on_snooze=on_snooze,
        )
        try:
            popup._handle_done()
            assert done_called is True
            popup._handle_snooze(5)
            assert snooze_called is True
        finally:
            popup.deleteLater()
    finally:
        dlg.deleteLater()


def test_companion_reminder_scheduler_and_chips(tmp_path, monkeypatch):
    from datetime import datetime
    import task_manager
    app = _get_qapp()
    test_db = tmp_path / "scheduler_tasks.json"
    tm = task_manager.TaskManager(str(test_db))
    monkeypatch.setattr(task_manager, "get_task_manager", lambda: tm)
    monkeypatch.setattr(dc, "play_alert_sound", lambda *args, **kwargs: None)

    cfg = dc.CharacterConfig(character_name="Lumi", character_id="lumi")
    controller = dc.DesktopCompanionApp(app, cfg)
    try:
        # Check Tasks chip in popup
        assert controller.popup._tasks_chip is not None
        assert controller.popup._tasks_chip.isHidden() is False

        # Add due reminder
        rem = tm.add_reminder("Immediate stretch", due_time=datetime(2020, 1, 1, 12, 0, 0))
        controller._check_reminders_and_alarms()

        # Alert popup should now be created
        assert controller._alert_popup is not None
        assert "Reminder: Immediate stretch" in controller.character._speech_text
    finally:
        if controller._reminder_timer:
            controller._reminder_timer.stop()
        if controller._alert_popup:
            controller._alert_popup.close()
            controller._alert_popup.deleteLater()
        controller.character.deleteLater()
        controller.popup.deleteLater()


def test_pomodoro_tab_and_focus_controls(tmp_path, monkeypatch):
    import task_manager
    _get_qapp()
    test_db = tmp_path / "gui_pomodoro.json"
    tm = task_manager.TaskManager(str(test_db))
    monkeypatch.setattr(task_manager, "get_task_manager", lambda: tm)

    cfg = dc.CharacterConfig(character_name="Ben", character_id="ben_tennyson")
    dlg = dc.TasksDialog(config=cfg)
    try:
        # Check Pomodoro tab exists
        dlg.set_tab("pomodoro")
        assert dlg._tabs.currentIndex() == 3

        # Default display is 25:00
        assert dlg._pomo_timer_lbl.text() == "25:00"
        assert "Ready to Focus" in dlg._pomo_badge.text()

        # Start pomodoro
        dlg._on_start_pomodoro()
        st = tm.get_pomodoro_status()
        assert st["status"] == "work"
        assert "Focus Session" in dlg._pomo_badge.text()

        # Change duration preset to 15m
        dlg._on_set_pomodoro_duration(15)
        assert dlg._pomo_timer_lbl.text() == "15:00"
        assert tm.get_pomodoro_status()["work_duration_minutes"] == 15

        # Pause and resume
        dlg._on_toggle_pause_pomodoro()
        assert tm.get_pomodoro_status()["is_paused"] is True
        dlg._on_toggle_pause_pomodoro()
        assert tm.get_pomodoro_status()["is_paused"] is False

        # Reset
        dlg._on_stop_pomodoro()
        assert tm.get_pomodoro_status()["status"] == "idle"
    finally:
        dlg._pomo_ui_timer.stop()
        dlg.deleteLater()


def test_screen_snipping_overlay_and_chat_attachment():
    _get_qapp()
    overlay = dc.ScreenSnippingOverlay()
    try:
        assert overlay.isModal() is False
        # Esc key cancels overlay
        esc_event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape, QtCore.Qt.KeyboardModifier.NoModifier)
        overlay.keyPressEvent(esc_event)
    finally:
        overlay.deleteLater()

    # ChatPopupWindow attachment test
    cfg = dc.CharacterConfig(character_name="Lumi", character_id="lumi")
    popup = dc.ChatPopupWindow(cfg)
    try:
        assert popup._attachment_bar.isHidden() is True
        dummy_b64 = "QUJDREVG"
        popup.attach_screenshot(dummy_b64)
        assert popup._attachment_bar.isHidden() is False
        assert popup._attached_images == [dummy_b64]

        # Clearing screenshot
        popup.clear_attached_screenshot()
        assert popup._attachment_bar.isHidden() is True
        assert len(popup._attached_images) == 0

        # Send with attachment emits send_message_with_images
        sent_with_imgs = []
        popup.send_message_with_images.connect(lambda txt, imgs: sent_with_imgs.append((txt, imgs)))
        popup.attach_screenshot(dummy_b64)
        popup._input.setPlainText("Explain this screen error")
        popup._on_send_clicked()

        assert len(sent_with_imgs) == 1
        assert sent_with_imgs[0][0] == "Explain this screen error"
        assert sent_with_imgs[0][1] == [dummy_b64]
        assert popup._attachment_bar.isHidden() is True
    finally:
        popup.deleteLater()


def test_alarm_sound_theme_and_voice_briefing_config(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "play_alarm_ringtone", lambda *args, **kwargs: None)
    monkeypatch.setattr(dc, "speak_voice_briefing", lambda *args, **kwargs: None)

    cfg = dc.CharacterConfig(
        alarm_sound_theme="omnitrix_pulse",
        custom_alarm_sound_path=str(tmp_path / "custom.wav"),
        voice_alarm_enabled=True,
    )
    # Save & reload roundtrip
    p = tmp_path / "cfg.json"
    cfg.save(p)
    loaded = dc.CharacterConfig.load(p)
    assert loaded.alarm_sound_theme == "omnitrix_pulse"
    assert loaded.custom_alarm_sound_path == str(tmp_path / "custom.wav")
    assert loaded.voice_alarm_enabled is True

    # Alert popup with sound theme
    _get_qapp()
    popup = dc.AlertNotificationPopup(
        title="🚨 Alarm",
        message="Wake up standup",
        target_id="alm_1",
        is_alarm=True,
        sound_enabled=True,
        sound_theme=loaded.alarm_sound_theme,
        custom_sound_path=loaded.custom_alarm_sound_path,
    )
    try:
        assert popup._sound_theme == "omnitrix_pulse"
        popup.stop_sound()
        assert popup._stop_sound_event.is_set()
    finally:
        popup.deleteLater()


def test_ui_themes_registry_and_fallback():
    expected_themes = [
        "deep_slate",
        "cyberpunk_teal",
        "neon_green",
        "sakura_pink",
        "electric_purple",
        "sunset_amber",
        "crimson_red",
    ]
    for tid in expected_themes:
        assert tid in dc.UI_THEMES
        theme = dc.get_ui_theme(tid)
        assert theme.id == tid
        assert theme.name
        assert theme.accent_color.startswith("#")
        assert theme.primary_gradient_start.startswith("#")
        assert theme.primary_gradient_end.startswith("#")

    # Character-based auto-resolution checks
    assert dc.get_ui_theme("auto", character_id="heatblast").id == "sunset_amber"
    assert dc.get_ui_theme("auto", character_id="fourarms").id == "crimson_red"
    assert dc.get_ui_theme("auto", character_id="ben_tennyson").id == "neon_green"
    assert dc.get_ui_theme("auto", character_id="gwen_mana").id == "electric_purple"
    assert dc.get_ui_theme("auto", character_id="xlr8").id == "cyberpunk_teal"
    assert dc.get_ui_theme("auto", character_id="anime_sakura").id == "sakura_pink"
    assert dc.get_ui_theme("auto", character_id="lumi").id == "deep_slate"
    assert dc.get_ui_theme(None, character_id="heatblast").id == "sunset_amber"
    assert dc.get_ui_theme("", character_id="fourarms").id == "crimson_red"


def test_ui_theme_qss_generators():
    for tid, theme in dc.UI_THEMES.items():
        chat_qss = dc.get_chat_frame_qss(theme)
        assert "#popupFrame" in chat_qss
        assert theme.accent_color in chat_qss

        dialog_qss = dc.get_dialog_qss(theme)
        assert "QDialog" in dialog_qss
        assert theme.accent_color in dialog_qss

        tasks_qss = dc.get_tasks_dialog_qss(theme)
        assert "QDialog" in tasks_qss
        assert theme.accent_color in tasks_qss


def test_character_config_ui_theme_roundtrip(tmp_path):
    cfg = dc.CharacterConfig(ui_theme="cyberpunk_teal")
    p = tmp_path / "cfg.json"
    cfg.save(p)
    loaded = dc.CharacterConfig.load(p)
    assert loaded.ui_theme == "cyberpunk_teal"

    # Test unknown theme fallback
    bad_p = tmp_path / "bad_cfg.json"
    bad_p.write_text('{"ui_theme": "neon_rainbow_fantasy"}', encoding="utf-8")
    loaded_bad = dc.CharacterConfig.load(bad_p)
    assert loaded_bad.ui_theme == "auto"


def test_settings_dialog_ui_theme_selection():
    _get_qapp()
    cfg = dc.CharacterConfig(character_id="heatblast", ui_theme="auto")
    dlg = dc.SettingsDialog(cfg)
    try:
        assert hasattr(dlg, "_theme_combo")
        # +1 for "✨ Auto (Match Avatar: Heatblast)" item
        assert dlg._theme_combo.count() == len(dc.UI_THEMES) + 1
        assert dlg._theme_combo.currentData() == "auto"
        # Auto resolves to Heatblast's sunset_amber
        assert dlg._theme.id == "sunset_amber"

        # Change theme to neon_green
        idx = dlg._theme_combo.findData("neon_green")
        assert idx >= 0
        dlg._theme_combo.setCurrentIndex(idx)
        assert dlg._theme.id == "neon_green"

        updated = dlg.updated_config()
        assert updated.ui_theme == "neon_green"
    finally:
        dlg.deleteLater()


def test_chat_popup_and_tasks_dialog_apply_theme():
    _get_qapp()
    cfg = dc.CharacterConfig(character_id="heatblast", ui_theme="auto")
    popup = dc.ChatPopupWindow(cfg)
    tasks_dlg = dc.TasksDialog(config=cfg)
    try:
        amber_theme = dc.get_ui_theme("sunset_amber")
        popup.apply_config(cfg)
        assert popup._config.ui_theme == "auto"

        tasks_dlg.apply_config(cfg)
        assert tasks_dlg._theme.id == "sunset_amber"
        assert amber_theme.accent_color in tasks_dlg._title_lbl.styleSheet()

        # Switch to Four Arms
        cfg.character_id = "fourarms"
        cfg.ui_theme = "auto"
        popup.apply_config(cfg)
        tasks_dlg.apply_config(cfg)
        crimson_theme = dc.get_ui_theme("crimson_red")
        assert tasks_dlg._theme.id == "crimson_red"
        assert crimson_theme.accent_color in tasks_dlg._title_lbl.styleSheet()
    finally:
        popup.deleteLater()
        tasks_dlg.deleteLater()


def test_wake_greeting_and_user_bubbles_dynamic_theme_switch():
    _get_qapp()
    cfg = dc.CharacterConfig(character_id="lumi", ui_theme="auto")
    popup = dc.ChatPopupWindow(cfg)
    try:
        greeting_data = dc.build_wake_greeting_data(cfg)
        popup.show_wake_greeting(greeting_data)
        popup.add_user_message("hello there")

        assert popup._wake_card is not None
        slate_theme = dc.get_ui_theme("deep_slate")
        assert slate_theme.card_border in popup._wake_card.styleSheet()

        # Switch to Four Arms (Crimson Red)
        cfg.character_id = "fourarms"
        popup.apply_config(cfg)

        assert popup._wake_card is not None
        crimson_theme = dc.get_ui_theme("crimson_red")
        assert crimson_theme.card_border in popup._wake_card.styleSheet()
        assert crimson_theme.card_bg in popup._wake_card.styleSheet()

        # Check user message bubble dynamic recolor
        user_lbl = popup.findChild(QtWidgets.QLabel, "userMsgBubble")
        assert user_lbl is not None
        assert crimson_theme.user_bubble_start in user_lbl.styleSheet()

        # Switch to Heatblast (Sunset Amber)
        cfg.character_id = "heatblast"
        popup.apply_config(cfg)
        amber_theme = dc.get_ui_theme("sunset_amber")
        assert amber_theme.card_border in popup._wake_card.styleSheet()
        assert amber_theme.user_bubble_start in user_lbl.styleSheet()
    finally:
        popup.deleteLater()


def test_wake_greeting_close_button_and_top_position():
    _get_qapp()
    cfg = dc.CharacterConfig(character_id="lumi", ui_theme="auto")
    popup = dc.ChatPopupWindow(cfg)
    try:
        greeting_data = dc.build_wake_greeting_data(cfg)
        popup.show_wake_greeting(greeting_data)

        # 1. Wake card must be at index 0 (top of layout)
        assert popup._wake_card is not None
        assert popup._msg_layout.indexOf(popup._wake_card) == 0

        # 2. Close button exists inside wake card
        close_btn = popup._wake_card.findChild(QtWidgets.QPushButton, "wakeCloseBtn")
        assert close_btn is not None
        assert close_btn.text() == "×"

        # 3. Add user message and assistant message, wake card must remain at index 0 (top)
        popup.add_user_message("Show me sports news")
        assert popup._msg_layout.indexOf(popup._wake_card) == 0

        # 4. Clicking close button dismisses greeting card
        close_btn.click()
        assert popup._wake_card is None
        assert popup._wake_dismissed is True

        # 5. Subsequent apply_config or streaming state updates must NOT restore wake card
        popup.apply_config(cfg)
        assert popup._wake_card is None

        # 6. Next start / wake reset re-allows it to appear once
        popup.reset_wake_dismissed()
        assert popup._wake_dismissed is False
        popup.show_wake_greeting(greeting_data)
        assert popup._wake_card is not None
        assert popup._msg_layout.indexOf(popup._wake_card) == 0
    finally:
        popup.deleteLater()


def test_markdown_tables_and_horizontal_rules():
    raw_md = """AU Australia Bowling
| Bowler | Overs | Maidens | Runs | Wickets | Economy |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Spencer Johnson | 3.0 | 0 | 29 | 0 | 9.67 |
| Mahli Beardman | 0.5 | 0 | 10 | 0 | 12.00 |
---
England got off to an aggressive flyer!"""

    html_out = dc.markdown_to_qt_html(raw_md)
    assert "<table" in html_out
    assert "<th align='left'" in html_out
    assert "Bowler" in html_out
    assert "Spencer Johnson" in html_out
    assert "Mahli Beardman" in html_out
    assert "<hr style=" in html_out
    assert "England got off to an aggressive flyer!" in html_out


def test_chat_bubble_height_sync_prevents_overlap():
    app = _get_qapp()
    cfg = dc.CharacterConfig(character_id="lumi", ui_theme="auto")
    popup = dc.ChatPopupWindow(cfg)
    try:
        popup.resize(360, 520)
        popup.show()
        app.processEvents()

        # Add assistant message with 2 long paragraphs
        p1 = "First long paragraph detailing the current match situation and highlights. " * 5
        p2 = "Second long paragraph with extensive player statistics and commentary notes. " * 5
        full_msg = f"{p1}\n\n{p2}"

        popup.start_assistant_message()
        popup.finish_assistant_message(full_msg)
        app.processEvents()

        # Add user message
        popup.add_user_message("Give me the bowling scorecard")
        app.processEvents()

        # Assistant bubble is at item 1 (item 0 is system note or greeting)
        asst_w = None
        user_w = None
        for i in range(popup._msg_layout.count()):
            item = popup._msg_layout.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, QtWidgets.QTextBrowser):
                asst_w = w
            elif w and w.findChild(QtWidgets.QLabel, "userMsgBubble"):
                user_w = w

        assert asst_w is not None
        assert user_w is not None
        # User widget y must be strictly greater than assistant widget bottom (no overlap)
        assert user_w.geometry().y() >= asst_w.geometry().bottom(), (
            f"Overlap detected: user_w.y={user_w.geometry().y()} < asst_w.bottom={asst_w.geometry().bottom()}"
        )
    finally:
        popup.deleteLater()


def test_cricket_topic_prompt_and_briefing_summary(monkeypatch):
    cfg = dc.CharacterConfig(character_id="lumi")
    topic = {"id": "cricket", "label": "Cricket", "kind": "cricket", "query": "live cricket scores"}

    prompt = dc.topic_prompt_for_config(topic, cfg)
    assert "live cricket scores" in prompt

    monkeypatch.setattr(
        dc.api_tools,
        "get_live_cricket_scores",
        lambda query="": "### 🏏 Live Cricket\nAUS vs ENG: 328/10 (48.3 ov)\nInnings Break\n"
    )
    summary = dc._fetch_single_topic_summary(topic, cfg)
    assert "AUS vs ENG" in summary or "Live Cricket" in summary


def test_clean_text_for_speech():
    sample = "Hello! Check [link](https://example.com) and ```python\ncode()\n``` with | Table | Cell | and **bold** text."
    cleaned = dc.clean_text_for_speech(sample)
    assert "https://" not in cleaned
    assert "```" not in cleaned
    assert "Code snippet provided in chat." in cleaned
    assert "| Table |" not in cleaned
    assert "link" in cleaned
    assert "bold" in cleaned


def test_character_voice_profiles():
    assert "lumi" in dc.CHARACTER_VOICE_PROFILES
    assert "ben_tennyson" in dc.CHARACTER_VOICE_PROFILES
    assert "heatblast" in dc.CHARACTER_VOICE_PROFILES
    assert "gwen_classic" in dc.CHARACTER_VOICE_PROFILES
    assert "tamil_female" in dc.CHARACTER_VOICE_PROFILES
    assert "tamil_male" in dc.CHARACTER_VOICE_PROFILES

    assert dc.CHARACTER_VOICE_PROFILES["lumi"]["voice"] == "en-US-AnaNeural"
    assert dc.CHARACTER_VOICE_PROFILES["ben_tennyson"]["voice"] == "en-US-GuyNeural"
    assert dc.CHARACTER_VOICE_PROFILES["heatblast"]["voice"] == "en-US-EricNeural"
    assert dc.CHARACTER_VOICE_PROFILES["gwen_classic"]["voice"] == "en-US-JennyNeural"
    assert dc.CHARACTER_VOICE_PROFILES["tamil_female"]["voice"] == "ta-IN-PallaviNeural"
    assert dc.CHARACTER_VOICE_PROFILES["tamil_male"]["voice"] == "ta-IN-ValluvarNeural"

    # Verify voice options include Tamil Neural choices
    voice_ids = [vid for vid, _ in dc.AVAILABLE_VOICE_OPTIONS]
    assert "ta-IN-PallaviNeural" in voice_ids
    assert "ta-IN-ValluvarNeural" in voice_ids


def test_tamil_voice_resolution_and_auto_detection():
    mgr = dc.TextToSpeechManager()

    # 1. English text uses avatar's native voice
    v_eng, _, _ = mgr.resolve_voice_and_prosody("Hello, how are you today?", character_id="lumi")
    assert v_eng == "en-US-AnaNeural"

    # 2. Tamil text auto-detects Tamil script and chooses Pallavi for female/cute avatar Lumi
    v_tam_fem, _, _ = mgr.resolve_voice_and_prosody("வணக்கம்! நான் Lumi, எப்படி இருக்கீங்க?", character_id="lumi")
    assert v_tam_fem == "ta-IN-PallaviNeural"

    # 3. Tamil text auto-detects Tamil script and chooses Valluvar for male avatar Heatblast / Ben 10
    v_tam_male, _, _ = mgr.resolve_voice_and_prosody("வணக்கம் நண்பா! நான் Ben 10.", character_id="ben_tennyson")
    assert v_tam_male == "ta-IN-ValluvarNeural"

    v_tam_heatblast, _, _ = mgr.resolve_voice_and_prosody("தீப்பிழம்பு சக்தி தயாராக உள்ளது!", character_id="heatblast")
    assert v_tam_heatblast == "ta-IN-ValluvarNeural"

    # 4. Explicit Tamil voice override is preserved regardless of avatar
    v_override, _, _ = mgr.resolve_voice_and_prosody("Mixed Tanglish text", character_id="lumi", voice_override="ta-IN-ValluvarNeural")
    assert v_override == "ta-IN-ValluvarNeural"


def test_cricket_ticker_widget_creation_and_update():
    _get_qapp()
    ticker = dc.CricketTickerWidget("Lumi")
    try:
        assert ticker._title_lbl is not None
        assert ticker._score_lbl is not None
        assert ticker._status_lbl is not None

        data = {
            "match_id": "12345",
            "title": "IND vs AUS",
            "score": "IND 280/4 (45 ov)",
            "status": "In Progress · Kohli 80*",
            "state": "In Progress",
            "is_live": True,
        }
        ticker.update_data(data)
        assert "IND vs AUS" in ticker._title_lbl.text()
        assert "IND 280/4" in ticker._score_lbl.text()
        assert "Kohli 80*" in ticker._status_lbl.text()
        assert ticker._match_id == "12345"

        received = []
        ticker.score_clicked.connect(lambda mid, title: received.append((mid, title)))
        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(10, 10),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        ticker.mouseReleaseEvent(event)
        assert len(received) == 1
        assert received[0] == ("12345", "IND vs AUS")
    finally:
        ticker.deleteLater()


def test_chat_popup_voice_toggle_button():
    _get_qapp()
    cfg = dc.CharacterConfig(tts_enabled=True)
    popup = dc.ChatPopupWindow(cfg)
    try:
        assert hasattr(popup, "_voice_btn")
        assert popup._voice_btn.isChecked() is True
        assert popup._voice_btn.text() == "🔊"

        toggled = []
        popup.voice_toggled.connect(lambda val: toggled.append(val))
        popup._voice_btn.toggle()
        assert popup._voice_btn.isChecked() is False
        assert popup._voice_btn.text() == "🔇"
        assert toggled == [False]
    finally:
        popup.deleteLater()


def test_companion_cricket_ticker_data_and_toggle():
    app = _get_qapp()
    cfg = dc.CharacterConfig(cricket_ticker_enabled=True)
    companion = dc.DesktopCompanionApp(app, cfg)
    try:
        companion.show_character()
        assert companion.cricket_ticker.isVisible() is True

        # Test emitting data update through signal with multiple matches
        test_data = {
            "match_id": "9999",
            "title": "IND vs ENG",
            "score": "IND 150/2 (18 ov)",
            "status": "Rohit 75*",
            "is_live": True,
            "available_matches": [
                {
                    "match_id": "9999",
                    "title": "IND vs ENG",
                    "score": "IND 150/2 (18 ov)",
                    "status": "Rohit 75*",
                    "is_live": True,
                },
                {
                    "match_id": "8888",
                    "title": "AUS vs SA",
                    "score": "AUS 220/4 (35 ov)",
                    "status": "Smith 88*",
                    "is_live": True,
                },
            ],
            "total_matches": 2,
            "current_index": 0,
        }
        companion._cricket_ticker_data_ready.emit(test_data)
        app.processEvents()

        assert "IND vs ENG" in companion.cricket_ticker._title_lbl.text()
        assert "IND 150/2" in companion.cricket_ticker._score_lbl.text()
        assert companion.cricket_ticker._idx_lbl.text() == "1/2"

        # Test switching to next match
        companion.cricket_ticker._select_next_match()
        assert "AUS vs SA" in companion.cricket_ticker._title_lbl.text()
        assert "AUS 220/4" in companion.cricket_ticker._score_lbl.text()
        assert companion.cricket_ticker._match_id == "8888"
        assert companion.cricket_ticker._idx_lbl.text() == "2/2"

        # Test switching to previous match
        companion.cricket_ticker._select_previous_match()
        assert "IND vs ENG" in companion.cricket_ticker._title_lbl.text()
        assert companion.cricket_ticker._match_id == "9999"

        # Test toggle off
        companion.toggle_cricket_ticker(False)
        assert companion.cricket_ticker.isVisible() is False

        # Test toggle on
        companion.toggle_cricket_ticker(True)
        assert companion.cricket_ticker.isVisible() is True
    finally:
        companion.quit_app()


def test_character_config_memory_and_history_fields(tmp_path: Path):
    cfg_file = tmp_path / "test_cfg.json"
    cfg = dc.CharacterConfig(
        persist_chat_history=True,
        max_saved_history_messages=75,
        enable_long_term_memory=True,
        companion_memories=["Likes Python", "Lives in Chennai"],
    )
    cfg.save(cfg_file)
    assert cfg_file.is_file()

    loaded = dc.CharacterConfig.load(cfg_file)
    assert loaded.persist_chat_history is True
    assert loaded.max_saved_history_messages == 75
    assert loaded.enable_long_term_memory is True
    assert "Likes Python" in loaded.companion_memories
    assert "Lives in Chennai" in loaded.companion_memories


def test_build_effective_system_prompt_with_memories():
    prompt = dc.build_effective_system_prompt(
        "Lumi",
        "Cheerful pet",
        use_tools=True,
        memories=["User prefers dark theme", "User is an AI researcher"],
        enable_long_term_memory=True,
    )
    assert "[Persistent Long-Term Memory & User Facts]:" in prompt
    assert "User prefers dark theme" in prompt
    assert "User is an AI researcher" in prompt
    assert "remember_user_fact" in prompt

    disabled_prompt = dc.build_effective_system_prompt(
        "Lumi",
        "Cheerful pet",
        use_tools=True,
        memories=["User prefers dark theme"],
        enable_long_term_memory=False,
    )
    assert "[Persistent Long-Term Memory & User Facts]:" not in disabled_prompt


def test_chat_popup_add_assistant_message():
    _get_qapp()
    cfg = dc.CharacterConfig()
    popup = dc.ChatPopupWindow(cfg)
    try:
        popup.add_user_message("Hello Lumi!")
        popup.add_assistant_message("Hello there! Welcome back.")
        # Message layout contains stretch + user wrap + assistant browser
        assert popup._msg_layout.count() >= 2
    finally:
        popup.deleteLater()


def test_chat_history_persistence_and_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app = _get_qapp()
    hist_file = tmp_path / "chat_history.json"
    monkeypatch.setattr(dc, "_resolve_history_file", lambda: hist_file)

    cfg = dc.CharacterConfig(persist_chat_history=True, max_saved_history_messages=50)
    companion = dc.DesktopCompanionApp(app, cfg)
    try:
        # Populate bot history
        companion._bot.history.append(dc.chatbot.Message(role="user", content="What is the weather today?"))
        companion._bot.history.append(dc.chatbot.Message(role="assistant", content="The weather in Chennai is 28°C and partly cloudy."))
        companion._save_chat_history()

        assert hist_file.is_file()
        saved_data = json.loads(hist_file.read_text(encoding="utf-8"))
        assert len(saved_data) == 2
        assert saved_data[0]["role"] == "user"
        assert saved_data[0]["content"] == "What is the weather today?"
        assert saved_data[1]["role"] == "assistant"
        assert "28°C" in saved_data[1]["content"]

        # Clear memory in companion to simulate clean restart
        companion._bot.reset_history()
        companion.popup.clear_messages()
        assert len(companion._bot.history) == 0

        # Load chat history from disk
        companion._load_chat_history()
        assert len(companion._bot.history) == 2
        assert companion._bot.history[0].content == "What is the weather today?"
        assert "28°C" in companion._bot.history[1].content

        # Test clear_conversation resets history on disk
        companion.clear_conversation()
        assert len(companion._bot.history) == 0
        cleared_file_data = json.loads(hist_file.read_text(encoding="utf-8"))
        assert cleared_file_data == []
    finally:
        companion.quit_app()


def test_settings_dialog_memory_tab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _get_qapp()
    mem_file = tmp_path / "companion_memories.json"
    import memory_manager
    monkeypatch.setattr(memory_manager, "get_memories_path", lambda custom_path=None: mem_file)

    cfg = dc.CharacterConfig()
    dlg = dc.SettingsDialog(cfg)
    try:
        assert dlg._tabs.count() == 6
        assert "Memory" in dlg._tabs.tabText(5)

        # Test adding manual memory
        dlg._new_memory_edit.setText("User likes chocolate ice cream")
        dlg._add_manual_memory()
        assert "User likes chocolate ice cream" in dlg._memories_draft
        assert dlg._mem_count_label.text() == "Total remembered facts: 1"

        # Test deleting single memory
        dlg._delete_single_memory("User likes chocolate ice cream")
        assert len(dlg._memories_draft) == 0
        assert dlg._mem_count_label.text() == "Total remembered facts: 0"
    finally:
        dlg.deleteLater()


def test_clean_text_for_speech_does_not_truncate():
    # Long text of 800+ chars with multiple sentences and markdown
    paragraphs = [
        "First sentence explaining artificial intelligence and companion architecture.",
        "Second sentence detailing system tools, file system operations, and prompt engineering.",
        "Third sentence reviewing real-time sports tickers, pomodoro timers, and calendar scheduling.",
        "Fourth sentence validating neural text-to-speech synthesis without arbitrary character cut-offs.",
        "Fifth sentence ensuring complete and uninterrupted spoken audio playback for the user.",
    ]
    raw_markdown = "\n\n".join(paragraphs)
    assert len(raw_markdown) > 400
    cleaned = dc.clean_text_for_speech(raw_markdown)
    # Ensure it wasn't cut off at ~360 chars
    assert len(cleaned) > 360
    assert "First sentence" in cleaned
    assert "Fifth sentence ensuring complete and uninterrupted spoken audio playback" in cleaned


def test_chat_popup_narrate_action_bar():
    _get_qapp()
    cfg = dc.CharacterConfig()
    popup = dc.ChatPopupWindow(cfg)
    try:
        received = []
        popup.narrate_requested.connect(lambda txt, btn: received.append((txt, btn)))

        # Test add_assistant_message generates action bar with narrate button
        popup.add_assistant_message("Here is the generated answer for you.")
        # Find QPushButton in layout
        narrate_btns = [
            b for b in popup.findChildren(QtWidgets.QPushButton) if "Narrate" in b.text()
        ]
        assert len(narrate_btns) >= 1
        btn = narrate_btns[-1]
        assert "Narrate" in btn.text()

        # Click the button and check signal emission
        btn.click()
        assert len(received) == 1
        assert received[0][0] == "Here is the generated answer for you."
        assert received[0][1] is btn
    finally:
        popup.deleteLater()


def test_companion_narration_decision_and_controls():
    app = _get_qapp()
    cfg = dc.CharacterConfig(tts_enabled=True, tts_auto_narrate=False)
    companion = dc.DesktopCompanionApp(app, cfg)
    try:
        spoken_calls = []
        stopped_calls = []

        class MockTTSManager:
            def __init__(self):
                self._speaking = False

            def speak(self, text, **kwargs):
                spoken_calls.append(text)
                self._speaking = True
                if "on_started" in kwargs and kwargs["on_started"]:
                    kwargs["on_started"]()

            def stop(self):
                stopped_calls.append(True)
                self._speaking = False

            def is_speaking(self):
                return self._speaking

        mock_tts = MockTTSManager()
        companion._tts_manager = mock_tts

        # 1. Normal turn without prompt requesting narration -> must NOT auto-narrate
        companion.popup.clear_messages()
        companion._prompt_requested_narration = False
        companion._on_worker_finished("This is a standard answer that should NOT auto-speak.")
        assert len(spoken_calls) == 0

        # 2. Turn where user explicitly asked to narrate -> DOES speak
        companion.send_user_message("Please narrate this response to me")
        assert companion._prompt_requested_narration is True
        companion._on_worker_finished("This response was requested to be read aloud.")
        assert len(spoken_calls) == 1
        assert "requested to be read aloud" in spoken_calls[0]

        # 3. On-demand click of Narrate button -> speaks completely and updates button
        btn = QtWidgets.QPushButton("🔊 Narrate")
        companion._on_narrate_requested("Complete custom text to read.", btn)
        assert len(spoken_calls) == 2
        assert spoken_calls[1] == "Complete custom text to read."
        assert btn.text() == "⏹ Stop"

        # 4. Clicking the Stop button while speaking stops narration and resets button
        companion._on_narrate_requested("Complete custom text to read.", btn)
        assert len(stopped_calls) >= 1
        assert btn.text() == "🔊 Narrate"

        # 5. Config with tts_auto_narrate=True -> auto-speaks
        companion._config.tts_auto_narrate = True
        companion._on_worker_finished("Auto narrate is enabled so speak this.")
        assert len(spoken_calls) == 3
        assert "Auto narrate is enabled" in spoken_calls[2]
    finally:
        companion.quit_app()








