#!/usr/bin/env python3
"""Resumable, single-site collector for Patriotic Alternative news pages.

Research use only. The collector:
- checks and enforces robots.txt per origin;
- never authenticates, solves challenges, rotates identities, or bypasses blocks;
- stops on 401/403/429 and can be resumed later;
- collects only public news article pages discovered from /news pagination;
- stores raw HTML separately from derived text and downloaded image objects.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import mimetypes
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
import yaml
from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser
from PIL import Image

EXIT_TEMPORARY_BLOCK = 75
BLOCK_TAGS = {"p", "li", "blockquote", "h2", "h3", "h4", "pre"}
NOISE_RE = re.compile(
    r"(?:nav|menu|footer|header|sidebar|share|social|reaction|comment|signup|newsletter|"
    r"petition|donat|login|account|breadcrumb|pagination|site-map)", re.I
)
STOP_TEXT_RE = re.compile(
    r"^(?:do you like this page\??|showing\s+\d+\s+reaction|sign in with|"
    r"or sign in with email|create an account|site map|newsletter|follow us|contact address)",
    re.I,
)
META_TEXT_RE = re.compile(r"^(?:posted by\b|[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\b)", re.I)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg"}
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)


class CrawlBlocked(RuntimeError):
    """Raised when the server asks the crawler to stop."""


class RobotsUnavailable(RuntimeError):
    """Raised when robots.txt cannot be checked safely."""


@dataclass
class Config:
    raw: dict[str, Any]
    config_path: Path

    @property
    def root(self) -> Path:
        p = Path(self.raw["output"]["root"])
        return p if p.is_absolute() else (Path.cwd() / p)

    def out(self, key: str) -> Path:
        return self.root / self.raw["output"][key]


class JsonlWriter:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())


class RobotsCache:
    def __init__(self, crawler: "Collector"):
        self.crawler = crawler
        self.cache: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.cache:
            self.cache[origin] = self._load(origin)
        rp = self.cache[origin]
        return True if rp is None else rp.can_fetch(self.crawler.user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.cache:
            self.cache[origin] = self._load(origin)
        rp = self.cache[origin]
        if rp is None:
            return None
        return rp.crawl_delay(self.crawler.user_agent) or rp.crawl_delay("*")

    def _load(self, origin: str) -> RobotFileParser | None:
        robots_url = origin + "/robots.txt"
        try:
            response = self.crawler._request_raw(robots_url, purpose="robots", apply_delay=False)
        except CrawlBlocked as exc:
            raise RobotsUnavailable(f"robots check blocked for {origin}: {exc}") from exc
        except requests.RequestException as exc:
            if self.crawler.cfg.raw["crawl"].get("stop_if_robots_unavailable", True):
                raise RobotsUnavailable(f"robots check failed for {origin}: {exc}") from exc
            self.crawler.logger.warning("robots unavailable for %s; continuing by configuration", origin)
            return None
        if response.status_code == 404:
            self.crawler.logger.info("robots.txt absent (HTTP 404) for %s", origin)
            return None
        if response.status_code != 200:
            if self.crawler.cfg.raw["crawl"].get("stop_if_robots_unavailable", True):
                raise RobotsUnavailable(
                    f"robots check returned HTTP {response.status_code} for {origin}"
                )
            return None
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.parse(response.text.splitlines())
        self.crawler.logger.info("robots.txt loaded for %s", origin)
        return rp


class Collector:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.site = cfg.raw["site"]
        self.scope = cfg.raw["scope"]
        self.crawl = cfg.raw["crawl"]
        self.root = cfg.root
        self.root.mkdir(parents=True, exist_ok=True)
        for key in (
            "raw_html_dir", "image_object_dir", "processed_jsonl", "images_jsonl",
            "urls_jsonl", "requests_jsonl", "failures_jsonl", "skipped_images_jsonl",
            "run_summary_json", "log_file"
        ):
            cfg.out(key).parent.mkdir(parents=True, exist_ok=True)
        self.logger = setup_logging(cfg.out("log_file"))
        contact = os.environ.get("CRAWLER_CONTACT_EMAIL", "").strip()
        if not contact or "@" not in contact:
            raise SystemExit(
                "Set CRAWLER_CONTACT_EMAIL to your institutional research contact before crawling."
            )
        self.user_agent = (
            f"Nouran-Khallaf-CL-research/1.0 (mailto:{contact}; "
            "non-commercial corpus research; single-threaded)"
        )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/*;q=0.8,*/*;q=0.5",
                "Accept-Language": "en-GB,en;q=0.8",
            }
        )
        self.requests_log = JsonlWriter(cfg.out("requests_jsonl"))
        self.failures_log = JsonlWriter(cfg.out("failures_jsonl"))
        self.skipped_images_log = JsonlWriter(cfg.out("skipped_images_jsonl"))
        self.urls_log = JsonlWriter(cfg.out("urls_jsonl"))
        self.images_log = JsonlWriter(cfg.out("images_jsonl"))
        self.robots = RobotsCache(self)
        self.last_request_monotonic = 0.0
        self.run_id = datetime.now(timezone.utc).strftime("pa-news-%Y%m%dT%H%M%SZ")
        self.stats = {
            "run_id": self.run_id,
            "started_at_utc": utc_now(),
            "listing_pages_requested": 0,
            "article_urls_discovered": 0,
            "articles_attempted": 0,
            "articles_written": 0,
            "articles_skipped_existing": 0,
            "article_failures": 0,
            "images_attempted": 0,
            "images_written": 0,
            "images_skipped": 0,
        }

    def _polite_wait(self, url: str) -> None:
        configured = float(self.crawl.get("delay_seconds", 3.0))
        robots_delay = self.robots.crawl_delay(url) if self.crawl.get("require_robots_check", True) else None
        base = max(configured, float(robots_delay or 0.0))
        jitter = random.uniform(0.0, float(self.crawl.get("jitter_seconds", 0.0)))
        elapsed = time.monotonic() - self.last_request_monotonic
        wait = max(0.0, base + jitter - elapsed)
        if wait:
            time.sleep(wait)

    def _request_raw(
        self,
        url: str,
        *,
        purpose: str,
        apply_delay: bool = True,
        stream: bool = False,
    ) -> requests.Response:
        if apply_delay:
            self._polite_wait(url)
        started = utc_now()
        t0 = time.monotonic()
        try:
            response = self.session.get(
                url,
                timeout=int(self.crawl.get("timeout_seconds", 45)),
                allow_redirects=True,
                stream=stream,
            )
            self.last_request_monotonic = time.monotonic()
        except requests.RequestException as exc:
            self.failures_log.append(
                {
                    "run_id": self.run_id,
                    "url": url,
                    "purpose": purpose,
                    "attempted_at_utc": started,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            raise
        record = {
            "run_id": self.run_id,
            "request_url": url,
            "final_url": response.url,
            "purpose": purpose,
            "requested_at_utc": started,
            "elapsed_seconds": round(time.monotonic() - t0, 3),
            "http_status": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "content_length_header": response.headers.get("Content-Length"),
            "retry_after": response.headers.get("Retry-After"),
            "redirect_chain": [r.url for r in response.history],
        }
        self.requests_log.append(record)
        stop_statuses = set(int(x) for x in self.crawl.get("stop_statuses", [401, 403, 429]))
        if response.status_code in stop_statuses:
            raise CrawlBlocked(
                f"HTTP {response.status_code} for {url}; Retry-After={response.headers.get('Retry-After')!r}. "
                "The run stopped without attempting a workaround."
            )
        return response

    def fetch(self, url: str, *, purpose: str, binary: bool = False) -> tuple[bytes, requests.Response]:
        if self.crawl.get("require_robots_check", True) and purpose != "robots":
            if not self.robots.allowed(url):
                raise PermissionError(f"robots.txt disallows {url} for {self.user_agent}")
        max_retries = int(self.crawl.get("max_retries_server_errors", 2))
        for attempt in range(max_retries + 1):
            response = self._request_raw(url, purpose=purpose, stream=binary)
            if response.status_code not in {500, 502, 503, 504}:
                break
            if attempt >= max_retries:
                break
            backoff = float(self.crawl.get("server_error_backoff_seconds", 30)) * (2**attempt)
            self.logger.warning("server error %s for %s; sleeping %.0fs", response.status_code, url, backoff)
            time.sleep(backoff)
        response.raise_for_status()
        max_bytes = int(
            self.crawl.get("max_image_bytes" if binary else "max_response_bytes", 30_000_000)
        )
        if binary:
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"response exceeds {max_bytes} bytes: {url}")
                chunks.append(chunk)
            content = b"".join(chunks)
        else:
            content = response.content
            if len(content) > max_bytes:
                raise ValueError(f"response exceeds {max_bytes} bytes: {url}")
        return content, response

    def preflight(self) -> None:
        news_url = self.site["news_url"]
        if self.crawl.get("require_robots_check", True) and not self.robots.allowed(news_url):
            raise PermissionError(f"robots.txt disallows the news index: {news_url}")
        content, response = self.fetch(news_url, purpose="preflight")
        soup = BeautifulSoup(content, "html.parser")
        urls = extract_listing_article_urls(soup, self.site, self.scope)
        if not urls:
            raise RuntimeError("preflight found no article links; inspect selectors before crawling")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "news_url": news_url,
                    "http_status": response.status_code,
                    "article_links_on_first_page": len(urls),
                    "example_urls": urls[:3],
                    "user_agent": self.user_agent,
                },
                indent=2,
            )
        )

    def discover(self, limit_pages: int | None = None) -> list[str]:
        found: dict[str, dict[str, Any]] = load_url_records(self.cfg.out("urls_jsonl"))
        max_pages = min(
            int(self.crawl.get("max_listing_pages", 500)),
            limit_pages if limit_pages is not None else 10**9,
        )
        no_new = 0
        page = 1
        first_page_max: int | None = None
        while page <= max_pages:
            page_url = self.site["news_url"] if page == 1 else f"{self.site['news_url']}?page={page}"
            self.logger.info("discovering listing page %d: %s", page, page_url)
            content, _ = self.fetch(page_url, purpose="listing")
            self.stats["listing_pages_requested"] += 1
            soup = BeautifulSoup(content, "html.parser")
            if first_page_max is None:
                first_page_max = max_pagination_number(soup)
                if first_page_max:
                    self.logger.info("largest pagination number on page 1: %d", first_page_max)
            urls = extract_listing_article_urls(soup, self.site, self.scope)
            new_count = 0
            for position, url in enumerate(urls, start=1):
                if url in found:
                    continue
                rec = {
                    "url": url,
                    "discovered_from": page_url,
                    "listing_page": page,
                    "position": position,
                    "discovered_at_utc": utc_now(),
                    "run_id": self.run_id,
                }
                self.urls_log.append(rec)
                found[url] = rec
                new_count += 1
            self.logger.info("listing page %d: %d links, %d new", page, len(urls), new_count)
            no_new = no_new + 1 if new_count == 0 else 0
            if no_new >= int(self.crawl.get("stop_after_consecutive_pages_without_new_urls", 2)):
                self.logger.info("stopping discovery after %d pages without new URLs", no_new)
                break
            if first_page_max is not None and page >= first_page_max and not urls:
                break
            page += 1
        ordered = [r["url"] for r in sorted(found.values(), key=lambda x: (x.get("listing_page", 0), x.get("position", 0)))]
        self.stats["article_urls_discovered"] = len(ordered)
        self.write_summary()
        return ordered

    def collect(
        self,
        urls: list[str],
        *,
        limit_articles: int | None,
        download_images: bool,
        reuse_raw_html: bool = False,
    ) -> None:
        existing = load_processed_urls(self.cfg.out("processed_jsonl"))
        processed_writer = JsonlWriter(self.cfg.out("processed_jsonl"))
        todo = [u for u in urls if u not in existing]
        if limit_articles is not None:
            todo = todo[:limit_articles]
        self.logger.info("article collection: %d queued, %d already present", len(todo), len(existing))
        for url in todo:
            self.stats["articles_attempted"] += 1
            try:
                if reuse_raw_html:
                    record = self.collect_one_article_from_raw(
                        url, download_images=download_images
                    )
                else:
                    record = self.collect_one_article(url, download_images=download_images)
                processed_writer.append(record)
                self.stats["articles_written"] += 1
                self.logger.info("wrote article %s (%d words, %d images)", url, record["word_count"], len(record["images"]))
            except CrawlBlocked:
                self.write_summary(blocked=True)
                raise
            except Exception as exc:  # continue only for page-specific extraction/download errors
                self.stats["article_failures"] += 1
                self.failures_log.append(
                    {
                        "run_id": self.run_id,
                        "url": url,
                        "purpose": "article",
                        "attempted_at_utc": utc_now(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                self.logger.exception("article failed: %s", url)
            finally:
                self.write_summary()
        self.stats["articles_skipped_existing"] = len(existing)
        self.write_summary()

    def capture_html_only(
        self,
        urls: list[str],
        *,
        limit_articles: int | None,
    ) -> None:
        """Capture missing article HTML without parsing text or downloading images.

        This is the safest first pass for a large archive: successful captures are
        immutable source records, while extraction can be rerun offline later.
        """
        todo: list[str] = []
        skipped = 0
        raw_dir = self.cfg.out("raw_html_dir")

        for url in urls:
            request_meta = latest_article_request_metadata(
                self.cfg.out("requests_jsonl"), url
            )
            candidates = {canonicalise_url(url)}
            final_url = request_meta.get("final_url")
            if final_url:
                candidates.add(canonicalise_url(final_url))
            exists = any(
                (raw_dir / f"{hashlib.sha256(candidate.encode('utf-8')).hexdigest()[:20]}.html").exists()
                for candidate in candidates
            )
            if exists:
                skipped += 1
            else:
                todo.append(url)

        if limit_articles is not None:
            todo = todo[:limit_articles]

        self.stats["html_capture_queued"] = len(todo)
        self.stats["html_capture_skipped_existing"] = skipped
        self.stats.setdefault("html_capture_attempted", 0)
        self.stats.setdefault("html_capture_written", 0)
        self.stats.setdefault("html_capture_failures", 0)
        self.logger.info(
            "HTML-only capture: %d queued, %d already present", len(todo), skipped
        )

        for url in todo:
            self.stats["html_capture_attempted"] += 1
            try:
                if not article_url_allowed(url, self.site, self.scope):
                    raise ValueError(f"out-of-scope article URL: {url}")
                content, response = self.fetch(url, purpose="article_html_capture")
                content_type = response.headers.get("Content-Type", "")
                if "html" not in content_type.lower():
                    raise ValueError(f"article is not HTML: {content_type}")
                canonical_url = canonicalise_url(response.url)
                doc_id = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:20]
                raw_path = raw_dir / f"{doc_id}.html"
                atomic_write_bytes(raw_path, content)
                self.stats["html_capture_written"] += 1
                self.logger.info(
                    "captured HTML %s -> %s (%d bytes)",
                    url, raw_path.name, len(content),
                )
            except CrawlBlocked:
                self.write_summary(blocked=True)
                raise
            except Exception as exc:
                self.stats["html_capture_failures"] += 1
                self.failures_log.append(
                    {
                        "run_id": self.run_id,
                        "url": url,
                        "purpose": "article_html_capture",
                        "attempted_at_utc": utc_now(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                self.logger.exception("HTML capture failed: %s", url)
            finally:
                self.write_summary()

        self.write_summary()

    def collect_one_article(self, url: str, *, download_images: bool) -> dict[str, Any]:
        if not article_url_allowed(url, self.site, self.scope):
            raise ValueError(f"out-of-scope article URL: {url}")
        content, response = self.fetch(url, purpose="article")
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            raise ValueError(f"article is not HTML: {content_type}")
        canonical_url = canonicalise_url(response.url)
        doc_id = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:20]
        raw_path = self.cfg.out("raw_html_dir") / f"{doc_id}.html"
        atomic_write_bytes(raw_path, content)
        request_meta = {
            "request_url": url,
            "final_url": canonical_url,
            "retrieved_at_utc": utc_now(),
            "http_status": response.status_code,
            "content_type": content_type,
            "content_encoding": response.encoding,
            "redirect_chain": [r.url for r in response.history],
            "source_type": "live_public_web",
        }
        return self._build_article_record(
            content,
            request_meta=request_meta,
            raw_path=raw_path,
            download_images=download_images,
        )

    def collect_one_article_from_raw(
        self, url: str, *, download_images: bool
    ) -> dict[str, Any]:
        """Reparse a previously captured HTML file without refetching the article page."""
        if not article_url_allowed(url, self.site, self.scope):
            raise ValueError(f"out-of-scope article URL: {url}")
        request_meta = latest_article_request_metadata(self.cfg.out("requests_jsonl"), url)
        final_url = canonicalise_url(request_meta.get("final_url") or url)
        doc_id = hashlib.sha256(final_url.encode("utf-8")).hexdigest()[:20]
        raw_path = self.cfg.out("raw_html_dir") / f"{doc_id}.html"
        if not raw_path.exists():
            fallback_id = hashlib.sha256(canonicalise_url(url).encode("utf-8")).hexdigest()[:20]
            fallback = self.cfg.out("raw_html_dir") / f"{fallback_id}.html"
            if fallback.exists():
                raw_path = fallback
                final_url = canonicalise_url(url)
            else:
                raise FileNotFoundError(
                    f"no saved raw HTML for {url}; expected {raw_path} or {fallback}"
                )
        content = raw_path.read_bytes()
        retrieved_at = request_meta.get("requested_at_utc")
        if not retrieved_at:
            retrieved_at = datetime.fromtimestamp(
                raw_path.stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds")
        meta = {
            "request_url": url,
            "final_url": final_url,
            "retrieved_at_utc": retrieved_at,
            "http_status": request_meta.get("http_status", 200),
            "content_type": request_meta.get("content_type") or "text/html",
            "content_encoding": None,
            "redirect_chain": request_meta.get("redirect_chain", []),
            "source_type": "saved_live_capture_reparsed",
        }
        return self._build_article_record(
            content,
            request_meta=meta,
            raw_path=raw_path,
            download_images=download_images,
        )

    def _build_article_record(
        self,
        content: bytes,
        *,
        request_meta: dict[str, Any],
        raw_path: Path,
        download_images: bool,
    ) -> dict[str, Any]:
        canonical_url = canonicalise_url(str(request_meta["final_url"]))
        doc_id = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:20]
        raw_sha = hashlib.sha256(content).hexdigest()
        soup = BeautifulSoup(content, "html.parser")
        parsed = parse_article(
            soup,
            canonical_url,
            minimum_words=int(self.scope.get("minimum_body_words", 20)),
        )
        image_records: list[dict[str, Any]] = []
        if download_images:
            for idx, image in enumerate(parsed.pop("image_candidates"), start=1):
                self.stats["images_attempted"] += 1
                image_record = self.download_image(doc_id, idx, image, canonical_url)
                if image_record is not None:
                    image_records.append(image_record)
        else:
            parsed.pop("image_candidates")
        # Commit image-manifest rows only after the complete article has been parsed
        # and all of its permitted image requests have finished. This prevents duplicate
        # image rows when a run is interrupted mid-article and later resumed.
        for image_record in image_records:
            self.images_log.append(image_record)
            self.stats["images_written"] += 1
        body, redaction_count = redact_derived_text(parsed["body"])
        paragraphs = [redact_derived_text(p)[0] for p in parsed["paragraphs"]]
        for image_record in image_records:
            for field in ("alt_text", "title_text", "figcaption"):
                if image_record.get(field):
                    image_record[field] = redact_derived_text(image_record[field])[0]
        return {
            "document_id": doc_id,
            "request_url": str(request_meta["request_url"]),
            "final_url": canonical_url,
            "retrieved_at_utc": str(request_meta["retrieved_at_utc"]),
            "published_at": parsed["published_at"],
            "author": parsed["author"],
            "title": parsed["title"],
            "section": "news",
            "language": "en",
            "body": body,
            "paragraphs": paragraphs,
            "tags": parsed["tags"],
            "body_selector": parsed.get("body_selector"),
            "word_count": len(body.split()),
            "raw_payload_sha256": raw_sha,
            "derived_text_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "raw_html_path": str(raw_path.relative_to(self.root)),
            "http_status": request_meta.get("http_status"),
            "content_type": request_meta.get("content_type"),
            "content_encoding": request_meta.get("content_encoding"),
            "redirect_chain": request_meta.get("redirect_chain", []),
            "images": image_records,
            "collection_run_id": self.run_id,
            "source_type": request_meta.get("source_type", "live_public_web"),
            "corpus_layer": "derived",
            "comments_collected": False,
            "email_redactions": redaction_count,
            "personal_data_flag": bool(redaction_count),
            "rights_status": "research_capture_not_cleared_for_raw_redistribution",
        }

    def download_image(
        self, doc_id: str, position: int, candidate: dict[str, Any], article_url: str
    ) -> dict[str, Any] | None:
        image_url = candidate["url"]
        host = (urlparse(image_url).hostname or "").lower()
        allowed_hosts = {h.lower() for h in self.site.get("image_hosts", [])}
        if host not in allowed_hosts:
            self.stats["images_skipped"] += 1
            self.skipped_images_log.append(
                {
                    "run_id": self.run_id,
                    "document_id": doc_id,
                    "article_url": article_url,
                    "image_url": image_url,
                    "reason": "image_host_not_allowlisted",
                    "host": host,
                }
            )
            return None
        try:
            content, response = self.fetch(image_url, purpose="image", binary=True)
        except (PermissionError, RobotsUnavailable) as exc:
            self.stats["images_skipped"] += 1
            self.skipped_images_log.append(
                {
                    "run_id": self.run_id,
                    "document_id": doc_id,
                    "article_url": article_url,
                    "image_url": image_url,
                    "reason": type(exc).__name__,
                    "detail": str(exc),
                }
            )
            return None
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if not mime.startswith("image/"):
            raise ValueError(f"non-image MIME type for {image_url}: {mime}")
        sha = hashlib.sha256(content).hexdigest()
        ext = extension_for_image(mime, response.url)
        object_path = self.cfg.out("image_object_dir") / f"{sha}{ext}"
        if not object_path.exists():
            atomic_write_bytes(object_path, content)
        width = height = None
        if mime != "image/svg+xml":
            try:
                with Image.open(object_path) as im:
                    width, height = im.size
                    im.verify()
            except Exception as exc:
                self.logger.warning("Pillow could not validate %s: %s", image_url, exc)
        return {
            "image_id": f"{doc_id}-img-{position:03d}",
            "document_id": doc_id,
            "article_url": article_url,
            "position": position,
            "request_url": image_url,
            "final_url": response.url,
            "retrieved_at_utc": utc_now(),
            "mime_type": mime,
            "byte_count": len(content),
            "sha256": sha,
            "width": width,
            "height": height,
            "object_path": str(object_path.relative_to(self.root)),
            "alt_text": candidate.get("alt_text"),
            "title_text": candidate.get("title_text"),
            "figcaption": candidate.get("figcaption"),
            "caption_source": candidate.get("caption_source"),
            "image_role": candidate.get("image_role", "inline"),
            "source_location": candidate.get("source_location"),
            "dom_index": candidate.get("dom_index"),
            "source_element": candidate.get("source_element"),
            "collection_run_id": self.run_id,
        }

    def write_summary(self, blocked: bool = False) -> None:
        summary = dict(self.stats)
        summary["updated_at_utc"] = utc_now()
        summary["status"] = "BLOCKED_TEMPORARILY" if blocked else "RUNNING_OR_COMPLETE"
        atomic_write_text(self.cfg.out("run_summary_json"), json.dumps(summary, indent=2, sort_keys=True) + "\n")


def setup_logging(path: Path) -> logging.Logger:
    logger = logging.getLogger("pa_news_collector")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(formatter)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Config(raw=raw, config_path=path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonicalise_url(url: str) -> str:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host == "patrioticalternative.org.uk":
        host = "www.patrioticalternative.org.uk"
    netloc = host
    if p.port and not ((p.scheme == "https" and p.port == 443) or (p.scheme == "http" and p.port == 80)):
        netloc = f"{host}:{p.port}"
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((p.scheme.lower() or "https", netloc, path, "", "", ""))


def article_url_allowed(url: str, site: dict[str, Any], scope: dict[str, Any]) -> bool:
    p = urlparse(url)
    if p.scheme not in {"http", "https"}:
        return False
    if (p.hostname or "").lower() not in {h.lower() for h in site["article_hosts"]}:
        return False
    path = p.path.rstrip("/") or "/"
    if path in {"/", scope["listing_path"]}:
        return False
    if any(path.startswith(prefix) for prefix in scope.get("excluded_path_prefixes", [])):
        return False
    if any(path.lower().endswith(ext) for ext in IMAGE_EXTENSIONS):
        return False
    return True


def extract_listing_article_urls(
    soup: BeautifulSoup, site: dict[str, Any], scope: dict[str, Any]
) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    selectors = (
        "h3 a[href]",
        "article h2 a[href]",
        "article h3 a[href]",
        ".page-excerpt h2 a[href]",
        ".page-excerpt h3 a[href]",
        ".blog-post h2 a[href]",
        ".blog-post h3 a[href]",
    )
    for selector in selectors:
        for a in soup.select(selector):
            href = a.get("href")
            if not href:
                continue
            url = canonicalise_url(urljoin(site["base_url"], href))
            if article_url_allowed(url, site, scope) and url not in seen:
                seen.add(url)
                links.append(url)
    return links


def max_pagination_number(soup: BeautifulSoup) -> int | None:
    values: list[int] = []
    for a in soup.select('a[href*="page="]'):
        href = a.get("href", "")
        for value in parse_qs(urlparse(href).query).get("page", []):
            if value.isdigit():
                values.append(int(value))
    return max(values) if values else None


def select_primary_article_body(soup: BeautifulSoup) -> Tag | None:
    """Return the site-specific NationBuilder article body when present.

    Verified against saved PA news HTML from both the normal and ``-wide``
    NationBuilder blog-post templates. The outer page contains several elements
    named ``content``; the article itself is the nested ``#intro > .content``
    inside ``main#content``.
    """
    selectors = (
        "main#content div#intro.intro > div.content",
        "main#content #intro.intro > .content",
        "main#content #intro > .content",
        "body.page-type-blog-post main#content .intro > .content",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if isinstance(node, Tag):
            return node
    return None


def text_without_images(node: Tag) -> str:
    clone = BeautifulSoup(str(node), "html.parser")
    for child in clone.select("img,picture,source,figure,figcaption,script,style,noscript"):
        child.decompose()
    return clean_text(clone.get_text(" ", strip=True))


def is_inline_image_caption_container(node: Tag, residual_text: str) -> bool:
    """Identify NationBuilder captions stored as text beside an image in one block."""
    if not node.find("img") or not residual_text:
        return False
    signature = node_signature(node)
    style = str(node.get("style") or "")
    centred = bool(re.search(r"text-align\s*:\s*center", style, re.I))
    caption_class = bool(re.search(r"caption|credit|image-description", signature, re.I))
    words = residual_text.split()
    # The PA theme often writes ``<p><img ...>Reaching out in Morley</p>``.
    # A short, image-dominated block is therefore a caption, even without a
    # figcaption element. Long mixed text/image paragraphs remain body text.
    image_dominated = len(words) <= 25 and len(residual_text) <= 280
    return caption_class or centred or image_dominated


def extract_primary_body_blocks(root: Tag, *, title: str) -> list[str]:
    """Extract text only from the verified article-body subtree.

    Image-only blocks and short same-block image captions are excluded from the
    linguistic body because they are retained in the image metadata instead.
    """
    blocks: list[str] = []
    seen: set[str] = set()
    for node in root.find_all(["p", "li", "blockquote", "h2", "h3", "h4", "pre"]):
        if is_noise_node(node):
            continue
        # Avoid duplicate extraction from nested block elements.
        parent = node.parent
        nested = False
        while isinstance(parent, Tag) and parent is not root:
            if parent.name in BLOCK_TAGS:
                nested = True
                break
            parent = parent.parent
        if nested:
            continue
        residual = text_without_images(node) if node.find("img") else clean_text(node.get_text(" ", strip=True))
        if node.find("img") and is_inline_image_caption_container(node, residual):
            continue
        value = clean_candidate_block(residual, title=title, tag_texts=set())
        if value == "__STOP__":
            break
        if not value or value in seen:
            continue
        seen.add(value)
        blocks.append(value)
    return blocks


def extract_article_tags(soup: BeautifulSoup, root: Tag | BeautifulSoup) -> list[str]:
    # Tags live in the article header, immediately before #intro, rather than in
    # the body subtree. Restricting the selector to the main article avoids tags
    # that might occur in unrelated navigation or footer material.
    tags = {
        clean_text(a.get_text(" ", strip=True))
        for a in soup.select("main#content header a[href^='/tags/'], main#content header a[href*='/tags/']")
        if clean_text(a.get_text(" ", strip=True))
    }
    return sorted(tags) if tags else extract_tags(root) or extract_tags(soup)


def extract_hero_image_candidate(soup: BeautifulSoup, article_url: str) -> dict[str, Any] | None:
    sources: list[tuple[str, str]] = []
    meta = soup.find("meta", attrs={"property": "og:image"})
    if meta and meta.get("content"):
        sources.append((str(meta["content"]), "og:image"))
    link = soup.find("link", attrs={"rel": lambda value: value and "image_src" in value})
    if link and link.get("href"):
        sources.append((str(link["href"]), "link:image_src"))
    banner = soup.select_one("section.blog-home-banner .banner-overlay[style*='background']")
    if banner:
        match = re.search(r"background(?:-image)?\s*:\s*url\((['\"]?)(.*?)\1\)", str(banner.get("style") or ""), re.I)
        if match:
            sources.append((match.group(2), "banner_background"))
    if not sources:
        return None
    raw, source = sources[0]
    image_url = canonicalise_asset_url(urljoin(article_url, raw))
    return {
        "url": image_url,
        "alt_text": None,
        "title_text": None,
        "figcaption": None,
        "caption_source": None,
        "image_role": "hero",
        "source_location": source,
        "source_element": f"{source}:{raw}"[:1000],
    }


def merge_image_candidates(*candidate_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for group in candidate_groups:
        for candidate in group:
            key = canonicalise_asset_url(candidate["url"])
            if key in positions:
                existing = merged[positions[key]]
                # Prefer the inline record because it can carry a genuine caption.
                if candidate.get("image_role") == "inline":
                    existing.update({k: v for k, v in candidate.items() if v is not None})
                continue
            positions[key] = len(merged)
            merged.append(candidate)
    return merged


def parse_article(soup: BeautifulSoup, url: str, minimum_words: int) -> dict[str, Any]:
    title = extract_title(soup)
    published_at = extract_published_at(soup)
    author = extract_author(soup)

    primary_root = select_primary_article_body(soup)
    candidate_debug: list[str] = []
    if primary_root is not None:
        root = primary_root
        paragraphs = extract_primary_body_blocks(root, title=title)
        candidate_debug.append(
            f"verified selector main#content #intro > .content words={word_count_blocks(paragraphs)}"
        )
    else:
        root, anchor, candidate_debug = choose_article_root(soup, title)
        structured = extract_body_blocks(root, anchor, title=title)
        line_fallback = extract_body_lines(root, title=title)
        paragraphs = choose_better_body(structured, line_fallback)

        if word_count_blocks(paragraphs) < minimum_words and soup.body is not None and root is not soup.body:
            body_structured = extract_body_blocks(soup.body, None, title=title)
            body_lines = extract_body_lines(soup.body, title=title)
            paragraphs = choose_better_body(paragraphs, body_structured, body_lines)

    jsonld = extract_jsonld_article(soup)
    if word_count_blocks(paragraphs) < minimum_words and jsonld.get("paragraphs"):
        paragraphs = choose_better_body(paragraphs, jsonld["paragraphs"])
    if published_at is None and jsonld.get("published_at"):
        published_at = jsonld["published_at"]
    if author is None and jsonld.get("author"):
        author = jsonld["author"]

    paragraphs = [
        p for p in paragraphs
        if normalise_for_match(p) != normalise_for_match(title)
    ]
    body = "\n\n".join(paragraphs).strip()
    if len(body.split()) < minimum_words:
        raise ValueError(
            f"extracted body is too short ({len(body.split())} words) for {url}; "
            f"top candidate roots: {'; '.join(candidate_debug[:6])}"
        )

    inline_images = extract_image_candidates(root, url)
    hero = extract_hero_image_candidate(soup, url)
    image_candidates = merge_image_candidates(
        [hero] if hero else [], inline_images
    )
    return {
        "title": title,
        "published_at": published_at,
        "author": author,
        "paragraphs": paragraphs,
        "body": body,
        "tags": extract_article_tags(soup, root),
        "image_candidates": image_candidates,
        "body_selector": "main#content #intro > .content" if primary_root is not None else "fallback_scored_root",
    }

def extract_title(soup: BeautifulSoup) -> str:
    # Metadata is stable across NationBuilder themes and avoids choosing the decorative
    # H1 when a second H2 contains the actual article heading.
    for attrs in (
        {"property": "og:title"},
        {"name": "twitter:title"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            return clean_site_title(meta["content"])
    for selector in ("main h1", "article h1", "h1", "main h2", "article h2"):
        heading = soup.select_one(selector)
        if heading and clean_text(heading.get_text(" ", strip=True)):
            return clean_site_title(heading.get_text(" ", strip=True))
    if soup.title:
        return clean_site_title(soup.title.get_text(" ", strip=True))
    raise ValueError("article title not found")



def clean_site_title(value: str) -> str:
    title = clean_text(value)
    return re.sub(r"\s+(?:-|\|)\s+Patriotic Alternative\s*$", "", title, flags=re.I).strip()

def extract_published_at(soup: BeautifulSoup) -> str | None:
    candidates: list[str] = []
    for attrs in (
        {"property": "article:published_time"},
        {"name": "date"},
        {"name": "publish_date"},
        {"itemprop": "datePublished"},
    ):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            candidates.append(meta["content"])
    for time_tag in soup.find_all("time"):
        if time_tag.get("datetime"):
            candidates.append(time_tag["datetime"])
        candidates.append(time_tag.get_text(" ", strip=True))
    for selector in (".byline", ".published-at", ".date", ".post-date", ".blog-date"):
        for node in soup.select(selector):
            candidates.append(node.get_text(" ", strip=True))
    candidates.extend(soup.get_text("\n", strip=True).splitlines()[:120])
    date_re = re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}(?:\s+\d{1,2}:\d{2}\s*(?:AM|PM))?\b",
        re.I,
    )
    for value in candidates:
        if not value:
            continue
        match = date_re.search(value)
        candidate = match.group(0) if match else value
        try:
            dt = date_parser.parse(candidate, fuzzy=True)
            if dt.year < 1990 or dt.year > datetime.now().year + 1:
                continue
            if dt.tzinfo is None:
                return dt.isoformat()
            return dt.astimezone(timezone.utc).isoformat()
        except (ValueError, OverflowError):
            continue
    return None


def extract_author(soup: BeautifulSoup) -> str | None:
    for attrs in ({"name": "author"}, {"property": "article:author"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            return clean_text(meta["content"])
    text = soup.get_text("\n", strip=True)
    match = re.search(r"Posted by\s+(.+?)(?:\s*[·•|]\s*|\n|$)", text, re.I)
    return clean_text(match.group(1)) if match else None


def normalise_for_match(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).casefold()).strip()


def node_signature(node: Tag) -> str:
    return " ".join(node.get("class", [])) + " " + (node.get("id") or "")


def matching_title_headings(root: Tag | BeautifulSoup, title: str) -> list[Tag]:
    target = normalise_for_match(title)
    matches: list[Tag] = []
    for heading in root.find_all(["h1", "h2", "h3"]):
        text = normalise_for_match(heading.get_text(" ", strip=True))
        if text and (text == target or text in target or target in text):
            matches.append(heading)
    return matches


def candidate_content_roots(soup: BeautifulSoup, title: str) -> list[Tag]:
    selectors = (
        "[itemprop='articleBody']",
        "article",
        ".article-content",
        ".post-content",
        ".entry-content",
        ".blog-post",
        ".page-content",
        ".content-pages",
        ".content",
        "main",
        "[role='main']",
        "#content",
    )
    roots: list[Tag] = []
    seen: set[int] = set()

    def add(node: Tag | None) -> None:
        if isinstance(node, Tag) and id(node) not in seen:
            seen.add(id(node))
            roots.append(node)

    for selector in selectors:
        for node in soup.select(selector):
            add(node)
    for heading in matching_title_headings(soup, title):
        parent = heading.parent
        depth = 0
        while isinstance(parent, Tag) and parent.name != "html" and depth < 8:
            add(parent)
            if parent.name == "body":
                break
            parent = parent.parent
            depth += 1
    add(soup.body)
    return roots


def root_specificity_bonus(root: Tag) -> int:
    signature = node_signature(root).casefold()
    bonus = 0
    if root.name == "article":
        bonus += 160
    if root.get("itemprop") == "articleBody":
        bonus += 220
    if re.search(r"article|post|entry|blog|page-content|content-pages", signature):
        bonus += 100
    if root.name in {"body", "html"}:
        bonus -= 180
    elif root.name == "main":
        bonus -= 40
    if NOISE_RE.search(signature):
        bonus -= 500
    return bonus


def choose_article_root(
    soup: BeautifulSoup, title: str
) -> tuple[Tag, Tag | None, list[str]]:
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    scored: list[tuple[int, int, Tag, Tag | None]] = []
    for root in candidate_content_roots(soup, title):
        anchors: list[Tag | None] = list(matching_title_headings(root, title))
        anchors.append(None)
        best_words = -1
        best_anchor: Tag | None = None
        for anchor in anchors:
            blocks = choose_better_body(
                extract_body_blocks(root, anchor, title=title),
                extract_body_lines(root, title=title, anchor=anchor),
            )
            words = word_count_blocks(blocks)
            if words > best_words:
                best_words = words
                best_anchor = anchor
        score = best_words + root_specificity_bonus(root)
        score += min(len(root.find_all(["p", "blockquote", "li"])), 50) * 12
        score -= min(sum(1 for _ in root.descendants) // 80, 80)
        scored.append((score, best_words, root, best_anchor))
    if not scored:
        raise ValueError("article root not found")
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _, _, root, anchor = scored[0]
    debug = [
        f"<{node.name} id={node.get('id')!r} class={node.get('class')!r}> "
        f"score={score} words={words}"
        for score, words, node, _ in scored[:10]
    ]
    return root, anchor, debug


def is_noise_node(node: Tag) -> bool:
    current: Tag | None = node
    while isinstance(current, Tag):
        if current.name in {"nav", "footer", "header", "aside", "form"}:
            return True
        if NOISE_RE.search(node_signature(current)):
            return True
        current = current.parent if isinstance(current.parent, Tag) else None
    return False


def extract_tags(root: Tag | BeautifulSoup) -> list[str]:
    return sorted(
        {
            clean_text(a.get_text(" ", strip=True))
            for a in root.select('a[href*="/tags/"]')
            if clean_text(a.get_text(" ", strip=True))
        }
    )


def clean_candidate_block(text: str, *, title: str, tag_texts: set[str]) -> str | None:
    text = clean_text(text)
    if not text:
        return None
    norm = normalise_for_match(text)
    title_norm = normalise_for_match(title)
    if norm == title_norm or norm in title_norm or title_norm in norm:
        return None
    if text in tag_texts:
        return None
    if STOP_TEXT_RE.search(text):
        return "__STOP__"
    if META_TEXT_RE.search(text):
        return None
    if norm in {"home", "news", "read more"}:
        return None
    return text


def extract_body_blocks(root: Tag, anchor: Tag | None, *, title: str) -> list[str]:
    blocks: list[str] = []
    seen: set[str] = set()
    tag_texts = set(extract_tags(root))
    anchor_is_inside = anchor is not None and (anchor is root or anchor in root.descendants)
    started = not anchor_is_inside
    for node in root.descendants:
        if not isinstance(node, Tag):
            continue
        if anchor_is_inside and node is anchor:
            started = True
            continue
        if not started or node.name not in BLOCK_TAGS or is_noise_node(node):
            continue
        value = clean_candidate_block(
            node.get_text(" ", strip=True), title=title, tag_texts=tag_texts
        )
        if value == "__STOP__":
            break
        if not value or value in seen:
            continue
        if any(value == previous or value in previous for previous in blocks[-3:]):
            continue
        seen.add(value)
        blocks.append(value)
    return blocks


def extract_body_lines(
    root: Tag, *, title: str, anchor: Tag | None = None
) -> list[str]:
    """Fallback for themes that use div/br text instead of semantic paragraphs."""
    clone = BeautifulSoup(str(root), "html.parser")
    for node in clone.select(
        "script,style,noscript,template,nav,footer,header,aside,form,.breadcrumb,.breadcrumbs,"
        ".share,.social,.reaction,.reactions,.comment,.comments,.signup,.newsletter,.pagination,"
        "figcaption,.caption,.image-caption,.wp-caption-text"
    ):
        node.decompose()
    tag_texts = set(extract_tags(clone))
    lines = [clean_text(x) for x in clone.get_text("\n", strip=True).splitlines()]
    lines = [x for x in lines if x]
    title_norm = normalise_for_match(title)
    title_positions = [i for i, line in enumerate(lines) if normalise_for_match(line) == title_norm]
    start = title_positions[-1] + 1 if title_positions else 0
    out: list[str] = []
    seen: set[str] = set()
    for line in lines[start:]:
        value = clean_candidate_block(line, title=title, tag_texts=tag_texts)
        if value == "__STOP__":
            break
        if not value or value in seen or re.fullmatch(r"Posted by", value, re.I):
            continue
        seen.add(value)
        out.append(value)
    return out


def choose_better_body(*candidates: list[str]) -> list[str]:
    usable = [candidate for candidate in candidates if candidate]
    return max(usable, key=lambda x: (word_count_blocks(x), len(x))) if usable else []


def word_count_blocks(blocks: list[str]) -> int:
    return sum(len(text.split()) for text in blocks)


def extract_jsonld_article(soup: BeautifulSoup) -> dict[str, Any]:
    def walk(value: Any):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in walk(data):
            kind = item.get("@type")
            kinds = {kind} if isinstance(kind, str) else set(kind or [])
            if not kinds.intersection({"Article", "NewsArticle", "BlogPosting"}):
                continue
            article_body = item.get("articleBody")
            paragraphs: list[str] = []
            if isinstance(article_body, str) and article_body.strip():
                body_soup = BeautifulSoup(article_body, "html.parser")
                paragraphs = [
                    clean_text(line)
                    for line in body_soup.get_text("\n", strip=True).splitlines()
                    if clean_text(line)
                ]
            author = item.get("author")
            if isinstance(author, dict):
                author = author.get("name")
            elif isinstance(author, list):
                author = ", ".join(
                    str(x.get("name")) if isinstance(x, dict) else str(x)
                    for x in author
                )
            return {
                "paragraphs": paragraphs,
                "published_at": item.get("datePublished"),
                "author": clean_text(str(author)) if author else None,
            }
    return {}


def extract_inline_caption(img: Tag) -> tuple[str | None, str | None]:
    """Extract explicit or NationBuilder same-paragraph captions for one image."""
    figure = img.find_parent("figure")
    if figure:
        cap = figure.find("figcaption")
        if cap:
            value = clean_text(cap.get_text(" ", strip=True))
            if value:
                return value, "figcaption"

    parent = img.parent if isinstance(img.parent, Tag) else None
    if parent and parent.name in {"p", "div", "span"}:
        residual = text_without_images(parent)
        if residual and is_inline_image_caption_container(parent, residual):
            return residual, "inline_parent_text"

    if parent:
        for sibling in parent.find_next_siblings(limit=2):
            if not isinstance(sibling, Tag):
                continue
            signature = node_signature(sibling)
            if re.search(r"caption|credit|image-description", signature, re.I):
                value = clean_text(sibling.get_text(" ", strip=True))
                if value:
                    return value, "caption_class_sibling"
    return None, None


def extract_image_candidates(root: Tag, article_url: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for dom_index, img in enumerate(root.find_all("img"), start=1):
        if is_noise_node(img):
            continue
        raw = best_image_source(img)
        if not raw:
            continue
        url = urljoin(article_url, raw)
        if url.startswith("data:"):
            continue
        canonical = canonicalise_asset_url(url)
        if canonical in seen or likely_decorative_image(img, canonical):
            continue
        seen.add(canonical)
        figcaption, caption_source = extract_inline_caption(img)
        candidates.append(
            {
                "url": canonical,
                "alt_text": clean_text(img.get("alt", "")) or None,
                "title_text": clean_text(img.get("title", "")) or None,
                "figcaption": figcaption,
                "caption_source": caption_source,
                "image_role": "inline",
                "source_location": "article_body",
                "dom_index": dom_index,
                "source_element": str(img)[:1000],
            }
        )
    return candidates

def best_image_source(img: Tag) -> str | None:
    for attr in ("data-src", "data-original", "data-lazy-src", "data-cfsrc"):
        if img.get(attr):
            return str(img[attr]).strip()
    srcset = img.get("data-srcset") or img.get("srcset")
    if srcset:
        options: list[tuple[int, str]] = []
        for item in str(srcset).split(","):
            bits = item.strip().split()
            if not bits:
                continue
            score = 0
            if len(bits) > 1:
                descriptor = bits[1].lower()
                try:
                    score = int(float(descriptor.rstrip("wx")) * (1000 if descriptor.endswith("x") else 1))
                except ValueError:
                    pass
            options.append((score, bits[0]))
        if options:
            return max(options, key=lambda x: x[0])[1]
    return str(img.get("src", "")).strip() or None


def likely_decorative_image(img: Tag, url: str) -> bool:
    signature = " ".join(img.get("class", [])) + " " + (img.get("id") or "") + " " + url
    if re.search(r"logo|avatar|profile|icon|emoji|spinner|tracking|pixel|gravatar", signature, re.I):
        return True
    try:
        width = int(str(img.get("width", "0")).replace("px", ""))
        height = int(str(img.get("height", "0")).replace("px", ""))
        if width and height and width <= 80 and height <= 80:
            return True
    except ValueError:
        pass
    return False


def canonicalise_asset_url(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme or "https", p.netloc, p.path, "", p.query, ""))


def extension_for_image(mime: str, url: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/avif": ".avif",
        "image/svg+xml": ".svg",
    }
    if mime in mapping:
        return mapping[mime]
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix
    return mimetypes.guess_extension(mime) or ".img"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


def redact_derived_text(value: str) -> tuple[str, int]:
    """Redact email addresses from distributable derived text; raw HTML is unchanged."""
    matches = EMAIL_RE.findall(value)
    return EMAIL_RE.sub("[EMAIL_REDACTED]", value), len(matches)


def load_url_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            records[rec["url"]] = rec
    return records


def latest_article_request_metadata(path: Path, request_url: str) -> dict[str, Any]:
    target = canonicalise_url(request_url)
    latest: dict[str, Any] = {}
    if not path.exists():
        return latest
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("purpose") != "article":
                continue
            if canonicalise_url(str(record.get("request_url", ""))) == target:
                latest = record
    return latest


def load_processed_urls(path: Path) -> set[str]:
    urls: set[str] = set()
    if not path.exists():
        return urls
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            urls.add(canonicalise_url(rec["final_url"]))
            urls.add(canonicalise_url(rec["request_url"]))
    return urls


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["preflight", "discover", "capture", "collect", "reparse", "all"])
    ap.add_argument("--config", type=Path, default=Path("config/pa_news.yml"))
    ap.add_argument("--limit-pages", type=int)
    ap.add_argument("--limit-articles", type=int)
    ap.add_argument("--skip-images", action="store_true")
    ap.add_argument(
        "--reuse-raw-html",
        action="store_true",
        help="parse saved raw article HTML instead of refetching article pages",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    collector = Collector(load_config(args.config))
    try:
        if args.command == "preflight":
            collector.preflight()
        elif args.command == "discover":
            collector.discover(args.limit_pages)
        elif args.command in {"capture", "collect", "reparse"}:
            records = load_url_records(collector.cfg.out("urls_jsonl"))
            if not records:
                raise SystemExit("No URL manifest found. Run discover first.")
            urls = [
                record["url"]
                for record in sorted(
                    records.values(),
                    key=lambda x: (x.get("listing_page", 0), x.get("position", 0)),
                )
            ]
            if args.command == "capture":
                collector.capture_html_only(
                    urls,
                    limit_articles=args.limit_articles,
                )
            else:
                collector.collect(
                    urls,
                    limit_articles=args.limit_articles,
                    download_images=not args.skip_images,
                    reuse_raw_html=(args.command == "reparse" or args.reuse_raw_html),
                )
        else:
            urls = collector.discover(args.limit_pages)
            collector.collect(
                urls,
                limit_articles=args.limit_articles,
                download_images=not args.skip_images,
                reuse_raw_html=args.reuse_raw_html,
            )
        collector.write_summary()
        return 0
    except (CrawlBlocked, RobotsUnavailable) as exc:
        collector.logger.error("COLLECTION STOPPED: %s", exc)
        collector.write_summary(blocked=True)
        return EXIT_TEMPORARY_BLOCK


if __name__ == "__main__":
    raise SystemExit(main())
