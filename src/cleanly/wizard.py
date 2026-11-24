"""`cleanly start`: ask one question at a time, then run the job."""

from __future__ import annotations

from pathlib import Path

import questionary
from questionary import Choice, Style
from rich.panel import Panel

from . import ai as ai_mod
from .job import EFFECT_DESC, TEXT_KINDS, Job, default_output, default_report
from .ui import Tone, console
from .wordlist import Entry, UserList, load_saved, saved_list_path

STYLE = Style([
    ("qmark", "fg:#d670d6 bold"),
    ("question", "bold"),
    ("answer", "fg:#5fd7ff bold"),
    ("pointer", "fg:#d670d6 bold"),
    ("highlighted", "fg:#d670d6 bold"),
    ("selected", "fg:#5fd7ff"),
    ("instruction", "fg:#8a8a8a italic"),
    ("disabled", "fg:#6c6c6c italic"),
])


class Cancelled(Exception):
    pass


def _ask(q):
    """Run a question; Ctrl+C cancels the whole flow."""
    answer = q.ask()
    if answer is None:
        raise Cancelled
    return answer


def clean_path(s: str) -> str:
    # Dragging a file into the terminal often adds quotes or a trailing space.
    return s.strip().strip("'\"").strip()


def _validate_file(s: str):
    s = clean_path(s)
    if not s:
        return "type a file path (Tab completes)"
    p = Path(s).expanduser()
    if not p.is_file():
        return "can't find that file"
    if p.suffix.lower() not in TEXT_KINDS:
        return f"this version handles {', '.join(TEXT_KINDS)} (audio/video coming soon)"
    return True


def words(s: str) -> list[str]:
    return [w.strip() for w in s.replace("\n", ",").split(",") if w.strip()]


def _customize(c: bool, q: str) -> UserList:
    saved = load_saved()
    if saved and not saved.is_empty():
        use_saved = _ask(questionary.select(
            "you've got a saved list. use it?" if c else "Use your saved Customize list?",
            choices=[
                Choice(f"yes · {saved.base} list, {len(saved.remove)} let through, {len(saved.add)} added", True),
                Choice("no, set up a new one", False),
            ],
            qmark=q, style=STYLE))
        if use_saved:
            return saved

    base = _ask(questionary.select(
        "start from which list?" if c else "Start from",
        choices=[
            Choice("Strict · the kids list (everything)", "strict"),
            Choice("Standard · the adults list", "standard"),
        ],
        qmark=q, style=STYLE))
    remove = words(_ask(questionary.text(
        "any words to let through? (comma-separated, enter to skip)" if c
        else "Words NOT to censor (comma-separated, optional)",
        qmark=q, style=STYLE)))
    add = words(_ask(questionary.text(
        "your own words to cover? (comma-separated, enter to skip)" if c
        else "Your own words to censor (comma-separated, optional)",
        qmark=q, style=STYLE)))
    user = UserList(base=base, remove=[w.lower() for w in remove],
                    add=[Entry(w, source="user") for w in add])
    if _ask(questionary.confirm(
            "save this setup for next time? 💾" if c else "Save these settings for next time?",
            default=True, qmark=q, style=STYLE)):
        user.save(saved_list_path())
        console.print(f"  [dim]saved to {saved_list_path()}[/]")
    return user


def _ask_ai(c: bool, q: str) -> ai_mod.AIConfig:
    console.print("[dim]  layers 1 (word list) and 2 (ML model) always run. layer 3 is optional:[/]" if c
                  else "[dim]  Layers 1 (word list) and 2 (ML model) always run. Layer 3 is optional.[/]")
    provider = _ask(questionary.select(
        "add an AI second opinion?" if c else "AI check (layer 3)",
        choices=[
            Choice("no thanks · word list + ML only", "off"),
            Choice("local AI (Ollama) · private, free, runs on your PC", "ollama"),
            Choice("Claude API · your own key, sends text snippets", "anthropic"),
            Choice("OpenAI / compatible API · your own key, sends text snippets", "openai"),
        ],
        qmark=q, style=STYLE))
    if provider == "off":
        return ai_mod.AIConfig()
    cfg = ai_mod.AIConfig(provider)
    model = _ask(questionary.text("model" if c else "Model name", default=ai_mod.DEFAULT_MODEL[provider],
                                  qmark=q, style=STYLE)).strip()
    cfg.model = model
    if provider == "ollama":
        problem = ai_mod.check_ollama(cfg)
        if problem:
            console.print(f"  [warn]! {problem}[/]")
            if not _ask(questionary.confirm("try anyway? (if it fails, Cleanly just skips the AI layer)",
                                            default=False, qmark=q, style=STYLE)):
                return ai_mod.AIConfig()
        return cfg
    if provider == "openai":
        url = _ask(questionary.text("API base URL (enter for OpenAI)", default=ai_mod.DEFAULT_URL["openai"],
                                    qmark=q, style=STYLE)).strip()
        cfg.url = url
    if not cfg.resolved().api_key:
        console.print("  [dim]tip: set the key as an environment variable so you don't have to paste it "
                      f"each time ({' or '.join(ai_mod.KEY_ENV[provider][::-1])})[/]")
        key = _ask(questionary.password("paste your API key (hidden, used for this run only)",
                                        qmark=q, style=STYLE)).strip()
        if not key:
            console.print("  [dim]no key, so the AI layer is off[/]")
            return ai_mod.AIConfig()
        cfg.api_key = key
    console.print("  [dim]privacy: only short text snippets around flagged words are sent, never your whole file[/]")
    return cfg


def run_wizard(tone: Tone) -> Job | None:
    c = tone.chill
    q = "›" if c else "?"
    console.print()
    console.print(tone.line("hello"))
    console.print("[dim]arrow keys to pick, enter to confirm, ctrl+c to bail[/]" if c
                  else "[dim]Use arrow keys and Enter. Press Ctrl+C to cancel.[/]")
    console.print()

    try:
        # 1. Language
        language = _ask(questionary.select(
            "what language we cleaning? 🌍" if c else "Language",
            choices=[
                Choice("English", "en"),
                Choice("Hindi / Hinglish", "hi", disabled="coming soon"),
                Choice("Gujarati", "gu", disabled="coming soon"),
            ],
            qmark=q, style=STYLE,
        ))

        # 2. File
        raw = _ask(questionary.path(
            "drop the file path 📂" if c else "File to clean",
            validate=_validate_file, qmark=q, style=STYLE,
        ))
        src = Path(clean_path(raw)).expanduser()

        # 3. Mode
        mode = _ask(questionary.select(
            "pick a mode" if c else "Censorship mode",
            choices=[
                Choice("👶 Strict · for kids, covers everything harmful", "strict"),
                Choice("🧑 Standard · for adults: swearing, slurs, drug names", "standard"),
                Choice("🛠️  Customize · start from a list, add or remove words", "customize"),
            ],
            qmark=q, style=STYLE,
        ))
        user = _customize(c, q) if mode == "customize" else None

        # 4. Optional AI layer
        ai_cfg = _ask_ai(c, q)

        # 5. How to cover
        effect = _ask(questionary.select(
            "how should we cover them?" if c else "Cover words with",
            choices=[
                Choice("d*** · first letter + stars", "stars"),
                Choice("**** · all stars", "full"),
                Choice("♪ · a music note", "symbol"),
                Choice("a word I pick (e.g. beep)", "replace"),
            ],
            qmark=q, style=STYLE,
        ))
        replacement = ""
        if effect == "replace":
            replacement = _ask(questionary.text(
                "replace them with?" if c else "Replacement word", default="beep",
                validate=lambda s: bool(s.strip()) or "type a word", qmark=q, style=STYLE)).strip()

        # 6. Output
        out = Path(clean_path(_ask(questionary.text(
            "save the clean file as" if c else "Save clean file as",
            default=str(default_output(src)), qmark=q, style=STYLE,
            validate=lambda s: (Path(clean_path(s)).expanduser().resolve() != src.resolve())
            or "pick a different name so the original stays safe",
        )))).expanduser()
        want_report = _ask(questionary.confirm(
            "save the receipts too? (a report of every change)" if c else "Also save a report of every change?",
            default=True, qmark=q, style=STYLE))

        job = Job(input=src, language=language, mode=mode, user=user, effect=effect,
                  replacement=replacement, output=out,
                  report=default_report(out) if want_report else None, ai=ai_cfg)

        # 7. Recap + go
        mode_desc = {"strict": "Strict (kids)", "standard": "Standard (adults)",
                     "customize": f"Customize (from {user.base})" if user else "Customize"}[mode]
        effect_desc = EFFECT_DESC[effect] if effect != "replace" else f'"{replacement}"'
        recap = (
            f"[dim]file[/]      {src}\n"
            f"[dim]language[/]  English\n"
            f"[dim]mode[/]      {mode_desc}\n"
            f"[dim]layers[/]    word list + ML" + (f" + AI ({ai_cfg.label()})" if ai_cfg.enabled else "") + "\n"
            f"[dim]cover[/]     {effect_desc}\n"
            f"[dim]save as[/]   {job.out_path()}"
        )
        console.print()
        console.print(Panel(recap, title="the plan" if c else "Summary", title_align="left",
                            border_style="magenta", expand=False))
        if not _ask(questionary.confirm("let's go? 🚀" if c else "Start?", default=True, qmark=q, style=STYLE)):
            raise Cancelled
        console.print()
        return job
    except (Cancelled, KeyboardInterrupt):
        console.print()
        console.print(f"[dim]{tone.line('bye')}[/]")
        return None
