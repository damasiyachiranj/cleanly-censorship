"""Censor text, JSON and SRT (ALGORITHM.md, section 4)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace

from .matcher import Match, Matcher, tokenize

EFFECTS = ("stars", "full", "symbol", "replace")


def mask(word: str) -> str:
    """'damn' -> 'd***'. Used for effects and for safe reports."""
    out, seen_first = [], False
    for ch in word:
        if ch.isalnum() or ch in "@$!*":
            out.append(ch if not seen_first else "*")
            seen_first = True
        else:
            out.append(ch)
    return "".join(out)


def _match_case(original: str, new: str) -> str:
    if original.isupper():
        return new.upper()
    if original[:1].isupper():
        return new[:1].upper() + new[1:]
    return new


def apply_effect(original: str, effect: str, replacement: str = "") -> str:
    if effect == "stars":
        return mask(original)
    if effect == "full":
        return "".join("*" if not c.isspace() else c for c in original)
    if effect == "symbol":
        return "♪"
    if effect == "replace":
        return _match_case(original, replacement)
    raise ValueError(f"effect must be one of {EFFECTS}")


@dataclass
class Result:
    text: str
    matches: list[Match] = field(default_factory=list)


def censor_string(text: str, matcher: Matcher, effect: str = "stars", replacement: str = "") -> Result:
    matches = matcher.find(tokenize(text))
    out = text
    for m in sorted(matches, key=lambda m: m.start, reverse=True):
        s, e = int(m.start), int(m.end)
        out = out[:s] + apply_effect(out[s:e], effect, replacement) + out[e:]
    return Result(out, matches)


def censor_json(data, matcher: Matcher, effect: str = "stars", replacement: str = ""):
    """Censor string values only; keys and other types are untouched."""
    found: list[Match] = []

    def walk(node):
        if isinstance(node, str):
            r = censor_string(node, matcher, effect, replacement)
            found.extend(r.matches)
            return r.text
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return node

    return walk(data), found


SRT_TIME = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}")


def censor_srt(text: str, matcher: Matcher, effect: str = "stars", replacement: str = "") -> Result:
    """Keep index and timestamp lines exactly; censor caption lines only."""
    out_lines, found = [], []
    lines = text.splitlines(keepends=True)
    offset = 0  # where this line starts in the original file, so match positions are file-wide
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_index = stripped.isdigit() and i + 1 < len(lines) and SRT_TIME.match(lines[i + 1])
        if stripped and not is_index and not SRT_TIME.match(line):
            r = censor_string(line, matcher, effect, replacement)
            found.extend(replace(mt, start=mt.start + offset, end=mt.end + offset) for mt in r.matches)
            line = r.text
        out_lines.append(line)
        offset += len(lines[i])
    return Result("".join(out_lines), found)


def censor_file_text(content: str, kind: str, matcher: Matcher, effect: str = "stars",
                     replacement: str = "") -> Result:
    """kind: 'txt', 'json' or 'srt'."""
    if kind == "json":
        data, found = censor_json(json.loads(content), matcher, effect, replacement)
        return Result(json.dumps(data, ensure_ascii=False, indent=2) + "\n", found)
    if kind == "srt":
        return censor_srt(content, matcher, effect, replacement)
    return censor_string(content, matcher, effect, replacement)
