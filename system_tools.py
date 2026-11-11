"""Local system, filesystem, Windows Recycle Bin, clipboard, and app-control tools.

All operations pass through SystemToolsPolicy so paths outside allowed roots or inside
critical OS / secret locations (.env, .git, C:\\Windows, Program Files) are blocked, critical
Windows OS processes cannot be terminated, and destructive / overwrite / app-launch /
app-close actions require explicit confirmation callbacks.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
import fnmatch
from functools import lru_cache
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple


DEFAULT_SEARCH_MAX_RESULTS = 25
DEFAULT_READ_MAX_LINES = 120
MAX_READ_BYTES = 32_768
SEARCH_TIMEOUT_SECONDS = 4.0

_SKIP_SEARCH_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".venv",
    "venv",
    "$recycle.bin",
    "system volume information",
}

_KNOWN_FOLDER_ALIASES = {
    "desktop": "Desktop",
    "document": "Documents",
    "documents": "Documents",
    "download": "Downloads",
    "downloads": "Downloads",
    "picture": "Pictures",
    "pictures": "Pictures",
    "music": "Music",
    "video": "Videos",
    "videos": "Videos",
}

_BUILTIN_WINDOWS_APPS: Dict[str, str] = {
    "notepad": "notepad.exe",
    "calc": "calc.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "mspaint": "mspaint.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "task manager": "taskmgr.exe",
    "taskmgr": "taskmgr.exe",
    "control panel": "control.exe",
    "snipping tool": "SnippingTool.exe",
}

FOLDER_SIZE_TIMEOUT_SECONDS = 12.0

_PROTECTED_PROCESS_NAMES = frozenset({
    "system",
    "system idle process",
    "registry",
    "secure system",
    "memory compression",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "lsaiso.exe",
    "svchost.exe",
    "winlogon.exe",
    "dwm.exe",
    "fontdrvhost.exe",
    "sihost.exe",
    "taskhostw.exe",
    "explorer.exe",
    "ctfmon.exe",
    "conhost.exe",
    "audiodg.exe",
    "runtimebroker.exe",
    "searchindexer.exe",
})

_CLOSE_APP_ALIASES: Dict[str, Tuple[str, ...]] = {
    "chrome": ("chrome.exe",),
    "google chrome": ("chrome.exe",),
    "edge": ("msedge.exe",),
    "microsoft edge": ("msedge.exe",),
    "firefox": ("firefox.exe",),
    "brave": ("brave.exe",),
    "vscode": ("code.exe",),
    "vs code": ("code.exe",),
    "visual studio code": ("code.exe",),
    "code": ("code.exe",),
    "spyder": ("spyder.exe",),
    "word": ("winword.exe",),
    "excel": ("excel.exe",),
    "powerpoint": ("powerpnt.exe",),
    "outlook": ("outlook.exe", "olk.exe"),
    "calculator": ("calculatorapp.exe", "calc.exe"),
    "calc": ("calculatorapp.exe", "calc.exe"),
    "vlc": ("vlc.exe",),
    "spotify": ("spotify.exe",),
    "discord": ("discord.exe",),
    "slack": ("slack.exe",),
    "teams": ("ms-teams.exe", "teams.exe"),
    "zoom": ("zoom.exe",),
    "ollama": ("ollama.exe", "ollama app.exe"),
    "docker": ("docker desktop.exe",),
    "docker desktop": ("docker desktop.exe",),
}

ConfirmCallback = Callable[[str, str, str], bool]
ClipboardCallback = Callable[[str, str, List[str]], str]
RecycleCallback = Callable[[Path], Tuple[bool, str]]
LaunchCallback = Callable[[str, str], Tuple[bool, str]]
ProcessListCallback = Callable[[], List[Dict[str, Any]]]
CloseProcessCallback = Callable[[List[int], bool], Tuple[bool, str]]


def default_allowed_dirs() -> List[Path]:
    """Return sensible default user folders for local file tools."""
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        Path.cwd(),
    ]
    unique: List[Path] = []
    seen: set[str] = set()
    for p in candidates:
        try:
            resolved = p.resolve()
        except Exception:
            resolved = p
        key = str(resolved).lower()
        if key not in seen and resolved.exists():
            seen.add(key)
            unique.append(resolved)
    if not unique:
        unique.append(home.resolve())
    return unique


def default_allowed_dir_strings() -> List[str]:
    return [str(p) for p in default_allowed_dirs()]


@dataclass
class SystemToolsPolicy:
    """Runtime permissions & UI callbacks for local PC / file tools."""

    enabled: bool = False
    allowed_roots: List[Path] = field(default_factory=default_allowed_dirs)
    allow_all_non_system: bool = False
    confirm_destructive: bool = True
    confirm_app_launch: bool = True
    confirm_callback: Optional[ConfirmCallback] = None
    clipboard_callback: Optional[ClipboardCallback] = None
    recycle_fn: Optional[RecycleCallback] = None
    recycle_list_fn: Optional[Callable[[int], Tuple[int, List[Dict[str, Any]]]]] = None
    drives_fn: Optional[Callable[[], List[Dict[str, Any]]]] = None
    launch_fn: Optional[LaunchCallback] = None
    list_processes_fn: Optional[ProcessListCallback] = None
    close_process_fn: Optional[CloseProcessCallback] = None


@lru_cache(maxsize=1)
def _system_blocked_dirs() -> Tuple[Path, ...]:
    raw_dirs: List[str] = []
    for env_var in ("WINDIR", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        val = os.getenv(env_var)
        if val:
            raw_dirs.append(val)
    if sys.platform == "win32" and not raw_dirs:
        raw_dirs.extend(["C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)", "C:\\ProgramData"])
    out: List[Path] = []
    for item in raw_dirs:
        try:
            out.append(Path(item).resolve())
        except Exception:
            pass
    return tuple(out)


def _is_under_dir(path: Path, parent: Path) -> bool:
    try:
        return path == parent or path.is_relative_to(parent)
    except Exception:
        return False


def _is_hard_blocked(path: Path) -> Optional[str]:
    """Return a reason string if path is protected OS state, git metadata, or .env secret."""
    name_low = path.name.lower()
    if name_low == ".env" or (name_low.startswith(".env.") and name_low != ".env.example"):
        return f"Access denied to protected environment secret file: {path.name}"
    for part in path.parts:
        low = part.lower()
        if low in (".git", "$recycle.bin", "system volume information"):
            return f"Access denied inside protected folder: {part}"
    for sys_dir in _system_blocked_dirs():
        if _is_under_dir(path, sys_dir):
            return f"Access denied inside Windows system directory: {sys_dir}"
    return None


def get_available_drives() -> List[Dict[str, Any]]:
    """Enumerate accessible filesystem drive roots and disk capacity."""
    if sys.platform != "win32":
        try:
            usage = shutil.disk_usage("/")
            return [
                {
                    "root": "/",
                    "type": "Root",
                    "ready": True,
                    "free_bytes": usage.free,
                    "total_bytes": usage.total,
                }
            ]
        except OSError:
            return [{"root": "/", "type": "Root", "ready": True, "free_bytes": 0, "total_bytes": 0}]

    import ctypes

    kernel32 = ctypes.windll.kernel32
    drive_mask = int(kernel32.GetLogicalDrives())
    raw_strings = [f"{chr(65 + i)}:\\" for i in range(26) if drive_mask & (1 << i)]
    if not raw_strings:
        return []
    type_names = {
        2: "Removable",
        3: "Fixed",
        4: "Network",
        5: "CD-ROM",
        6: "RAM Disk",
    }
    drives: List[Dict[str, Any]] = []
    for root in raw_strings:
        dtype = type_names.get(int(kernel32.GetDriveTypeW(root)), "Drive")
        ready = False
        free_b = 0
        total_b = 0
        try:
            if os.path.exists(root):
                usage = shutil.disk_usage(root)
                ready = True
                free_b = int(usage.free)
                total_b = int(usage.total)
        except OSError:
            ready = False
        drives.append(
            {
                "root": root,
                "type": dtype,
                "ready": ready,
                "free_bytes": free_b,
                "total_bytes": total_b,
            }
        )
    return drives


def _resolve_user_path(raw_path: str, policy: SystemToolsPolicy) -> Path:
    text = (raw_path or "").strip().strip('"').strip("'")
    if not text:
        base = policy.allowed_roots[0] if policy.allowed_roots else Path.home()
        return base.resolve()

    expanded = os.path.expandvars(os.path.expanduser(text))
    drive_match = re.match(
        r"^(?:([a-zA-Z])\s*:|([a-zA-Z])\s+drive|drive\s+([a-zA-Z]):?)$",
        expanded.strip(),
        re.IGNORECASE,
    )
    if drive_match:
        letter = (drive_match.group(1) or drive_match.group(2) or drive_match.group(3)).upper()
        return Path(f"{letter}:\\").resolve(strict=False)

    candidate = Path(expanded)
    if not candidate.is_absolute():
        parts = candidate.parts
        if parts and parts[0].lower() in _KNOWN_FOLDER_ALIASES:
            home_base = Path.home() / _KNOWN_FOLDER_ALIASES[parts[0].lower()]
            candidate = home_base.joinpath(*parts[1:]) if len(parts) > 1 else home_base
        else:
            base = policy.allowed_roots[0] if policy.allowed_roots else Path.cwd()
            candidate = base / candidate
    return candidate.resolve(strict=False)


def _validate_path(
    raw_path: str,
    policy: SystemToolsPolicy,
    *,
    allow_root_itself: bool = True,
) -> Tuple[Optional[Path], Optional[str]]:
    """Resolve and verify a path against allowed roots and hard-blocked locations."""
    if not policy.enabled:
        return None, "PC & File Control tools are disabled. Enable them in Settings."

    resolved = _resolve_user_path(raw_path, policy)
    blocked = _is_hard_blocked(resolved)
    if blocked:
        return None, blocked

    if not allow_root_itself:
        home_resolved = Path.home().resolve()
        stripped_raw = (raw_path or "").strip().strip('"').strip("'")
        if re.match(
            r"^(?:[a-zA-Z]\s*:[/\\]?|[a-zA-Z]\s+drive|drive\s+[a-zA-Z]:?)$",
            stripped_raw,
            re.IGNORECASE,
        ):
            return None, f"Refusing destructive action directly on drive root: {resolved}"
        if resolved == home_resolved or resolved == Path(resolved.anchor):
            return None, f"Refusing destructive action on protected root folder: {resolved}"
        for root in policy.allowed_roots:
            if resolved == root.resolve():
                return None, f"Refusing destructive action directly on configured root folder: {resolved}"

    if not policy.allow_all_non_system:
        roots = [r.resolve() for r in policy.allowed_roots] or default_allowed_dirs()
        if not any(_is_under_dir(resolved, root) for root in roots):
            roots_txt = ", ".join(str(r) for r in roots[:4])
            return None, (
                f"Path '{resolved}' is outside allowed folders ({roots_txt}). "
                "Add the folder or enable broader access in Customize -> Allowed Folders."
            )

    return resolved, None


def _require_confirmation(
    policy: SystemToolsPolicy,
    action_title: str,
    detail: str,
    *,
    always_confirm: bool = True,
    risk: str = "confirm",
) -> Optional[str]:
    if not always_confirm:
        return None
    if policy.confirm_callback is None:
        return f"Confirmation required for '{action_title}', but interactive approval is unavailable."
    try:
        approved = bool(policy.confirm_callback(action_title, detail, risk))
    except Exception as exc:
        return f"Confirmation prompt failed for '{action_title}': {exc}"
    if not approved:
        return f"Cancelled by user: {action_title} ({detail})"
    return None


def _format_size(num_bytes: int) -> str:
    size = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{int(num_bytes)} B"


def _send_to_recycle_bin_win32(target: Path) -> Tuple[bool, str]:
    """Move a file or directory to the Windows Recycle Bin using SHFileOperationW."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", wintypes.WORD),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    FO_DELETE = 3
    FOF_SILENT = 0x0004
    FOF_NOCONFIRMATION = 0x0010
    FOF_ALLOWUNDO = 0x0040
    FOF_NOERRORUI = 0x0400

    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = f"{target}\0\0"
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    op.fAnyOperationsAborted = False
    op.hNameMappings = None
    op.lpszProgressTitle = None

    ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if ret != 0 or op.fAnyOperationsAborted:
        return False, f"SHFileOperationW failed with code {ret}"
    return True, f"Moved to Recycle Bin: {target}"


def _recycle_path(target: Path, policy: SystemToolsPolicy) -> Tuple[bool, str]:
    if policy.recycle_fn is not None:
        return policy.recycle_fn(target)
    if sys.platform == "win32":
        return _send_to_recycle_bin_win32(target)
    return False, "Windows Recycle Bin is only supported on win32; deletion aborted safely."


def _find_windows_app_target(query: str) -> Optional[Tuple[str, str]]:
    """Resolve an app name or executable to (display_name, path_or_exe)."""
    clean = (query or "").strip().strip('"').strip("'")
    if not clean:
        return None
    low = clean.lower()

    if low in _BUILTIN_WINDOWS_APPS:
        return clean, _BUILTIN_WINDOWS_APPS[low]
    for alias, exe_name in _BUILTIN_WINDOWS_APPS.items():
        if low == exe_name.lower():
            return alias, exe_name

    # Direct file/folder path if it exists on disk
    direct = Path(os.path.expandvars(os.path.expanduser(clean)))
    if direct.exists():
        return direct.name, str(direct.resolve())

    # Search Start Menu .lnk shortcuts
    shortcut_roots: List[Path] = []
    for env_name, sub in (
        ("APPDATA", Path("Microsoft/Windows/Start Menu/Programs")),
        ("ProgramData", Path("Microsoft/Windows/Start Menu/Programs")),
    ):
        base = os.getenv(env_name)
        if base:
            p = Path(base) / sub
            if p.is_dir():
                shortcut_roots.append(p)

    best_exact: Optional[Tuple[str, str]] = None
    best_partial: Optional[Tuple[str, str]] = None
    for root in shortcut_roots:
        for lnk in root.rglob("*.lnk"):
            stem_low = lnk.stem.lower()
            if stem_low == low:
                best_exact = (lnk.stem, str(lnk))
                break
            if low in stem_low and best_partial is None:
                best_partial = (lnk.stem, str(lnk))
        if best_exact:
            return best_exact
    if best_partial:
        return best_partial

    # Check App Paths registry on Windows
    if sys.platform == "win32":
        try:
            import winreg

            subkey_base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
            names_to_try = [clean] if low.endswith(".exe") else [f"{clean}.exe", clean]
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for candidate_name in names_to_try:
                    try:
                        with winreg.OpenKey(hive, f"{subkey_base}\\{candidate_name}") as key:
                            val, _ = winreg.QueryValueEx(key, None)
                            if val and Path(val.strip('"')).exists():
                                return candidate_name, val.strip('"')
                    except OSError:
                        continue
        except Exception:
            pass

    exe_on_path = shutil.which(clean) or shutil.which(f"{clean}.exe")
    if exe_on_path:
        return Path(exe_on_path).stem, exe_on_path
    return None


def _default_launch_win32(resolved_target: str, arguments: str = "") -> Tuple[bool, str]:
    target_path = Path(resolved_target)
    arg_list = shlex.split(arguments, posix=False) if (arguments or "").strip() else []
    if arg_list and (resolved_target.lower().endswith(".exe") or shutil.which(resolved_target)):
        subprocess.Popen([resolved_target, *arg_list], shell=False)
        return True, f"Launched {resolved_target}"
    if hasattr(os, "startfile") and (target_path.exists() or resolved_target.lower().endswith(".exe")):
        os.startfile(resolved_target)
        return True, f"Opened {resolved_target}"
    exe = shutil.which(resolved_target)
    if exe:
        subprocess.Popen([exe, *arg_list], shell=False)
        return True, f"Launched {exe}"
    return False, f"Cannot launch '{resolved_target}'"


# ============================================================
# USER-FACING TOOL FUNCTIONS
# ============================================================

def search_files(
    query: str = "",
    directory: str = "",
    extension: str = "",
    max_results: int = DEFAULT_SEARCH_MAX_RESULTS,
    *,
    policy: SystemToolsPolicy,
) -> str:
    """Search for files/folders by filename substring or wildcard under allowed directories."""
    if not policy.enabled:
        return "Error: PC & File Control tools are disabled. Enable them in Settings."

    roots: List[Path] = []
    if directory.strip():
        target_dir, err = _validate_path(directory, policy, allow_root_itself=True)
        if err:
            return f"Error: {err}"
        assert target_dir is not None
        if not target_dir.is_dir():
            return f"Error: Directory does not exist: {target_dir}"
        roots = [target_dir]
    else:
        roots = [r.resolve() for r in policy.allowed_roots if r.exists()] or default_allowed_dirs()
        if policy.allow_all_non_system:
            drive_reader = policy.drives_fn or get_available_drives
            sys_drive = (os.getenv("SystemDrive", "C:") + "\\").lower()
            drive_roots: List[Path] = []
            for d in drive_reader():
                if not d.get("ready", True) or not d.get("root"):
                    continue
                r_str = str(d["root"]).strip()
                if 2 <= len(r_str) <= 3 and r_str[1] == ":":
                    drive_roots.append(Path(f"{r_str[0].upper()}:\\"))
                else:
                    drive_roots.append(Path(r_str).resolve(strict=False))
            # Search secondary drives (e.g. K:\, D:\) before scanning the whole C:\ root
            drive_roots.sort(key=lambda p: (str(p).lower() == sys_drive, str(p).lower()))
            seen_roots = {str(r).lower() for r in roots}
            for dr in drive_roots:
                key = str(dr).lower()
                if key not in seen_roots and dr.exists():
                    seen_roots.add(key)
                    roots.append(dr)

    clean_query = (query or "").strip().lower()
    clean_ext = (extension or "").strip().lower()
    if clean_ext and not clean_ext.startswith("."):
        clean_ext = f".{clean_ext}"
    try:
        cap = max(1, min(100, int(max_results)))
    except (TypeError, ValueError):
        cap = DEFAULT_SEARCH_MAX_RESULTS

    has_glob = any(ch in clean_query for ch in ("*", "?", "["))
    matches: List[str] = []
    seen: set[str] = set()
    completed_root_keys: set[str] = set()
    total_budget = 8.0 if (len(roots) > 1 and policy.allow_all_non_system) else SEARCH_TIMEOUT_SECONDS
    overall_deadline = time.monotonic() + total_budget
    timed_out = False

    for idx, root in enumerate(roots):
        now = time.monotonic()
        if now >= overall_deadline or len(matches) >= cap:
            if now >= overall_deadline:
                timed_out = True
            break
        remaining_roots = max(1, len(roots) - idx)
        root_deadline = now + max(0.5, (overall_deadline - now) / remaining_roots)
        root_timed_out = False

        for cur_root, dirnames, filenames in os.walk(root):
            if time.monotonic() > root_deadline:
                root_timed_out = True
                timed_out = True
                break
            cur_path = Path(cur_root)
            if _is_hard_blocked(cur_path):
                dirnames[:] = []
                continue
            dirnames[:] = [
                d for d in dirnames
                if d.lower() not in _SKIP_SEARCH_DIRS
                and not d.startswith(".")
                and str(cur_path / d).lower() not in completed_root_keys
                and not _is_hard_blocked(cur_path / d)
            ]

            for entry_name, is_dir in (
                [(d, True) for d in dirnames] + [(f, False) for f in filenames]
            ):
                full_path = cur_path / entry_name
                if _is_hard_blocked(full_path):
                    continue
                low_name = entry_name.lower()
                if clean_ext and (is_dir or not low_name.endswith(clean_ext)):
                    continue
                if clean_query:
                    ok = fnmatch.fnmatch(low_name, clean_query) if has_glob else (clean_query in low_name)
                    if not ok:
                        continue
                key = str(full_path).lower()
                if key in seen:
                    continue
                seen.add(key)
                tag = "[DIR]" if is_dir else "[FILE]"
                try:
                    info = "" if is_dir else f" ({_format_size(full_path.stat().st_size)})"
                except OSError:
                    info = ""
                matches.append(f"{tag} {full_path}{info}")
                if len(matches) >= cap:
                    break
            if len(matches) >= cap or root_timed_out:
                break
        if not root_timed_out and len(matches) < cap:
            completed_root_keys.add(str(root).lower())
        if len(matches) >= cap:
            break

    if not matches:
        return f"No matching files found for query={query!r} extension={clean_ext!r}."
    header = f"Found {len(matches)} item(s)" + (" (search cap/time reached):" if len(matches) >= cap or timed_out else ":")
    return header + "\n" + "\n".join(matches)


def _clean_shell_text(value: Any) -> str:
    """Strip invisible Windows bidi direction markers from Shell strings."""
    return str(value or "").replace("\u200e", "").replace("\u200f", "").strip()


def _list_recycle_bin_win32(max_items: int = 50) -> Tuple[int, List[Dict[str, Any]]]:
    """Query Windows Recycle Bin via Shell.Application COM (read-only)."""
    if sys.platform != "win32":
        raise RuntimeError("Recycle Bin listing is only supported on Windows.")
    limit = max(1, min(int(max_items), 200))
    ps_script = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
        "$sh = New-Object -ComObject Shell.Application\n"
        "$rb = $sh.Namespace(10)\n"
        "if ($null -eq $rb) {\n"
        "    [PSCustomObject]@{ total = 0; items = @() } | ConvertTo-Json -Compress\n"
        "    exit 0\n"
        "}\n"
        "$all = @($rb.Items())\n"
        f"$picked = @($all | Select-Object -First {limit} | ForEach-Object {{\n"
        "    [PSCustomObject]@{\n"
        "        name = [string]$_.Name\n"
        "        orig = [string]$rb.GetDetailsOf($_, 1)\n"
        "        deleted = [string]$rb.GetDetailsOf($_, 2)\n"
        "        size = $_.Size\n"
        "        is_dir = [bool]$_.IsFolder\n"
        "    }\n"
        "})\n"
        "[PSCustomObject]@{ total = $all.Count; items = $picked } | ConvertTo-Json -Compress -Depth 3\n"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"PowerShell exited with {proc.returncode}")
    payload = json.loads((proc.stdout or "").strip() or "{}")
    total = int(payload.get("total", 0) or 0)
    raw_items = payload.get("items") or []
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    return total, list(raw_items)


def list_recycle_bin(
    max_items: int = 50,
    *,
    policy: SystemToolsPolicy,
) -> str:
    """List filenames and metadata currently inside the Windows Recycle Bin (read-only)."""
    if not policy.enabled:
        return "Error: PC & File Control tools are disabled. Enable them in Settings."
    try:
        limit = max(1, min(int(max_items), 200))
        reader = policy.recycle_list_fn or _list_recycle_bin_win32
        total, items = reader(limit)
    except Exception as exc:
        return f"Error listing Recycle Bin: {exc}"

    if not items and total == 0:
        return "Recycle Bin is empty."

    lines: List[str] = []
    for item in items[:limit]:
        is_dir = bool(item.get("is_dir"))
        tag = "[DIR] " if is_dir else "[FILE]"
        name = _clean_shell_text(item.get("name")) or "(unnamed)"
        orig = _clean_shell_text(item.get("orig"))
        deleted = _clean_shell_text(item.get("deleted"))
        try:
            size_val = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size_val = 0
        size_text = "folder" if is_dir and size_val == 0 else _format_size(size_val)
        meta = [size_text]
        if orig:
            meta.append(f"from: {orig}")
        if deleted:
            meta.append(f"deleted: {deleted}")
        lines.append(f"{tag} {name}  ({' | '.join(meta)})")

    total_count = max(int(total), len(lines))
    if total_count > len(lines):
        header = f"Recycle Bin contains {total_count} item(s) (showing first {len(lines)}):"
    else:
        header = f"Recycle Bin contains {total_count} item(s):"
    return header + "\n" + "\n".join(lines)


def _format_drive_lines(policy: SystemToolsPolicy) -> List[str]:
    reader = policy.drives_fn or get_available_drives
    lines: List[str] = []
    for d in reader():
        root = str(d.get("root") or "").strip()
        if not root:
            continue
        dtype = str(d.get("type") or "Drive")
        if d.get("ready", True):
            free_txt = _format_size(int(d.get("free_bytes") or 0))
            total_txt = _format_size(int(d.get("total_bytes") or 0))
            detail = f"{dtype} | {free_txt} free / {total_txt} total"
        else:
            detail = f"{dtype} | not ready"
        lines.append(f"[DRIVE] {root}  ({detail})")
    return lines


def list_drives(*, policy: SystemToolsPolicy) -> str:
    """List all mounted Windows/PC drives, their types, and free/total capacity."""
    if not policy.enabled:
        return "Error: PC & File Control tools are disabled. Enable them in Settings."
    drive_lines = _format_drive_lines(policy)
    if not drive_lines:
        return "No accessible drives detected."
    mode_note = (
        "All-Drive Control: ON (all non-system paths across every drive are accessible; OS & .env/.git stay protected)"
        if policy.allow_all_non_system
        else "All-Drive Control: OFF (restricted to Allowed Folders whitelist)"
    )
    return "Available drives:\n" + "\n".join(drive_lines) + "\n" + mode_note


def list_directory(
    path: str = "",
    include_hidden: bool = False,
    *,
    policy: SystemToolsPolicy,
) -> str:
    """List folders and files inside an allowed directory or drive root."""
    cleaned = path.strip().strip('"').strip("'").lower()
    if cleaned in ("recycle bin", "recyclebin", "$recycle.bin", "trash"):
        return list_recycle_bin(policy=policy)
    if cleaned in ("drives", "all drives", "this pc", "my computer", "computer"):
        return list_drives(policy=policy)
    if not path.strip():
        if not policy.enabled:
            return "Error: PC & File Control tools are disabled. Enable them in Settings."
        roots = [r.resolve() for r in policy.allowed_roots] or default_allowed_dirs()
        lines = [f"[ROOT] {r} ({'exists' if r.exists() else 'missing'})" for r in roots]
        out = ["Allowed base folders:", *lines]
        drive_lines = _format_drive_lines(policy)
        if drive_lines:
            out.append("")
            out.append("Available drives:")
            out.extend(drive_lines)
            out.append(
                "All-Drive Control: ON (you can access any non-system drive path such as C:\\, K:\\, etc.)"
                if policy.allow_all_non_system
                else "All-Drive Control: OFF (restricted to Allowed Folders whitelist)"
            )
        return "\n".join(out)

    resolved, err = _validate_path(path, policy, allow_root_itself=True)
    if err:
        return f"Error: {err}"
    assert resolved is not None
    if not resolved.exists():
        return f"Error: Directory not found: {resolved}"
    if not resolved.is_dir():
        return f"Error: Not a directory: {resolved}"

    dirs: List[str] = []
    files: List[str] = []
    try:
        entries = sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        return f"Error reading directory '{resolved}': {exc}"

    for item in entries:
        if not include_hidden and item.name.startswith("."):
            continue
        if _is_hard_blocked(item):
            continue
        if item.is_dir():
            dirs.append(f"[DIR]  {item.name}")
        else:
            try:
                sz = _format_size(item.stat().st_size)
            except OSError:
                sz = "?"
            files.append(f"[FILE] {item.name} ({sz})")

    combined = dirs + files
    if not combined:
        return f"Directory '{resolved}' is empty (0 files, 0 folders)."
    capped = combined[:100]
    suffix = f"\n... ({len(combined) - 100} more)" if len(combined) > 100 else ""
    summary = f"Contents of {resolved} ({len(files)} file(s), {len(dirs)} folder(s), {len(combined)} total):"
    return f"{summary}\n" + "\n".join(capped) + suffix


def read_text_file(
    path: str,
    max_lines: int = DEFAULT_READ_MAX_LINES,
    *,
    policy: SystemToolsPolicy,
) -> str:
    """Read a text/code file preview inside allowed folders."""
    resolved, err = _validate_path(path, policy, allow_root_itself=True)
    if err:
        return f"Error: {err}"
    assert resolved is not None
    if not resolved.is_file():
        return f"Error: File not found: {resolved}"

    try:
        cap = max(1, min(400, int(max_lines)))
    except (TypeError, ValueError):
        cap = DEFAULT_READ_MAX_LINES

    try:
        raw = resolved.read_bytes()[:MAX_READ_BYTES]
    except OSError as exc:
        return f"Error reading file '{resolved}': {exc}"

    if b"\x00" in raw:
        return f"Error: '{resolved.name}' appears to be a binary file and cannot be read as text."

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    truncated = len(lines) > cap or resolved.stat().st_size > MAX_READ_BYTES
    body = "\n".join(lines[:cap])
    note = "\n[Truncated preview]" if truncated else ""
    return f"File: {resolved}\n{body}{note}"


def create_item(
    path: str,
    is_directory: bool = False,
    content: str = "",
    *,
    policy: SystemToolsPolicy,
) -> str:
    """Create a folder or text file (requires confirmation before overwriting an existing file)."""
    resolved, err = _validate_path(path, policy, allow_root_itself=False)
    if err:
        return f"Error: {err}"
    assert resolved is not None

    if is_directory:
        if resolved.exists():
            return f"Directory already exists: {resolved}"
        try:
            resolved.mkdir(parents=True, exist_ok=True)
            return f"Created directory: {resolved}"
        except OSError as exc:
            return f"Error creating directory '{resolved}': {exc}"

    if resolved.exists():
        if resolved.is_dir():
            return f"Error: A directory already exists at '{resolved}'."
        deny = _require_confirmation(
            policy,
            "Overwrite existing file",
            f"Overwrite existing file:\n{resolved}",
            always_confirm=policy.confirm_destructive,
            risk="overwrite",
        )
        if deny:
            return deny

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content or "", encoding="utf-8")
        return f"Created file: {resolved} ({len(content or '')} chars)"
    except OSError as exc:
        return f"Error writing file '{resolved}': {exc}"


def copy_or_move(
    source: str,
    destination: str,
    mode: str = "copy",
    *,
    policy: SystemToolsPolicy,
) -> str:
    """Copy or move (cut/paste/rename) a file or directory."""
    clean_mode = (mode or "copy").strip().lower()
    if clean_mode not in ("copy", "move"):
        return f"Error: mode must be 'copy' or 'move', got {mode!r}."

    src_path, src_err = _validate_path(
        source,
        policy,
        allow_root_itself=(clean_mode == "copy"),
    )
    if src_err:
        return f"Error: {src_err}"
    assert src_path is not None
    if not src_path.exists():
        return f"Error: Source does not exist: {src_path}"

    dst_path, dst_err = _validate_path(destination, policy, allow_root_itself=True)
    if dst_err:
        return f"Error: {dst_err}"
    assert dst_path is not None

    final_dst = (dst_path / src_path.name) if dst_path.is_dir() else dst_path
    dst_blocked = _is_hard_blocked(final_dst)
    if dst_blocked:
        return f"Error: {dst_blocked}"

    needs_confirm = (clean_mode == "move") or final_dst.exists()
    if needs_confirm:
        verb = "Move/Rename" if clean_mode == "move" else "Overwrite"
        deny = _require_confirmation(
            policy,
            f"{verb} item",
            f"{verb}:\nFrom: {src_path}\nTo:   {final_dst}",
            always_confirm=policy.confirm_destructive,
            risk="destructive" if clean_mode == "move" else "overwrite",
        )
        if deny:
            return deny

    try:
        final_dst.parent.mkdir(parents=True, exist_ok=True)
        if clean_mode == "move":
            shutil.move(str(src_path), str(final_dst))
            return f"Moved '{src_path}' -> '{final_dst}'"
        if src_path.is_dir():
            shutil.copytree(src_path, final_dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src_path, final_dst)
        return f"Copied '{src_path}' -> '{final_dst}'"
    except Exception as exc:
        return f"Error during {clean_mode}: {exc}"


def delete_item(
    path: str,
    *,
    policy: SystemToolsPolicy,
) -> str:
    """Safely send a file or directory to the Windows Recycle Bin after confirmation."""
    resolved, err = _validate_path(path, policy, allow_root_itself=False)
    if err:
        return f"Error: {err}"
    assert resolved is not None
    if not resolved.exists():
        return f"Error: Item not found: {resolved}"

    deny = _require_confirmation(
        policy,
        "Move to Recycle Bin",
        f"Send to Windows Recycle Bin:\n{resolved}",
        always_confirm=True,
        risk="destructive",
    )
    if deny:
        return deny

    ok, msg = _recycle_path(resolved, policy)
    return msg if ok else f"Error: {msg}"


def clipboard_action(
    action: str,
    text: str = "",
    paths: Optional[List[str]] = None,
    *,
    policy: SystemToolsPolicy,
) -> str:
    """Get or set Windows clipboard text, or copy file paths onto clipboard for Ctrl+V paste."""
    if not policy.enabled:
        return "Error: PC & File Control tools are disabled. Enable them in Settings."

    clean_action = (action or "").strip().lower()
    if clean_action not in ("get", "set", "copy_files"):
        return f"Error: action must be 'get', 'set', or 'copy_files', got {action!r}."

    validated_paths: List[str] = []
    if clean_action == "copy_files":
        raw_list = paths if isinstance(paths, list) else ([paths] if isinstance(paths, str) else [])
        if not raw_list:
            return "Error: 'paths' must list at least one file/folder path for copy_files."
        for raw_p in raw_list:
            resolved, err = _validate_path(str(raw_p), policy, allow_root_itself=True)
            if err:
                return f"Error: {err}"
            assert resolved is not None
            if not resolved.exists():
                return f"Error: Path does not exist: {resolved}"
            validated_paths.append(str(resolved))

    if policy.clipboard_callback is not None:
        return policy.clipboard_callback(clean_action, text or "", validated_paths)

    if sys.platform != "win32":
        return "Error: Clipboard fallback is only supported on Windows."

    try:
        if clean_action == "get":
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return res.stdout if res.returncode == 0 else f"Error reading clipboard: {res.stderr.strip()}"
        if clean_action == "set":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
                input=text or "",
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            return f"Copied {len(text or '')} character(s) to clipboard."
        return "Error: Explorer file clipboard requires the Desktop Companion GUI session."
    except Exception as exc:
        return f"Error accessing clipboard: {exc}"


def launch_app_or_file(
    target: str,
    arguments: str = "",
    *,
    policy: SystemToolsPolicy,
) -> str:
    """Open an installed Windows application, Start Menu shortcut, or allowed document/folder."""
    if not policy.enabled:
        return "Error: PC & File Control tools are disabled. Enable them in Settings."

    clean_target = (target or "").strip().strip('"').strip("'")
    if not clean_target:
        return "Error: target app or file name is required."

    # Check if user asked for an allowed file or folder first
    candidate_path = _resolve_user_path(clean_target, policy)
    resolved_label = ""
    resolved_exec = ""

    if candidate_path.exists():
        blocked = _is_hard_blocked(candidate_path)
        if blocked:
            return f"Error: {blocked}"
        if not policy.allow_all_non_system:
            roots = [r.resolve() for r in policy.allowed_roots] or default_allowed_dirs()
            if not any(_is_under_dir(candidate_path, r) for r in roots):
                # Allow Start Menu shortcuts explicitly if matched cleanly below
                candidate_path = Path("__not_in_allowed_root__")
        if candidate_path.exists():
            resolved_label = candidate_path.name or str(candidate_path)
            resolved_exec = str(candidate_path)

    if not resolved_exec:
        app_match = _find_windows_app_target(clean_target)
        if not app_match:
            return (
                f"Could not find application or file matching '{clean_target}'. "
                "Try an installed app name (e.g. 'notepad', 'calculator', 'chrome') or full file path."
            )
        resolved_label, resolved_exec = app_match

    is_executable = resolved_exec.lower().endswith((".exe", ".bat", ".cmd", ".ps1", ".msi", ".vbs"))
    must_confirm = policy.confirm_app_launch or is_executable
    detail = f"Open: {resolved_label}\nTarget: {resolved_exec}"
    if arguments.strip():
        detail += f"\nArguments: {arguments.strip()}"
    deny = _require_confirmation(
        policy,
        "Open application or file",
        detail,
        always_confirm=must_confirm,
    )
    if deny:
        return deny

    if policy.launch_fn is not None:
        ok, msg = policy.launch_fn(resolved_exec, arguments or "")
        return msg if ok else f"Error: {msg}"

    try:
        ok, msg = _default_launch_win32(resolved_exec, arguments or "")
        return msg if ok else f"Error: {msg}"
    except Exception as exc:
        return f"Error opening '{resolved_exec}': {exc}"


def _scan_tree_size(root: Path, deadline: float) -> Tuple[int, int, int, bool]:
    """Recursively total bytes, file count, and subdir count without following symlinks."""
    total_bytes = 0
    file_count = 0
    dir_count = 0
    timed_out = False
    stack: List[Path] = [root]

    while stack:
        if time.monotonic() > deadline:
            timed_out = True
            break
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                            file_count += 1
                        elif entry.is_dir(follow_symlinks=False):
                            sub_path = Path(entry.path)
                            if _is_hard_blocked(sub_path):
                                continue
                            dir_count += 1
                            stack.append(sub_path)
                    except OSError:
                        continue
        except OSError:
            continue

    return total_bytes, file_count, dir_count, timed_out


def get_folder_size(
    path: str = "",
    top_n: int = 12,
    *,
    policy: SystemToolsPolicy,
) -> str:
    """Calculate total disk usage of a folder (and rank its largest direct subfolders)."""
    if not policy.enabled:
        return "Error: PC & File Control tools are disabled. Enable them in Settings."

    try:
        cap = max(1, min(30, int(top_n)))
    except (TypeError, ValueError):
        cap = 12

    if not path.strip():
        roots = [r.resolve() for r in policy.allowed_roots if r.exists()] or default_allowed_dirs()
        deadline = time.monotonic() + FOLDER_SIZE_TIMEOUT_SECONDS
        rows: List[Tuple[int, str, int, bool]] = []
        for idx, r in enumerate(roots):
            rem = max(0.5, (deadline - time.monotonic()) / max(1, len(roots) - idx))
            sz, files, _, clipped = _scan_tree_size(r, min(deadline, time.monotonic() + rem))
            rows.append((sz, str(r), files, clipped))
        rows.sort(reverse=True)
        lines = [
            f"[DIR]  {p}  ->  {_format_size(sz)} ({files} files){' [partial]' if clipped else ''}"
            for sz, p, files, clipped in rows[:cap]
        ]
        return "Folder sizes (allowed roots):\n" + "\n".join(lines)

    resolved, err = _validate_path(path, policy, allow_root_itself=True)
    if err:
        return f"Error: {err}"
    assert resolved is not None
    if not resolved.exists():
        return f"Error: Directory not found: {resolved}"
    if resolved.is_file():
        try:
            sz = resolved.stat().st_size
            return f"File '{resolved}' size: {_format_size(sz)} ({sz} bytes)"
        except OSError as exc:
            return f"Error reading file size '{resolved}': {exc}"

    deadline = time.monotonic() + FOLDER_SIZE_TIMEOUT_SECONDS
    direct_files_bytes = 0
    direct_files_count = 0
    subdirs: List[Path] = []
    skipped_protected: List[str] = []

    try:
        with os.scandir(resolved) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        direct_files_bytes += entry.stat(follow_symlinks=False).st_size
                        direct_files_count += 1
                    elif entry.is_dir(follow_symlinks=False):
                        sub = Path(entry.path)
                        if _is_hard_blocked(sub):
                            skipped_protected.append(entry.name)
                        else:
                            subdirs.append(sub)
                except OSError:
                    continue
    except OSError as exc:
        return f"Error reading directory '{resolved}': {exc}"

    total_bytes = direct_files_bytes
    total_files = direct_files_count
    total_dirs = len(subdirs)
    clipped_any = False
    breakdown: List[Tuple[int, str, int, bool]] = []

    for idx, sub in enumerate(subdirs):
        now = time.monotonic()
        if now >= deadline:
            clipped_any = True
            break
        per_budget = max(0.35, (deadline - now) / max(1, len(subdirs) - idx))
        sz, f_cnt, d_cnt, sub_clipped = _scan_tree_size(sub, min(deadline, now + per_budget))
        total_bytes += sz
        total_files += f_cnt
        total_dirs += d_cnt
        clipped_any = clipped_any or sub_clipped
        breakdown.append((sz, sub.name, f_cnt, sub_clipped))

    breakdown.sort(key=lambda item: (-item[0], item[1].lower()))
    header = (
        f"Folder size for {resolved}: {_format_size(total_bytes)} "
        f"({total_files} file(s), {total_dirs} subfolder(s))"
    )
    if clipped_any:
        header += " [partial — time limit reached]"

    lines = [header]
    if breakdown:
        lines.append(f"Largest subfolders (top {min(cap, len(breakdown))}):")
        for sz, name, f_cnt, sub_clipped in breakdown[:cap]:
            note = " [partial]" if sub_clipped else ""
            lines.append(f"  [DIR]  {name}  ->  {_format_size(sz)} ({f_cnt} files){note}")
    if direct_files_count > 0:
        lines.append(f"  [FILES in root]  ->  {_format_size(direct_files_bytes)} ({direct_files_count} file(s))")
    if skipped_protected:
        lines.append(f"Skipped protected OS/system folders: {', '.join(skipped_protected[:8])}")
    return "\n".join(lines)


def _visible_window_titles_win32() -> Dict[int, str]:
    """Return {pid: main_visible_window_title} using fast non-blocking Win32 EnumWindows."""
    if sys.platform != "win32":
        return {}
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        titles: Dict[int, str] = {}
        wnd_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum_cb(hwnd: Any, _lparam: Any) -> bool:
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    text = buf.value.strip()
                    if text:
                        pid = wintypes.DWORD()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        if pid.value and pid.value not in titles:
                            titles[int(pid.value)] = text
            return True

        user32.EnumWindows(wnd_proc_type(_enum_cb), 0)
        return titles
    except Exception:
        return {}


def _list_running_processes_win32() -> List[Dict[str, Any]]:
    """Enumerate running Windows processes via `tasklist /FO CSV /NH` plus visible window titles."""
    if sys.platform != "win32":
        return []
    res = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=8,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or f"tasklist exited with {res.returncode}")

    titles = _visible_window_titles_win32()
    procs: List[Dict[str, Any]] = []
    for row in csv.reader(io.StringIO(res.stdout)):
        if len(row) < 5 or not row[1].strip().isdigit():
            continue
        pid = int(row[1].strip())
        procs.append(
            {
                "name": row[0].strip(),
                "pid": pid,
                "mem": row[4].strip(),
                "title": titles.get(pid, ""),
            }
        )
    return procs


def _is_protected_process(name: str, pid: int) -> bool:
    if pid <= 4 or pid == os.getpid():
        return True
    return (name or "").strip().lower() in _PROTECTED_PROCESS_NAMES


def _default_close_pids_win32(pids: List[int], force: bool = False) -> Tuple[bool, str]:
    """Terminate specific Windows PIDs cleanly via `taskkill`."""
    if sys.platform != "win32":
        return False, "Closing Windows applications is only supported on Windows."
    if not pids:
        return False, "No target PIDs supplied."
    cmd = ["taskkill", "/T"]
    if force:
        cmd.append("/F")
    for pid in pids:
        cmd.extend(["/PID", str(int(pid))])

    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    out = (res.stdout or "").strip()
    err = (res.stderr or "").strip()
    if res.returncode == 0:
        return True, out or f"Closed PID(s): {', '.join(str(p) for p in pids)}"
    msg = err or out or f"taskkill exited with {res.returncode}"
    if not force and "forcefully" in msg.lower():
        msg += " (This process needs force=True to terminate if it does not respond to a normal close request.)"
    return False, msg


def _resolve_close_targets(
    clean_target: str,
    processes: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Return (closable_matches, blocked_reasons) for a user app name, exe, or PID."""
    low = clean_target.lower()
    closable: List[Dict[str, Any]] = []
    blocked: List[str] = []

    if clean_target.isdigit():
        wanted_pid = int(clean_target)
        for p in processes:
            if int(p.get("pid", -1)) == wanted_pid:
                name = str(p.get("name") or "")
                if _is_protected_process(name, wanted_pid):
                    blocked.append(f"{name or 'PID'} (PID {wanted_pid})")
                else:
                    closable.append(p)
        return closable, blocked

    candidate_names = set(_CLOSE_APP_ALIASES.get(low, ()))
    if low in _BUILTIN_WINDOWS_APPS:
        candidate_names.add(_BUILTIN_WINDOWS_APPS[low].lower())
    candidate_names.add(low if low.endswith(".exe") else f"{low}.exe")
    candidate_names.add(low)

    seen_pids: set[int] = set()
    # 1. Exact / alias executable name match (plus visible window title match for wrapper apps like Spyder)
    for p in processes:
        pid = int(p.get("pid", -1))
        name = str(p.get("name") or "")
        name_low = name.lower()
        stem_low = Path(name_low).stem
        title_low = str(p.get("title") or "").lower()

        exe_match = name_low in candidate_names or stem_low == low.removesuffix(".exe")
        title_match = len(low) >= 3 and bool(title_low) and low in title_low
        if not (exe_match or title_match):
            continue
        if _is_protected_process(name, pid):
            blocked.append(f"{name} (PID {pid})")
            continue
        if pid not in seen_pids:
            seen_pids.add(pid)
            closable.append(p)

    # 2. Prefix fallback on executable stem when query >= 4 chars and nothing matched yet
    if not closable and not blocked and len(low) >= 4:
        clean_stem = low.removesuffix(".exe")
        for p in processes:
            pid = int(p.get("pid", -1))
            name = str(p.get("name") or "")
            stem_low = Path(name.lower()).stem
            if not stem_low.startswith(clean_stem):
                continue
            if _is_protected_process(name, pid):
                blocked.append(f"{name} (PID {pid})")
                continue
            if pid not in seen_pids:
                seen_pids.add(pid)
                closable.append(p)

    return closable, blocked


def list_running_apps(
    filter_text: str = "",
    max_items: int = 40,
    *,
    policy: SystemToolsPolicy,
) -> str:
    """List currently running non-system applications and visible window titles (read-only)."""
    if not policy.enabled:
        return "Error: PC & File Control tools are disabled. Enable them in Settings."
    try:
        limit = max(1, min(100, int(max_items)))
    except (TypeError, ValueError):
        limit = 40

    reader = policy.list_processes_fn or _list_running_processes_win32
    try:
        processes = reader()
    except Exception as exc:
        return f"Error listing running apps: {exc}"

    needle = (filter_text or "").strip().lower()
    rows: List[Tuple[bool, str, int, str, str]] = []
    for p in processes:
        pid = int(p.get("pid", -1))
        name = str(p.get("name") or "")
        if _is_protected_process(name, pid):
            continue
        title = str(p.get("title") or "").strip()
        mem = str(p.get("mem") or "").strip()
        if needle and needle not in name.lower() and needle not in title.lower():
            continue
        rows.append((bool(title), name, pid, mem, title))

    if not rows:
        return (
            f"No running applications matching {filter_text!r}."
            if needle
            else "No non-system running applications detected."
        )

    rows.sort(key=lambda item: (not item[0], item[1].lower(), item[2]))
    lines = []
    for _, name, pid, mem, title in rows[:limit]:
        parts = [f"PID {pid}"]
        if mem:
            parts.append(mem)
        if title:
            parts.append(f'window: "{title}"')
        lines.append(f"[APP] {name}  ({' | '.join(parts)})")

    header = f"Running applications ({len(rows)} matched, showing {len(lines)}):"
    return header + "\n" + "\n".join(lines)


def close_app(
    target: str,
    force: bool = False,
    *,
    policy: SystemToolsPolicy,
) -> str:
    """Close a running non-system Windows application by name, window title, or PID after confirmation."""
    if not policy.enabled:
        return "Error: PC & File Control tools are disabled. Enable them in Settings."

    clean_target = (target or "").strip().strip('"').strip("'")
    if not clean_target:
        return "Error: target application name, executable, or PID is required."

    reader = policy.list_processes_fn or _list_running_processes_win32
    try:
        processes = reader()
    except Exception as exc:
        return f"Error inspecting running applications: {exc}"

    closable, blocked = _resolve_close_targets(clean_target, processes)
    if not closable:
        if blocked:
            return f"Refusing to close protected system/companion process: {', '.join(blocked[:4])}"
        return (
            f"No running application found matching '{clean_target}'. "
            "Call list_running_apps to check the exact process name or window title."
        )

    pids = [int(p["pid"]) for p in closable]
    preview_lines = []
    for p in closable[:8]:
        title = str(p.get("title") or "").strip()
        suffix = f' — "{title}"' if title else ""
        preview_lines.append(f"• {p['name']} (PID {p['pid']}){suffix}")
    if len(closable) > 8:
        preview_lines.append(f"... and {len(closable) - 8} more matching process(es)")

    mode_label = "FORCE CLOSE (unsaved work may be lost)" if force else "Graceful close"
    detail = f"Close: {clean_target} ({mode_label})\nMatched process(es):\n" + "\n".join(preview_lines)
    deny = _require_confirmation(
        policy,
        "Close running application",
        detail,
        always_confirm=True,
        risk="destructive",
    )
    if deny:
        return deny

    closer = policy.close_process_fn or _default_close_pids_win32
    try:
        ok, msg = closer(pids, bool(force))
        if ok:
            return f"Closed '{clean_target}' ({len(pids)} process(es)): {msg}"
        return f"Error closing '{clean_target}': {msg}"
    except Exception as exc:
        return f"Error closing '{clean_target}': {exc}"


# ============================================================
# TOOL SCHEMAS & DISPATCH
# ============================================================

SYSTEM_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "search_files",
        "description": (
            "Search local folders for files or subdirectories by name or wildcard (e.g. '*.pdf', 'report'). "
            "Use this to locate exact file paths before reading, copying, moving, or deleting."
        ),
        "properties": {
            "query": {"type": "string", "description": "Filename substring or glob pattern, e.g. 'notes' or '*.pdf'."},
            "directory": {
                "type": "string",
                "description": "Optional starting folder or drive path (e.g. 'K:\\', 'D:', 'Downloads').",
            },
            "extension": {"type": "string", "description": "Optional file extension filter, e.g. '.pdf' or 'txt'."},
        },
        "required": ["query"],
        "fn": search_files,
    },
    {
        "name": "list_drives",
        "description": "List all drives on the PC (C:\\, D:\\, K:\\, USB/network drives) with free/total disk space and access mode.",
        "properties": {},
        "required": [],
        "fn": list_drives,
    },
    {
        "name": "list_directory",
        "description": "List folders and files in a folder or drive root (e.g. 'K:\\', 'C:\\', 'Downloads'), or omit path to see drives & base folders.",
        "properties": {
            "path": {"type": "string", "description": "Drive or folder path (e.g. 'K:\\', 'C:\\work', 'Downloads') or alias."},
        },
        "required": [],
        "fn": list_directory,
    },
    {
        "name": "read_text_file",
        "description": "Read a text, Markdown, JSON, CSV, log, or source-code file from an allowed folder.",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read."},
        },
        "required": ["path"],
        "fn": read_text_file,
    },
    {
        "name": "create_item",
        "description": "Create a new folder or create/write a text file in an allowed directory.",
        "properties": {
            "path": {"type": "string", "description": "Target file or folder path to create."},
            "is_directory": {"type": "boolean", "description": "Set true to create a directory, false for a file."},
            "content": {"type": "string", "description": "Text contents when creating a file."},
        },
        "required": ["path"],
        "fn": create_item,
    },
    {
        "name": "copy_or_move",
        "description": "Copy or move/rename (cut and paste) a file or directory to a destination path.",
        "properties": {
            "source": {"type": "string", "description": "Existing source file or directory path."},
            "destination": {"type": "string", "description": "Destination folder or full target file path."},
            "mode": {"type": "string", "description": "'copy' or 'move'.", "enum": ["copy", "move"]},
        },
        "required": ["source", "destination"],
        "fn": copy_or_move,
    },
    {
        "name": "delete_item",
        "description": "Move a local file or folder to the Windows Recycle Bin (asks user confirmation first).",
        "properties": {
            "path": {"type": "string", "description": "Exact path to the file or directory to delete."},
        },
        "required": ["path"],
        "fn": delete_item,
    },
    {
        "name": "clipboard_action",
        "description": (
            "Read clipboard text ('get'), copy text to clipboard ('set'), or place local file paths "
            "onto the Windows clipboard ('copy_files') so the user can paste them anywhere with Ctrl+V."
        ),
        "properties": {
            "action": {"type": "string", "description": "Clipboard operation.", "enum": ["get", "set", "copy_files"]},
            "text": {"type": "string", "description": "Text to copy when action='set'."},
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File or folder paths when action='copy_files'.",
            },
        },
        "required": ["action"],
        "fn": clipboard_action,
    },
    {
        "name": "list_recycle_bin",
        "description": (
            "Read-only view of files and folders currently inside the Windows Recycle Bin, "
            "including display filename, size, original folder, and deletion date."
        ),
        "properties": {
            "max_items": {
                "type": "integer",
                "description": "Maximum number of Recycle Bin items to return (default 50, max 200).",
            },
        },
        "required": [],
        "fn": list_recycle_bin,
    },
    {
        "name": "launch_app_or_file",
        "description": (
            "Open a Windows application by name (e.g. 'notepad', 'calculator', 'chrome', 'code') "
            "or open an allowed file or folder with its default app."
        ),
        "properties": {
            "target": {"type": "string", "description": "Application name, executable, or file/folder path."},
            "arguments": {"type": "string", "description": "Optional CLI arguments when launching an executable."},
        },
        "required": ["target"],
        "fn": launch_app_or_file,
    },
    {
        "name": "get_folder_size",
        "description": (
            "Calculate the total recursive disk storage used by a folder (e.g. 'C:\\Users\\KF0052', "
            "'Downloads', 'K:\\') and rank its largest subfolders."
        ),
        "properties": {
            "path": {
                "type": "string",
                "description": "Folder or drive path (or omit to measure all allowed root folders).",
            },
            "top_n": {
                "type": "integer",
                "description": "Number of largest subfolders to list (default 12, max 30).",
            },
        },
        "required": [],
        "fn": get_folder_size,
    },
    {
        "name": "list_running_apps",
        "description": (
            "List currently running non-system Windows applications, PIDs, memory usage, and visible window titles."
        ),
        "properties": {
            "filter_text": {
                "type": "string",
                "description": "Optional substring filter for process name or window title (e.g. 'spyder', 'chrome').",
            },
        },
        "required": [],
        "fn": list_running_apps,
    },
    {
        "name": "close_app",
        "description": (
            "Close a running non-system Windows application by app name, executable, window title, or PID "
            "(e.g. 'spyder', 'notepad', 'chrome'). Always asks user confirmation first and blocks OS processes."
        ),
        "properties": {
            "target": {
                "type": "string",
                "description": "Application name (e.g. 'spyder', 'notepad'), executable ('spyder.exe'), window title, or PID.",
            },
            "force": {
                "type": "boolean",
                "description": "Set true to force-terminate if the app ignores a graceful close request (default false).",
            },
        },
        "required": ["target"],
        "fn": close_app,
    },
]

SYSTEM_TOOL_FUNCTIONS = {spec["name"]: spec["fn"] for spec in SYSTEM_TOOL_SPECS}


def execute_system_tool(name: str, args: Dict[str, Any], policy: SystemToolsPolicy) -> Optional[str]:
    """Execute a system tool if name belongs to SYSTEM_TOOL_FUNCTIONS, else return None."""
    fn = SYSTEM_TOOL_FUNCTIONS.get(name)
    if fn is None:
        return None
    clean_args = dict(args or {})
    clean_args["policy"] = policy
    return str(fn(**clean_args))
