#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from dateutil import parser as date_parser


BOILERPLATE_PATTERNS = {
    "do_you_like_this_page": re.compile(
        r"\bDo you like this page\??",
        flags=re.IGNORECASE,
    ),
    "reaction_section": re.compile(
        r"\bShowing\s+\d+\s+reactions?\b",
        flags=re.IGNORECASE,
    ),
    "sign_in_section": re.compile(
        r"\bSign in with\b",
        flags=re.IGNORECASE,
    ),
    "create_account": re.compile(
        r"\bCreate an account\b",
        flags=re.IGNORECASE,
    ),
    "post_comment": re.compile(
        r"\bPost your comment\b",
        flags=re.IGNORECASE,
    ),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    if not path.exists():
        return rows

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue

            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Invalid JSON in {path}, line {line_number}: {exc}"
                ) from exc

    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalise_url(value: str | None) -> str | None:
    if not value:
        return None

    parts = urlsplit(value.strip())
    path = parts.path.rstrip("/") or "/"

    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            "",
            "",
        )
    )


def get_article_url(article: dict[str, Any]) -> str | None:
    for field in (
        "canonical_url",
        "final_url",
        "article_url",
        "request_url",
        "url",
    ):
        if article.get(field):
            return normalise_url(str(article[field]))

    return None


def parse_date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None

    try:
        parsed = date_parser.parse(str(value))
        return parsed.replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def create_manifest_order(
    manifest_rows: list[dict[str, Any]],
) -> dict[str, int]:
    order: dict[str, int] = {}

    for position, row in enumerate(manifest_rows):
        url = normalise_url(
            row.get("url")
            or row.get("final_url")
            or row.get("request_url")
        )

        if url and url not in order:
            order[url] = position

    return order


def add_date_fields(
    articles: list[dict[str, Any]],
    manifest_order: dict[str, int],
) -> None:
    indexed = list(enumerate(articles))

    indexed.sort(
        key=lambda item: manifest_order.get(
            get_article_url(item[1]) or "",
            len(manifest_order) + item[0],
        )
    )

    ordered_indices = [index for index, _ in indexed]
    ordered_dates = [
        parse_date(articles[index].get("published_at"))
        for index in ordered_indices
    ]

    # Preserve exact dates first.
    for article_index, parsed_date in zip(
        ordered_indices,
        ordered_dates,
        strict=True,
    ):
        article = articles[article_index]

        if parsed_date is not None:
            article["analysis_date"] = parsed_date.date().isoformat()
            article["date_status"] = "exact"
            article["date_imputation_method"] = None
            article["date_lower_bound"] = None
            article["date_upper_bound"] = None
            article["date_confidence"] = "high"

    position = 0

    while position < len(ordered_indices):
        if ordered_dates[position] is not None:
            position += 1
            continue

        run_start = position

        while (
            position < len(ordered_indices)
            and ordered_dates[position] is None
        ):
            position += 1

        run_end = position - 1

        previous_position = run_start - 1
        next_position = position

        previous_date = (
            ordered_dates[previous_position]
            if previous_position >= 0
            else None
        )

        next_date = (
            ordered_dates[next_position]
            if next_position < len(ordered_dates)
            else None
        )

        missing_count = run_end - run_start + 1

        for offset, ordered_position in enumerate(
            range(run_start, run_end + 1),
            start=1,
        ):
            article_index = ordered_indices[ordered_position]
            article = articles[article_index]

            if previous_date is None or next_date is None:
                article["analysis_date"] = None
                article["date_status"] = "unresolved"
                article["date_imputation_method"] = None
                article["date_lower_bound"] = (
                    previous_date.date().isoformat()
                    if previous_date
                    else None
                )
                article["date_upper_bound"] = (
                    next_date.date().isoformat()
                    if next_date
                    else None
                )
                article["date_confidence"] = "none"
                continue

            fraction = offset / (missing_count + 1)
            interpolated = previous_date + (
                next_date - previous_date
            ) * fraction

            gap_days = abs((next_date - previous_date).days)

            if gap_days == 0:
                confidence = "high"
            elif gap_days <= 31:
                confidence = "medium"
            else:
                confidence = "low"

            lower = min(previous_date, next_date)
            upper = max(previous_date, next_date)

            article["analysis_date"] = interpolated.date().isoformat()
            article["date_status"] = "imputed"
            article[
                "date_imputation_method"
            ] = "bounded_linear_interpolation"
            article["date_lower_bound"] = lower.date().isoformat()
            article["date_upper_bound"] = upper.date().isoformat()
            article["date_confidence"] = confidence


def count_images_by_document(
    image_rows: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)

    for image in image_rows:
        document_id = image.get("document_id")

        if document_id:
            counts[str(document_id)] += 1

    return counts


def add_content_status(
    articles: list[dict[str, Any]],
    image_counts: dict[str, int],
) -> None:
    for article in articles:
        document_id = str(article.get("document_id") or "")
        image_count = image_counts.get(document_id, 0)
        word_count = int(article.get("word_count") or 0)

        article["linked_image_count"] = image_count
        article["has_images"] = image_count > 0

        if word_count == 0 and image_count > 0:
            article["content_status"] = "image_only"
            article["include_in_text_analysis"] = False
            article["include_in_image_analysis"] = True

        elif word_count == 0:
            article["content_status"] = "no_extracted_text"
            article["include_in_text_analysis"] = False
            article["include_in_image_analysis"] = False

        elif word_count < 20:
            article["content_status"] = "short_text"
            article["include_in_text_analysis"] = True
            article["include_in_image_analysis"] = image_count > 0

        else:
            article["content_status"] = "textual"
            article["include_in_text_analysis"] = True
            article["include_in_image_analysis"] = image_count > 0


def add_author_status(articles: list[dict[str, Any]]) -> None:
    for article in articles:
        author = article.get("author")

        if author and str(author).strip():
            article["author_status"] = "stated"
        else:
            article["author"] = None
            article["author_status"] = "not_stated"

        # Publisher is not a replacement for a missing personal author.
        article.setdefault("publisher", "Patriotic Alternative")


def clean_known_boilerplate(
    body: str,
) -> tuple[str, str, list[str]]:
    if not body:
        return body, "not_applicable", []

    candidates: list[tuple[int, str]] = []

    for name, pattern in BOILERPLATE_PATTERNS.items():
        match = pattern.search(body)

        if match:
            candidates.append((match.start(), name))

    if not candidates:
        return body, "unchanged", []

    candidates.sort()
    first_position, first_marker = candidates[0]

    # Only truncate automatically when the marker occurs near the end.
    minimum_position = max(200, int(len(body) * 0.70))

    if first_position < minimum_position:
        return (
            body,
            "marker_found_but_not_removed",
            [name for _, name in candidates],
        )

    cleaned = body[:first_position].rstrip()

    return (
        cleaned,
        "truncated_known_footer",
        [name for _, name in candidates],
    )


def add_clean_body(articles: list[dict[str, Any]]) -> None:
    for article in articles:
        body = str(article.get("body") or "")

        clean_body, status, markers = clean_known_boilerplate(body)

        article["body_clean"] = clean_body
        article["body_cleaning_status"] = status
        article["boilerplate_markers"] = markers
        article["clean_word_count"] = len(clean_body.split())


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--articles",
        type=Path,
        default=Path(
            "outputs/pa_news/data/processed/articles.jsonl"
        ),
    )

    parser.add_argument(
        "--images",
        type=Path,
        default=Path(
            "outputs/pa_news/data/processed/images.jsonl"
        ),
    )

    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(
            "outputs/pa_news/manifests/article_urls.jsonl"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "outputs/pa_news/data/processed/"
            "articles_analysis_ready.jsonl"
        ),
    )

    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(
            "outputs/pa_news/manifests/"
            "metadata_resolution_summary.json"
        ),
    )

    args = parser.parse_args()

    articles = read_jsonl(args.articles)
    images = read_jsonl(args.images)
    manifest = read_jsonl(args.manifest)

    manifest_order = create_manifest_order(manifest)
    image_counts = count_images_by_document(images)

    add_date_fields(articles, manifest_order)
    add_author_status(articles)
    add_content_status(articles, image_counts)
    add_clean_body(articles)

    write_jsonl(args.output, articles)

    date_statuses = Counter(
        article.get("date_status")
        for article in articles
    )

    author_statuses = Counter(
        article.get("author_status")
        for article in articles
    )

    content_statuses = Counter(
        article.get("content_status")
        for article in articles
    )

    cleaning_statuses = Counter(
        article.get("body_cleaning_status")
        for article in articles
    )

    summary = {
        "article_records": len(articles),
        "date_statuses": dict(date_statuses),
        "author_statuses": dict(author_statuses),
        "content_statuses": dict(content_statuses),
        "body_cleaning_statuses": dict(cleaning_statuses),
        "records_included_in_text_analysis": sum(
            bool(article.get("include_in_text_analysis"))
            for article in articles
        ),
        "records_included_in_image_analysis": sum(
            bool(article.get("include_in_image_analysis"))
            for article in articles
        ),
        "output": str(args.output),
    }

    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()