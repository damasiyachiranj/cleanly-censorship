"""Terminal look and feel: tone of voice, spinners, colours."""

from __future__ import annotations

import random
import sys
import time
from contextlib import contextmanager

from rich.console import Console
from rich.theme import Theme

THEME = Theme({
    "brand": "bold magenta",
    "ok": "bold green",
    "warn": "yellow",
    "err": "bold red",
    "dim": "grey58",
    "mild": "yellow",
    "strong": "dark_orange",
    "slur": "bold red",
    "accent": "cyan",
})

console = Console(theme=THEME, highlight=False)
err_console = Console(theme=THEME, highlight=False, stderr=True)

# Every line has a chill (default) and a plain version.
LINES = {
    "hello": (
        "[brand]cleanly[/] ✨ [dim]let's make your content squeaky clean[/]",
        "[brand]Cleanly[/] [dim]· content censoring tool[/]",
    ),
    "load_list": ("loading the no-no list 📋", "Loading word list"),
    "read": ("reading your file 👀", "Reading file"),
    "scan": ("layer 1: scanning for sus words 🔍", "Layer 1: word list"),
    "ml": ("layer 2: ML vibe-checking every sentence 🧠", "Layer 2: ML model"),
    "ai": ("layer 3: AI double-checking the context 🤖", "Layer 3: AI check"),
    "model_dl": ("downloading the ML brain, one-time (~23 MB) 📦", "Downloading ML model (one-time, ~23 MB)"),
    "model_load": ("waking up the ML model 🧠", "Loading ML model"),
    "cover_stars": ("starring out the chaos ✳️", "Covering words with stars"),
    "cover_full": ("blacking out the bad stuff ⬛", "Covering words"),
    "cover_symbol": ("dropping music notes on bad words 🎵", "Replacing words with ♪"),
    "cover_replace": ("swapping in the clean words 🔁", "Replacing words"),
    "save": ("saving the glow-up ✨", "Saving clean file"),
    "report": ("writing the receipts 🧾", "Writing report"),
    "done_some": ("all clean, no cap 🧼", "Done"),
    "done_none": ("already squeaky clean, we love to see it 💅", "Done: nothing needed covering"),
    "bye": ("no worries, nothing changed ✌️", "Cancelled. Nothing was changed."),
}

# Extra flavour shown while a step runs (chill tone only).
WAITING = [
    "vibe check in progress",
    "hold up, almost there",
    "doing the thing",
    "cooking",
    "lowkey working hard",
]


class Tone:
    def __init__(self, chill: bool = True, animate: bool | None = None):
        self.chill = chill
        # Animate only in a real terminal.
        self.animate = sys.stdout.isatty() if animate is None else animate

    def line(self, key: str) -> str:
        chill, plain = LINES[key]
        return chill if self.chill else plain

    @contextmanager
    def step(self, key: str, min_seconds: float = 0.45):
        """Show a spinner while the block runs, then a tick when it's done.

        min_seconds keeps very fast steps on screen long enough to read.
        """
        label = self.line(key)
        start = time.monotonic()
        if self.animate:
            extra = f" [dim]· {random.choice(WAITING)}[/]" if self.chill else ""
            with console.status(f"{label}{extra}", spinner="dots", spinner_style="brand"):
                yield
                left = min_seconds - (time.monotonic() - start)
                if left > 0:
                    time.sleep(left)
        else:
            yield
        took = time.monotonic() - start
        console.print(f"  [ok]✔[/] {label} [dim]{took:.1f}s[/]")


CATEGORY_STYLE = {
    "slurs": "bold red", "harassment": "bold red", "self-harm": "bold red",
    "sexual": "magenta", "swearing": "dark_orange", "insults": "yellow",
    "drugs": "cyan", "alcohol": "cyan", "violence": "red", "custom": "blue",
    "hate": "bold red", "toxic": "dark_orange", "other": "white",
}


def category_style(cat: str) -> str:
    return CATEGORY_STYLE.get(cat, "white")
