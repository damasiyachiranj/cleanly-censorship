#!/usr/bin/env bash
# Cleanly installer for Linux (Debian/Ubuntu/Kali, Fedora, Arch, openSUSE).
#
#   curl -fsSL https://raw.githubusercontent.com/damasiyachiranj/cleanly-censorship/main/install.sh | bash
#
# What it does:
#   1. Checks for Python 3.10+, Git and FFmpeg; installs any that are missing
#      with your package manager (asks for your sudo password if needed).
#   2. Downloads Cleanly to ~/.local/share/cleanly-censorship (or updates it).
#   3. Creates a private Python environment there and installs Cleanly into it.
#   4. Puts the `cleanly` command in ~/.local/bin.
#
# Options (pass after `bash -s --` when piping, e.g. `... | bash -s -- --no-ffmpeg`):
#   --no-ffmpeg    don't install FFmpeg (only needed for audio/video)
#   --dir PATH     install somewhere else
#   --branch NAME  install a different branch (default: main)
#   --from PATH    install from a local copy of the code (for development)
#   --uninstall    remove Cleanly (leaves Python, Git and FFmpeg alone)

set -euo pipefail

REPO_URL="https://github.com/damasiyachiranj/cleanly-censorship"
BRANCH="main"
INSTALL_DIR="${CLEANLY_HOME:-$HOME/.local/share/cleanly-censorship}"
BIN_DIR="$HOME/.local/bin"
WANT_FFMPEG=1
UNINSTALL=0
FROM_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --no-ffmpeg) WANT_FFMPEG=0 ;;
    --dir) INSTALL_DIR="$2"; shift ;;
    --branch) BRANCH="$2"; shift ;;
    --uninstall) UNINSTALL=1 ;;
    --from) FROM_DIR="$2"; shift ;;
    -h|--help) sed -n '2,22p' "$0" 2>/dev/null || echo "See $REPO_URL"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ok\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  !\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

if [ "$UNINSTALL" = 1 ]; then
  say "Removing Cleanly from $INSTALL_DIR"
  rm -rf "$INSTALL_DIR"
  rm -f "$BIN_DIR/cleanly"
  for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ -f "$rc" ] && grep -qF "# added by cleanly installer" "$rc"; then
      sed -i '/# added by cleanly installer/d' "$rc"
    fi
  done
  ok "Removed. Python, Git and FFmpeg were left installed. Your saved word list (~/.config/cleanly) was kept."
  exit 0
fi

[ "$(uname -s)" = "Linux" ] || die "This installer is for Linux. On Windows use install.ps1."

# ---- package manager -------------------------------------------------------
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  have sudo && SUDO="sudo" || warn "sudo not found: missing software can't be installed automatically."
fi

PM=""
for p in apt-get dnf pacman zypper; do have "$p" && { PM="$p"; break; }; done

APT_UPDATED=0
# Package names are passed as space-separated lists and split on purpose.
# shellcheck disable=SC2086
pkg_install() {  # pkg_install <apt names> <dnf names> <pacman names> <zypper names>
  case "$PM" in
    apt-get)
      if [ "$APT_UPDATED" = 0 ]; then $SUDO apt-get update -qq; APT_UPDATED=1; fi
      $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $1 ;;
    dnf)    [ -n "$2" ] && $SUDO dnf install -y -q $2 ;;
    pacman) [ -n "$3" ] && $SUDO pacman -S --needed --noconfirm $3 ;;
    zypper) [ -n "$4" ] && $SUDO zypper --non-interactive install $4 ;;
    *) return 1 ;;
  esac
}

# ---- Python 3.10+ ----------------------------------------------------------
find_python() {
  for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if have "$c" && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}

say "Checking Python 3.10+"
if ! PY="$(find_python)"; then
  say "Installing Python"
  pkg_install "python3 python3-venv python3-pip" "python3 python3-pip" "python python-pip" "python3 python3-pip" \
    || die "Couldn't install Python. Install Python 3.10 or newer, then run this again."
  PY="$(find_python)" || die "Python 3.10 or newer is required, but the installed version is older."
fi
ok "$("$PY" --version)"

# Debian/Ubuntu/Kali ship venv separately.
if ! "$PY" -m venv --help >/dev/null 2>&1 || ! "$PY" -c 'import ensurepip' >/dev/null 2>&1; then
  say "Installing Python venv support"
  ver="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
  pkg_install "python3-venv python$ver-venv" "python3" "python" "python3" || pkg_install "python3-venv" "" "" "" \
    || die "Couldn't install Python venv support (python3-venv)."
fi

# ---- FFmpeg (audio/video) --------------------------------------------------
if [ "$WANT_FFMPEG" = 1 ]; then
  say "Checking FFmpeg"
  if have ffmpeg; then
    ok "FFmpeg found"
  else
    say "Installing FFmpeg"
    if pkg_install "ffmpeg" "ffmpeg-free" "ffmpeg" "ffmpeg"; then
      ok "FFmpeg installed"
    else
      warn "Couldn't install FFmpeg. Text files still work; install FFmpeg later for audio/video."
    fi
  fi
fi

# ---- Download or update Cleanly ------------------------------------------
mkdir -p "$(dirname "$INSTALL_DIR")"
if [ -n "$FROM_DIR" ]; then
  say "Copying Cleanly from $FROM_DIR into $INSTALL_DIR"
  [ -f "$FROM_DIR/pyproject.toml" ] || die "$FROM_DIR doesn't look like a Cleanly folder."
  rm -rf "$INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"
  tar -C "$FROM_DIR" --exclude=.venv --exclude=.git --exclude=build --exclude=.pytest_cache --exclude='*.egg-info' -cf - . | tar -C "$INSTALL_DIR" -xf -
  ok "Copied"
elif [ -d "$INSTALL_DIR/.git" ] && have git; then
  say "Updating Cleanly ($BRANCH) in $INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --quiet origin "$BRANCH"
  git -C "$INSTALL_DIR" checkout --quiet "$BRANCH"
  git -C "$INSTALL_DIR" reset --quiet --hard "origin/$BRANCH"
  ok "Updated to the latest version"
else
  say "Getting Cleanly ($BRANCH) into $INSTALL_DIR"
  if ! have git; then
    pkg_install "git" "git" "git" "git" >/dev/null 2>&1 || true
  fi
  rm -rf "$INSTALL_DIR"
  if have git; then
    git clone --quiet --depth 1 --branch "$BRANCH" "$REPO_URL.git" "$INSTALL_DIR"
  else
    # No Git: download the source archive instead.
    have curl || have wget || die "Need git, curl or wget to download Cleanly."
    tmp="$(mktemp -d)"
    url="$REPO_URL/archive/refs/heads/$BRANCH.tar.gz"
    if have curl; then
      curl -fsSL "$url" -o "$tmp/src.tar.gz" || die "Couldn't download $url. Check your internet connection."
    else
      wget -q "$url" -O "$tmp/src.tar.gz" || die "Couldn't download $url. Check your internet connection."
    fi
    mkdir -p "$INSTALL_DIR"
    tar -xzf "$tmp/src.tar.gz" -C "$INSTALL_DIR" --strip-components=1
    rm -rf "$tmp"
  fi
  ok "Downloaded"
fi

# ---- Private Python environment -------------------------------------------
say "Installing Cleanly into its own Python environment"
"$PY" -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/python" -m pip install --quiet "$INSTALL_DIR"
ok "Installed"

# ---- ML model (layer 2, mandatory) -----------------------------------------
say "Downloading the ML model (one-time, ~23 MB, verified)"
if "$INSTALL_DIR/.venv/bin/cleanly" models download; then
  ok "ML model ready"
else
  warn "Couldn't download the ML model now. Cleanly will try again the first time you run it."
fi

# Marks this folder as installer-managed, so `cleanly update/uninstall` may touch it.
echo "Installed by install.sh. Safe to remove with: cleanly uninstall" > "$INSTALL_DIR/.cleanly-installed"

# ---- `cleanly` command ----------------------------------------------------
mkdir -p "$BIN_DIR"
ln -sf "$INSTALL_DIR/.venv/bin/cleanly" "$BIN_DIR/cleanly"

version="$("$BIN_DIR/cleanly" --version)" || die "Installed, but 'cleanly --version' failed."
ok "$version is ready"

PATH_LINE='export PATH="$HOME/.local/bin:$PATH"  # added by cleanly installer'
NEED_NEW_TERMINAL=0
RC_USED=""
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    # Add ~/.local/bin to PATH in the shells you use (zsh is Kali's default).
    for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
      shell_name="$(basename "$rc" | tr -d '.' | sed 's/rc$//')"
      if [ -f "$rc" ] || [ "$(basename "${SHELL:-}")" = "$shell_name" ]; then
        if ! grep -qF "# added by cleanly installer" "$rc" 2>/dev/null; then
          printf '\n%s\n' "$PATH_LINE" >> "$rc"
          ok "Added cleanly to your PATH in $rc"
          RC_USED="$rc"
        fi
      fi
    done
    NEED_NEW_TERMINAL=1
    ;;
esac

echo
if [ "$NEED_NEW_TERMINAL" = 1 ]; then
  echo "Open a new terminal (or run: source ${RC_USED:-~/.bashrc}), then:"
else
  echo "Ready! Try:"
fi
echo "  cleanly start       guided mode"
echo "  cleanly help        all commands"
echo "Update:  cleanly update      Remove:  cleanly uninstall"
