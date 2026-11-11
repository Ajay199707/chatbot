# AI Chatbot & Always-On-Screen Desktop Character

An AI assistant supporting **100% free local AI (Ollama)**, **Google Gemini** (including free `gemini-3.5-flash-lite` & `gemma-4-31b-it`), **Groq Cloud** (free tier, no card), **xAI Grok**, **NVIDIA NIM**, and an offline **Mock** demo mode, available in three ways:
- **Always-on-screen Desktop Character** ([desktop_companion.py](desktop_companion.py)) — transparent floating pet/avatar on Windows with custom PNG/GIF sprites, custom personality, system tray, and `Ctrl+Shift+Space` global shortcut
- **Modern Web UI** ([chatbot.py](chatbot.py) + [static/index.html](static/index.html)) — FastAPI + SSE streaming, Markdown/code blocks, thinking display, and session history
- **Streaming CLI** ([chatbot.py](chatbot.py))

Built-in real-time tools:
- `web_search`: Live web search via **Tavily Search API** (`TAVILY_API_KEY`)
- `get_india_gold_price`: Live Indian gold and silver buy/sell quotes (INR/gram)
- `get_news`: Google News RSS headline search
- `get_current_datetime`: Current local and UTC date/time

Optional Desktop **PC & File Control** tools ([system_tools.py](system_tools.py)) — toggle via right-click -> **PC & File Control Tools** or **Control All Drives (Full PC)**:
- `list_drives`: Discover mounted PC drives (`C:\`, `D:\`, `K:\`, USB/network) with free/total disk space
- `search_files`: Search files and folders across all drives or Allowed Folders (`Desktop`, `Documents`, `Downloads`, project folder, `K:\`, etc.)
- `list_directory`, `get_folder_size`, `list_recycle_bin`, & `read_text_file`: Browse drives/folders, calculate recursive folder storage totals, inspect Windows Recycle Bin filenames (read-only), and read text/code files
- `create_item` & `copy_or_move`: Create folders/files and copy, move (cut/paste), or rename items
- `delete_item`: Safely moves files/folders to the **Windows Recycle Bin** (never permanent blind unlink)
- `clipboard_action`: Read clipboard text (`get`), copy text (`set`), or place files on the Windows clipboard (`copy_files`) for `Ctrl+V` paste
- `launch_app_or_file`, `list_running_apps`, & `close_app`: Open installed Windows apps, inspect running non-system apps/windows, or close running apps (e.g. Spyder, Notepad, Chrome)
- **Safety guardrails**: Interactive **Allow / Deny** dialog before Recycle Bin deletion, move/rename, overwrite, launching apps/executables, or closing running apps; `.env`, `.git/`, `$Recycle.Bin`, Windows system directories, and critical OS processes stay blocked, and browser `--web` sessions never expose local PC tools.

---

## Quick Setup (Windows)

```powershell
# 1. Install dependencies (or pass -UseVenv to create a .venv)
.\setup.ps1

# Optional flags:
.\setup.ps1 -CreateDesktopShortcut -EnableStartup
```

Configure your API key in `.env` (or directly in the Desktop Character's **Edit / Customize** dialog), or switch to **Ollama** for 100% free unlimited local AI with no API key:

```env
GEMINI_API_KEY="your-gemini-api-key"
GROQ_API_KEY="gsk_your-free-groq-key"
GROK_API_KEY="xai-your-grok-key"
NVIDIA_API_KEY="nvapi-your-key"
TAVILY_API_KEY="tvly-your-tavily-search-key"
```

---

## Running

### 1. Standalone Windows `.exe`
```powershell
# Build dist\AICompanion.exe (windowed, no console window, with Lumi icon)
.\build_exe.ps1

# Optional flags:
# .\build_exe.ps1 -CreateDesktopShortcut -EnableStartup
# .\build_exe.ps1 -CopyToRoot
```
Once built, double-click **`dist\AICompanion.exe`** (or run from any folder). Config (`character_config.json`) and `.env` keys save right beside the `.exe` (`dist\AICompanion.exe` also automatically reads `.env` and `character_config.json` from the parent project folder if present).

### 2. Desktop Character Companion (from Python)
```powershell
# Silent background launch (no PowerShell window stays open):
wscript launch_companion.vbs

# Or run from terminal:
python desktop_companion.py
python chatbot.py --desktop
```
**Desktop Controls:**
- **Left-click** character or press **`Ctrl+Shift+Space`**: toggle chat popup
- **Drag** character: move anywhere on screen
- **Scroll wheel** over character: resize live (`40–260 px`)
- **Drag-and-drop** any `.png` / `.gif` / `.webp`: swap the character sprite instantly
- **Right-click**: customize name, personality prompt, API keys, Windows auto-start, character size presets, provider switch, hide to tray, or quit

### 3. Web UI
```powershell
python chatbot.py --web
# Open http://127.0.0.1:8000
```

### 4. Terminal CLI
```powershell
python chatbot.py
```

---

## Tests

```powershell
python -m pytest -v
```
