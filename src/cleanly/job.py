"""One censoring job: run it with live progress, then explain what changed."""

from __future__ import annotations

import json
import shlex
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from .matcher import Match, Matcher, tokenize
from .text import apply_effect, censor_file_text, mask
from .ui import Tone, category_style, console
from .wordlist import MODE_DESC, UserList, build_list, load_builtin

TEXT_KINDS = {".txt": "txt", ".md": "txt", ".json": "json", ".srt": "srt"}

EFFECT_DESC = {
    "stars": "its first letter plus stars (d***)",
    "full": "stars (****)",
    "symbol": "a music note (♪)",
    "replace": "your replacement word",
}


MAX_ROWS = 25


def default_output(src: Path) -> Path:
    return src.with_name(f"{src.stem}.clean{src.suffix}")


def default_report(out: Path) -> Path:
    return out.with_name(f"{out.stem}.report.json")


@dataclass
class Job:
    input: Path
    language: str = "en"
    mode: str = "strict"
    user: UserList | None = None
    effect: str = "stars"
    replacement: str = ""
    output: Path | None = None
    report: Path | None = None
    preset: str = ""  # e.g. "kids", for the summary only

    @property
    def kind(self) -> str:
        return TEXT_KINDS.get(self.input.suffix.lower(), "")

    def out_path(self) -> Path:
        return self.output or default_output(self.input)

    def as_command(self) -> str:
        """The one-line command that repeats this job."""
        parts = ["cleanly", "do", str(self.input), "-m", self.mode, "-e", self.effect]
        if self.effect == "replace":
            parts += ["--replacement", self.replacement]
        if self.mode == "customize":
            parts += ["--base", self.user.base if self.user else "standard"]
            if self.user and self.user.remove:
                parts += ["--remove", ",".join(self.user.remove)]
            if self.user and self.user.add:
                parts += ["--add", ",".join(e.word for e in self.user.add)]
        if self.output:
            parts += ["-o", str(self.output)]
        if self.report:
            parts += ["-r", str(self.report)]
        return " ".join(shlex.quote(p) for p in parts)


@dataclass
class Outcome:
    job: Job
    content: str
    result_text: str
    matches: list[Match] = field(default_factory=list)
    words_scanned: int = 0


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    col = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return line, col


def report_rows(o: Outcome) -> list[dict]:
    rows = []
    for m in o.matches:
        row = {
            "masked": mask(m.text),
            "became": apply_effect(m.text, o.job.effect, o.job.replacement),
            "category": m.category,
            "why": m.how,
            "rule": m.entry.source,
        }
        if o.job.kind != "json":
            row["line"], row["column"] = _line_col(o.content, int(m.start))
        rows.append(row)
    return rows


def run(job: Job, tone: Tone) -> Outcome:
    if not job.kind:
        raise ValueError(f"{job.input.suffix or 'this file type'} isn't supported yet "
                         f"(v0.2 handles {', '.join(TEXT_KINDS)}). Audio and video are coming next.")

    with tone.step("load_list"):
        entries = build_list(load_builtin(job.language), job.mode, job.user)
        matcher = Matcher(entries)

    with tone.step("read"):
        content = job.input.read_text(encoding="utf-8")
        words = len(tokenize(content))

    with tone.step("scan"):
        result = censor_file_text(content, job.kind, matcher, job.effect, job.replacement)

    outcome = Outcome(job, content, result.text, result.matches, words)

    if outcome.matches:
        # Covering happens in the same pass as scanning; this line reports it.
        console.print(f"  [ok]✔[/] {tone.line(f'cover_{job.effect}')} [dim]· {len(outcome.matches)} word(s)[/]")

    with tone.step("save"):
        out = job.out_path()
        out.write_text(result.text, encoding="utf-8")

    if job.report:
        with tone.step("report", min_seconds=0.25):
            job.report.write_text(json.dumps(report_rows(outcome), indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
    return outcome


def summarize(o: Outcome, tone: Tone) -> None:
    job = o.job
    n = len(o.matches)
    by_cat = Counter(m.category for m in o.matches)

    console.print()
    title = tone.line("done_some" if n else "done_none")
    stats = (f"scanned [bold]{o.words_scanned}[/] words · covered [bold]{n}[/]"
             if tone.chill else f"Words scanned: [bold]{o.words_scanned}[/] · Covered: [bold]{n}[/]")
    if n:
        parts = [f"[{category_style(c)}]{k} {c}[/]" for c, k in by_cat.most_common()]
        stats += " (" + ", ".join(parts) + ")"
    console.print(Panel(stats, title=f"[ok]{title}[/]", title_align="left", border_style="green", expand=False))

    if n:
        table = Table(title="what changed" if tone.chill else "Changes", title_justify="left",
                      header_style="bold", border_style="grey50")
        if job.kind != "json":
            table.add_column("where", style="accent", no_wrap=True)
        table.add_column("word", no_wrap=True)
        table.add_column("became", no_wrap=True)
        table.add_column("type")
        table.add_column("why it matched")
        for row, m in list(zip(report_rows(o), o.matches))[:MAX_ROWS]:
            cells = []
            if job.kind != "json":
                cells.append(f"line {row['line']}:{row['column']}")
            rule = "" if m.entry.source == "builtin" else " [dim](your word)[/]"
            hidden = mask(m.text).replace("*", "•")
            cells += [hidden, f"[bold]{row['became']}[/]",
                      f"[{category_style(m.category)}]{m.category}[/]", m.reason + rule]
            table.add_row(*cells)
        console.print(table)
        if n > MAX_ROWS:
            console.print(f"[dim]  …and {n - MAX_ROWS} more. The report has all of them.[/]")

    # Plain-language explanation of the whole job.
    console.print()
    console.print("[bold]the rundown[/]" if tone.chill else "[bold]Summary[/]")
    if job.mode == "customize":
        u = job.user or UserList()
        mode_line = (f"Mode [bold]customize[/]: started from the [bold]{u.base}[/] list, "
                     f"let {len(u.remove)} word(s) through and added {len(u.add)} of your own.")
    else:
        mode_line = f"Mode [bold]{job.mode}[/]: {MODE_DESC[job.mode]}."
    lines = [mode_line]
    if n:
        effect = EFFECT_DESC[job.effect]
        if job.effect == "replace":
            effect = f'the word "{job.replacement}" (matching the original capitals)'
        lines.append(f"Each covered word was replaced with {effect}.")
    keep = {
        "json": "JSON keys, numbers and structure were kept; only text values were checked.",
        "srt": "Subtitle numbers and timestamps were kept; only caption text was checked.",
        "txt": "Spacing, punctuation and line breaks were kept.",
    }[job.kind]
    lines.append(f"Nothing else changed: {o.words_scanned - n} other words were left as they were. {keep}")
    lines.append("Whole words only, so words like class or assess are never touched.")
    for line in lines:
        console.print(f"  • {line}")

    console.print()
    console.print(f"  [dim]original[/]    {job.input}  [dim](untouched)[/]")
    console.print(f"  [dim]clean file[/]  [bold]{job.out_path()}[/]")
    if job.report:
        console.print(f"  [dim]report[/]      {job.report}")
    console.print()
    tip = "run it again in one line:" if tone.chill else "To repeat this job:"
    console.print(f"  [dim]{tip}[/] [accent]{job.as_command()}[/]")
    console.print()
