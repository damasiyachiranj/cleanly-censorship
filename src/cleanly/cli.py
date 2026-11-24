"""The `cleanly` command.

  cleanly                 same as `cleanly start`
  cleanly start           guided mode: asks you everything, one question at a time
  cleanly do FILE [opts]  clean a file in one line
  cleanly update          get the latest version
  cleanly uninstall       remove Cleanly
  cleanly help            show help
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .job import TEXT_KINDS, Job, run, summarize
from .text import EFFECTS
from .ui import Tone, console, err_console
from .wordlist import BASES, MODES, Entry, UserList, load_saved


def _safe_console() -> None:
    """Never crash on characters the console can't show (e.g. Windows cp1252 when output is redirected)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def show_help() -> None:
    console.print(f"""
[brand]cleanly[/] {__version__} ✨ [dim]find bad words, cover them, keep everything else[/]

[bold]easiest[/]
  [accent]cleanly start[/]              guided mode, asks you everything step by step

[bold]one-liners[/]
  [accent]cleanly do FILE[/]            clean a file (Strict mode, d*** style)
    [dim]-m, --mode[/]   strict [dim](kids)[/] · standard [dim](adults)[/] · customize
    [dim]-e, --effect[/] stars [dim]d***[/] · full [dim]****[/] · symbol [dim]♪[/] · replace [dim](+ --replacement WORD)[/]
    [dim]-o, --output[/] where to save   [dim]-r, --report[/] save a report of every change
    [dim]customize:[/] --base strict|standard  --add w1,w2  --remove w3  [dim](or --list my_list.json)[/]

[bold]housekeeping[/]
  [accent]cleanly update[/]             get the latest version
  [accent]cleanly uninstall[/]          remove Cleanly
  [accent]cleanly version[/]

[bold]extras[/]  [dim]--plain[/] serious tone · [dim]--fast[/] no animations · [dim]--quiet[/] one-line output

[dim]examples:[/]
  cleanly do notes.txt
  cleanly do subs.srt -m standard -e symbol
  cleanly do chat.json -m customize --base standard --add frick --remove hell
""")


def _do_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cleanly do", add_help=False)
    p.add_argument("input")
    p.add_argument("-o", "--output")
    p.add_argument("-m", "--mode", choices=MODES, default="strict")
    p.add_argument("--base", choices=BASES)
    p.add_argument("--add", default="")
    p.add_argument("--remove", default="")
    p.add_argument("--list", dest="user_list")
    p.add_argument("-e", "--effect", choices=EFFECTS, default="stars")
    p.add_argument("--replacement", default="")
    p.add_argument("-r", "--report")
    p.add_argument("--language", default="en")
    p.add_argument("--plain", action="store_true")
    p.add_argument("--fast", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    return p


class _Fail(Exception):
    pass


def _parse_do(argv: list[str]):
    p = _do_parser()
    # Friendly errors instead of argparse's wall of text.
    p.error = lambda msg: (_ for _ in ()).throw(_Fail(msg))  # type: ignore[method-assign]
    return p.parse_args(argv)


def _split(s: str) -> list[str]:
    return [w.strip() for w in s.split(",") if w.strip()]


def cmd_do(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        show_help()
        return 0
    try:
        a = _parse_do(argv)
    except _Fail as e:
        err_console.print(f"[err]hmm:[/] {e}")
        err_console.print("[dim]see [accent]cleanly help[/] for options[/]")
        return 2

    src = Path(a.input).expanduser()
    if not src.is_file():
        err_console.print(f"[err]can't find[/] {src}")
        return 2
    if src.suffix.lower() not in TEXT_KINDS:
        err_console.print(f"[err]{src.suffix or 'that file type'} isn't supported yet.[/] "
                          f"This version handles {', '.join(TEXT_KINDS)}; audio and video are coming next.")
        return 2
    if a.effect == "replace" and not a.replacement:
        err_console.print("[err]--effect replace needs[/] --replacement WORD")
        return 2

    user = None
    if a.mode == "customize":
        try:
            if a.user_list:
                user = UserList.load(a.user_list)
            elif not (a.add or a.remove or a.base):
                user = load_saved()
        except (ValueError, json.JSONDecodeError) as e:
            err_console.print(f"[err]couldn't read your list:[/] {e}")
            return 2
        user = user or UserList()
        if a.base:
            user.base = a.base
        user.remove += [w.lower() for w in _split(a.remove)]
        user.add += [Entry(w, source="user") for w in _split(a.add)]

    out = Path(a.output).expanduser() if a.output else None
    if out and out.resolve() == src.resolve():
        err_console.print("[err]pick a different output name[/] so the original stays safe")
        return 2

    job = Job(input=src, language=a.language, mode=a.mode, user=user, effect=a.effect,
              replacement=a.replacement, output=out, report=Path(a.report) if a.report else None)
    tone = Tone(chill=not a.plain, animate=False if (a.fast or a.quiet) else None)

    try:
        if a.quiet:
            with console.capture():  # hide the step-by-step lines
                o = run(job, Tone(chill=False, animate=False))
            console.print(f"covered {len(o.matches)} word(s) -> {job.out_path()}")
            return 0
        o = run(job, tone)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        err_console.print(f"[err]couldn't finish:[/] {e}")
        return 2
    summarize(o, tone)
    return 0


def cmd_start(argv: list[str]) -> int:
    from .wizard import run_wizard

    plain = "--plain" in argv
    fast = "--fast" in argv
    if not sys.stdin.isatty():
        err_console.print("[err]guided mode needs an interactive terminal.[/] "
                          "Use [accent]cleanly do FILE[/] in scripts.")
        return 2
    tone = Tone(chill=not plain, animate=False if fast else None)
    job = run_wizard(tone)
    if job is None:
        return 130
    try:
        o = run(job, tone)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        err_console.print(f"[err]couldn't finish:[/] {e}")
        return 2
    summarize(o, tone)
    return 0


def main(argv: list[str] | None = None) -> int:
    _safe_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    first = argv[0] if argv else "start"
    rest = argv[1:]

    try:
        if first in ("start", "go"):
            # "cleanly start now" works too.
            return cmd_start([x for x in rest if x != "now"])
        if first in ("--plain", "--fast"):
            return cmd_start(argv)
        if first == "do":
            return cmd_do(rest)
        if first in ("help", "-h", "--help"):
            show_help()
            return 0
        if first in ("version", "--version", "-V"):
            console.print(f"cleanly {__version__}")
            return 0
        if first in ("update", "--update", "upgrade"):
            from .manage import update
            return update()
        if first in ("uninstall", "--uninstall", "remove"):
            from .manage import uninstall
            return uninstall(yes="--yes" in rest or "-y" in rest)
        if not first.startswith("-") and (Path(first).suffix or Path(first).exists()):
            # Old style still works: `cleanly notes.txt ...`
            return cmd_do(argv)
    except KeyboardInterrupt:
        console.print("\n[dim]no worries, nothing changed ✌️[/]")
        return 130

    err_console.print(f"[err]hmm, don't know[/] '{first}'. Try [accent]cleanly start[/] or [accent]cleanly help[/].")
    return 2


if __name__ == "__main__":
    sys.exit(main())
