# Cleanly installer for Windows 10/11 (PowerShell 5.1 or 7+).
#
#   irm https://raw.githubusercontent.com/damasiyachiranj/cleanly-censorship/main/install.ps1 | iex
#
# What it does:
#   1. Checks for Python 3.10+ and FFmpeg; installs any that are missing with
#      winget (Windows' built-in package manager), for your user only.
#   2. Downloads Cleanly to %LOCALAPPDATA%\cleanly-censorship (or updates it).
#   3. Creates a private Python environment there and installs Cleanly into it.
#   4. Downloads and verifies the ML model (layer 2).
#   5. Adds the `cleanly` command to your user PATH.
#
# Options (when piping, use:  & ([scriptblock]::Create((irm <url>))) -NoFfmpeg ):
#   -NoFfmpeg       don't install FFmpeg (only needed for audio/video)
#   -Dir <path>     install somewhere else
#   -Branch <name>  install a different branch (default: main)
#   -Plain          no animations
#   -Uninstall      remove Cleanly (leaves Python and FFmpeg alone)
#
# This file is plain ASCII on purpose: Windows PowerShell 5.1 can garble other
# characters when it reads a script from disk.

param(
    [switch]$NoFfmpeg,
    [string]$Dir = "$env:LOCALAPPDATA\cleanly-censorship",
    [string]$Branch = "main",
    [switch]$Plain,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/damasiyachiranj/cleanly-censorship"
$BinDir = Join-Path $Dir "bin"

# ---- Look and feel ----------------------------------------------------------
$Animate = (-not $Plain) -and (-not [Console]::IsOutputRedirected)
$Frames = @("|", "/", "-", "\")
# Playful verbs that rotate while a step runs.
$Verbs = @("Brewing", "Tinkering", "Wrangling", "Conjuring", "Assembling", "Polishing", "Untangling",
           "Summoning", "Cooking", "Vibing", "Calibrating", "Stitching", "Juggling", "Percolating",
           "Noodling", "Bootstrapping")
$Script:Pct = 0
$Script:Started = Get-Date
$Script:Log = Join-Path $env:TEMP ("cleanly-install-" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".log")

function Say($m)  { Write-Host "==> " -ForegroundColor Magenta -NoNewline; Write-Host $m }
function Ok($m)   { Write-Host "  OK " -ForegroundColor Green -NoNewline; Write-Host $m }
function Warn($m) { Write-Host "  !  $m" -ForegroundColor Yellow }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

function Die($m) {
    Clear-Line
    Write-Host "error: $m" -ForegroundColor Red
    if (Test-Path $Script:Log) {
        Write-Host "last lines of the log ($($Script:Log)):" -ForegroundColor DarkGray
        Get-Content $Script:Log -Tail 15 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
    throw $m
}

function Format-Time([int]$s) {
    if ($s -ge 60) { return "{0}m {1:D2}s" -f [int][math]::Floor($s / 60), ($s % 60) }
    return "${s}s"
}

function Get-Width {
    try { return [Math]::Max(40, [Console]::WindowWidth - 1) } catch { return 100 }
}

function Clear-Line {
    if ($Animate) { [Console]::Write("`r" + (" " * (Get-Width)) + "`r") }
}

function Join-Args([string[]]$Arguments) {
    # Start-Process joins arguments with spaces, so quote any that contain spaces.
    ($Arguments | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join " "
}

function Write-Done([bool]$Success, [string]$Label, [int]$Seconds, [string]$Color = "Green") {
    Clear-Line
    if ($Success) {
        Write-Host "  OK " -ForegroundColor $Color -NoNewline
        Write-Host "$Label  " -NoNewline
        Write-Host ("{0} - {1}%" -f (Format-Time $Seconds), $Script:Pct) -ForegroundColor Blue
    } else {
        Write-Host "  X  " -ForegroundColor Red -NoNewline
        Write-Host "$Label  " -NoNewline
        Write-Host (Format-Time $Seconds) -ForegroundColor DarkGray
    }
}

# Invoke-Step: run a program in the background (its output goes to the log) while showing
#   / Brewing... installing Python packages   12s - 47%
# The percentage moves towards EndPct while the step runs (an estimate) and is exact
# once it finishes. -Progress can supply real progress instead (used for the ML model).
function Invoke-Step {
    param(
        [int]$EndPct, [int]$Expected, [string]$Label, [string]$Exe, [string[]]$Arguments,
        [string]$Color = "Magenta", [scriptblock]$Progress
    )
    $start = $Script:Pct
    $t0 = Get-Date
    $verb = Get-Random -InputObject $Verbs
    $out = "$($Script:Log).out"
    $err = "$($Script:Log).err"
    Add-Content -Path $Script:Log -Value "=== $Label : $Exe $($Arguments -join ' ')"
    try {
        $p = Start-Process -FilePath $Exe -ArgumentList (Join-Args $Arguments) -NoNewWindow -PassThru `
            -RedirectStandardOutput $out -RedirectStandardError $err
    } catch {
        Add-Content -Path $Script:Log -Value "could not start ${Exe}: $_"
        Write-Done $false $Label 0
        return $false
    }
    $null = $p.Handle  # keeps ExitCode available after the process ends (PowerShell 5.1 quirk)
    $i = 0
    while (-not $p.HasExited) {
        if ($Animate) {
            $el = [int]((Get-Date) - $t0).TotalSeconds
            if ($i % 30 -eq 29) { $verb = Get-Random -InputObject $Verbs }
            if ($Progress) {
                $info = & $Progress            # returns @{ Pct = ..; Text = .. }
                $pct = $info.Pct
                $text = $info.Text
            } else {
                $pct = $start + [int](($EndPct - $start) * $el / ($el + $Expected))
                $text = "$verb... $Label"
            }
            $timer = "  {0} - {1}%" -f (Format-Time $el), $pct
            $room = (Get-Width) - $timer.Length - 3
            if ($text.Length -gt $room) { $text = $text.Substring(0, [Math]::Max(10, $room - 3)) + "..." }
            [Console]::Write("`r")
            Write-Host ($Frames[$i % 4] + " ") -ForegroundColor $Color -NoNewline
            Write-Host $text -NoNewline -ForegroundColor $(if ($Progress) { $Color } else { "Gray" })
            Write-Host $timer -NoNewline -ForegroundColor Blue
            Write-Host (" " * [Math]::Max(0, $room - $text.Length)) -NoNewline
        }
        $i++
        Start-Sleep -Milliseconds 120
    }
    $p.WaitForExit()
    $code = $p.ExitCode
    foreach ($f in @($out, $err)) {
        if (Test-Path $f) { Get-Content $f | Add-Content -Path $Script:Log; Remove-Item $f -Force }
    }
    $secs = [int]((Get-Date) - $t0).TotalSeconds
    if ($code -eq 0) {
        $Script:Pct = $EndPct
        Write-Done $true $Label $secs $(if ($Progress) { $Color } else { "Green" })
        return $true
    }
    Add-Content -Path $Script:Log -Value "exit code $code"
    Write-Done $false $Label $secs
    return $false
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

# ---- Uninstall --------------------------------------------------------------
if ($Uninstall) {
    Say "Removing Cleanly from $Dir"
    Remove-FromUserPath $BinDir
    if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir }
    Ok "Removed. Python and FFmpeg were left installed. Your saved word list (%APPDATA%\cleanly) was kept."
    return
}

# Older Windows PowerShell needs this to talk to GitHub.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

Write-Host ""
Write-Host "cleanly" -ForegroundColor Magenta -NoNewline
Write-Host " installer" -ForegroundColor DarkGray
Write-Host ""

# ---- Python 3.10+ and FFmpeg ----------------------------------------------------
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

function Install-WithWinget([string]$Id, [string]$Name, [int]$EndPct) {
    if (-not (Have "winget")) {
        Die "winget isn't available, so $Name can't be installed automatically. Install 'App Installer' from the Microsoft Store, or install $Name yourself, then run this again."
    }
    $common = @("install", "--id", $Id, "--exact", "--silent", "--accept-package-agreements", "--accept-source-agreements")
    $ok = Invoke-Step $EndPct 60 "installing $Name (winget)" "winget" ($common + @("--scope", "user"))
    if (-not $ok) {
        # Some packages don't support per-user installs; try the default scope.
        $ok = Invoke-Step $EndPct 60 "installing $Name (winget, all users)" "winget" $common
    }
    Update-SessionPath
    return $ok
}

$py = Find-Python
$needFfmpeg = (-not $NoFfmpeg) -and (-not (Have "ffmpeg"))
if ($py -and -not $needFfmpeg) {
    $Script:Pct = 25
    Write-Done $true "Python and FFmpeg already here" 0
}
if (-not $py) {
    if (-not (Install-WithWinget "Python.Python.3.12" "Python 3.12" 15)) { Die "Couldn't install Python." }
    $py = Find-Python
    if (-not $py) {
        # A fresh per-user install may not be on PATH in this window yet.
        $direct = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
        if (Test-Path $direct) { $py = @{ Exe = $direct; Pre = @() } }
    }
    if (-not $py) { Die "Python was installed but can't be found yet. Open a new PowerShell window and run this again." }
}
if ($needFfmpeg) {
    if (-not (Install-WithWinget "Gyan.FFmpeg" "FFmpeg" 25)) {
        Warn "Couldn't install FFmpeg. Text files still work; install it later for audio/video."
    }
}
$Script:Pct = [Math]::Max($Script:Pct, 25)

# ---- Download or update Cleanly ---------------------------------------------------
$src = Join-Path $Dir "src-repo"
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
if ((Test-Path (Join-Path $src ".git")) -and (Have "git")) {
    $ok = (Invoke-Step 28 5 "fetching the latest Cleanly" "git" @("-C", $src, "fetch", "--quiet", "origin", $Branch)) -and
          (Invoke-Step 30 2 "switching to $Branch" "git" @("-C", $src, "checkout", "--quiet", $Branch)) -and
          (Invoke-Step 32 2 "applying the update" "git" @("-C", $src, "reset", "--quiet", "--hard", "origin/$Branch"))
    if (-not $ok) { Die "Couldn't update. Check your internet connection." }
} else {
    if (Test-Path $src) { Remove-Item -Recurse -Force $src }
    if (Have "git") {
        if (-not (Invoke-Step 32 8 "downloading Cleanly" "git" @("clone", "--quiet", "--depth", "1", "--branch", $Branch, "$RepoUrl.git", $src))) {
            Die "Couldn't download Cleanly. Check your internet connection."
        }
    } else {
        # No Git needed: download the source as a zip (curl.exe ships with Windows 10 and 11).
        $zip = Join-Path $env:TEMP "cleanly-$Branch.zip"
        $tmp = Join-Path $env:TEMP "cleanly-$Branch-extract"
        $url = "$RepoUrl/archive/refs/heads/$Branch.zip"
        if (Have "curl.exe") {
            $ok = Invoke-Step 30 8 "downloading Cleanly" "curl.exe" @("-fsSL", "-o", $zip, $url)
        } else {
            try { Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip; $ok = $true } catch { $ok = $false }
        }
        if (-not $ok) { Die "Couldn't download Cleanly from GitHub. Check your internet connection." }
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $inner = Get-ChildItem $tmp | Select-Object -First 1
        Move-Item $inner.FullName $src
        Remove-Item -Force $zip
        Remove-Item -Recurse -Force $tmp
        $Script:Pct = 32
        Ok "unpacked Cleanly"
    }
}

# ---- Private Python environment ---------------------------------------------------
$venv = Join-Path $Dir ".venv"
$venvPy = Join-Path $venv "Scripts\python.exe"
if (-not (Invoke-Step 38 10 "creating a private Python environment" $py.Exe ($py.Pre + @("-m", "venv", $venv)))) {
    Die "Couldn't create the Python environment."
}
if (-not (Invoke-Step 42 10 "updating pip" $venvPy @("-m", "pip", "install", "--quiet", "--upgrade", "pip"))) {
    Die "Couldn't update pip."
}
if (-not (Invoke-Step 80 45 "installing Python packages (ONNX Runtime, tokenizers...)" $venvPy @("-m", "pip", "install", "--quiet", $src))) {
    Die "Couldn't install Cleanly's Python packages."
}

# ---- ML model (layer 2, mandatory), shown in red with real download progress -------
$cleanlyExe = Join-Path $venv "Scripts\cleanly.exe"
$info = (& $cleanlyExe models path) -split "`t"
$Script:ModelDir = $info[0]
$Script:ModelTotal = [double]$info[1]
$Script:ModelStart = Get-Date
$modelProgress = {
    $got = 0
    if (Test-Path $Script:ModelDir) {
        $sum = (Get-ChildItem $Script:ModelDir -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
        if ($sum) { $got = [Math]::Min([double]$sum, $Script:ModelTotal) }
    }
    $mb = "{0:N1}/{1:N1} MB" -f ($got / 1MB), ($Script:ModelTotal / 1MB)
    @{ Pct = 80 + [int](18 * $got / $Script:ModelTotal); Text = "Downloading the ML brain... verifying every byte $mb" }
}
$modelOk = Invoke-Step 98 20 "ML model downloaded and verified" $cleanlyExe @("models", "download") -Color "Red" -Progress $modelProgress
if (-not $modelOk) {
    if (Select-String -Path $Script:Log -Pattern "integrity check" -Quiet) {
        Warn "The downloaded ML model did NOT match its fingerprint, so it was deleted and not used."
        Warn "That can mean a broken download or tampering. Run 'cleanly models download' later to retry."
    } else {
        Warn "Couldn't download the ML model now. Cleanly will try again the first time you run it."
    }
}

# ---- Finish up ------------------------------------------------------------------
# Marks this folder as installer-managed, so `cleanly update/uninstall` may touch it.
Set-Content -Path (Join-Path $Dir ".cleanly-installed") -Value "Installed by install.ps1. Safe to remove with: cleanly uninstall"

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
}
$env:Path = "$env:Path;$BinDir"

$version = & $shim --version
if ($LASTEXITCODE -ne 0) { Die "Installed, but 'cleanly --version' failed." }
$Script:Pct = 100
Write-Done $true "added the cleanly command to your PATH" 0

$total = [int]((Get-Date) - $Script:Started).TotalSeconds
Write-Host ""
Write-Host "  $version installed in " -ForegroundColor Green -NoNewline
Write-Host (Format-Time $total) -ForegroundColor Blue
Write-Host ""
Write-Host "Open a new PowerShell window, then:"
Write-Host "  cleanly start       guided mode"
Write-Host "  cleanly help        all commands"
Write-Host "Update:  cleanly update      Remove:  cleanly uninstall"
Remove-Item -Force $Script:Log -ErrorAction SilentlyContinue
