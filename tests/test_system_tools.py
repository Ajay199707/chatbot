"""Tests for system_tools.py and chatbot integration for local PC & file control."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chatbot  # noqa: E402
import system_tools  # noqa: E402


def _make_policy(tmp_path: Path, **overrides) -> system_tools.SystemToolsPolicy:
    defaults = dict(
        enabled=True,
        allowed_roots=[tmp_path],
        allow_all_non_system=False,
        confirm_destructive=True,
        confirm_app_launch=True,
    )
    defaults.update(overrides)
    return system_tools.SystemToolsPolicy(**defaults)


def test_path_guardrails_block_outside_roots_and_sensitive_paths(tmp_path):
    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("nope", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=123", encoding="utf-8")
    git_cfg = tmp_path / ".git" / "config"
    git_cfg.parent.mkdir()
    git_cfg.write_text("[core]", encoding="utf-8")

    policy = _make_policy(tmp_path, confirm_callback=lambda *_: True)

    try:
        # Outside allowed root & parent traversal escape
        res_out = system_tools.read_text_file(str(outside), policy=policy)
        assert "outside allowed folders" in res_out.lower()

        res_trav = system_tools.read_text_file(str(tmp_path / ".." / outside.name), policy=policy)
        assert "outside allowed folders" in res_trav.lower()

        # Hard-blocked .env and .git inside allowed root
        res_env = system_tools.read_text_file(str(env_file), policy=policy)
        assert "access denied" in res_env.lower()

        res_git = system_tools.read_text_file(str(git_cfg), policy=policy)
        assert "access denied" in res_git.lower()

        # Hard-blocked Windows OS folder even with allow_all_non_system=True
        broad_policy = _make_policy(tmp_path, allow_all_non_system=True)
        win_sys = system_tools.read_text_file(r"C:\Windows\System32\drivers\etc\hosts", policy=broad_policy)
        assert "access denied" in win_sys.lower()

        # Cannot delete configured allowed root itself
        res_root_del = system_tools.delete_item(str(tmp_path), policy=policy)
        assert "refusing destructive action" in res_root_del.lower()
    finally:
        if outside.exists():
            outside.unlink()


def test_search_list_and_read_text_file(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    todo = notes / "project_todo.txt"
    todo.write_text("line 1\nline 2", encoding="utf-8")
    (notes / ".env").write_text("TOKEN=hidden", encoding="utf-8")
    raw_bin = notes / "photo.bin"
    raw_bin.write_bytes(b"\x00\x01\x02\x03binary")

    policy = _make_policy(tmp_path)

    # List roots when empty path is supplied
    roots_out = system_tools.list_directory("", policy=policy)
    assert str(tmp_path.resolve()) in roots_out

    # List directory skips hidden/hard-blocked .env
    list_out = system_tools.list_directory(str(notes), policy=policy)
    assert "project_todo.txt" in list_out
    assert ".env" not in list_out

    # Search files by wildcard & substring
    search_out = system_tools.search_files("*.txt", directory=str(tmp_path), policy=policy)
    assert str(todo.resolve()) in search_out

    # Read text vs binary
    txt_out = system_tools.read_text_file(str(todo), policy=policy)
    assert "line 1" in txt_out and "line 2" in txt_out

    bin_out = system_tools.read_text_file(str(raw_bin), policy=policy)
    assert "binary" in bin_out.lower()


def test_create_item_and_overwrite_confirmation(tmp_path):
    prompts = []

    def deny_cb(title, detail, risk):
        prompts.append((title, risk))
        return False

    def allow_cb(title, detail, risk):
        prompts.append((title, risk))
        return True

    target_dir = tmp_path / "sub" / "folder"
    policy_deny = _make_policy(tmp_path, confirm_callback=deny_cb)
    assert "Created directory" in system_tools.create_item(str(target_dir), is_directory=True, policy=policy_deny)
    assert target_dir.is_dir()

    target_file = target_dir / "hello.txt"
    assert "Created file" in system_tools.create_item(str(target_file), content="v1", policy=policy_deny)
    assert target_file.read_text(encoding="utf-8") == "v1"

    # Overwrite asks confirmation and aborts on Deny
    res_denied = system_tools.create_item(str(target_file), content="v2", policy=policy_deny)
    assert "Cancelled by user" in res_denied
    assert target_file.read_text(encoding="utf-8") == "v1"
    assert prompts[-1][1] == "overwrite"

    # Overwrite succeeds on Allow
    policy_allow = _make_policy(tmp_path, confirm_callback=allow_cb)
    res_ok = system_tools.create_item(str(target_file), content="v2", policy=policy_allow)
    assert "Created file" in res_ok
    assert target_file.read_text(encoding="utf-8") == "v2"


def test_copy_and_move_with_confirmation(tmp_path):
    src = tmp_path / "draft.txt"
    src.write_text("hello copy", encoding="utf-8")
    dest_dir = tmp_path / "archive"
    dest_dir.mkdir()

    # Copy into existing directory needs no confirmation when target does not exist
    policy_deny = _make_policy(tmp_path, confirm_callback=lambda *_: False)
    copy_res = system_tools.copy_or_move(str(src), str(dest_dir), mode="copy", policy=policy_deny)
    assert "Copied" in copy_res
    copied = dest_dir / "draft.txt"
    assert copied.read_text(encoding="utf-8") == "hello copy"

    # Move requires confirmation -> Deny aborts
    moved_target = dest_dir / "renamed.txt"
    move_denied = system_tools.copy_or_move(str(src), str(moved_target), mode="move", policy=policy_deny)
    assert "Cancelled by user" in move_denied
    assert src.exists()
    assert not moved_target.exists()

    # Move -> Allow succeeds
    risks = []
    policy_allow = _make_policy(
        tmp_path,
        confirm_callback=lambda t, d, r: (risks.append(r) or True),
    )
    move_ok = system_tools.copy_or_move(str(src), str(moved_target), mode="move", policy=policy_allow)
    assert "Moved" in move_ok
    assert not src.exists()
    assert moved_target.read_text(encoding="utf-8") == "hello copy"
    assert risks == ["destructive"]


def test_delete_item_confirmation_and_recycle_hook(tmp_path):
    victim = tmp_path / "old_report.txt"
    victim.write_text("dispose", encoding="utf-8")
    recycled = []

    def fake_recycle(path: Path):
        recycled.append(path)
        path.unlink()
        return True, f"Moved to Recycle Bin: {path}"

    policy_deny = _make_policy(
        tmp_path,
        confirm_callback=lambda *_: False,
        recycle_fn=fake_recycle,
    )
    res_deny = system_tools.delete_item(str(victim), policy=policy_deny)
    assert "Cancelled by user" in res_deny
    assert victim.exists()
    assert recycled == []

    risks = []
    policy_allow = _make_policy(
        tmp_path,
        confirm_callback=lambda t, d, r: (risks.append(r) or True),
        recycle_fn=fake_recycle,
    )
    res_ok = system_tools.delete_item(str(victim), policy=policy_allow)
    assert "Recycle Bin" in res_ok
    assert not victim.exists()
    assert recycled == [victim.resolve()]
    assert risks == ["destructive"]


def test_win32_recycle_bin_struct_on_temp_file(tmp_path):
    if sys.platform != "win32":
        return
    trash_me = tmp_path / "systools_recycle_smoke.tmp"
    trash_me.write_text("safe throwaway", encoding="utf-8")
    ok, msg = system_tools._send_to_recycle_bin_win32(trash_me.resolve())
    assert ok is True, msg
    assert "Recycle Bin" in msg
    assert not trash_me.exists()


def test_clipboard_action_validates_paths_and_delegates(tmp_path):
    good = tmp_path / "clip.txt"
    good.write_text("data", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("K=V", encoding="utf-8")

    calls = []
    policy = _make_policy(
        tmp_path,
        clipboard_callback=lambda action, text, paths: (calls.append((action, text, paths)) or "CLIP_OK"),
    )

    assert system_tools.clipboard_action("set", text="hello", policy=policy) == "CLIP_OK"
    assert system_tools.clipboard_action("get", policy=policy) == "CLIP_OK"
    assert system_tools.clipboard_action("copy_files", paths=[str(good)], policy=policy) == "CLIP_OK"
    assert calls[-1] == ("copy_files", "", [str(good.resolve())])

    # Blocked path rejected before invoking callback
    bad_res = system_tools.clipboard_action("copy_files", paths=[str(env_file)], policy=policy)
    assert "Error:" in bad_res


def test_launch_app_or_file_resolves_alias_and_enforces_confirmation(tmp_path):
    doc = tmp_path / "readme.txt"
    doc.write_text("hello", encoding="utf-8")
    launched = []

    def fake_launch(target: str, args: str):
        launched.append((target, args))
        return True, f"Opened: {target}"

    # Built-in Windows alias resolves and prompts before launch
    policy_deny = _make_policy(
        tmp_path,
        confirm_callback=lambda *_: False,
        launch_fn=fake_launch,
    )
    res_deny = system_tools.launch_app_or_file("notepad", policy=policy_deny)
    assert "Cancelled by user" in res_deny
    assert launched == []

    policy_allow = _make_policy(
        tmp_path,
        confirm_callback=lambda *_: True,
        launch_fn=fake_launch,
    )
    res_ok = system_tools.launch_app_or_file("notepad", policy=policy_allow)
    assert "Opened: notepad.exe" in res_ok
    assert launched == [("notepad.exe", "")]

    # When confirm_app_launch=False, non-executable document launches without prompt,
    # whereas executables still enforce confirmation
    launched.clear()
    policy_no_prompt_docs = _make_policy(
        tmp_path,
        confirm_app_launch=False,
        confirm_callback=None,
        launch_fn=fake_launch,
    )
    res_doc = system_tools.launch_app_or_file(str(doc), policy=policy_no_prompt_docs)
    assert "Opened:" in res_doc
    assert launched and launched[0][0] == str(doc.resolve())

    res_exe_denied = system_tools.launch_app_or_file("notepad", policy=policy_no_prompt_docs)
    assert "Confirmation required" in res_exe_denied


def test_chatbot_schemas_and_execute_tool_respect_system_policy(tmp_path):
    base_openai = [t["function"]["name"] for t in chatbot.build_openai_tools(include_system=False)]
    all_openai = [t["function"]["name"] for t in chatbot.build_openai_tools(include_system=True)]
    assert "search_files" not in base_openai
    assert "search_files" in all_openai
    assert "launch_app_or_file" in all_openai

    gemini_decls = chatbot.build_gemini_tools(include_system=True)[0]["functionDeclarations"]
    clip_decl = next(d for d in gemini_decls if d["name"] == "clipboard_action")
    paths_schema = clip_decl["parameters"]["properties"]["paths"]
    assert paths_schema["type"] == "ARRAY"
    assert paths_schema["items"]["type"] == "STRING"

    # Disabled policy refuses system tool
    disabled_policy = _make_policy(tmp_path, enabled=False)
    refused = chatbot.execute_tool("list_directory", {}, system_policy=disabled_policy)
    assert "disabled" in refused.lower()

    # Enabled policy executes system tool and reports counts
    sample = tmp_path / "item.txt"
    sample.write_text("ok", encoding="utf-8")
    enabled_policy = _make_policy(tmp_path, enabled=True)
    listed = chatbot.execute_tool("list_directory", {"path": str(tmp_path)}, system_policy=enabled_policy)
    assert "item.txt" in listed
    assert "1 file(s), 0 folder(s), 1 total" in listed


def test_system_tools_work_with_web_tools_disabled_and_mock_mode(monkeypatch, tmp_path):
    # Only system tools enabled, web tools disabled
    sys_only_openai = [
        t["function"]["name"]
        for t in chatbot.build_openai_tools(include_system=True, include_web=False)
    ]
    assert "list_directory" in sys_only_openai
    assert "web_search" not in sys_only_openai

    sys_only_gemini = [
        d["name"]
        for d in chatbot.build_gemini_tools(include_system=True, include_web=False)[0]["functionDeclarations"]
    ]
    assert "search_files" in sys_only_gemini
    assert "web_search" not in sys_only_gemini

    # Singular 'download' alias maps to Home/Downloads when resolved
    downloads_dir = tmp_path / "Downloads"
    downloads_dir.mkdir()
    (downloads_dir / "a.txt").write_text("1", encoding="utf-8")
    (downloads_dir / "b.txt").write_text("2", encoding="utf-8")
    monkeypatch.setattr(system_tools.Path, "home", classmethod(lambda cls: tmp_path))

    policy = _make_policy(downloads_dir)
    bot = chatbot.Chatbot(
        chatbot.ChatbotConfig(
            provider="mock",
            use_tools=False,
            enable_system_tools=True,
            system_policy=policy,
        )
    )
    events = list(bot.stream_turn("how many files are in the download folder"))
    tool_ends = [e for e in events if e["type"] == "tool_end"]
    assert tool_ends and tool_ends[0]["name"] == "list_directory"
    assert "2 file(s)" in tool_ends[0]["result"]


def test_list_recycle_bin_and_directory_delegation(tmp_path):
    disabled = _make_policy(tmp_path, enabled=False)
    assert "disabled" in system_tools.list_recycle_bin(policy=disabled).lower()

    empty_policy = system_tools.SystemToolsPolicy(
        enabled=True,
        allowed_roots=[tmp_path],
        recycle_list_fn=lambda limit: (0, []),
    )
    assert system_tools.list_recycle_bin(policy=empty_policy) == "Recycle Bin is empty."

    sample_items = [
        {
            "name": "old_notes.txt",
            "orig": r"C:\Users\KF0052\Desktop",
            "deleted": "\u200e11/10/2026 \u200f10:30 AM",
            "size": 2048,
            "is_dir": False,
        },
        {
            "name": "Archive",
            "orig": r"C:\Users\KF0052\Documents",
            "deleted": "11/09/2026",
            "size": 0,
            "is_dir": True,
        },
    ]
    populated = system_tools.SystemToolsPolicy(
        enabled=True,
        allowed_roots=[tmp_path],
        recycle_list_fn=lambda limit: (3, sample_items[:limit]),
    )
    out = system_tools.list_recycle_bin(max_items=2, policy=populated)
    assert "Recycle Bin contains 3 item(s) (showing first 2):" in out
    assert "[FILE] old_notes.txt" in out
    assert "2.0 KB" in out
    assert r"from: C:\Users\KF0052\Desktop" in out
    assert "deleted: 11/10/2026 10:30 AM" in out
    assert "\u200e" not in out and "\u200f" not in out
    assert "[DIR]  Archive  (folder" in out

    # list_directory delegates virtual Recycle Bin queries to list_recycle_bin
    for alias in ("recyclebin", "Recycle Bin", "$Recycle.Bin", "trash"):
        delegated = system_tools.list_directory(alias, policy=populated)
        assert "old_notes.txt" in delegated

    # Exposed to both tool schemas and executable via Mock Mode
    assert "list_recycle_bin" in {
        t["function"]["name"]
        for t in chatbot.build_openai_tools(include_system=True, include_web=False)
    }
    assert "list_recycle_bin" in {
        d["name"]
        for d in chatbot.build_gemini_tools(include_system=True, include_web=False)[0]["functionDeclarations"]
    }

    bot = chatbot.Chatbot(
        chatbot.ChatbotConfig(
            provider="mock",
            use_tools=False,
            enable_system_tools=True,
            system_policy=populated,
        )
    )
    events = list(bot.stream_turn("show the file names in the recyclebin"))
    tool_ends = [e for e in events if e["type"] == "tool_end"]
    assert tool_ends and tool_ends[0]["name"] == "list_recycle_bin"
    assert "old_notes.txt" in tool_ends[0]["result"]


def test_win32_shell_list_recycle_bin_read_only_smoke():
    if sys.platform != "win32":
        return
    total, items = system_tools._list_recycle_bin_win32(max_items=5)
    assert isinstance(total, int) and total >= 0
    assert isinstance(items, list)


def test_list_drives_and_all_drive_control(tmp_path, monkeypatch):
    drive_c = tmp_path / "drive_c"
    drive_k = tmp_path / "drive_k"
    drive_c.mkdir()
    drive_k.mkdir()
    nested = drive_k / "projects" / "alpha_notes.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("cross-drive content", encoding="utf-8")

    fake_drives = [
        {"root": str(drive_c), "type": "Fixed", "ready": True, "free_bytes": 10 * 1024**3, "total_bytes": 100 * 1024**3},
        {"root": str(drive_k), "type": "Fixed", "ready": True, "free_bytes": 50 * 1024**3, "total_bytes": 200 * 1024**3},
    ]

    policy_off = _make_policy(tmp_path, enabled=False, drives_fn=lambda: fake_drives)
    assert "disabled" in system_tools.list_drives(policy=policy_off).lower()

    policy_all = system_tools.SystemToolsPolicy(
        enabled=True,
        allowed_roots=[drive_c],
        allow_all_non_system=True,
        confirm_destructive=True,
        confirm_app_launch=False,
        confirm_callback=lambda *_: True,
        drives_fn=lambda: fake_drives,
    )
    drives_out = system_tools.list_drives(policy=policy_all)
    assert str(drive_c) in drives_out and str(drive_k) in drives_out
    assert "All-Drive Control: ON" in drives_out

    # Empty list_directory shows both roots and drives; 'drives' delegates to list_drives
    root_view = system_tools.list_directory("", policy=policy_all)
    assert "Available drives:" in root_view and str(drive_k) in root_view
    assert "Available drives:" in system_tools.list_directory("drives", policy=policy_all)

    # Search with empty directory scans across all ready drives in drives_fn when allow_all_non_system=True
    found = system_tools.search_files("alpha_notes.txt", policy=policy_all)
    assert str(nested.resolve()) in found

    # Cross-drive create, copy, move work; drive anchor root deletion stays refused
    new_on_k = drive_k / "created_from_agent" / "note.txt"
    assert "Created file" in system_tools.create_item(str(new_on_k), content="ok", policy=policy_all)
    copied_to_c = drive_c / "copied.txt"
    assert "Copied" in system_tools.copy_or_move(str(new_on_k), str(copied_to_c), mode="copy", policy=policy_all)
    assert copied_to_c.read_text(encoding="utf-8") == "ok"

    # Bare drive normalization e.g. 'K:', 'K drive', 'drive K'
    assert system_tools._resolve_user_path("K:", policy_all) == system_tools.Path("K:\\").resolve(strict=False)
    assert system_tools._resolve_user_path("k drive", policy_all) == system_tools.Path("K:\\").resolve(strict=False)
    assert system_tools._resolve_user_path("drive D", policy_all) == system_tools.Path("D:\\").resolve(strict=False)

    # Deleting raw drive anchor like 'C:\\' or 'K:' is strictly refused even in All-Drive mode
    assert "refusing destructive action" in system_tools.delete_item("C:\\", policy=policy_all).lower()
    assert "refusing destructive action" in system_tools.delete_item("K:", policy=policy_all).lower()

    # Schema & Mock Mode recognize list_drives and drive queries
    assert "list_drives" in {
        t["function"]["name"]
        for t in chatbot.build_openai_tools(include_system=True, include_web=False)
    }
    bot = chatbot.Chatbot(
        chatbot.ChatbotConfig(
            provider="mock",
            use_tools=False,
            enable_system_tools=True,
            system_policy=policy_all,
        )
    )
    events = list(bot.stream_turn("show all drives on this pc"))
    tool_ends = [e for e in events if e["type"] == "tool_end"]
    assert tool_ends and tool_ends[0]["name"] == "list_drives"
    assert str(drive_k) in tool_ends[0]["result"]

    if sys.platform == "win32":
        import os

        real_drives = system_tools.get_available_drives()
        roots_upper = {d["root"].upper() for d in real_drives}
        assert any(r.startswith("C:") for r in roots_upper)
        if os.path.exists("K:\\"):
            assert any(r.startswith("K:") for r in roots_upper)


def test_get_folder_size_ranks_subfolders_and_skips_protected(tmp_path):
    large_dir = tmp_path / "large_dir"
    small_dir = tmp_path / "small_dir"
    git_dir = tmp_path / ".git"
    (large_dir / "nested").mkdir(parents=True)
    small_dir.mkdir()
    git_dir.mkdir()

    (large_dir / "nested" / "big.bin").write_bytes(b"x" * 6000)
    (small_dir / "tiny.txt").write_bytes(b"y" * 200)
    (git_dir / "objects.pack").write_bytes(b"z" * 99999)  # protected; must be skipped
    (tmp_path / "root.dat").write_bytes(b"r" * 400)

    policy = _make_policy(tmp_path)
    out = system_tools.get_folder_size(str(tmp_path), policy=policy)
    assert "6.4 KB" in out  # 6000 + 200 + 400 = 6600 bytes -> 6.4 KB
    assert large_dir.name in out and small_dir.name in out
    assert out.index("large_dir") < out.index("small_dir")
    assert "Skipped protected" in out and ".git" in out

    # Empty path reports allowed root totals
    roots_out = system_tools.get_folder_size("", policy=policy)
    assert str(tmp_path.resolve()) in roots_out

    # Schema & Mock Mode storage query
    assert "get_folder_size" in {
        t["function"]["name"]
        for t in chatbot.build_openai_tools(include_system=True, include_web=False)
    }
    bot = chatbot.Chatbot(
        chatbot.ChatbotConfig(
            provider="mock",
            use_tools=False,
            enable_system_tools=True,
            system_policy=policy,
        )
    )
    events = list(bot.stream_turn("which folder occupies more storage"))
    tool_ends = [e for e in events if e["type"] == "tool_end"]
    assert tool_ends and tool_ends[0]["name"] == "get_folder_size"


def test_list_running_apps_and_close_app_confirmation_and_guardrails(tmp_path):
    import os

    sample_procs = [
        {"name": "svchost.exe", "pid": 800, "mem": "20,000 K", "title": ""},
        {"name": "explorer.exe", "pid": 1400, "mem": "90,000 K", "title": "Program Manager"},
        {"name": "AICompanion.exe", "pid": os.getpid(), "mem": "80,000 K", "title": "Lumi"},
        {"name": "pythonw.exe", "pid": 4321, "mem": "250,000 K", "title": "Spyder (Python 3.11)"},
        {"name": "pythonw.exe", "pid": 4399, "mem": "30,000 K", "title": "Other Worker"},
        {"name": "notepad.exe", "pid": 5555, "mem": "12,000 K", "title": "Untitled - Notepad"},
    ]
    closed_calls = []

    def fake_close(pids, force):
        closed_calls.append((list(pids), force))
        return True, f"Terminated PIDs {pids}"

    # 1. list_running_apps hides protected OS/self processes
    policy_deny = system_tools.SystemToolsPolicy(
        enabled=True,
        allowed_roots=[tmp_path],
        confirm_app_launch=False,
        confirm_callback=lambda *_: False,
        list_processes_fn=lambda: sample_procs,
        close_process_fn=fake_close,
    )
    apps_out = system_tools.list_running_apps(policy=policy_deny)
    assert "Spyder (Python 3.11)" in apps_out
    assert "notepad.exe" in apps_out
    assert "svchost.exe" not in apps_out
    assert f"PID {os.getpid()}" not in apps_out

    # 2. Protected OS processes & self-PID cannot be closed even if allowed
    policy_allow = system_tools.SystemToolsPolicy(
        enabled=True,
        allowed_roots=[tmp_path],
        confirm_app_launch=False,
        confirm_callback=lambda *_: True,
        list_processes_fn=lambda: sample_procs,
        close_process_fn=fake_close,
    )
    assert "refusing" in system_tools.close_app("svchost", policy=policy_allow).lower()
    assert "refusing" in system_tools.close_app("explorer", policy=policy_allow).lower()
    assert "refusing" in system_tools.close_app(str(os.getpid()), policy=policy_allow).lower()
    assert closed_calls == []

    # 3. Close by Deny cancels safely
    res_deny = system_tools.close_app("spyder", policy=policy_deny)
    assert "Cancelled by user" in res_deny
    assert closed_calls == []

    # 4. Close 'spyder' matches ONLY PID 4321 via window title (not unrelated pythonw 4399)
    #    and enforces confirmation even when confirm_app_launch=False
    prompts = []
    policy_confirm_spyder = system_tools.SystemToolsPolicy(
        enabled=True,
        allowed_roots=[tmp_path],
        confirm_app_launch=False,
        confirm_callback=lambda t, d, r: (prompts.append((t, d, r)) or True),
        list_processes_fn=lambda: sample_procs,
        close_process_fn=fake_close,
    )
    res_ok = system_tools.close_app("spyder", policy=policy_confirm_spyder)
    assert "Closed 'spyder'" in res_ok
    assert closed_calls == [([4321], False)]
    assert prompts and prompts[-1][2] == "destructive" and "Spyder" in prompts[-1][1]

    # 5. Force close passes force=True and alias 'notepad' resolves cleanly
    res_force = system_tools.close_app("notepad", force=True, policy=policy_confirm_spyder)
    assert "Closed 'notepad'" in res_force
    assert closed_calls[-1] == ([5555], True)

    # 6. Exposed in OpenAI + Gemini tool declarations and Mock Mode
    assert {"list_running_apps", "close_app"}.issubset({
        t["function"]["name"]
        for t in chatbot.build_openai_tools(include_system=True, include_web=False)
    })
    assert {"list_running_apps", "close_app"}.issubset({
        d["name"]
        for d in chatbot.build_gemini_tools(include_system=True, include_web=False)[0]["functionDeclarations"]
    })

    bot = chatbot.Chatbot(
        chatbot.ChatbotConfig(
            provider="mock",
            use_tools=False,
            enable_system_tools=True,
            system_policy=policy_confirm_spyder,
        )
    )
    events = list(bot.stream_turn("please close spyder"))
    tool_ends = [e for e in events if e["type"] == "tool_end"]
    assert tool_ends and tool_ends[0]["name"] == "close_app"
    assert closed_calls[-1] == ([4321], False)

    if sys.platform == "win32":
        real_procs = system_tools._list_running_processes_win32()
        assert isinstance(real_procs, list) and len(real_procs) > 5
