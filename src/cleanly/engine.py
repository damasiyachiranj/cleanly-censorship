"""Run the security layers over a file (ALGORITHM.md, sections 1b and 3–4).

  L1 word list   mandatory   exact words
  L2 ML model    mandatory   harmful sentences with no listed word
  L3 LLM judge   optional    context check + missed items, under strict limits
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Callable

from . import ai as ai_mod
from .matcher import Matcher, tokenize
from .ml import DEFAULT_THRESHOLD, Scorer, category_for
from .segments import Segment, sentences, split
from .text import apply_effect, mask
from .wordlist import Entry


@dataclass
class Finding:
    seg: int
    start: int
    end: int
    text: str
    layer: str                 # "list" | "ml" | "ai"
    category: str
    status: str                # "covered" | "review" | "kept"
    reason: str                # why it was flagged
    entry: Entry | None = None
    score: float | None = None
    ai_note: str = ""          # what the LLM said, if anything
    shown: str = ""            # safe-to-display text (listed words masked); empty = use mask/text


@dataclass
class EngineResult:
    text: str
    segments: list[Segment]
    findings: list[Finding] = field(default_factory=list)
    words_scanned: int = 0
    ai_used: bool = False
    warnings: list[str] = field(default_factory=list)

    def by_status(self, status: str) -> list[Finding]:
        return [f for f in self.findings if f.status == status]


Step = Callable[[str], object]  # context-manager factory for progress display


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def run_layers(content: str, kind: str, matcher: Matcher, scorer: Scorer | None, *,
               mode: str, effect: str, replacement: str = "",
               threshold: float = DEFAULT_THRESHOLD,
               ai_cfg: ai_mod.AIConfig | None = None,
               step: Step | None = None) -> EngineResult:
    from contextlib import nullcontext

    step = step or (lambda key: nullcontext())
    segs, rebuild = split(content, kind)
    res = EngineResult(text=content, segments=segs)
    res.words_scanned = sum(len(tokenize(s.text)) for s in segs)

    # ---- L1: word list -------------------------------------------------
    with step("scan"):
        for si, s in enumerate(segs):
            for m in matcher.find(tokenize(s.text)):
                res.findings.append(Finding(si, int(m.start), int(m.end), m.text, "list", m.category,
                                            "covered", m.reason, entry=m.entry))

    # ---- L2: ML model --------------------------------------------------
    if scorer is not None:
        with step("ml"):
            # L1 spans per segment, so each sentence finds its listed words quickly.
            l1: dict[int, list[tuple[int, int]]] = {}
            for f in res.findings:
                l1.setdefault(f.seg, []).append((f.start, f.end))
            todo, texts_to_score, shown = [], [], []
            for si, s in enumerate(segs):
                spans = sorted(l1.get(si, []))
                starts = [sp[0] for sp in spans]
                for a, b in sentences(s.text):
                    # Listed words inside the sentence are already handled by L1, so the
                    # model judges what's LEFT: "You ___ piece of garbage, I will destroy you"
                    # is still harmful; "What the ___ is this ___?" is not.
                    inside = [sp for sp in spans[max(0, bisect_left(starts, a) - 1):bisect_left(starts, b)]
                              if _overlaps((a, b), sp)]
                    rest, safe, pos = [], [], a
                    for x, y in inside:
                        x, y = max(x, a), min(y, b)
                        rest.append(s.text[pos:x])
                        safe.append(s.text[pos:x] + mask(s.text[x:y]))
                        pos = y
                    rest.append(s.text[pos:b])
                    safe.append(s.text[pos:b])
                    remainder = " ".join(" ".join(rest).split())
                    if len(tokenize(remainder)) >= 2:
                        todo.append((si, a, b))
                        texts_to_score.append(remainder)
                        shown.append("".join(safe))
            scores = scorer.score(texts_to_score) if todo else []
            for (si, a, b), sc, safe_text in zip(todo, scores, shown):
                if sc.score >= threshold:
                    res.findings.append(Finding(
                        si, a, b, segs[si].text[a:b], "ml", category_for(sc),
                        "covered" if mode == "strict" else "review",
                        f"ML: {sc.label.replace('_', ' ')} ({sc.score:.0%})", score=sc.score,
                        shown=safe_text))

    # ---- L3: LLM judge (optional) ---------------------------------------
    if ai_cfg is not None and ai_cfg.enabled and res.findings:
        with step("ai"):
            try:
                _apply_ai(res, segs, ai_cfg, mode)
                res.ai_used = True
            except ai_mod.AIError as e:
                res.warnings.append(f"AI layer skipped: {e}. Layers 1 and 2 still ran.")

    # ---- Apply covers ---------------------------------------------------
    texts = [s.text for s in segs]
    covered: dict[int, set[tuple[int, int]]] = {}
    for f in res.findings:
        if f.status == "covered":
            covered.setdefault(f.seg, set()).add((f.start, f.end))
    for si in covered:
        spans = sorted(covered[si])
        merged: list[list[int]] = []
        for a, b in spans:
            if merged and a < merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        t, out, pos = texts[si], [], 0
        for a, b in merged:  # one pass; no repeated copying of the whole text
            out.append(t[pos:a])
            out.append(apply_effect(t[a:b], effect, replacement))
            pos = b
        out.append(t[pos:])
        texts[si] = "".join(out)
    res.text = rebuild(texts)
    res.findings.sort(key=lambda f: (f.seg, f.start))
    return res


def _context(text: str, a: int, b: int) -> str:
    lo = max(0, a - ai_mod.CONTEXT_CHARS)
    hi = min(len(text), b + ai_mod.CONTEXT_CHARS)
    return ("…" if lo > 0 else "") + text[lo:hi] + ("…" if hi < len(text) else "")


def may_uncover(f: Finding) -> bool:
    """Least privilege: what the LLM is allowed to un-cover."""
    if f.layer != "list" or f.entry is None:
        return False                      # never ML or AI findings
    if f.entry.source != "builtin":
        return False                      # never words the user added
    if f.category in ai_mod.PROTECTED_CATEGORIES:
        return False
    if f.category == "insults" and f.entry.level != "strict":
        return False                      # only mild (kids-only) insults
    return f.category in ai_mod.CONTEXT_CATEGORIES


def _apply_ai(res: EngineResult, segs: list[Segment], cfg: ai_mod.AIConfig, mode: str) -> None:
    items, by_id = [], {}
    for i, f in enumerate(res.findings, start=1):
        if f.status not in ("covered", "review"):
            continue
        items.append(ai_mod.Item(i, f.text, _context(segs[f.seg].text, f.start, f.end),
                                 f.category, f.layer, f.status))
        by_id[i] = f
    decisions, missed = ai_mod.judge(cfg, items, mode)

    keeps = [d for d in decisions if d.decision == "keep" and by_id[d.id].status == "covered"]
    covered_total = sum(1 for f in by_id.values() if f.status == "covered")
    distrust = len(keeps) >= ai_mod.SANITY_MIN_KEEPS and len(keeps) > covered_total * ai_mod.SANITY_MAX_SHARE
    if distrust:
        res.warnings.append(f"The AI wanted to un-cover {len(keeps)} of {covered_total} items, which "
                            f"looks wrong (or like the text tried to trick it), so those were ignored.")

    for d in decisions:
        f = by_id[d.id]
        f.ai_note = d.reason
        if d.decision == "keep":
            if f.status == "covered" and not distrust and may_uncover(f):
                f.status = "kept"
            elif f.status == "review" and f.layer == "ml" and mode != "strict":
                f.status = "kept"         # dismissing a suggestion is always allowed
            elif f.status == "covered":
                f.ai_note = f"{d.reason} (AI asked to keep this; not allowed for {f.category})".strip()
        elif d.decision == "cover":
            f.status = "covered"          # adding a cover is always allowed

    for m in missed:
        src = by_id[m.id]
        text = segs[src.seg].text
        lo = max(0, src.start - ai_mod.CONTEXT_CHARS)
        hi = min(len(text), src.end + ai_mod.CONTEXT_CHARS)
        pos = text.find(m.quote, lo, hi)
        if pos < 0:
            continue                      # must be an exact quote from what we sent
        span = (pos, pos + len(m.quote))
        if any(f.seg == src.seg and _overlaps(span, (f.start, f.end)) for f in res.findings):
            continue
        res.findings.append(Finding(src.seg, span[0], span[1], m.quote, "ai", m.category,
                                    "covered" if mode == "strict" else "review",
                                    "AI: missed by the list", ai_note=m.reason))
