#!/usr/bin/env bash
# Cleanly installer for Linux (Debian/Ubuntu/Kali, Fedora, Arch, openSUSE).
#
#   curl -fsSL https://raw.githubusercontent.com/damasiyachiranj/cleanly-censorship/main/install.sh | bash
#
# What it does:
#   1. Checks for Python 3.10+, Git and FFmpeg; installs any that are missing
#      with your package manager (asks for your sudo password once, if needed).
#   2. Downloads Cleanly to ~/.local/share/cleanly-censorship (or updates it).
#   3. Creates a private Python environment there and installs Cleanly into it.
#   4. Downloads and verifies the ML model (layer 2).
#   5. Puts the `cleanly` command on your PATH.
#
# Options (pass after `bash -s --` when piping, e.g. `... | bash -s -- --no-ffmpeg`):
#   --no-ffmpeg    don't install FFmpeg (only needed for audio/video)
#   --dir PATH     install somewhere else
#   --branch NAME  install a different branch (default: main)
#   --from PATH    install from a local copy of the code (for development)
#   --plain        no animations
#   --uninstall    remove Cleanly (leaves Python, Git and FFmpeg alone)

set -euo pipefail

REPO_URL="https://github.com/damasiyachiranj/cleanly-censorship"
BRANCH="main"
INSTALL_DIR="${CLEANLY_HOME:-$HOME/.local/share/cleanly-censorship}"
BIN_DIR="$HOME/.local/bin"
WANT_FFMPEG=1
UNINSTALL=0
FROM_DIR=""
ANIMATE=1

while [ $# -gt 0 ]; do
  case "$1" in
    --no-ffmpeg) WANT_FFMPEG=0 ;;
    --dir) INSTALL_DIR="$2"; shift ;;
    --branch) BRANCH="$2"; shift ;;
    --uninstall) UNINSTALL=1 ;;
    --from) FROM_DIR="$2"; shift ;;
    --plain) ANIMATE=0 ;;
    -h|--help) sed -n '2,24p' "$0" 2>/dev/null || echo "See $REPO_URL"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

# ---- Look and feel --------------------------------------------------------
if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
  BLUE=$'\033[1;34m'; RED=$'\033[1;31m'; GREEN=$'\033[1;32m'; YELLOW=$'\033[1;33m'
  MAGENTA=$'\033[1;35m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; RESET=$'\033[0m'; CLEAR=$'\r\033[K'
else
  BLUE=""; RED=""; GREEN=""; YELLOW=""; MAGENTA=""; DIM=""; BOLD=""; RESET=""; CLEAR=""
  ANIMATE=0
fi

FRAMES=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
# Playful verbs that rotate while a step runs.
VERBS=(Brewing Tinkering Wrangling Conjuring Assembling Polishing Untangling Summoning
       Cooking Vibing Calibrating Stitching Juggling Percolating Noodling Bootstrapping)
LOG="$(mktemp -t cleanly-install.XXXXXX)"
T_START=$SECONDS
PCT=0  # overall progress, 0-100

say()  { printf '%s==>%s %s\n' "$MAGENTA" "$RESET" "$*"; }
ok()   { printf '  %s✔%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  {
  printf '%s%serror:%s %s\n' "$CLEAR" "$RED" "$RESET" "$*" >&2
  if [ -s "$LOG" ]; then
    printf '%slast lines of the log (%s):%s\n' "$DIM" "$LOG" "$RESET" >&2
    tail -n 15 "$LOG" | sed 's/^/    /' >&2
  fi
  exit 1
}
have() { command -v "$1" >/dev/null 2>&1; }
fmt_time() { local s=$1; if [ "$s" -ge 60 ]; then printf '%dm %02ds' $((s / 60)) $((s % 60)); else printf '%ds' "$s"; fi; }

# run_step END_PCT EXPECTED_SECONDS "what is happening" command [args...]
# Runs the command in the background with its output in the log, while showing
#   ⠹ Brewing… what is happening   12s · 47%
# The percentage moves from the current value towards END_PCT; it's an estimate
# while the step runs and exact when it finishes.
run_step() {
  local end=$1 expected=$2 label=$3; shift 3
  local start=$PCT t0=$SECONDS i=0 rc=0 pid elapsed pct verb
  verb=${VERBS[$((RANDOM % ${#VERBS[@]}))]}
  echo "=== $label: $*" >>"$LOG"
  "$@" >>"$LOG" 2>&1 &
  pid=$!
  if [ "$ANIMATE" = 1 ]; then
    while kill -0 "$pid" 2>/dev/null; do
      elapsed=$((SECONDS - t0))
      # Ease towards END_PCT without ever claiming to be done early.
      pct=$((start + (end - start) * elapsed / (elapsed + expected)))
      if [ $((i % 30)) -eq 29 ]; then verb=${VERBS[$((RANDOM % ${#VERBS[@]}))]}; fi
      printf '%s%s%s%s %s… %s  %s%s · %d%%%s' "$CLEAR" "$MAGENTA" "${FRAMES[$((i % 10))]}" "$RESET" \
        "$verb" "$label" "$BLUE" "$(fmt_time "$elapsed")" "$pct" "$RESET"
      i=$((i + 1))
      sleep 0.1
    done
  fi
  if wait "$pid"; then rc=0; else rc=$?; fi
  elapsed=$((SECONDS - t0))
  if [ "$rc" -eq 0 ]; then
    PCT=$end
    printf '%s  %s✔%s %s  %s%s · %d%%%s\n' "$CLEAR" "$GREEN" "$RESET" "$label" "$BLUE" "$(fmt_time "$elapsed")" "$PCT" "$RESET"
  else
    printf '%s  %s✘%s %s  %s%s%s\n' "$CLEAR" "$RED" "$RESET" "$label" "$DIM" "$(fmt_time "$elapsed")" "$RESET"
  fi
  return "$rc"
}

# ---- Uninstall --------------------------------------------------------------
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

printf '\n%scleanly%s ✨ %sinstaller%s\n\n' "$MAGENTA$BOLD" "$RESET" "$DIM" "$RESET"

# ---- What's missing? ----------------------------------------------------------
SUDO=""
if [ "$(id -u)" -ne 0 ]; then have sudo && SUDO="sudo"; fi
PM=""
for p in apt-get dnf pacman zypper; do have "$p" && { PM="$p"; break; }; done

find_python() {
  for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if have "$c" && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}

# Package names per manager, in the order apt dnf pacman zypper.
NEED_APT=""; NEED_DNF=""; NEED_PACMAN=""; NEED_ZYPPER=""; NEED_WHAT=""
need() { NEED_APT+=" $1"; NEED_DNF+=" $2"; NEED_PACMAN+=" $3"; NEED_ZYPPER+=" $4"; NEED_WHAT+=", $5"; }

PY="$(find_python || true)"
if [ -z "$PY" ]; then
  need "python3 python3-venv python3-pip" "python3 python3-pip" "python python-pip" "python3 python3-pip" "Python"
elif ! "$PY" -m venv --help >/dev/null 2>&1 || ! "$PY" -c 'import ensurepip' >/dev/null 2>&1; then
  ver="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
  need "python3-venv python$ver-venv" "" "" "" "Python venv"
fi
if [ "$WANT_FFMPEG" = 1 ] && ! have ffmpeg; then need ffmpeg ffmpeg-free ffmpeg ffmpeg FFmpeg; fi
if [ -z "$FROM_DIR" ] && ! have git && ! [ -d "$INSTALL_DIR/.git" ]; then need git git git git Git; fi

# shellcheck disable=SC2086  # package lists are split on purpose
install_packages() {
  case "$PM" in
    apt-get) $SUDO apt-get update -qq && $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $NEED_APT ;;
    dnf)     $SUDO dnf install -y -q $NEED_DNF ;;
    pacman)  $SUDO pacman -S --needed --noconfirm $NEED_PACMAN ;;
    zypper)  $SUDO zypper --non-interactive install $NEED_ZYPPER ;;
    *) return 1 ;;
  esac
}

if [ -n "$NEED_WHAT" ]; then
  what="${NEED_WHAT#, }"
  [ -n "$PM" ] || die "Please install $what yourself (no supported package manager found), then run this again."
  if [ -n "$SUDO" ] && ! sudo -n true 2>/dev/null; then
    say "Cleanly needs to install $what. Your sudo password, please:"
    sudo -v || die "Couldn't get sudo access to install $what."
  elif [ "$(id -u)" -ne 0 ] && [ -z "$SUDO" ]; then
    die "Please install $what yourself (sudo isn't available), then run this again."
  fi
  if ! run_step 25 40 "installing $what" install_packages; then
    case "$what" in
      FFmpeg) warn "Couldn't install FFmpeg. Text files still work; install it later for audio/video." ;;
      *) die "Couldn't install $what." ;;
    esac
  fi
  PY="$(find_python)" || die "Python 3.10 or newer is required, but it couldn't be installed."
else
  PCT=25
  ok "Python, Git and FFmpeg already here  ${BLUE}0s · ${PCT}%${RESET}"
fi

# ---- Download or update Cleanly -------------------------------------------------
mkdir -p "$(dirname "$INSTALL_DIR")"
get_from_dir() {
  [ -f "$FROM_DIR/pyproject.toml" ] || { echo "$FROM_DIR doesn't look like a Cleanly folder"; return 1; }
  rm -rf "$INSTALL_DIR" && mkdir -p "$INSTALL_DIR"
  tar -C "$FROM_DIR" --exclude=.venv --exclude=.git --exclude=build --exclude=.pytest_cache \
      --exclude='*.egg-info' -cf - . | tar -C "$INSTALL_DIR" -xf -
}
update_git() {
  git -C "$INSTALL_DIR" fetch --quiet origin "$BRANCH" &&
  git -C "$INSTALL_DIR" checkout --quiet "$BRANCH" &&
  git -C "$INSTALL_DIR" reset --quiet --hard "origin/$BRANCH"
}
fresh_download() {
  rm -rf "$INSTALL_DIR"
  if have git; then
    git clone --quiet --depth 1 --branch "$BRANCH" "$REPO_URL.git" "$INSTALL_DIR"
  else
    local tmp url
    tmp="$(mktemp -d)"
    url="$REPO_URL/archive/refs/heads/$BRANCH.tar.gz"
    if have curl; then curl -fsSL "$url" -o "$tmp/src.tar.gz"; else wget -q "$url" -O "$tmp/src.tar.gz"; fi
    mkdir -p "$INSTALL_DIR"
    tar -xzf "$tmp/src.tar.gz" -C "$INSTALL_DIR" --strip-components=1
    rm -rf "$tmp"
  fi
}
if [ -n "$FROM_DIR" ]; then
  run_step 32 3 "copying Cleanly from $FROM_DIR" get_from_dir || die "Couldn't copy from $FROM_DIR."
elif [ -d "$INSTALL_DIR/.git" ] && have git; then
  run_step 32 5 "fetching the latest Cleanly" update_git || die "Couldn't update. Check your internet connection."
else
  run_step 32 8 "downloading Cleanly" fresh_download || die "Couldn't download Cleanly. Check your internet connection."
fi

# ---- Private Python environment -------------------------------------------------
VENV="$INSTALL_DIR/.venv"
make_venv() { "$PY" -m venv "$VENV" && "$VENV/bin/python" -m pip install --quiet --upgrade pip; }
run_step 42 10 "creating a private Python environment" make_venv || die "Couldn't create the Python environment."
run_step 80 45 "installing Python packages (ONNX Runtime, tokenizers…)" \
  "$VENV/bin/python" -m pip install --quiet "$INSTALL_DIR" || die "Couldn't install Cleanly's Python packages."

# ---- ML model (layer 2, mandatory), shown in red with real download progress -----
download_model() {
  local info dir total pid t0=$SECONDS i=0 got pct elapsed rc
  info="$("$VENV/bin/cleanly" models path 2>/dev/null)" || { warn "Couldn't check the ML model."; return 0; }
  dir="${info%%$'\t'*}"; total="${info##*$'\t'}"
  echo "=== ML model: $dir" >>"$LOG"
  "$VENV/bin/cleanly" models download >>"$LOG" 2>&1 &
  pid=$!
  if [ "$ANIMATE" = 1 ]; then
    while kill -0 "$pid" 2>/dev/null; do
      got=$( (du -cb "$dir" 2>/dev/null || true) | tail -n 1 | cut -f1); got=${got:-0}
      [ "$got" -gt "$total" ] && got=$total
      elapsed=$((SECONDS - t0))
      pct=$((80 + 18 * got / total))
      printf '%s%s%s %s %s/%s MB%s  %s · %d%%%s' "$CLEAR" "$RED" "${FRAMES[$((i % 10))]}" \
        "Downloading the ML brain… verifying every byte" \
        "$(awk "BEGIN{printf \"%.1f\", $got/1048576}")" "$(awk "BEGIN{printf \"%.1f\", $total/1048576}")" \
        "$RESET$BLUE" "$(fmt_time "$elapsed")" "$pct" "$RESET"
      i=$((i + 1))
      sleep 0.1
    done
  fi
  if wait "$pid"; then rc=0; else rc=$?; fi
  elapsed=$((SECONDS - t0))
  if [ "$rc" -eq 0 ]; then
    PCT=98
    printf '%s  %s✔ ML model downloaded and verified%s  %s%s · %d%%%s\n' "$CLEAR" "$RED" "$RESET" "$BLUE" "$(fmt_time "$elapsed")" "$PCT" "$RESET"
  else
    printf '%s' "$CLEAR"
    if grep -q "integrity check" "$LOG"; then
      warn "The downloaded ML model did NOT match its fingerprint, so it was deleted and not used."
      warn "That can mean a broken download or tampering. Run 'cleanly models download' later to retry."
    else
      warn "Couldn't download the ML model now. Cleanly will try again the first time you run it."
    fi
  fi
}
download_model

# ---- Finish up --------------------------------------------------------------------
# Marks this folder as installer-managed, so `cleanly update/uninstall` may touch it.
echo "Installed by install.sh. Safe to remove with: cleanly uninstall" > "$INSTALL_DIR/.cleanly-installed"
mkdir -p "$BIN_DIR"
ln -sf "$VENV/bin/cleanly" "$BIN_DIR/cleanly"
version="$("$BIN_DIR/cleanly" --version)" || die "Installed, but 'cleanly --version' failed."

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
          RC_USED="$rc"
        fi
      fi
    done
    NEED_NEW_TERMINAL=1
    ;;
esac
PCT=100
ok "added the cleanly command${RC_USED:+ (PATH set in $RC_USED)}  ${BLUE}0s · ${PCT}%${RESET}"

printf '\n%s✨ %s installed in %s%s%s\n\n' "$GREEN$BOLD" "$version" "$BLUE" "$(fmt_time $((SECONDS - T_START)))" "$RESET"
if [ "$NEED_NEW_TERMINAL" = 1 ]; then
  echo "Open a new terminal (or run: source ${RC_USED:-~/.bashrc}), then:"
else
  echo "Ready! Try:"
fi
echo "  cleanly start       guided mode"
echo "  cleanly help        all commands"
echo "Update:  cleanly update      Remove:  cleanly uninstall"
rm -f "$LOG"
