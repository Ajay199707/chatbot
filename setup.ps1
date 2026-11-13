param(
    [switch]$UseVenv,
    [switch]$CreateDesktopShortcut,
    [switch]$EnableStartup
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

Write-Host "=== AI Chatbot & Desktop Companion Setup ===" -ForegroundColor Cyan

if ($UseVenv) {
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        Write-Host "Creating virtual environment (.venv)..."
        python -m venv .venv
    }
    $PythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    $PythonwExe = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"
} else {
    $PythonExe = (Get-Command python).Source
    $SiblingPyw = Join-Path (Split-Path $PythonExe) "pythonw.exe"
    $PythonwExe = if (Test-Path $SiblingPyw) { $SiblingPyw } else { $PythonExe }
}

Write-Host "Installing dependencies from requirements.txt..."
& $PythonExe -m pip install -r (Join-Path $ProjectDir "requirements.txt")

if (-not (Test-Path (Join-Path $ProjectDir ".env")) -and (Test-Path (Join-Path $ProjectDir ".env.example"))) {
    Copy-Item (Join-Path $ProjectDir ".env.example") (Join-Path $ProjectDir ".env")
    Write-Host "Created .env from .env.example. Add your GEMINI_API_KEY inside .env or via the app UI." -ForegroundColor Yellow
}

function New-CompanionShortcut {
    param(
        [string]$ShortcutPath,
        [switch]$StartupMode
    )
    $RootExe = Join-Path $ProjectDir "AICompanion.exe"
    $DistExe = Join-Path $ProjectDir "dist\AICompanion.exe"
    $BuiltExe = if (Test-Path $RootExe) { $RootExe } elseif (Test-Path $DistExe) { $DistExe } else { "" }

    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($ShortcutPath)
    if ($BuiltExe) {
        $sc.TargetPath = $BuiltExe
        if ($StartupMode) {
            $sc.Arguments = "--startup"
        }
        $sc.WorkingDirectory = (Split-Path -Parent $BuiltExe)
        $sc.IconLocation = "$BuiltExe,0"
    } else {
        $sc.TargetPath = $PythonwExe
        $ScriptArg = '"' + (Join-Path $ProjectDir "desktop_companion.py") + '"'
        $sc.Arguments = if ($StartupMode) { "$ScriptArg --startup" } else { $ScriptArg }
        $sc.WorkingDirectory = $ProjectDir
        $IconFile = Join-Path $ProjectDir "assets\app_icon.ico"
        if (Test-Path $IconFile) {
            $sc.IconLocation = $IconFile
        }
    }
    $sc.Description = "Always-on-screen Desktop AI Character Companion"
    $sc.Save()
}

if ($CreateDesktopShortcut) {
    $DesktopDir = [Environment]::GetFolderPath("Desktop")
    $DesktopLink = Join-Path $DesktopDir "AI Character Companion.lnk"
    New-CompanionShortcut -ShortcutPath $DesktopLink
    Write-Host "Created Desktop shortcut: $DesktopLink" -ForegroundColor Green
}

if ($EnableStartup) {
    $StartupDir = [Environment]::GetFolderPath("Startup")
    $StartupLink = Join-Path $StartupDir "AICharacterCompanion.lnk"
    New-CompanionShortcut -ShortcutPath $StartupLink -StartupMode
    Write-Host "Enabled Windows Startup launch: $StartupLink" -ForegroundColor Green
}

Write-Host "`nSetup complete!" -ForegroundColor Green
Write-Host "Build standalone .exe      : .\build_exe.ps1"
Write-Host "Run silently in background : wscript launch_companion.vbs"
Write-Host "Run desktop character      : python desktop_companion.py"
Write-Host "Run web interface          : python chatbot.py --web"
