#!/usr/bin/env python3
"""Audit saved PA HTML against the verified NationBuilder extraction rules.

This command performs no network requests. It reports selector coverage, article
word counts, metadata extraction, inline/hero image counts and parsing failures.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collect_pa_news import parse_article, select_primary_article_body


def canonical_url(soup: BeautifulSoup, fallback: str) -> str:
    link = soup.select_one("link[rel='canonical'][href]")
    if link and link.get("href"):
        return urljoin("https://www.patrioticalternative.org.uk", str(link["href"]))
    meta = soup.select_one("meta[property='og:url'][content]")
    if meta and meta.get("content"):
        return str(meta["content"])
    return fallback


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html-dir", type=Path, required=True)
    ap.add_argument("--output-json", type=Path, required=True)
    ap.add_argument("--output-csv", type=Path, required=True)
    ap.add_argument("--minimum-words", type=int, default=20)
    args = ap.parse_args()

    rows: list[dict[str, object]] = []
    for path in sorted(args.html_dir.glob("*.html")):
        raw = path.read_bytes()
        soup = BeautifulSoup(raw, "html.parser")
        url = canonical_url(soup, f"file://{path.name}")
        primary = select_primary_article_body(soup)
        row: dict[str, object] = {
            "file": path.name,
            "url": url,
            "verified_selector_present": primary is not None,
            "status": "ok",
            "error": None,
        }
        try:
            record = parse_article(soup, url, args.minimum_words)
            images = record.get("image_candidates", [])
            row.update(
                {
                    "title": record.get("title"),
                    "published_at": record.get("published_at"),
                    "author": record.get("author"),
                    "body_selector": record.get("body_selector"),
                    "word_count": len(str(record.get("body", "")).split()),
                    "paragraph_count": len(record.get("paragraphs", [])),
                    "image_count": len(images),
                    "hero_image_count": sum(x.get("image_role") == "hero" for x in images),
                    "inline_image_count": sum(x.get("image_role") == "inline" for x in images),
                    "caption_count": sum(bool(x.get("figcaption")) for x in images),
                    "tag_count": len(record.get("tags", [])),
                }
            )
        except Exception as exc:  # audit must continue across all captures
            row["status"] = "failed"
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)

    summary = {
        "html_files": len(rows),
        "verified_selector_present": sum(bool(r["verified_selector_present"]) for r in rows),
        "parsed_ok": sum(r["status"] == "ok" for r in rows),
        "failed": sum(r["status"] == "failed" for r in rows),
        "total_words": sum(int(r.get("word_count") or 0) for r in rows),
        "total_images": sum(int(r.get("image_count") or 0) for r in rows),
        "total_captions": sum(int(r.get("caption_count") or 0) for r in rows),
        "records": rows,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with args.output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(json.dumps({k: v for k, v in summary.items() if k != "records"}, indent=2))
    raise SystemExit(1 if summary["failed"] else 0)


if __name__ == "__main__":
    main()
