#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

import yaml

TOKEN_RE = re.compile(r"(?u)\b[^\W\d_][\w'’-]*\b")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“‘(])")


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding='utf-8'))


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'{path}:{line_no}: invalid JSON: {exc}') from exc


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
    tmp.replace(path)


def dump_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def tokenise(text: str) -> list[str]:
    return [m.group(0).lower().replace('’', "'") for m in TOKEN_RE.finditer(text)]


def sentence_split(text: str) -> list[str]:
    return [x.strip() for x in SENTENCE_RE.split(re.sub(r'\s+', ' ', text).strip()) if x.strip()]


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def mattr(tokens: list[str], window: int = 50) -> float:
    if not tokens:
        return 0.0
    if len(tokens) <= window:
        return len(set(tokens)) / len(tokens)
    vals = [len(set(tokens[i:i+window])) / window for i in range(len(tokens)-window+1)]
    return sum(vals) / len(vals)


def syllable_estimate(word: str) -> int:
    word = re.sub(r'[^a-z]', '', word.lower())
    if not word:
        return 0
    groups = re.findall(r'[aeiouy]+', word)
    count = len(groups)
    if word.endswith('e') and count > 1 and not word.endswith(('le','ye')):
        count -= 1
    return max(1, count)


def readability(text: str, sentences: list[str] | None = None) -> dict[str, float]:
    tokens = tokenise(text)
    sents = sentences or sentence_split(text)
    words = len(tokens)
    n_sents = max(1, len(sents))
    syllables = sum(syllable_estimate(w) for w in tokens)
    flesch = 206.835 - 1.015 * safe_div(words, n_sents) - 84.6 * safe_div(syllables, words)
    return {
        'word_count': words,
        'sentence_count': len(sents),
        'mean_sentence_words': safe_div(words, n_sents),
        'mean_word_characters': safe_div(sum(len(w) for w in tokens), words),
        'type_token_ratio': safe_div(len(set(tokens)), words),
        'mattr_50': mattr(tokens, 50),
        'flesch_reading_ease_estimate': flesch,
    }


def log_likelihood(k1: int, n1: int, k2: int, n2: int) -> float:
    if n1 <= 0 or n2 <= 0 or (k1 + k2) == 0:
        return 0.0
    e1 = n1 * (k1 + k2) / (n1 + n2)
    e2 = n2 * (k1 + k2) / (n1 + n2)
    def term(k: int, e: float) -> float:
        return 0.0 if k == 0 or e == 0 else k * math.log(k/e)
    return 2.0 * (term(k1,e1) + term(k2,e2))


def log_ratio(k1: int, n1: int, k2: int, n2: int, smoothing: float = 0.5) -> float:
    f1 = (k1 + smoothing) / (n1 + smoothing)
    f2 = (k2 + smoothing) / (n2 + smoothing)
    return math.log2(f1 / f2)


def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    m=len(pvalues)
    order=sorted(range(m), key=lambda i:pvalues[i])
    out=[1.0]*m
    prev=1.0
    for rank,i in reversed(list(enumerate(order,1))):
        val=min(prev, pvalues[i]*m/rank)
        out[i]=val; prev=val
    return out


def load_articles(config: dict[str, Any], repo_root: Path) -> list[dict[str, Any]]:
    preferred = config['paths'].get('analysis_articles_jsonl')
    preferred_path = repo_root / preferred if preferred else None
    source_path = repo_root / config['paths']['articles_jsonl']
    path = preferred_path if preferred_path is not None and preferred_path.exists() else source_path
    rows=list(iter_jsonl(path) or [])
    if not rows:
        raise FileNotFoundError(f'No article records found at {path}. Run collection first.')
    return rows


def load_images(config: dict[str, Any], repo_root: Path) -> list[dict[str, Any]]:
    path = repo_root / config['paths']['images_jsonl']
    return list(iter_jsonl(path) or [])


def stopwords_en() -> set[str]:
    # Small built-in set used only when a spaCy model is unavailable.
    return set(('a an and are as at be been being but by can could did do does for from had has have he her hers him his i if in into is it its may me might more most must my no not of on one or our ours she should so than that the their theirs them then there these they this those to too us was we were what when where which who will with would you your yours').split())
