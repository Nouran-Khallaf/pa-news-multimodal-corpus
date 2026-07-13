#!/usr/bin/env python3
"""
Static, non-executing security and integrity scanner for JSONL/NDJSON files.

Checks:
- MD5, SHA-1, SHA-256, file size
- strict UTF-8 decoding
- JSONL parsing
- duplicate full records and duplicate IDs
- unexpected control characters
- suspicious executable/script/payload indicators
- long Base64-like and hex-like blobs
- URLs, schemes, and suspicious downloadable extensions
- optional ClamAV and YARA scans when installed

This script does not execute file content.
It is not a substitute for a current multi-engine malware scan.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse


HASH_CHUNK_SIZE = 1024 * 1024

URL_RE = re.compile(
    r"""(?ix)
    \b(
        (?:https?|ftp|file|data|javascript|vbscript|about):
        (?://)?
        [^\s<>"'{}|\\^`\[\]]+
    )
    """
)

BASE64_RE = re.compile(
    r"(?<![A-Za-z0-9+/=])(?:[A-Za-z0-9+/]{4}){32,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?(?![A-Za-z0-9+/=])"
)

HEX_BLOB_RE = re.compile(
    r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}){64,}(?![0-9A-Fa-f])"
)

SUSPICIOUS_EXTENSIONS = {
    ".exe", ".dll", ".scr", ".com", ".bat", ".cmd", ".ps1", ".psm1",
    ".vbs", ".vbe", ".js", ".jse", ".jar", ".msi", ".msp", ".hta",
    ".apk", ".dmg", ".pkg", ".iso", ".img", ".lnk", ".reg",
    ".docm", ".xlsm", ".pptm", ".xlam", ".xll",
    ".sh", ".bash", ".zsh", ".ksh", ".pyc", ".so",
}

ID_FIELD_CANDIDATES = (
    "document_id", "article_id", "record_id", "id", "uuid", "pair_id"
)

SUSPICIOUS_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("javascript_scheme", re.compile(r"\bjavascript\s*:", re.I)),
    ("vbscript_scheme", re.compile(r"\bvbscript\s*:", re.I)),
    ("data_html_uri", re.compile(r"\bdata\s*:\s*text/html", re.I)),
    ("html_script_tag", re.compile(r"<\s*script\b", re.I)),
    ("html_iframe_tag", re.compile(r"<\s*iframe\b", re.I)),
    ("html_object_embed", re.compile(r"<\s*(?:object|embed)\b", re.I)),
    ("php_code", re.compile(r"<\?php\b", re.I)),
    ("powershell", re.compile(r"\bpowershell(?:\.exe)?\b", re.I)),
    ("powershell_encoded", re.compile(r"\b(?:-enc|-encodedcommand)\b", re.I)),
    ("cmd_execution", re.compile(r"\bcmd(?:\.exe)?\s+/[ck]\b", re.I)),
    ("shell_execution", re.compile(r"(?:^|[\s;&|])(?:/bin/)?(?:ba|z|k|c)?sh\s+-c\b", re.I)),
    ("python_exec", re.compile(r"\bpython(?:3)?\s+-c\b", re.I)),
    ("perl_exec", re.compile(r"\bperl\s+-e\b", re.I)),
    ("ruby_exec", re.compile(r"\bruby\s+-e\b", re.I)),
    ("curl_pipe_shell", re.compile(r"\bcurl\b.{0,200}\|\s*(?:ba|z|k|c)?sh\b", re.I | re.S)),
    ("wget_pipe_shell", re.compile(r"\bwget\b.{0,200}\|\s*(?:ba|z|k|c)?sh\b", re.I | re.S)),
    ("certutil_download", re.compile(r"\bcertutil\b.{0,200}\b-urlcache\b", re.I | re.S)),
    ("bitsadmin", re.compile(r"\bbitsadmin\b", re.I)),
    ("invoke_webrequest", re.compile(r"\binvoke-webrequest\b|\biwr\b", re.I)),
    ("start_process", re.compile(r"\bstart-process\b", re.I)),
    ("process_spawn", re.compile(r"\b(?:subprocess\.(?:run|popen|call)|os\.system)\s*\(", re.I)),
    ("reverse_shell_tcp", re.compile(r"/dev/tcp/|nc\s+[^;\n]{0,120}\s+-e\s+", re.I)),
    ("netcat_listener", re.compile(r"\bnc(?:at)?\b.{0,80}\s-[^\n]*l", re.I)),
    ("meterpreter", re.compile(r"\bmeterpreter\b", re.I)),
    ("mimikatz", re.compile(r"\bmimikatz\b", re.I)),
    ("msfvenom", re.compile(r"\bmsfvenom\b", re.I)),
    ("sql_union_select", re.compile(r"\bunion\s+(?:all\s+)?select\b", re.I)),
    ("sql_sleep", re.compile(r"\b(?:sleep|benchmark|pg_sleep)\s*\(", re.I)),
    ("path_traversal", re.compile(r"(?:\.\./){2,}|(?:\.\.\\){2,}")),
    ("template_injection", re.compile(r"\{\{\s*[^{}]{1,100}\s*\}\}|\$\{\s*[^{}]{1,100}\s*\}")),
    ("office_vba", re.compile(r"\b(?:AutoOpen|Document_Open|Workbook_Open|CreateObject)\b", re.I)),
    ("elf_header_text", re.compile(r"\x7fELF")),
    ("pe_header_text", re.compile(r"\bMZ.{0,100}PE\x00\x00", re.S)),
]

# Indicators that are useful but especially prone to false positives in news prose.
CONTEXTUAL_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("shell_word_bash", re.compile(r"\bbash\b", re.I)),
    ("shell_word_sh", re.compile(r"\b(?:shell|sh)\b", re.I)),
    ("exploit_term", re.compile(r"\b(?:exploit kit|payload|shellcode|zero-day|0day)\b", re.I)),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a non-executing static integrity and security scan on a JSONL/NDJSON file."
    )
    parser.add_argument("input", type=Path, help="Path to the JSONL/NDJSON file")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("security_scan"),
        help="Directory for JSON and Markdown reports (default: security_scan)",
    )
    parser.add_argument(
        "--expected-sha256",
        help="Optional expected SHA-256 hash. A mismatch causes a non-zero exit status.",
    )
    parser.add_argument(
        "--id-field",
        help="Record field used for duplicate-ID checks. If omitted, common names are detected automatically.",
    )
    parser.add_argument(
        "--max-findings",
        type=int,
        default=200,
        help="Maximum stored examples per finding category (default: 200)",
    )
    parser.add_argument(
        "--clamav",
        action="store_true",
        help="Run clamscan if it is installed",
    )
    parser.add_argument(
        "--yara-rules",
        type=Path,
        help="Run yara with the supplied rule file or directory if yara is installed",
    )
    return parser.parse_args()


def compute_hashes(path: Path) -> Dict[str, str]:
    hashers = {
        "md5": hashlib.md5(),
        "sha1": hashlib.sha1(),
        "sha256": hashlib.sha256(),
    }
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            for hasher in hashers.values():
                hasher.update(chunk)
    return {name: hasher.hexdigest() for name, hasher in hashers.items()}


def flatten_strings(value: Any, prefix: str = "") -> Iterable[Tuple[str, str]]:
    if isinstance(value, str):
        yield prefix or "<root>", value
    elif isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            yield from flatten_strings(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child = f"{prefix}[{index}]" if prefix else f"[{index}]"
            yield from flatten_strings(item, child)


def canonical_record_hash(record: Any) -> str:
    payload = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def find_id_field(record: Dict[str, Any], explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit if explicit in record else explicit
    for candidate in ID_FIELD_CANDIDATES:
        if candidate in record:
            return candidate
    return None


def add_example(
    container: Dict[str, List[Dict[str, Any]]],
    category: str,
    example: Dict[str, Any],
    limit: int,
) -> None:
    if len(container[category]) < limit:
        container[category].append(example)


def safe_snippet(text: str, start: int, end: int, radius: int = 100) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = text[left:right].replace("\n", "\\n").replace("\r", "\\r")
    return snippet


def suspicious_url_info(raw_url: str) -> Dict[str, Any]:
    cleaned = raw_url.rstrip(".,;:!?)]}")
    parsed = urlparse(cleaned)
    path_lower = parsed.path.lower()
    ext = Path(path_lower).suffix
    return {
        "url": cleaned,
        "scheme": parsed.scheme.lower(),
        "hostname": parsed.hostname,
        "extension": ext,
        "suspicious_extension": ext in SUSPICIOUS_EXTENSIONS,
    }


def plausible_base64(blob: str) -> bool:
    compact = re.sub(r"\s+", "", blob)
    if len(compact) < 128 or len(compact) % 4 != 0:
        return False
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        return False
    if len(decoded) < 64:
        return False
    # Exclude long normal-language strings that happen to match loosely.
    printable = sum((32 <= byte <= 126) or byte in (9, 10, 13) for byte in decoded)
    return printable / max(1, len(decoded)) < 0.98 or any(
        marker in decoded[:16]
        for marker in (b"MZ", b"\x7fELF", b"PK\x03\x04", b"%PDF", b"\x89PNG")
    )


def run_external_scan(command: List[str]) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3600,
            check=False,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-20000:],
            "stderr": completed.stderr[-20000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "error": "timeout",
            "stdout": (exc.stdout or "")[-20000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-20000:] if isinstance(exc.stderr, str) else "",
        }
    except Exception as exc:
        return {"command": command, "error": repr(exc)}


def scan_file(args: argparse.Namespace) -> Dict[str, Any]:
    path = args.input.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Input path is not a regular file: {path}")

    size_bytes = path.stat().st_size
    hashes = compute_hashes(path)

    result: Dict[str, Any] = {
        "scanner": {
            "name": "static_scan_jsonl.py",
            "version": "1.0",
            "scan_time_utc": datetime.now(timezone.utc).isoformat(),
            "non_executing": True,
        },
        "file": {
            "path": str(path),
            "name": path.name,
            "size_bytes": size_bytes,
            "hashes": hashes,
            "expected_sha256": args.expected_sha256.lower() if args.expected_sha256 else None,
            "sha256_matches_expected": (
                hashes["sha256"].lower() == args.expected_sha256.lower()
                if args.expected_sha256
                else None
            ),
        },
        "structure": {
            "strict_utf8": True,
            "total_lines": 0,
            "blank_lines": 0,
            "valid_json_records": 0,
            "json_parse_errors": 0,
            "top_level_object_records": 0,
            "non_object_records": 0,
            "duplicate_exact_records": 0,
            "duplicate_ids": 0,
            "id_field": args.id_field,
            "unexpected_control_characters": 0,
        },
        "content": {
            "string_fields_scanned": 0,
            "characters_scanned": 0,
            "urls_found": 0,
            "url_schemes": {},
            "non_http_urls": 0,
            "suspicious_download_urls": 0,
            "base64_like_payloads": 0,
            "hex_like_payloads": 0,
            "suspicious_pattern_hits": 0,
            "contextual_pattern_hits": 0,
        },
        "findings": defaultdict(list),
        "external_scanners": {},
    }

    exact_hash_counts: Counter[str] = Counter()
    id_counts: Counter[str] = Counter()
    scheme_counts: Counter[str] = Counter()
    selected_id_field: Optional[str] = args.id_field

    with path.open("rb") as raw_handle:
        for line_number, raw_line in enumerate(raw_handle, start=1):
            result["structure"]["total_lines"] += 1

            if not raw_line.strip():
                result["structure"]["blank_lines"] += 1
                continue

            try:
                line = raw_line.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                result["structure"]["strict_utf8"] = False
                add_example(
                    result["findings"],
                    "utf8_errors",
                    {"line": line_number, "error": str(exc)},
                    args.max_findings,
                )
                continue

            # JSONL permits tab, CR, and LF. Other C0 controls are unexpected.
            bad_controls = [
                {"offset": idx, "codepoint": ord(char)}
                for idx, char in enumerate(line)
                if ord(char) < 32 and char not in "\t\r\n"
            ]
            if bad_controls:
                result["structure"]["unexpected_control_characters"] += len(bad_controls)
                add_example(
                    result["findings"],
                    "unexpected_control_characters",
                    {
                        "line": line_number,
                        "examples": bad_controls[:10],
                    },
                    args.max_findings,
                )

            try:
                record = json.loads(line)
                result["structure"]["valid_json_records"] += 1
            except json.JSONDecodeError as exc:
                result["structure"]["json_parse_errors"] += 1
                add_example(
                    result["findings"],
                    "json_parse_errors",
                    {
                        "line": line_number,
                        "column": exc.colno,
                        "message": exc.msg,
                        "snippet": line[:500],
                    },
                    args.max_findings,
                )
                continue

            exact_hash = canonical_record_hash(record)
            exact_hash_counts[exact_hash] += 1

            if isinstance(record, dict):
                result["structure"]["top_level_object_records"] += 1
                if selected_id_field is None:
                    selected_id_field = find_id_field(record, None)
                    result["structure"]["id_field"] = selected_id_field

                if selected_id_field and selected_id_field in record:
                    raw_id = record[selected_id_field]
                    if raw_id is not None:
                        id_counts[str(raw_id)] += 1
            else:
                result["structure"]["non_object_records"] += 1

            for field_path, text in flatten_strings(record):
                result["content"]["string_fields_scanned"] += 1
                result["content"]["characters_scanned"] += len(text)

                for match in URL_RE.finditer(text):
                    info = suspicious_url_info(match.group(1))
                    result["content"]["urls_found"] += 1
                    scheme_counts[info["scheme"]] += 1

                    if info["scheme"] not in {"http", "https"}:
                        result["content"]["non_http_urls"] += 1
                        add_example(
                            result["findings"],
                            "non_http_urls",
                            {
                                "line": line_number,
                                "field": field_path,
                                **info,
                            },
                            args.max_findings,
                        )

                    if info["suspicious_extension"]:
                        result["content"]["suspicious_download_urls"] += 1
                        add_example(
                            result["findings"],
                            "suspicious_download_urls",
                            {
                                "line": line_number,
                                "field": field_path,
                                **info,
                            },
                            args.max_findings,
                        )

                for match in BASE64_RE.finditer(text):
                    blob = match.group(0)
                    if plausible_base64(blob):
                        result["content"]["base64_like_payloads"] += 1
                        add_example(
                            result["findings"],
                            "base64_like_payloads",
                            {
                                "line": line_number,
                                "field": field_path,
                                "length": len(blob),
                                "snippet": blob[:160],
                            },
                            args.max_findings,
                        )

                for match in HEX_BLOB_RE.finditer(text):
                    blob = match.group(0)
                    result["content"]["hex_like_payloads"] += 1
                    add_example(
                        result["findings"],
                        "hex_like_payloads",
                        {
                            "line": line_number,
                            "field": field_path,
                            "length": len(blob),
                            "snippet": blob[:160],
                        },
                        args.max_findings,
                    )

                for name, pattern in SUSPICIOUS_PATTERNS:
                    for match in pattern.finditer(text):
                        result["content"]["suspicious_pattern_hits"] += 1
                        add_example(
                            result["findings"],
                            "suspicious_patterns",
                            {
                                "line": line_number,
                                "field": field_path,
                                "pattern": name,
                                "match": match.group(0)[:300],
                                "context": safe_snippet(text, match.start(), match.end()),
                            },
                            args.max_findings,
                        )

                for name, pattern in CONTEXTUAL_PATTERNS:
                    for match in pattern.finditer(text):
                        result["content"]["contextual_pattern_hits"] += 1
                        add_example(
                            result["findings"],
                            "contextual_patterns",
                            {
                                "line": line_number,
                                "field": field_path,
                                "pattern": name,
                                "match": match.group(0)[:300],
                                "context": safe_snippet(text, match.start(), match.end()),
                                "note": "Contextual indicator; manual review required because normal prose can trigger it.",
                            },
                            args.max_findings,
                        )

    result["structure"]["duplicate_exact_records"] = sum(
        count - 1 for count in exact_hash_counts.values() if count > 1
    )
    result["structure"]["duplicate_ids"] = sum(
        count - 1 for count in id_counts.values() if count > 1
    )
    result["content"]["url_schemes"] = dict(sorted(scheme_counts.items()))

    for digest, count in exact_hash_counts.items():
        if count > 1:
            add_example(
                result["findings"],
                "duplicate_exact_records",
                {"canonical_sha256": digest, "count": count},
                args.max_findings,
            )

    for record_id, count in id_counts.items():
        if count > 1:
            add_example(
                result["findings"],
                "duplicate_ids",
                {
                    "id_field": selected_id_field,
                    "id": record_id,
                    "count": count,
                },
                args.max_findings,
            )

    if args.clamav:
        clamscan = shutil.which("clamscan")
        if clamscan:
            result["external_scanners"]["clamav"] = run_external_scan(
                [clamscan, "--infected", "--no-summary", str(path)]
            )
        else:
            result["external_scanners"]["clamav"] = {
                "available": False,
                "message": "clamscan was requested but is not installed or not on PATH.",
            }

    if args.yara_rules:
        yara = shutil.which("yara")
        if yara:
            result["external_scanners"]["yara"] = run_external_scan(
                [yara, "-r", str(args.yara_rules.resolve()), str(path)]
            )
        else:
            result["external_scanners"]["yara"] = {
                "available": False,
                "message": "yara was requested but is not installed or not on PATH.",
            }

    # Convert defaultdict for stable JSON serialization.
    result["findings"] = dict(result["findings"])

    high_confidence_counts = {
        "json_parse_errors": result["structure"]["json_parse_errors"],
        "unexpected_control_characters": result["structure"]["unexpected_control_characters"],
        "non_http_urls": result["content"]["non_http_urls"],
        "suspicious_download_urls": result["content"]["suspicious_download_urls"],
        "base64_like_payloads": result["content"]["base64_like_payloads"],
        "hex_like_payloads": result["content"]["hex_like_payloads"],
        "suspicious_pattern_hits": result["content"]["suspicious_pattern_hits"],
    }

    result["assessment"] = {
        "high_confidence_finding_counts": high_confidence_counts,
        "requires_manual_review": any(high_confidence_counts.values())
        or result["content"]["contextual_pattern_hits"] > 0,
        "summary": (
            "One or more findings require review."
            if any(high_confidence_counts.values()) or result["content"]["contextual_pattern_hits"] > 0
            else "No suspicious indicators were detected by the implemented static checks."
        ),
        "limitations": [
            "The scanner does not execute content.",
            "Pattern-based checks can produce false positives and false negatives.",
            "A clean result is not an absolute guarantee that a file is harmless.",
            "Use a current antivirus or multi-engine scan as an additional control.",
        ],
    }

    return result


def write_markdown(result: Dict[str, Any], output_path: Path) -> None:
    file_info = result["file"]
    structure = result["structure"]
    content = result["content"]
    assessment = result["assessment"]
    external = result.get("external_scanners", {})

    lines = [
        "# Static JSONL Security and Integrity Scan",
        "",
        f"- **Scanned at:** {result['scanner']['scan_time_utc']}",
        f"- **File:** `{file_info['name']}`",
        f"- **Path:** `{file_info['path']}`",
        f"- **Size:** {file_info['size_bytes']:,} bytes",
        f"- **MD5:** `{file_info['hashes']['md5']}`",
        f"- **SHA-1:** `{file_info['hashes']['sha1']}`",
        f"- **SHA-256:** `{file_info['hashes']['sha256']}`",
    ]

    if file_info["expected_sha256"]:
        lines.append(
            f"- **Expected SHA-256 matched:** `{file_info['sha256_matches_expected']}`"
        )

    lines += [
        "",
        "## Structure",
        "",
        f"- Strict UTF-8: `{structure['strict_utf8']}`",
        f"- Total lines: {structure['total_lines']:,}",
        f"- Blank lines: {structure['blank_lines']:,}",
        f"- Valid JSON records: {structure['valid_json_records']:,}",
        f"- JSON parse errors: {structure['json_parse_errors']:,}",
        f"- Top-level object records: {structure['top_level_object_records']:,}",
        f"- Non-object records: {structure['non_object_records']:,}",
        f"- ID field: `{structure['id_field']}`",
        f"- Duplicate exact records: {structure['duplicate_exact_records']:,}",
        f"- Duplicate IDs: {structure['duplicate_ids']:,}",
        f"- Unexpected control characters: {structure['unexpected_control_characters']:,}",
        "",
        "## Static content checks",
        "",
        f"- String fields scanned: {content['string_fields_scanned']:,}",
        f"- Characters scanned: {content['characters_scanned']:,}",
        f"- URLs found: {content['urls_found']:,}",
        f"- URL schemes: `{json.dumps(content['url_schemes'], sort_keys=True)}`",
        f"- Non-HTTP(S) URLs: {content['non_http_urls']:,}",
        f"- URLs with suspicious downloadable extensions: {content['suspicious_download_urls']:,}",
        f"- Base64-like payloads: {content['base64_like_payloads']:,}",
        f"- Hex-like payloads: {content['hex_like_payloads']:,}",
        f"- Suspicious pattern hits: {content['suspicious_pattern_hits']:,}",
        f"- Contextual pattern hits requiring interpretation: {content['contextual_pattern_hits']:,}",
        "",
        "## Assessment",
        "",
        assessment["summary"],
        "",
        "Contextual hits are not automatically malicious. Terms such as `bash`, "
        "`payload`, or `exploit` may occur in ordinary prose and must be reviewed in context.",
    ]

    if external:
        lines += ["", "## Optional external scanners", ""]
        for scanner_name, scanner_result in external.items():
            lines.append(f"### {scanner_name}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(scanner_result, indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")

    findings = result.get("findings", {})
    if findings:
        lines += ["", "## Finding examples", ""]
        for category, examples in sorted(findings.items()):
            lines.append(f"### {category}")
            lines.append("")
            lines.append(f"Stored examples: {len(examples)}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(examples[:20], indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")

    lines += [
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in assessment["limitations"])
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        result = scan_file(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.input.stem
    json_path = args.output_dir / f"{stem}_static_scan_report.json"
    md_path = args.output_dir / f"{stem}_static_scan_summary.md"

    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_markdown(result, md_path)

    print(f"JSON report: {json_path}")
    print(f"Markdown summary: {md_path}")
    print(f"SHA-256: {result['file']['hashes']['sha256']}")
    print(f"Assessment: {result['assessment']['summary']}")

    if (
        args.expected_sha256
        and not result["file"]["sha256_matches_expected"]
    ):
        print("ERROR: SHA-256 does not match the expected value.", file=sys.stderr)
        return 3

    return 1 if result["assessment"]["requires_manual_review"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
