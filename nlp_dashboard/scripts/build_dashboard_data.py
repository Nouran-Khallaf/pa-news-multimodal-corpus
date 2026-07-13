#!/usr/bin/env python3
"""Build browser-ready dashboard data from the PA NLP analysis outputs.

Lexical outputs are rebuilt from spaCy token annotations so the displayed
frequencies exclude stop words, punctuation, numbers and web boilerplate.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

CONTENT_POS = {"NOUN", "PROPN", "VERB", "ADJ", "ADV"}
CUSTOM_STOPWORDS = {
    "amp", "nbsp", "http", "https", "www", "html", "javascript",
    "archive", "archived", "wayback",
}
TERM_RE = re.compile(r"^[a-z][a-z'-]*$", re.IGNORECASE)


def clean(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def frame_row(row: pd.Series, queue_type: str, category_col: str) -> dict[str, Any]:
    category = str(row.get(category_col, ""))
    sentence_id = str(row.get("sentence_id", ""))
    matched = str(row.get("matched_terms", "") or "")
    return {
        "id": f"{queue_type}:{sentence_id}:{category}",
        "type": queue_type,
        "documentId": str(row.get("document_id", "")),
        "sentenceId": sentence_id,
        "sentenceIndex": int(row.get("sentence_index", 0) or 0),
        "sentence": str(row.get("sentence", "")),
        "category": category,
        "matchedTerms": [x for x in matched.split("|") if x],
        "quotation": as_bool(row.get("quotation_flag", False)),
        "reportedSpeech": as_bool(row.get("reported_speech_flag", False)),
        "negation": as_bool(row.get("negation_flag", False)),
        "passive": as_bool(row.get("passive_voice_flag", False)),
        "question": as_bool(row.get("question_flag", False)),
        "reportingVerbs": str(row.get("reporting_verb_hits", "") or ""),
        "presuppositionTriggers": str(row.get("presupposition_trigger_hits", "") or ""),
        "sourceStatus": str(row.get("validation_status", "unreviewed_candidate")),
    }


def normalise_term(row: Any) -> str | None:
    """Return a content lemma or None when the token should be excluded."""
    if not as_bool(getattr(row, "is_alpha", False)):
        return None
    if as_bool(getattr(row, "is_stop", False)):
        return None
    pos = str(getattr(row, "pos", "") or "").upper()
    if pos not in CONTENT_POS:
        return None
    lemma = str(getattr(row, "lemma", "") or "").strip().lower()
    if not lemma or lemma == "-pron-":
        lemma = str(getattr(row, "lower", "") or "").strip().lower()
    lemma = lemma.replace("’", "'")
    if len(lemma) < 2 or lemma in CUSTOM_STOPWORDS or not TERM_RE.fullmatch(lemma):
        return None
    return lemma


def build_clean_lexical(tokens_path: Path, document_count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Stream token annotations and build stop-word-filtered lexical outputs."""
    term_freq: Counter[str] = Counter()
    term_doc_freq: Counter[str] = Counter()
    bigram_freq: Counter[str] = Counter()
    bigram_doc_freq: Counter[str] = Counter()
    trigram_freq: Counter[str] = Counter()
    trigram_doc_freq: Counter[str] = Counter()

    current_doc: str | None = None
    current_sentence: tuple[str, int] | None = None
    run: list[str] = []
    doc_terms: set[str] = set()
    doc_bigrams: set[str] = set()
    doc_trigrams: set[str] = set()
    token_rows = 0
    alphabetic_tokens = 0
    content_tokens = 0

    def flush_run() -> None:
        nonlocal run
        if len(run) >= 2:
            for i in range(len(run) - 1):
                gram = f"{run[i]} {run[i + 1]}"
                bigram_freq[gram] += 1
                doc_bigrams.add(gram)
        if len(run) >= 3:
            for i in range(len(run) - 2):
                gram = f"{run[i]} {run[i + 1]} {run[i + 2]}"
                trigram_freq[gram] += 1
                doc_trigrams.add(gram)
        run = []

    def flush_document() -> None:
        term_doc_freq.update(doc_terms)
        bigram_doc_freq.update(doc_bigrams)
        trigram_doc_freq.update(doc_trigrams)
        doc_terms.clear()
        doc_bigrams.clear()
        doc_trigrams.clear()

    columns = ["document_id", "sentence_index", "lower", "lemma", "pos", "is_stop", "is_alpha"]
    for chunk in pd.read_csv(tokens_path, usecols=columns, chunksize=100_000, low_memory=False):
        for row in chunk.itertuples(index=False):
            token_rows += 1
            doc_id = str(row.document_id)
            sentence_key = (doc_id, int(row.sentence_index))

            if current_doc is None:
                current_doc = doc_id
                current_sentence = sentence_key
            elif doc_id != current_doc:
                flush_run()
                flush_document()
                current_doc = doc_id
                current_sentence = sentence_key
            elif sentence_key != current_sentence:
                flush_run()
                current_sentence = sentence_key

            if as_bool(row.is_alpha):
                alphabetic_tokens += 1

            term = normalise_term(row)
            if term is None:
                flush_run()
                continue

            content_tokens += 1
            term_freq[term] += 1
            doc_terms.add(term)
            run.append(term)

    flush_run()
    if current_doc is not None:
        flush_document()

    denominator = max(1, alphabetic_tokens)

    terms = []
    for term, frequency in sorted(term_freq.items(), key=lambda item: (-item[1], item[0]))[:10_000]:
        df = term_doc_freq[term]
        terms.append({
            "term": term,
            "frequency": int(frequency),
            "perMillion": float(frequency / denominator * 1_000_000),
            "documentFrequency": int(df),
            "documentProportion": float(df / max(1, document_count)),
        })

    def ngram_rows(freq: Counter[str], doc_freq: Counter[str], limit: int = 2_000) -> list[dict[str, Any]]:
        return [
            {
                "ngram": gram,
                "frequency": int(count),
                "perMillion": float(count / denominator * 1_000_000),
                "documentFrequency": int(doc_freq[gram]),
            }
            for gram, count in sorted(freq.items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]

    metadata = {
        "unit": "lowercase spaCy lemma",
        "frequencyDenominator": "all alphabetic spaCy tokens before stop-word removal",
        "keptPartsOfSpeech": sorted(CONTENT_POS),
        "excluded": [
            "spaCy stop words",
            "punctuation and non-alphabetic tokens",
            "numbers and symbols",
            "tokens outside the content-word POS set",
            "single-character tokens",
            "audited web-boilerplate terms",
        ],
        "customStopwords": sorted(CUSTOM_STOPWORDS),
        "inputTokenRows": int(token_rows),
        "alphabeticTokenBase": int(alphabetic_tokens),
        "contentTokens": int(content_tokens),
        "uniqueContentTerms": int(len(term_freq)),
        "spacyStopFlagUsed": True,
    }
    return terms, ngram_rows(bigram_freq, bigram_doc_freq), ngram_rows(trigram_freq, trigram_doc_freq), metadata


def build_lemma_concordance(tokens_path: Path, terms: set[str], max_per_term: int = 80) -> dict[str, list[list[Any]]]:
    """Collect a bounded lemma-to-sentence occurrence index for KWIC display."""
    index: dict[str, list[list[Any]]] = {term: [] for term in terms}
    seen_sentences: dict[str, set[tuple[str, int]]] = {term: set() for term in terms}
    columns = ["document_id", "sentence_index", "text", "lower", "lemma", "pos", "is_stop", "is_alpha"]
    remaining = len(terms)
    for chunk in pd.read_csv(tokens_path, usecols=columns, chunksize=100_000, low_memory=False):
        for row in chunk.itertuples(index=False):
            term = normalise_term(row)
            if term not in index:
                continue
            bucket = index[term]
            if len(bucket) >= max_per_term:
                continue
            sentence_key = (str(row.document_id), int(row.sentence_index))
            if sentence_key in seen_sentences[term]:
                continue
            seen_sentences[term].add(sentence_key)
            bucket.append([sentence_key[0], sentence_key[1], str(row.text)])
            if len(bucket) == max_per_term:
                remaining -= 1
        if remaining <= 0:
            break
    return {term: rows for term, rows in index.items() if rows}


def read_sentences(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            rows.append({
                "id": str(row.get("sentence_id", "")),
                "documentId": str(row.get("document_id", "")),
                "index": int(row.get("sentence_index", 0) or 0),
                "text": str(row.get("text", "")),
            })
    return rows


def read_bnc_reference(path: Path | None, corpus_tokens: int) -> dict[str, Any] | None:
    """Read an optional normalized CSV: term,count and/or per_million."""
    if path is None:
        return None
    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    term_col = cols.get("term") or cols.get("word") or cols.get("lemma")
    if not term_col:
        raise ValueError("BNC reference CSV must include a term, word or lemma column")
    count_col = cols.get("count") or cols.get("frequency") or cols.get("raw_frequency")
    pm_col = cols.get("per_million") or cols.get("frequency_per_million")
    if not count_col and not pm_col:
        raise ValueError("BNC reference CSV must include count/frequency or per_million")
    aggregate: dict[str, dict[str, float]] = {}
    for _, row in df.iterrows():
        term = str(row[term_col]).strip().lower()
        if not term:
            continue
        count = float(row[count_col]) if count_col and not pd.isna(row[count_col]) else None
        pm = float(row[pm_col]) if pm_col and not pd.isna(row[pm_col]) else None
        if count is None and pm is not None:
            count = pm * corpus_tokens / 1_000_000
        if pm is None and count is not None:
            pm = count / corpus_tokens * 1_000_000
        slot = aggregate.setdefault(term, {"count": 0.0, "perMillion": 0.0})
        slot["count"] += float(count or 0)
    rows = []
    for term, values in aggregate.items():
        count = values["count"]
        rows.append({"term": term, "count": count, "perMillion": count / corpus_tokens * 1_000_000})
    return {
        "name": path.name,
        "corpusTokens": corpus_tokens,
        "unit": "lemma",
        "entries": rows,
        "loadedAtBuild": True,
        "basis": "count",
        "format": "normalized CSV",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("analysis_dir", type=Path, help="Path containing interim/ and results/")
    parser.add_argument("output", type=Path, help="Output dashboard_data.js")
    parser.add_argument("--security-summary", type=Path)
    parser.add_argument("--reference-date", default="2026-07-13")
    parser.add_argument("--bnc-reference", type=Path, help="Optional normalized BNC CSV")
    parser.add_argument("--bnc-tokens", type=int, default=100_000_000)
    args = parser.parse_args()

    base = args.analysis_dir.resolve()
    results = base / "results"
    interim = base / "interim"
    reference_date = pd.Timestamp(args.reference_date)

    docs = pd.read_csv(interim / "documents.csv")
    docs["published_dt"] = pd.to_datetime(docs["published_at"], errors="coerce")

    documents: list[dict[str, Any]] = []
    for _, row in docs.iterrows():
        dt = row["published_dt"]
        if pd.isna(dt):
            date_flag = "missing"
        elif dt > reference_date:
            date_flag = "future"
        else:
            date_flag = "ok"
        tags = [x.strip() for x in str(row.get("tags", "") or "").split("|") if x.strip() and x != "nan"]
        documents.append({
            "id": str(row["document_id"]),
            "url": str(row.get("final_url", "") or ""),
            "title": str(row.get("title", "") or "Untitled"),
            "publishedAt": None if pd.isna(dt) else dt.isoformat(),
            "year": None if pd.isna(row.get("year")) else int(float(row["year"])),
            "month": None if pd.isna(row.get("month")) else str(row["month"]),
            "author": "Unknown" if pd.isna(row.get("author")) or not str(row.get("author")).strip() else str(row["author"]),
            "tags": tags,
            "imageCount": int(row.get("image_count", 0) or 0),
            "paragraphCount": int(row.get("paragraph_count", 0) or 0),
            "wordCount": int(row.get("word_count", 0) or 0),
            "sentenceCount": int(row.get("sentence_count", 0) or 0),
            "meanSentenceWords": clean(row.get("mean_sentence_words")),
            "meanWordCharacters": clean(row.get("mean_word_characters")),
            "typeTokenRatio": clean(row.get("type_token_ratio")),
            "mattr50": clean(row.get("mattr_50")),
            "flesch": clean(row.get("flesch_reading_ease_estimate")),
            "dateFlag": date_flag,
        })

    clean_terms, clean_bigrams, clean_trigrams, lexical_cleaning = build_clean_lexical(
        interim / "tokens.csv.gz", len(documents)
    )
    sentences = read_sentences(interim / "sentences.jsonl")
    lemma_concordance = build_lemma_concordance(
        interim / "tokens.csv.gz", {row["term"] for row in clean_terms[:3000]}, max_per_term=80
    )

    coll_df = pd.read_csv(results / "collocations.csv")
    coll_df = coll_df.sort_values(["logdice", "cooccurrence_frequency"], ascending=False).head(1500)
    collocations = []
    for _, r in coll_df.iterrows():
        collocations.append({
            "node": str(r.node),
            "collocate": str(r.collocate),
            "cooccurrence": int(r.cooccurrence_frequency),
            "documentFrequency": int(r.document_frequency),
            "pmi": float(r.pmi),
            "logDice": float(r.logdice),
            "examples": str(r.examples),
        })

    frame_df = pd.read_csv(results / "political_discourse" / "frame_candidates.csv")
    legit_df = pd.read_csv(results / "political_discourse" / "legitimation_candidates.csv")
    coded_df = pd.read_csv(results / "political_discourse" / "coded_language_candidate_review.csv")
    actor_df = pd.read_csv(results / "political_discourse" / "actor_mentions.csv")
    rhet_df = pd.read_csv(results / "political_discourse" / "rhetorical_markers_by_document.csv")

    frame_queue = [frame_row(r, "frame", "frame") for _, r in frame_df.iterrows()]
    legit_queue = [frame_row(r, "legitimation", "strategy") for _, r in legit_df.iterrows()]

    coded_queue = []
    for index, row in coded_df.iterrows():
        form = str(row.get("surface_form", ""))
        coded_queue.append({
            "id": f"coded:{index}:{form}",
            "type": "coded_language",
            "documentId": None if pd.isna(row.get("document_id")) or not str(row.get("document_id", "")).strip() else str(row["document_id"]),
            "surfaceForm": form,
            "normalisedForm": str(row.get("normalised_form", "") or ""),
            "context": str(row.get("minimal_context", "") or ""),
            "category": str(row.get("candidate_basis", "") or "candidate"),
            "corpusFrequency": int(row.get("corpus_frequency", 0) or 0),
            "documentFrequency": int(row.get("document_frequency", 0) or 0),
            "sourceStatus": str(row.get("review_status", "unreviewed_candidate") or "unreviewed_candidate"),
            "proposedMeaning": str(row.get("proposed_decoded_meaning", "") or ""),
            "discursiveFunction": str(row.get("discursive_function", "") or ""),
            "targetReferent": str(row.get("target_or_referent", "") or ""),
            "ambiguity": str(row.get("ambiguity", "") or ""),
            "alternativeInterpretation": str(row.get("alternative_interpretation", "") or ""),
            "confidence": str(row.get("confidence", "") or ""),
            "harmNote": str(row.get("harm_or_amplification_note", "") or ""),
        })

    actor_counts = (
        actor_df.groupby(["entity_normalised", "entity_label"], dropna=False)
        .size().reset_index(name="frequency")
        .sort_values("frequency", ascending=False)
        .head(250)
    )
    top_actors = [
        {"entity": str(r.entity_normalised), "label": str(r.entity_label), "frequency": int(r.frequency)}
        for _, r in actor_counts.iterrows()
    ]

    rhetorical_totals = []
    for name, total in rhet_df.drop(columns=["document_id"]).sum(numeric_only=True).sort_values(ascending=False).items():
        rhetorical_totals.append({"marker": name, "count": int(total)})

    publication_year = pd.read_csv(results / "publication_by_year.csv").fillna(0).to_dict("records")
    publication_month = pd.read_csv(results / "publication_by_month.csv").fillna(0).to_dict("records")
    for row in publication_year:
        row["year"] = str(int(row["year"]))
        row["articles"] = int(row["articles"])
        row["words"] = int(row["words"])
        row["images"] = int(row["images"])
    for row in publication_month:
        row["month"] = str(row["month"])
        row["articles"] = int(row["articles"])
        row["words"] = int(row["words"])
        row["images"] = int(row["images"])

    summary = read_json(results / "analysis_summary.json", {})
    qc = read_json(results / "quality_control" / "deduplication_summary.json", {})

    security = {
        "file": "articles.jsonl",
        "sizeBytes": 33063566,
        "md5": "c0a5778825035e91c09fcd28147ab456",
        "sha1": "59987b5b30ba058e606a7a07ba90c5c7bbce6f42",
        "sha256": "083e7fb4ca92631d9ae7ecfc7819586a0410eafb489c52cdab31595af4c08277",
        "validRecords": 1801,
        "parseErrors": 0,
        "duplicateRecords": 0,
        "duplicateIds": 0,
        "highConfidenceHits": 0,
        "contextualHits": 61,
        "assessment": "No high-confidence malicious payload or executable-script indicators were detected. Contextual hits require human interpretation and were ordinary prose in the reviewed examples.",
    }

    frame_counts = [{"category": str(k), "count": int(v)} for k, v in frame_df["frame"].value_counts().items()]
    legit_counts = [{"category": str(k), "count": int(v)} for k, v in legit_df["strategy"].value_counts().items()]
    entity_label_counts = [{"category": str(k), "count": int(v)} for k, v in actor_df["entity_label"].value_counts().items()]

    tag_counts = Counter(tag for d in documents for tag in d["tags"])
    author_counts = Counter(d["author"] for d in documents)

    data = {
        "meta": {
            "title": "Patriotic Alternative News Corpus",
            "subtitle": "Corpus exploration, NLP candidate analysis and human validation",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "referenceDate": args.reference_date,
            "methodologicalWarning": "Frame, legitimation, actor and coded-language outputs are retrieval candidates, not validated substantive findings.",
        },
        "summary": {
            "documents": len(documents),
            "words": int(docs["word_count"].fillna(0).sum()),
            "sentences": int(docs["sentence_count"].fillna(0).sum()),
            "images": int(docs["image_count"].fillna(0).sum()),
            "tokensAfterFiltering": int(lexical_cleaning["contentTokens"]),
            "uniqueTerms": int(lexical_cleaning["uniqueContentTerms"]),
            "frameCandidates": len(frame_queue),
            "legitimationCandidates": len(legit_queue),
            "actorMentions": int(summary.get("actor_mentions", len(actor_df))),
            "codedLanguageCandidates": len(coded_queue),
            "missingDates": int(sum(d["dateFlag"] == "missing" for d in documents)),
            "futureDates": int(sum(d["dateFlag"] == "future" for d in documents)),
        },
        "quality": {"deduplication": qc, "security": security},
        "lexicalCleaning": lexical_cleaning,
        "documents": documents,
        "sentences": sentences,
        "lemmaConcordance": lemma_concordance,
        "publicationByYear": publication_year,
        "publicationByMonth": publication_month,
        "topTerms": clean_terms,
        "bigrams": clean_bigrams,
        "trigrams": clean_trigrams,
        "collocations": collocations,
        "frameCounts": frame_counts,
        "legitimationCounts": legit_counts,
        "entityLabelCounts": entity_label_counts,
        "topActors": top_actors,
        "rhetoricalTotals": rhetorical_totals,
        "topTags": [{"label": k, "count": v} for k, v in tag_counts.most_common(100)],
        "topAuthors": [{"label": k, "count": v} for k, v in author_counts.most_common(100)],
        "bncReference": read_bnc_reference(args.bnc_reference, args.bnc_tokens),
        "reviewQueues": {
            "frame": frame_queue,
            "legitimation": legit_queue,
            "coded_language": coded_queue,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    args.output.write_text("window.PA_DATA=" + encoded + ";\n", encoding="utf-8")
    print(f"Wrote {args.output} ({args.output.stat().st_size:,} bytes)")
    print(json.dumps({**data["summary"], "lexicalCleaning": lexical_cleaning}, indent=2))


if __name__ == "__main__":
    main()
