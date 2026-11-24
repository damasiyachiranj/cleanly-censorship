"""Layer 2: the ML toxicity model (mandatory). See ALGORITHM.md section 1b.

The model is pinned to one exact version and every file is checked against a
known fingerprint after download, so a changed or tampered file is never loaded.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# minuva/MiniLMv2-toxic-jigsaw-onnx (Apache-2.0), pinned to one commit.
MODEL = {
    "name": "MiniLMv2-toxic-jigsaw",
    "repo": "minuva/MiniLMv2-toxic-jigsaw-onnx",
    "revision": "c035f27b6a6d68770f8069a4829f1715a48b8d51",
    "files": {
        # name: (size in bytes, kind of fingerprint, fingerprint)
        "model_optimized_quantized.onnx": (
            22864978, "sha256", "bcd9dfb48cad802ac8f7cd789e1294f1f0b22d532797bd41f5a11694e3c269a0"),
        "tokenizer.json": (711649, "gitsha1", "3c0e6344ec45a9a6e5a621d6711baf109c2d9f87"),
        "config.json": (1007, "gitsha1", "8be2dac4f64ae121f18a0e9384133a9fcd0c79ff"),
    },
    "onnx": "model_optimized_quantized.onnx",
    "max_tokens": 256,
}

DEFAULT_THRESHOLD = 0.80   # adult modes: only flag when the model is quite sure
STRICT_THRESHOLD = 0.50    # kids mode: flag anything more likely harmful than not


def threshold_for(mode: str) -> float:
    return STRICT_THRESHOLD if mode == "strict" else DEFAULT_THRESHOLD

# How the model's labels map to Cleanly's categories.
LABEL_CATEGORY = {
    "identity_hate": "hate",
    "threat": "violence",
    "obscene": "swearing",   # in this dataset "obscene" means profanity, not sexual content
    "insult": "insults",
    "severe_toxic": "toxic",
    "toxic": "toxic",
}


class ModelError(Exception):
    pass


def data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "cleanly"


def model_dir(spec: dict = MODEL) -> Path:
    override = os.environ.get("CLEANLY_MODEL_DIR")
    if override:
        return Path(override)
    return data_dir() / "models" / f"{spec['name']}-{spec['revision'][:7]}"


def _fingerprint(data: bytes, kind: str) -> str:
    if kind == "sha256":
        return hashlib.sha256(data).hexdigest()
    if kind == "gitsha1":  # how Git identifies a file: sha1("blob <size>\0" + data)
        return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
    raise ValueError(kind)


def check_file(path: Path, size: int, kind: str, expected: str) -> bool:
    if not path.is_file() or path.stat().st_size != size:
        return False
    return _fingerprint(path.read_bytes(), kind) == expected


def is_ready(spec: dict = MODEL, full: bool = False) -> bool:
    """Quick check (sizes) by default; full=True re-checks every fingerprint."""
    d = model_dir(spec)
    for name, (size, kind, fp) in spec["files"].items():
        p = d / name
        if full:
            if not check_file(p, size, kind, fp):
                return False
        elif not p.is_file() or p.stat().st_size != size:
            return False
    return True


def download(spec: dict = MODEL, base_url: str | None = None,
             progress: Callable[[str, int, int], None] | None = None) -> Path:
    """Download the pinned model files and verify each one. Raises ModelError."""
    d = model_dir(spec)
    d.mkdir(parents=True, exist_ok=True)
    base = (base_url or os.environ.get("CLEANLY_MODEL_URL")
            or f"https://huggingface.co/{spec['repo']}/resolve/{spec['revision']}")
    for name, (size, kind, fp) in spec["files"].items():
        target = d / name
        if check_file(target, size, kind, fp):
            continue
        url = f"{base}/{name}"
        part = target.with_suffix(target.suffix + ".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cleanly"})
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
                got = 0
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if progress:
                        progress(name, got, size)
        except OSError as e:
            part.unlink(missing_ok=True)
            raise ModelError(f"couldn't download {name}: {e}") from e
        if not check_file(part, size, kind, fp):
            part.unlink(missing_ok=True)
            raise ModelError(f"{name} failed its integrity check (it may have been changed or "
                             f"corrupted in transit), so it was not used")
        part.replace(target)
    return d


@dataclass
class Score:
    label: str      # strongest model label, e.g. "insult"
    score: float    # 0..1
    all: dict       # every label's score


class Scorer:
    """Runs the ONNX model on CPU."""

    def __init__(self, directory: Path | None = None, spec: dict = MODEL):
        import numpy as np  # noqa: F401  (checked here for a clear error)
        import onnxruntime as ort
        from tokenizers import Tokenizer

        d = directory or model_dir(spec)
        try:
            cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
            self.labels = [cfg["id2label"][str(i)] for i in range(len(cfg["id2label"]))]
            self.multi_label = cfg.get("problem_type") == "multi_label_classification"
            self.tok = Tokenizer.from_file(str(d / "tokenizer.json"))
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            self.session = ort.InferenceSession(str(d / spec["onnx"]), sess_options=opts,
                                                providers=["CPUExecutionProvider"])
        except (OSError, KeyError, ValueError) as e:
            raise ModelError(f"couldn't load the ML model from {d}: {e}") from e
        self.tok.enable_truncation(spec.get("max_tokens", 256))
        self.tok.enable_padding()
        self.inputs = {i.name for i in self.session.get_inputs()}

    def score(self, texts: list[str]) -> list[Score]:
        """Score each text on its own. The model is quantized per batch, so scoring texts
        together could shift a borderline score; one at a time keeps results identical
        for the same sentence in any file. Repeated texts are scored once."""
        cache: dict[str, Score] = {}
        out: list[Score] = []
        for t in texts:
            if t not in cache:
                cache[t] = self._score_batch([t])[0]
            out.append(cache[t])
        return out

    def _score_batch(self, texts: list[str]) -> list[Score]:
        import numpy as np

        out: list[Score] = []
        for i in range(0, len(texts), 16):
            enc = self.tok.encode_batch(texts[i:i + 16])
            feed = {
                "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
                "token_type_ids": np.array([e.type_ids for e in enc], dtype=np.int64),
            }
            logits = self.session.run(None, {k: v for k, v in feed.items() if k in self.inputs})[0]
            if self.multi_label:
                probs = 1 / (1 + np.exp(-logits))
            else:
                ex = np.exp(logits - logits.max(axis=1, keepdims=True))
                probs = ex / ex.sum(axis=1, keepdims=True)
            for row in probs:
                scores = {lab: float(p) for lab, p in zip(self.labels, row)}
                best = max(scores, key=scores.get)
                out.append(Score(best, scores[best], scores))
        return out


def category_for(score: Score) -> str:
    """Pick the most specific category: prefer named harms over generic 'toxic'."""
    specific = {k: v for k, v in score.all.items() if k not in ("toxic", "severe_toxic")}
    if specific:
        lab = max(specific, key=specific.get)
        if specific[lab] >= 0.5:
            return LABEL_CATEGORY.get(lab, "toxic")
    return LABEL_CATEGORY.get(score.label, "toxic")
