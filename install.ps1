# Cleanly installer for Windows 10/11 (PowerShell 5.1 or 7+).
#
#   irm https://raw.githubusercontent.com/damasiyachiranj/cleanly-censorship/main/install.ps1 | iex
#
# What it does:
#   1. Checks for Python 3.10+ and FFmpeg; installs any that are missing with
#      winget (Windows' built-in package manager), for your user only.
#   2. Downloads Cleanly to %LOCALAPPDATA%\cleanly-censorship (or updates it).
#   3. Creates a private Python environment there and installs Cleanly into it.
#   4. Adds the `cleanly` command to your user PATH.
#
# Options (when piping, use:  & ([scriptblock]::Create((irm <url>))) -NoFfmpeg ):
#   -NoFfmpeg       don't install FFmpeg (only needed for audio/video)
#   -Dir <path>     install somewhere else
#   -Branch <name>  install a different branch (default: main)
#   -Uninstall      remove Cleanly (leaves Python and FFmpeg alone)

param(
    [switch]$NoFfmpeg,
    [string]$Dir = "$env:LOCALAPPDATA\cleanly-censorship",
    [string]$Branch = "main",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/damasiyachiranj/cleanly-censorship"
$BinDir = Join-Path $Dir "bin"

function Say($m)  { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host " ok $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "error: $m" -ForegroundColor Red; throw $m }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

function Invoke-Checked {
    # Run a program and stop if it fails (PowerShell doesn't do this for .exe files).
    param([string]$Exe, [string[]]$Arguments, [string]$What)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { Die "$What failed (exit code $LASTEXITCODE)." }
}

function Update-SessionPath {
    # Pick up PATH changes made by installers without opening a new window.
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Remove-FromUserPath($folder) {
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $user) { return }
    $parts = $user.Split(";") | Where-Object { $_ -and ($_.TrimEnd("\") -ne $folder.TrimEnd("\")) }
    [Environment]::SetEnvironmentVariable("Path", ($parts -join ";"), "User")
}

# ---- Uninstall ------------------------------------------------------------
if ($Uninstall) {
    Say "Removing Cleanly from $Dir"
    Remove-FromUserPath $BinDir
    if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir }
    Ok "Removed. Python and FFmpeg were left installed."
    return
}

# Older Windows PowerShell needs this to talk to GitHub.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

function Install-WithWinget($id, $name) {
    if (-not (Have "winget")) {
        Die "winget isn't available, so $name can't be installed automatically. Install 'App Installer' from the Microsoft Store, or install $name yourself, then run this again."
    }
    Say "Installing $name (winget)"
    & winget install --id $id --exact --silent --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        # Some packages don't support per-user installs; try the default scope.
        & winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements
    }
    Update-SessionPath
}

# ---- Python 3.10+ ----------------------------------------------------------
function Find-Python {
    $candidates = @(
        @{ Exe = "py"; Pre = @("-3") },
        @{ Exe = "python"; Pre = @() },
        @{ Exe = "python3"; Pre = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Have $c.Exe)) { continue }
        try {
            # The Microsoft Store "python" placeholder prints nothing useful; this check skips it.
            $out = & $c.Exe @($c.Pre + @("-c", "import sys; print(sys.version_info >= (3, 10))")) 2>$null
            if ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq "True") { return $c }
        } catch { }
    }
    return $null
}

Say "Checking Python 3.10+"
$py = Find-Python
if (-not $py) {
    Install-WithWinget "Python.Python.3.12" "Python 3.12"
    $py = Find-Python
    if (-not $py) {
        # A fresh per-user install may not be on PATH in this window yet.
        $direct = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
        if (Test-Path $direct) { $py = @{ Exe = $direct; Pre = @() } }
    }
    if (-not $py) { Die "Python was installed but can't be found yet. Open a new PowerShell window and run this again." }
}
$pyVersion = & $py.Exe @($py.Pre + @("--version"))
Ok $pyVersion

# ---- FFmpeg (audio/video) --------------------------------------------------
if (-not $NoFfmpeg) {
    Say "Checking FFmpeg"
    if (Have "ffmpeg") {
        Ok "FFmpeg found"
    } else {
        try {
            Install-WithWinget "Gyan.FFmpeg" "FFmpeg"
            if (Have "ffmpeg") { Ok "FFmpeg installed" }
            else { Warn "FFmpeg was installed; open a new window for it to be found." }
        } catch {
            Warn "Couldn't install FFmpeg. Text files still work; install FFmpeg later for audio/video."
        }
    }
}

# ---- Download or update Cleanly ------------------------------------------
Say "Getting Cleanly ($Branch) into $Dir"
$src = Join-Path $Dir "src-repo"
if ((Test-Path (Join-Path $src ".git")) -and (Have "git")) {
    Invoke-Checked "git" @("-C", $src, "fetch", "--quiet", "origin", $Branch) "git fetch"
    Invoke-Checked "git" @("-C", $src, "checkout", "--quiet", $Branch) "git checkout"
    Invoke-Checked "git" @("-C", $src, "reset", "--quiet", "--hard", "origin/$Branch") "git reset"
    Ok "Updated to the latest version"
} else {
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    if (Test-Path $src) { Remove-Item -Recurse -Force $src }
    if (Have "git") {
        Invoke-Checked "git" @("clone", "--quiet", "--depth", "1", "--branch", $Branch, "$RepoUrl.git", $src) "git clone"
    } else {
        # No Git needed: download the source as a zip.
        $zip = Join-Path $env:TEMP "cleanly-$Branch.zip"
        $tmp = Join-Path $env:TEMP "cleanly-$Branch-extract"
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "$RepoUrl/archive/refs/heads/$Branch.zip" -OutFile $zip
        } catch {
            Die "Couldn't download Cleanly from GitHub. Check your internet connection."
        }
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $inner = Get-ChildItem $tmp | Select-Object -First 1
        Move-Item $inner.FullName $src
        Remove-Item -Force $zip
        Remove-Item -Recurse -Force $tmp
    }
    Ok "Downloaded"
}

# ---- Private Python environment -------------------------------------------
Say "Installing Cleanly into its own Python environment"
$venv = Join-Path $Dir ".venv"
Invoke-Checked $py.Exe @($py.Pre + @("-m", "venv", $venv)) "Creating the Python environment"
$venvPy = Join-Path $venv "Scripts\python.exe"
Invoke-Checked $venvPy @("-m", "pip", "install", "--quiet", "--upgrade", "pip") "Updating pip"
Invoke-Checked $venvPy @("-m", "pip", "install", "--quiet", $src) "Installing Cleanly"
Ok "Installed"

# ---- `cleanly` command ----------------------------------------------------
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$shim = Join-Path $BinDir "cleanly.cmd"
Set-Content -Path $shim -Encoding ASCII -Value "@echo off`r`n`"%~dp0..\.venv\Scripts\cleanly.exe`" %*"

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$onPath = $false
if ($userPath) {
    foreach ($p in $userPath.Split(";")) { if ($p.TrimEnd("\") -eq $BinDir.TrimEnd("\")) { $onPath = $true } }
}
if (-not $onPath) {
    $newPath = if ($userPath) { "$userPath;$BinDir" } else { $BinDir }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Ok "Added $BinDir to your PATH"
}
$env:Path = "$env:Path;$BinDir"

$version = & $shim --version
if ($LASTEXITCODE -ne 0) { Die "Installed, but 'cleanly --version' failed." }
Ok "$version is ready"

Write-Host ""
Write-Host "Open a new PowerShell window, then try:"
Write-Host "  cleanly `"$src\examples\sample.txt`""
Write-Host "Update:  run this installer again"
Write-Host "Remove:  & `"$src\install.ps1`" -Uninstall"
