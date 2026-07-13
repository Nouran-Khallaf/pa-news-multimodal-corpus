#!/usr/bin/env python3
"""Prepare BNC frequency references for PA Corpus Explorer.

Supported inputs:
- UCREL List 4.1: imaginative vs informative writing, lemmatised
  (uses FrIn, the informative-writing frequency per million)
- UCREL List 1.1: whole BNC, lemmatised
- Adam Kilgarriff lemma.al or lemma.num
- CSV/TSV with term/word/lemma and count or per_million

For List 4.1, the default output is aligned with the dashboard's lexical
analysis: only common nouns, proper nouns, verbs, adjectives and adverbs are
kept; @/@ inflection rows are excluded; duplicate lemma/POS heads are summed.
"""
from __future__ import annotations

import argparse
import csv
import re
import urllib.request
from collections import defaultdict
from pathlib import Path

UCREL_11_URL = "https://ucrel.lancs.ac.uk/bncfreq/lists/1_1_all_alpha.txt"
TERM_RE = re.compile(r"^[A-Za-z][A-Za-z'-]*$")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
CONTENT_POS = {"NoC", "NoP", "Verb", "Adj", "Adv"}


def decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "windows-1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def decorated_number(value: str) -> float | None:
    match = NUMBER_RE.search(value.replace(",", ""))
    return float(match.group()) if match else None


def normalise_term(value: str) -> str:
    term = value.strip().lower().replace("’", "'")
    term = re.sub(r"[*#]+$", "", term).strip("'\"")
    # The dashboard compares single-token spaCy lemmas. Do not silently turn
    # multiword BNC entries such as "a bit" into the unigram "a".
    if re.search(r"\s|[/()]", term):
        return ""
    return term if TERM_RE.fullmatch(term) else ""


def parse_ucrel_4_1(
    text: str,
    *,
    content_only: bool = True,
) -> tuple[dict[str, dict[str, float]], str, dict[str, int]]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("The source file is empty")

    header = lines[0].split("\t")
    normalised = [re.sub(r"[^a-z0-9]+", "", cell.lower()) for cell in header]
    try:
        word_i = normalised.index("word")
        pos_i = normalised.index("pos")
        frin_i = normalised.index("frin")
    except ValueError as exc:
        raise ValueError("This is not a UCREL List 4.1 table") from exc

    output: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "per_million": 0.0}
    )
    stats = {
        "source_rows": 0,
        "lemma_head_rows": 0,
        "inflection_rows_skipped": 0,
        "non_content_pos_skipped": 0,
        "complex_terms_skipped": 0,
        "malformed_frequency_skipped": 0,
        "retained_rows": 0,
    }

    for raw_line in lines[1:]:
        stats["source_rows"] += 1
        cells = raw_line.split("\t")

        # A few rows in the published source omit the initial blank tab.
        if header and header[0] == "" and len(cells) == len(header) - 1 and cells[0] != "":
            cells.insert(0, "")

        if len(cells) <= max(word_i, pos_i, frin_i):
            stats["malformed_frequency_skipped"] += 1
            continue

        word = cells[word_i].strip()
        pos = cells[pos_i].strip()

        if word == "@" or pos == "@":
            stats["inflection_rows_skipped"] += 1
            continue

        stats["lemma_head_rows"] += 1
        if content_only and pos not in CONTENT_POS:
            stats["non_content_pos_skipped"] += 1
            continue

        term = normalise_term(word)
        if not term:
            stats["complex_terms_skipped"] += 1
            continue

        per_million = decorated_number(cells[frin_i])
        if per_million is None:
            stats["malformed_frequency_skipped"] += 1
            continue

        output[term]["per_million"] += per_million
        stats["retained_rows"] += 1

    if not output:
        raise ValueError("No List 4.1 lemma rows were retained")
    return dict(output), "per_million", stats


def parse_header_table(text: str) -> tuple[dict[str, dict[str, float]], str] | None:
    lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        return None
    delimiter = "\t" if "\t" in lines[0] else "," if "," in lines[0] else None
    if delimiter is None:
        return None

    rows = list(csv.reader(lines, delimiter=delimiter))
    headers = [re.sub(r"[^a-z0-9]+", "_", h.strip().lower()) for h in rows[0]]
    term_candidates = {"term", "word", "lemma", "headword"}
    count_candidates = {"count", "frequency", "raw_frequency", "freq"}
    pm_candidates = {
        "per_million",
        "frequency_per_million",
        "freq_per_million",
        "pmw",
    }
    term_i = next((i for i, h in enumerate(headers) if h in term_candidates), None)
    count_i = next((i for i, h in enumerate(headers) if h in count_candidates), None)
    pm_i = next((i for i, h in enumerate(headers) if h in pm_candidates), None)
    if term_i is None or (count_i is None and pm_i is None):
        return None

    output: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "per_million": 0.0}
    )
    for row in rows[1:]:
        if len(row) <= term_i:
            continue
        term = normalise_term(row[term_i])
        if not term:
            continue
        if count_i is not None and len(row) > count_i:
            value = decorated_number(row[count_i])
            if value is not None:
                output[term]["count"] += value
        if pm_i is not None and len(row) > pm_i:
            value = decorated_number(row[pm_i])
            if value is not None:
                output[term]["per_million"] += value

    basis = "per_million" if pm_i is not None else "count"
    return dict(output), basis


def parse_ucrel_1_1(text: str) -> tuple[dict[str, dict[str, float]], str]:
    output: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "per_million": 0.0}
    )
    parsed = 0
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = [cell.strip() for cell in line.split("\t") if cell.strip()]
        if len(cells) < 3:
            continue
        value = decorated_number(cells[2])
        term = normalise_term(cells[0])
        if value is None or not term:
            continue
        output[term]["per_million"] += value
        parsed += 1
    if not parsed:
        raise ValueError("No UCREL List 1.1 rows could be parsed")
    return dict(output), "per_million"


def parse_kilgarriff(text: str) -> tuple[dict[str, dict[str, float]], str]:
    output: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "per_million": 0.0}
    )
    parsed = 0
    for line in text.splitlines():
        cells = line.split()
        if len(cells) < 4:
            continue
        try:
            int(cells[0])
            count = float(cells[1])
        except ValueError:
            continue
        term = normalise_term(cells[2])
        if not term:
            continue
        output[term]["count"] += count
        parsed += 1
    if not parsed:
        raise ValueError("No Kilgarriff lemma rows could be parsed")
    return dict(output), "count"


def auto_parse(
    text: str,
    *,
    content_only: bool,
) -> tuple[dict[str, dict[str, float]], str, str, dict[str, int] | None]:
    first = next((line for line in text.splitlines() if line.strip()), "")

    if "FrIn" in first and "Word" in first and "PoS" in first:
        rows, basis, stats = parse_ucrel_4_1(text, content_only=content_only)
        return rows, basis, "UCREL List 4.1 informative writing", stats

    table = parse_header_table(text)
    if table:
        rows, basis = table
        return rows, basis, "header table", None

    if "\t" in first:
        rows, basis = parse_ucrel_1_1(text)
        return rows, basis, "UCREL List 1.1", None

    cells = first.split()
    if len(cells) >= 4:
        try:
            float(cells[0])
            float(cells[1])
            rows, basis = parse_kilgarriff(text)
            return rows, basis, "Kilgarriff lemma list", None
        except ValueError:
            pass

    raise ValueError("Unrecognised BNC frequency-list format")


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Downloaded BNC frequency list")
    source.add_argument(
        "--download-ucrel",
        action="store_true",
        help="Download UCREL List 1.1",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include-all-pos",
        action="store_true",
        help="For List 4.1, retain all POS rather than content POS only",
    )
    args = parser.parse_args()

    if args.download_ucrel:
        with urllib.request.urlopen(UCREL_11_URL, timeout=120) as response:
            data = response.read()
        source_name = UCREL_11_URL
    else:
        data = args.input.read_bytes()
        source_name = str(args.input)

    text = decode_bytes(data)
    rows, basis, detected, stats = auto_parse(
        text,
        content_only=not args.include_all_pos,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["term", "per_million"])
        for term in sorted(rows):
            per_million = rows[term]["per_million"]
            if basis == "count":
                # Count-only references need a corpus size before conversion.
                # Preserve the count in a separate compatible table instead.
                raise ValueError(
                    "Count-only input requires preparation with a known corpus size"
                )
            writer.writerow([term, f"{per_million:.6f}"])

    print(f"Source: {source_name}")
    print(f"Detected: {detected}")
    print(f"Basis: {basis}")
    print(f"Unique terms: {len(rows):,}")
    if stats:
        for key, value in stats.items():
            print(f"{key}: {value:,}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
