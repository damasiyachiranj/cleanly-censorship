"""Tokenize text and find words to censor (ALGORITHM.md, sections 2 and 3)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .wordlist import Entry

# A token: letters/digits plus look-alike characters and in-word separators,
# so "f.u.c.k", "sh1t", "f*ck" and "a$$" stay one token.
TOKEN_RE = re.compile(r"[\w@$!*]+(?:[.\-'][\w@$!*]+)*", re.UNICODE)

LEET = str.maketrans({"@": "a", "4": "a", "$": "s", "5": "s", "0": "o",
                      "1": "i", "!": "i", "3": "e", "7": "t"})
SEPARATORS = re.compile(r"[.\-_]")


@dataclass(frozen=True)
class Token:
    text: str
    start: float  # character offset for text, seconds for audio
    end: float


@dataclass(frozen=True)
class Match:
    start: float
    end: float
    text: str
    entry: Entry

    @property
    def severity(self) -> str:
        return self.entry.severity


def normalize(word: str) -> str:
    """ALGORITHM.md section 2: lowercase, undo look-alikes, drop in-word separators."""
    w = word.lower()
    # Trailing '!' is punctuation, not a look-alike 'i' ("damn!" is "damn").
    w = w.rstrip("!")
    w = w.translate(LEET)
    w = SEPARATORS.sub("", w)
    return w.strip("'")


def tokenize(text: str) -> list[Token]:
    tokens = []
    for m in TOKEN_RE.finditer(text):
        word = m.group().rstrip("!")  # "damn!" -> token "damn"; keep the '!' as punctuation
        if word:
            tokens.append(Token(word, m.start(), m.start() + len(word)))
    return tokens


class Matcher:
    def __init__(self, entries: list[Entry]):
        self.singles: dict[str, Entry] = {}
        self.phrases: list[tuple[tuple[str, ...], Entry]] = []
        for entry in entries:
            for form in entry.forms:
                parts = tuple(normalize(p) for p in form.split())
                if not parts:
                    continue
                if len(parts) == 1:
                    # First entry wins if two entries share a form.
                    self.singles.setdefault(parts[0], entry)
                else:
                    self.phrases.append((parts, entry))
        self.phrases.sort(key=lambda p: len(p[0]), reverse=True)
        self.by_length: dict[int, list[tuple[str, Entry]]] = {}
        for form, entry in self.singles.items():
            self.by_length.setdefault(len(form), []).append((form, entry))

    def _wildcard(self, t: str) -> Entry | None:
        if not any(c.isalpha() for c in t):
            return None  # "***" alone is not a word
        for form, entry in self.by_length.get(len(t), []):
            if all(a == "*" or a == b for a, b in zip(t, form)):
                return entry
        return None

    def find(self, tokens: list[Token]) -> list[Match]:
        """ALGORITHM.md section 3."""
        norm = [normalize(t.text) for t in tokens]
        matches: list[Match] = []
        i = 0
        while i < len(tokens):
            hit = False
            for seq, entry in self.phrases:
                n = len(seq)
                if tuple(norm[i:i + n]) == seq:
                    matches.append(Match(tokens[i].start, tokens[i + n - 1].end,
                                         " ".join(t.text for t in tokens[i:i + n]), entry))
                    i += n
                    hit = True
                    break
            if hit:
                continue
            t = norm[i]
            entry = self.singles.get(t)
            if entry is None and "*" in t:
                entry = self._wildcard(t)
            if entry is not None:
                matches.append(Match(tokens[i].start, tokens[i].end, tokens[i].text, entry))
            i += 1
        return matches
