param(
    [string]$Sprite = "",
    [switch]$Clean,
    [switch]$CopyToRoot,
    [switch]$CreateDesktopShortcut,
    [switch]$EnableStartup
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { (Get-Command python).Source }

Write-Host "=== Building AICompanion.exe ===" -ForegroundColor Cyan

# Ensure build dependencies (PyInstaller + Pillow) are present
& $PythonExe -c "import PyInstaller, PIL" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing build dependencies from requirements-build.txt..."
    & $PythonExe -m pip install -r (Join-Path $ProjectDir "requirements-build.txt")
}

$IconPath = Join-Path $ProjectDir "assets\app_icon.ico"
if ($Sprite -or -not (Test-Path $IconPath)) {
    Write-Host "Generating Windows app icon ($IconPath)..."
    if ($Sprite) {
        & $PythonExe (Join-Path $ProjectDir "scripts\generate_icon.py") --output $IconPath --sprite $Sprite
    } else {
        & $PythonExe (Join-Path $ProjectDir "scripts\generate_icon.py") --output $IconPath
    }
    if ($LASTEXITCODE -ne 0) { throw "Icon generation failed." }
}

$PyInstallerArgs = @("-m", "PyInstaller", "--noconfirm")
if ($Clean) {
    $PyInstallerArgs += "--clean"
}
$PyInstallerArgs += (Join-Path $ProjectDir "AICompanion.spec")

# Stop running instance if any so dist\AICompanion.exe is not locked
$RunningInstances = Get-Process -Name "AICompanion" -ErrorAction SilentlyContinue
if ($RunningInstances) {
    Write-Host "Stopping running AICompanion instance(s) before build..." -ForegroundColor Yellow
    $RunningInstances | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
}

Write-Host "Running PyInstaller..."
& $PythonExe @PyInstallerArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$DistExe = Join-Path $ProjectDir "dist\AICompanion.exe"
if (-not (Test-Path $DistExe)) {
    throw "Expected executable not found at $DistExe"
}

$FinalExe = $DistExe
if ($CopyToRoot) {
    $RootExe = Join-Path $ProjectDir "AICompanion.exe"
    Copy-Item -Force $DistExe $RootExe
    $FinalExe = $RootExe
}

function New-ExeShortcut {
    param(
        [string]$ShortcutPath,
        [string]$TargetExe,
        [switch]$StartupMode
    )
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($ShortcutPath)
    $sc.TargetPath = $TargetExe
    if ($StartupMode) {
        $sc.Arguments = "--startup"
    }
    $sc.WorkingDirectory = (Split-Path -Parent $TargetExe)
    $sc.IconLocation = "$TargetExe,0"
    $sc.Description = "Always-on-screen Desktop AI Character Companion"
    $sc.Save()
}

if ($CreateDesktopShortcut) {
    $DesktopDir = [Environment]::GetFolderPath("Desktop")
    $DesktopLink = Join-Path $DesktopDir "AI Character Companion.lnk"
    New-ExeShortcut -ShortcutPath $DesktopLink -TargetExe $FinalExe
    Write-Host "Created Desktop shortcut: $DesktopLink" -ForegroundColor Green
}

if ($EnableStartup) {
    $StartupDir = [Environment]::GetFolderPath("Startup")
    $StartupLink = Join-Path $StartupDir "AICharacterCompanion.lnk"
    New-ExeShortcut -ShortcutPath $StartupLink -TargetExe $FinalExe -StartupMode
    Write-Host "Enabled Windows Startup launch: $StartupLink" -ForegroundColor Green
}

$SizeMB = [Math]::Round((Get-Item $FinalExe).Length / 1MB, 1)
Write-Host "`nBuild succeeded!" -ForegroundColor Green
Write-Host "Executable : $FinalExe ($SizeMB MB)"
Write-Host "Notes      : Place .env and character_config.json next to the .exe (dist\AICompanion.exe also auto-reads .env from the project folder)."
