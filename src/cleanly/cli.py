"""Command line interface: `cleanly <file> [options]`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .matcher import Matcher
from .text import EFFECTS, censor_file_text, mask
from .wordlist import MODES, STRICTNESS, UserList, build_list, load_standard

TEXT_KINDS = {".txt": "txt", ".md": "txt", ".json": "json", ".srt": "srt"}


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="cleanly",
        description="Find listed words and cover them. v0.1: text, JSON and SRT files.",
    )
    p.add_argument("input", help="file to clean (.txt, .md, .json, .srt)")
    p.add_argument("-o", "--output", help="output path (default: <name>.clean<ext>)")
    p.add_argument("--language", default="en", help="word-list language (v1: en only)")
    p.add_argument("--mode", choices=MODES, default="standard",
                   help="standard: built-in list; customized: built-in + your edits; mylist: only your words")
    p.add_argument("--strictness", choices=tuple(STRICTNESS), default="strict",
                   help="light: slurs; moderate: + strong words; strict: everything")
    p.add_argument("--list", dest="user_list", help='your list JSON: {"remove": [...], "add": [...]}')
    p.add_argument("--effect", choices=EFFECTS, default="stars",
                   help="stars: d***, full: ****, symbol: ♪, replace: your word")
    p.add_argument("--replacement", default="", help="word to use with --effect replace")
    p.add_argument("--report", help="write a JSON report of what was covered")
    p.add_argument("--quiet", action="store_true", help="don't print the summary")
    p.add_argument("--version", action="version", version=f"cleanly {__version__}")
    return p.parse_args(argv)


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    col = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return line, col


def main(argv=None) -> int:
    args = parse_args(argv)
    src = Path(args.input)
    if not src.is_file():
        print(f"cleanly: file not found: {src}", file=sys.stderr)
        return 2
    kind = TEXT_KINDS.get(src.suffix.lower())
    if kind is None:
        print(f"cleanly: {src.suffix or 'this file type'} is not supported yet "
              f"(v0.1 handles {', '.join(TEXT_KINDS)}). Audio and video are coming next.",
              file=sys.stderr)
        return 2
    if args.mode != "standard" and not args.user_list:
        print(f"cleanly: --mode {args.mode} needs --list <file.json>", file=sys.stderr)
        return 2
    if args.effect == "replace" and not args.replacement:
        print("cleanly: --effect replace needs --replacement <word>", file=sys.stderr)
        return 2

    try:
        user = UserList.load(args.user_list) if args.user_list else None
        entries = build_list(load_standard(args.language), args.mode, args.strictness, user)
        content = src.read_text(encoding="utf-8")
        result = censor_file_text(content, kind, Matcher(entries), args.effect, args.replacement)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"cleanly: {e}", file=sys.stderr)
        return 2

    out = Path(args.output) if args.output else src.with_name(f"{src.stem}.clean{src.suffix}")
    out.write_text(result.text, encoding="utf-8")

    report = [
        {
            "masked": mask(m.text),
            "severity": m.severity,
            "rule": m.entry.source,
            **({"line": _line_col(content, int(m.start))[0], "column": _line_col(content, int(m.start))[1]}
               if kind != "json" else {}),
        }
        for m in result.matches
    ]
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if not args.quiet:
        print(f"Covered {len(report)} word(s) → {out}")
        for r in report:
            where = f"line {r['line']}, col {r['column']}: " if "line" in r else ""
            print(f"  {where}{r['masked']}  ({r['severity']}, {r['rule']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
