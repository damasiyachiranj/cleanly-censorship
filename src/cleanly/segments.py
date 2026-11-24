"""Split a file into text segments the layers can check, and put it back together.

- txt: the whole file is one segment
- srt: each caption line is a segment (numbers and timestamps are never touched)
- json: each string value is a segment (keys, numbers and structure are never touched)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

SRT_TIME = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}")


@dataclass
class Segment:
    text: str
    offset: int | None  # where it starts in the original file (None for JSON values)
    where: str = ""     # human label for JSON values, e.g. "messages[2].text"


Rebuild = Callable[[list[str]], str]


def split(content: str, kind: str) -> tuple[list[Segment], Rebuild]:
    if kind == "json":
        return _split_json(content)
    if kind == "srt":
        return _split_srt(content)
    return [Segment(content, 0)], lambda texts: texts[0]


def _split_srt(content: str) -> tuple[list[Segment], Rebuild]:
    lines = content.splitlines(keepends=True)
    segs: list[Segment] = []
    index_of_line: dict[int, int] = {}
    offset = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_index = stripped.isdigit() and i + 1 < len(lines) and SRT_TIME.match(lines[i + 1])
        if stripped and not is_index and not SRT_TIME.match(line):
            body = line.rstrip("\r\n")
            index_of_line[i] = len(segs)
            segs.append(Segment(body, offset))
        offset += len(line)

    def rebuild(texts: list[str]) -> str:
        out = []
        for i, line in enumerate(lines):
            if i in index_of_line:
                ending = line[len(line.rstrip("\r\n")):]
                out.append(texts[index_of_line[i]] + ending)
            else:
                out.append(line)
        return "".join(out)

    return segs, rebuild


def _split_json(content: str) -> tuple[list[Segment], Rebuild]:
    data = json.loads(content)
    segs: list[Segment] = []

    def collect(node, path: str):
        if isinstance(node, str):
            segs.append(Segment(node, None, path or "$"))
        elif isinstance(node, list):
            for i, x in enumerate(node):
                collect(x, f"{path}[{i}]")
        elif isinstance(node, dict):
            for k, v in node.items():
                collect(v, f"{path}.{k}" if path else str(k))

    collect(data, "")

    def rebuild(texts: list[str]) -> str:
        it = iter(texts)

        def put(node):
            if isinstance(node, str):
                return next(it)
            if isinstance(node, list):
                return [put(x) for x in node]
            if isinstance(node, dict):
                return {k: put(v) for k, v in node.items()}
            return node

        return json.dumps(put(data), ensure_ascii=False, indent=2) + "\n"

    return segs, rebuild


SENTENCE_END = re.compile(r"(?<=[.!?…])[\"')\]]*\s+|\n+")


def sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans (start, end) with surrounding spaces trimmed."""
    spans, start = [], 0
    for m in SENTENCE_END.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    out = []
    for s, e in spans:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            out.append((s, e))
    return out
