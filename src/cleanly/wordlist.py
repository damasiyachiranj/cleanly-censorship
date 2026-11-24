"""Word lists and modes (ALGORITHM.md, section 1).

Modes:
  strict     for kids: every word in the list
  standard   for adults: only words tagged level "standard"
  customize  start from strict or standard, then remove words and add your own
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

MODES = ("strict", "standard", "customize")
BASES = ("strict", "standard")
LEVELS = ("standard", "strict")

MODE_DESC = {
    "strict": "for kids: everything harmful (swearing, sexual, insults, slurs, drugs, alcohol, violence, self-harm)",
    "standard": "for adults: swearing, sexual words, slurs, harassment and drug names",
    "customize": "start from Strict or Standard, then remove words or add your own",
}


@dataclass(frozen=True)
class Entry:
    word: str
    variants: tuple[str, ...] = field(default_factory=tuple)
    category: str = "custom"
    level: str = "strict"     # "standard" = in both modes, "strict" = kids mode only
    source: str = "builtin"   # "builtin" or "user"

    @property
    def forms(self) -> tuple[str, ...]:
        return (self.word, *self.variants)


def _entry_from_obj(obj, source: str) -> Entry:
    if isinstance(obj, str):
        return Entry(word=obj, source=source)
    level = obj.get("level", "strict")
    if level not in LEVELS:
        raise ValueError(f"Unknown level {level!r} for word {obj.get('word')!r}")
    return Entry(
        word=obj["word"],
        variants=tuple(obj.get("variants", [])),
        category=obj.get("category", "custom"),
        level=level,
        source=source,
    )


def load_builtin(language: str = "en") -> list[Entry]:
    """Load the built-in word list for a language."""
    path = resources.files("cleanly") / "data" / f"standard_{language}.json"
    if not path.is_file():
        raise ValueError(f"No word list for language {language!r} yet")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [_entry_from_obj(e, "builtin") for e in data["entries"]]


@dataclass
class UserList:
    """Your Customize settings: which list to start from, what to remove, what to add."""
    base: str = "standard"
    remove: list[str] = field(default_factory=list)
    add: list[Entry] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "UserList":
        """Load {"base": "standard"|"strict", "remove": ["word"], "add": ["word" or {entry}]}"""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        base = data.get("base", "standard")
        if base not in BASES:
            raise ValueError(f"base must be one of {BASES}")
        return cls(
            base=base,
            remove=[w.lower() for w in data.get("remove", [])],
            add=[_entry_from_obj(e, "user") for e in data.get("add", [])],
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "base": self.base,
            "remove": sorted(set(self.remove)),
            "add": [{"word": e.word, "variants": list(e.variants)} if e.variants else e.word
                    for e in self.add],
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def is_empty(self) -> bool:
        return not self.remove and not self.add


def build_list(builtin: list[Entry], mode: str = "strict", user: UserList | None = None) -> list[Entry]:
    """Pick the words for a run (ALGORITHM.md, section 1)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")

    def pick(level_mode: str) -> list[Entry]:
        if level_mode == "strict":
            return list(builtin)
        return [e for e in builtin if e.level == "standard"]

    if mode in ("strict", "standard"):
        return pick(mode)

    user = user or UserList()
    removed = {w.lower() for w in user.remove}
    # Removing a main word ("damn") lets all its forms through.
    base = [e for e in pick(user.base) if e.word.lower() not in removed]
    # Removing a variant ("damned") lets only that one form through.
    trimmed = []
    for e in base:
        variants = tuple(v for v in e.variants if v.lower() not in removed)
        trimmed.append(Entry(e.word, variants, e.category, e.level, e.source) if variants != e.variants else e)
    # Your own words come first, so if one is also built in, yours wins
    # (and is treated as something you explicitly asked to cover).
    return list(user.add) + trimmed


# ---- Saved Customize settings ---------------------------------------------

def config_dir() -> Path:
    """Where Cleanly keeps your saved Customize list."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "cleanly"


def saved_list_path() -> Path:
    return config_dir() / "my_list.json"


def load_saved() -> UserList | None:
    path = saved_list_path()
    if path.is_file():
        try:
            return UserList.load(path)
        except (ValueError, json.JSONDecodeError):
            return None
    return None
