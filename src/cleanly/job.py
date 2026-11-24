"""One censoring job: run the layers with live progress, then explain what changed."""

from __future__ import annotations

import json
import shlex
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from . import ml
from .ai import DEFAULT_MODEL, DEFAULT_URL, AIConfig
from .engine import EngineResult, Finding, run_layers
from .matcher import Matcher
from .text import apply_effect, mask
from .ui import Tone, category_style, console
from .wordlist import MODE_DESC, UserList, build_list, load_builtin

TEXT_KINDS = {".txt": "txt", ".md": "txt", ".json": "json", ".srt": "srt"}

EFFECT_DESC = {
    "stars": "its first letter plus stars (d***)",
    "full": "stars (****)",
    "symbol": "a music note (♪)",
    "replace": "your replacement word",
}

LAYER_NAME = {"list": "word list", "ml": "ML", "ai": "AI"}
MAX_ROWS = 25


class JobError(Exception):
    pass


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
    ai: AIConfig = field(default_factory=AIConfig)
    threshold: float = ml.DEFAULT_THRESHOLD

    @property
    def kind(self) -> str:
        return TEXT_KINDS.get(self.input.suffix.lower(), "")

    def out_path(self) -> Path:
        return self.output or default_output(self.input)

    def as_command(self) -> str:
        """The one-line command that repeats this job (never includes API keys)."""
        parts = ["cleanly", "do", str(self.input), "-m", self.mode, "-e", self.effect]
        if self.effect == "replace":
            parts += ["--replacement", self.replacement]
        if self.mode == "customize":
            parts += ["--base", self.user.base if self.user else "standard"]
            if self.user and self.user.remove:
                parts += ["--remove", ",".join(self.user.remove)]
            if self.user and self.user.add:
                parts += ["--add", ",".join(e.word for e in self.user.add)]
        if self.ai.enabled:
            parts += ["--ai", self.ai.provider]
            if self.ai.model and self.ai.model != DEFAULT_MODEL.get(self.ai.provider):
                parts += ["--ai-model", self.ai.model]
            if self.ai.url and self.ai.url != DEFAULT_URL.get(self.ai.provider):
                parts += ["--ai-url", self.ai.url]
        if self.threshold != ml.DEFAULT_THRESHOLD:
            parts += ["--ml-threshold", str(self.threshold)]
        if self.output:
            parts += ["-o", str(self.output)]
        if self.report:
            parts += ["-r", str(self.report)]
        return " ".join(shlex.quote(p) for p in parts)


@dataclass
class Outcome:
    job: Job
    content: str
    result: EngineResult


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    col = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return line, col


def where(o: Outcome, f: Finding) -> str:
    seg = o.result.segments[f.seg]
    if seg.offset is None:
        return seg.where
    line, col = _line_col(o.content, seg.offset + f.start)
    return f"line {line}:{col}"


def short(text: str, width: int = 38) -> str:
    t = " ".join(text.split())
    return t if len(t) <= width else t[:width - 1] + "…"


def shown(f: Finding) -> str:
    """Listed words are always masked; ML/AI sentences contain no listed word, so they're shown, shortened."""
    if f.layer == "list":
        return mask(f.text).replace("*", "•")
    return short(f.text)


def report_rows(o: Outcome) -> list[dict]:
    rows = []
    for f in o.result.findings:
        row = {
            "where": where(o, f),
            "layer": f.layer,
            "status": f.status,
            "category": f.category,
            "found": mask(f.text) if f.layer == "list" else f.text,
            "why": f.reason,
        }
        if f.status == "covered":
            row["became"] = apply_effect(f.text, o.job.effect, o.job.replacement)
        if f.score is not None:
            row["score"] = round(f.score, 3)
        if f.ai_note:
            row["ai_note"] = f.ai_note
        rows.append(row)
    return rows


def _ensure_model(tone: Tone) -> ml.Scorer:
    if not ml.is_ready():
        with tone.step("model_dl", min_seconds=0):
            try:
                ml.download()
            except ml.ModelError as e:
                raise JobError(f"The ML layer is required and its model isn't downloaded yet ({e}). "
                               f"Connect to the internet once, or run: cleanly models download") from e
    with tone.step("model_load", min_seconds=0.3):
        try:
            return ml.Scorer()
        except ImportError as e:
            raise JobError(f"The ML layer needs {e.name}. Re-run the installer or: pip install "
                           f"onnxruntime tokenizers numpy") from e
        except ml.ModelError as e:
            raise JobError(f"{e}. Try: cleanly models download") from e


def run(job: Job, tone: Tone, scorer: ml.Scorer | None = None) -> Outcome:
    if not job.kind:
        raise JobError(f"{job.input.suffix or 'this file type'} isn't supported yet "
                       f"(this version handles {', '.join(TEXT_KINDS)}). Audio and video are coming next.")

    with tone.step("load_list"):
        matcher = Matcher(build_list(load_builtin(job.language), job.mode, job.user))

    with tone.step("read"):
        content = job.input.read_text(encoding="utf-8")

    scorer = scorer or _ensure_model(tone)

    result = run_layers(content, job.kind, matcher, scorer, mode=job.mode, effect=job.effect,
                        replacement=job.replacement, threshold=job.threshold,
                        ai_cfg=job.ai if job.ai.enabled else None, step=tone.step)
    outcome = Outcome(job, content, result)

    covered = result.by_status("covered")
    if covered:
        console.print(f"  [ok]✔[/] {tone.line(f'cover_{job.effect}')} [dim]· {len(covered)} item(s)[/]")

    with tone.step("save"):
        job.out_path().write_text(result.text, encoding="utf-8")

    if job.report:
        with tone.step("report", min_seconds=0.25):
            job.report.write_text(json.dumps(report_rows(outcome), indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
    return outcome


def summarize(o: Outcome, tone: Tone) -> None:
    job, r = o.job, o.result
    covered, review, kept = r.by_status("covered"), r.by_status("review"), r.by_status("kept")
    c = tone.chill

    for w in r.warnings:
        console.print(f"  [warn]! {escape(w)}[/]")

    console.print()
    title = tone.line("done_some" if (covered or review) else "done_none")
    stats = f"scanned [bold]{r.words_scanned}[/] words · covered [bold]{len(covered)}[/]"
    if review:
        stats += f" · [warn]{len(review)} to review[/]"
    if kept:
        stats += f" · [dim]{len(kept)} kept by AI[/]"
    if covered:
        by_cat = Counter(f.category for f in covered)
        stats += "\n" + ", ".join(f"[{category_style(k)}]{n} {k}[/]" for k, n in by_cat.most_common())
    by_layer = Counter(f.layer for f in r.findings)
    ai_state = (f"[ok]on[/] ({sum(1 for f in r.findings if f.ai_note)} checked, {by_layer['ai']} found)"
                if r.ai_used else "[dim]off[/]")
    stats += (f"\n[dim]layers:[/] word list {by_layer['list']} · ML {by_layer['ml']} · AI {ai_state}")
    console.print(Panel(stats, title=f"[ok]{title}[/]", title_align="left", border_style="green", expand=False))

    def table(title: str, rows: list[Finding], kind: str) -> None:
        t = Table(title=title, title_justify="left", header_style="bold", border_style="grey50")
        t.add_column("where", style="accent", no_wrap=True)
        t.add_column("found", overflow="fold")
        if kind == "covered":
            t.add_column("became", no_wrap=True)
        t.add_column("layer", no_wrap=True)
        t.add_column("type", no_wrap=True)
        t.add_column("why", overflow="fold")
        for f in rows[:MAX_ROWS]:
            why = escape(f.reason)
            if f.entry is not None and f.entry.source == "user":
                why += " [dim](your word)[/]"
            if f.ai_note:
                why += f"\n[dim]AI: {escape(f.ai_note)}[/]"
            cells = [escape(where(o, f)), escape(shown(f))]
            if kind == "covered":
                became = apply_effect(f.text, job.effect, job.replacement)
                cells.append(f"[bold]{escape(short(became))}[/]")
            cells += [LAYER_NAME[f.layer], f"[{category_style(f.category)}]{escape(f.category)}[/]", why]
            t.add_row(*cells)
        console.print(t)
        if len(rows) > MAX_ROWS:
            console.print(f"[dim]  …and {len(rows) - MAX_ROWS} more. The report has all of them.[/]")

    if covered:
        table("what changed" if c else "Changes", covered, "covered")
    if review:
        console.print()
        table("worth a look 👀 (not changed)" if c else "For review (not changed)", review, "review")
    if kept:
        console.print()
        table("kept by the AI (harmless here)" if c else "Kept by the AI layer", kept, "kept")

    console.print()
    console.print("[bold]the rundown[/]" if c else "[bold]Summary[/]")
    if job.mode == "customize":
        u = job.user or UserList()
        lines = [f"Mode [bold]customize[/]: started from the [bold]{u.base}[/] list, "
                 f"let {len(u.remove)} word(s) through and added {len(u.add)} of your own."]
    else:
        lines = [f"Mode [bold]{job.mode}[/]: {MODE_DESC[job.mode]}."]
    lines.append("Layer 1 (word list) found exact words; layer 2 (ML model) checked every other sentence"
                 + (" and covered harmful ones." if job.mode == "strict" else " and only suggested, never changed."))
    if r.ai_used:
        lines.append(f"Layer 3 (AI, {escape(job.ai.label())}) double-checked context. It may only un-cover "
                     "context words like 'kill' in 'kill time', never slurs, sexual words or your own words.")
    else:
        lines.append("Layer 3 (AI) was off" + (" because it failed." if job.ai.enabled else "."))
    if covered:
        effect = EFFECT_DESC[job.effect]
        if job.effect == "replace":
            effect = f'the word "{escape(job.replacement)}" (matching the original capitals)'
        lines.append(f"Each covered item was replaced with {effect}.")
    keep = {
        "json": "JSON keys, numbers and structure were kept; only text values were checked.",
        "srt": "Subtitle numbers and timestamps were kept; only caption text was checked.",
        "txt": "Spacing, punctuation and line breaks were kept.",
    }[job.kind]
    lines.append(f"Nothing else changed. {keep}")
    if review:
        lines.append("Items under 'worth a look' were [bold]not[/] changed. Re-run with Strict mode, "
                     "or add those words in Customize, to cover them.")
    for line in lines:
        console.print(f"  • {line}")

    console.print()
    console.print(f"  [dim]original[/]    {escape(str(job.input))}  [dim](untouched)[/]")
    console.print(f"  [dim]clean file[/]  [bold]{escape(str(job.out_path()))}[/]")
    if job.report:
        console.print(f"  [dim]report[/]      {escape(str(job.report))}")
    console.print()
    tip = "run it again in one line:" if c else "To repeat this job:"
    console.print(f"  [dim]{tip}[/] [accent]{escape(job.as_command())}[/]")
    console.print()
