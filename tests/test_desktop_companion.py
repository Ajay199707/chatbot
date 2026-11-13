"""Tests for desktop_companion.py (config, Markdown rendering, sprite loading, PySide6 UI)."""

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
        assert dlg._tabs.count() == 5
        tab_labels = [dlg._tabs.tabText(i).replace("&&", "&") for i in range(dlg._tabs.count())]
        assert tab_labels == ["Character", "AI & API Keys", "PC & Files", "APIs & Tools", "Wake-Up & Topics"]
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
    assert labels == ["Tech Field", "Cinema", "Gold Rate", "Weather", "Top News"]
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

