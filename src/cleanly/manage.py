"""`cleanly update` and `cleanly uninstall`: hand over to the installer that set Cleanly up."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .ui import console, err_console

MARKER = ".cleanly-installed"


def install_root() -> Path | None:
    """The folder the one-line installer created, or None for a pip/dev install."""
    venv = Path(sys.prefix)
    if venv.name != ".venv":
        return None
    root = venv.parent
    # The installers leave this marker. Without it, this could be someone's
    # development folder, which must never be deleted or reset.
    if (root / MARKER).is_file():
        return root
    return None


def _not_installer() -> int:
    err_console.print("[warn]Cleanly wasn't set up with the one-line installer here.[/]")
    err_console.print("  If you used pip:  [accent]pip install -U cleanly-censorship[/] to update, "
                      "[accent]pip uninstall cleanly-censorship[/] to remove.")
    return 1


def _run_installer(root: Path, extra: list[str]) -> int:
    if sys.platform == "win32":
        script = root / "src-repo" / "install.ps1"
        # Cleanly can't replace or delete itself while it's running, so the
        # installer starts in a new window a moment after this process exits.
        args = " ".join(extra)
        cmd = (f"Start-Sleep -Seconds 2; & '{script}' -Dir '{root}' {args}; "
               "Write-Host ''; Read-Host 'Press Enter to close'")
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        console.print("[dim]Continuing in a new window…[/]")
        return 0

    script = root / "install.sh"
    # The update rewrites install.sh itself, so run a copy.
    tmp = Path(tempfile.mkdtemp()) / "install.sh"
    shutil.copy2(script, tmp)
    os.execvp("bash", ["bash", str(tmp), "--dir", str(root), *extra])
    return 0  # not reached


def update() -> int:
    root = install_root()
    if root is None:
        return _not_installer()
    console.print("[brand]updating cleanly…[/]")
    return _run_installer(root, [])


def uninstall(yes: bool = False) -> int:
    root = install_root()
    if root is None:
        return _not_installer()
    if not yes:
        if not sys.stdin.isatty():
            err_console.print("Run [accent]cleanly uninstall --yes[/] to confirm.")
            return 1
        import questionary
        if not questionary.confirm(f"Remove Cleanly from {root}? Your saved word list stays.",
                                   default=False).ask():
            console.print("[dim]kept it ✌️[/]")
            return 0
    flag = "-Uninstall" if sys.platform == "win32" else "--uninstall"
    return _run_installer(root, [flag])
