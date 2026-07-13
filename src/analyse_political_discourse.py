#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from corpus_utils import load_articles, load_yaml


def compile_lexicons(section: dict[str, list[str]]) -> dict[str, list[re.Pattern]]:
    return {
        label: [re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.I) for term in terms]
        for label, terms in section.items()
    }


def lexical_hits(patterns: list[re.Pattern], text: str) -> list[str]:
    return sorted({match.group(0).lower() for pattern in patterns for match in pattern.finditer(text)})


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Candidate-level political discourse analysis for human validation."
    )
    ap.add_argument("--config", type=Path, default=Path("config/analysis.yml"))
    ap.add_argument(
        "--zero-shot", action="store_true", help="Run optional NLI frame scoring on sentences."
    )
    ap.add_argument(
        "--device", type=int, default=-1, help="Transformers pipeline device; 0 for first GPU."
    )
    args = ap.parse_args()

    root = Path.cwd()
    cfg = load_yaml(args.config)
    import spacy

    nlp = spacy.load(cfg["text"]["spacy_model"])
    articles = load_articles(cfg, root)
    political = cfg["political_analysis"]
    frames = compile_lexicons(political["frames"])
    legitimation = compile_lexicons(political["legitimation"])
    ingroup = {x.lower() for x in political["ingroup_markers"]}
    outgroup = {x.lower() for x in political["outgroup_markers"]}
    modals = {x.lower() for x in political["modals"]}
    certainty = {x.lower() for x in political["certainty_markers"]}
    hedges = {x.lower() for x in political["hedges"]}
    reporting_verbs = {x.lower() for x in political["reporting_verbs"]}
    presupposition = {x.lower() for x in political["presupposition_triggers"]}

    frame_rows: list[dict] = []
    legitimation_rows: list[dict] = []
    entity_rows: list[dict] = []
    predication_rows: list[dict] = []
    document_rows: list[dict] = []
    cooccurrence = Counter()
    zero_shot_sentences: list[dict] = []

    for record in articles:
        doc = nlp(record.get("body", ""))
        counts = Counter()
        for sentence_index, sentence in enumerate(doc.sents):
            text = sentence.text.strip()
            if not text:
                continue
            sentence_id = f"{record['document_id']}-s{sentence_index:04d}"
            lemmas = [token.lemma_.lower() for token in sentence if token.is_alpha]
            reporting_hits = sorted(set(lemmas) & reporting_verbs)
            presupposition_hits = sorted(set(lemmas) & presupposition)
            quotation_flag = any(mark in text for mark in ('"', "“", "”", "‘", "’"))
            reported_speech_flag = bool(reporting_hits or quotation_flag)
            negation_flag = any(token.dep_ == "neg" for token in sentence)
            passive_voice_flag = any(token.dep_ in {"nsubjpass", "auxpass"} for token in sentence)
            question_flag = text.endswith("?")
            sentence_meta = {
                "document_id": record["document_id"],
                "sentence_id": sentence_id,
                "sentence_index": sentence_index,
                "sentence": text,
                "quotation_flag": quotation_flag,
                "reported_speech_flag": reported_speech_flag,
                "reporting_verb_hits": "|".join(reporting_hits),
                "negation_flag": negation_flag,
                "passive_voice_flag": passive_voice_flag,
                "question_flag": question_flag,
                "presupposition_trigger_hits": "|".join(presupposition_hits),
            }

            actors: list[str] = []
            for entity in sentence.ents:
                if entity.label_ not in political["actor_entity_labels"]:
                    continue
                name = entity.text.strip()
                actors.append(name)
                entity_rows.append(
                    {
                        **sentence_meta,
                        "entity": name,
                        "entity_normalised": name.lower(),
                        "entity_label": entity.label_,
                    }
                )
                head = entity.root
                modifiers = sorted(
                    {
                        token.lemma_.lower()
                        for token in head.children
                        if token.dep_ in {"amod", "compound", "appos"} and token.is_alpha
                    }
                )
                predicates = []
                if head.dep_ in {"nsubj", "nsubjpass", "obj", "dobj", "pobj"}:
                    predicates.append(head.head.lemma_.lower())
                if modifiers or predicates:
                    predication_rows.append(
                        {
                            **sentence_meta,
                            "entity": name,
                            "entity_label": entity.label_,
                            "syntactic_role": head.dep_,
                            "modifiers": "|".join(modifiers),
                            "predicates": "|".join(predicates),
                            "validation_status": "unreviewed_candidate",
                        }
                    )
            unique_actors = sorted(set(actors))
            for actor_index, actor_a in enumerate(unique_actors):
                for actor_b in unique_actors[actor_index + 1 :]:
                    cooccurrence[(actor_a, actor_b)] += 1

            for frame, patterns in frames.items():
                hits = lexical_hits(patterns, text)
                if hits:
                    frame_rows.append(
                        {
                            **sentence_meta,
                            "frame": frame,
                            "matched_terms": "|".join(hits),
                            "validation_status": "unreviewed_candidate",
                        }
                    )
                    counts[f"frame_{frame}"] += 1

            for strategy, patterns in legitimation.items():
                hits = lexical_hits(patterns, text)
                if hits:
                    legitimation_rows.append(
                        {
                            **sentence_meta,
                            "strategy": strategy,
                            "matched_terms": "|".join(hits),
                            "validation_status": "unreviewed_candidate",
                        }
                    )
                    counts[f"legitimation_{strategy}"] += 1

            counts["ingroup_markers"] += sum(item in ingroup for item in lemmas)
            counts["outgroup_markers"] += sum(item in outgroup for item in lemmas)
            counts["modal_markers"] += sum(item in modals for item in lemmas)
            counts["certainty_markers"] += sum(item in certainty for item in lemmas)
            counts["hedge_markers"] += sum(item in hedges for item in lemmas)
            counts["reported_speech_sentences"] += int(reported_speech_flag)
            counts["negated_sentences"] += int(negation_flag)
            counts["passive_sentences"] += int(passive_voice_flag)
            counts["question_sentences"] += int(question_flag)
            counts["presupposition_trigger_tokens"] += len(presupposition_hits)
            zero_shot_sentences.append(sentence_meta)
        document_rows.append({"document_id": record["document_id"], **counts})

    out = root / cfg["paths"]["analysis_results"] / "political_discourse"
    out.mkdir(parents=True, exist_ok=True)
    sentence_columns = [
        "document_id",
        "sentence_id",
        "sentence_index",
        "sentence",
        "quotation_flag",
        "reported_speech_flag",
        "reporting_verb_hits",
        "negation_flag",
        "passive_voice_flag",
        "question_flag",
        "presupposition_trigger_hits",
    ]
    pd.DataFrame(
        frame_rows,
        columns=sentence_columns + ["frame", "matched_terms", "validation_status"],
    ).to_csv(out / "frame_candidates.csv", index=False)
    pd.DataFrame(
        legitimation_rows,
        columns=sentence_columns + ["strategy", "matched_terms", "validation_status"],
    ).to_csv(out / "legitimation_candidates.csv", index=False)
    pd.DataFrame(
        entity_rows,
        columns=sentence_columns + ["entity", "entity_normalised", "entity_label"],
    ).to_csv(out / "actor_mentions.csv", index=False)
    pd.DataFrame(
        predication_rows,
        columns=sentence_columns
        + [
            "entity",
            "entity_label",
            "syntactic_role",
            "modifiers",
            "predicates",
            "validation_status",
        ],
    ).to_csv(out / "actor_predications.csv", index=False)
    edge_columns = ["actor_1", "actor_2", "sentence_cooccurrence", "relation_type"]
    edge_rows = [
        {
            "actor_1": actor_a,
            "actor_2": actor_b,
            "sentence_cooccurrence": count,
            "relation_type": "textual_sentence_cooccurrence_only",
        }
        for (actor_a, actor_b), count in cooccurrence.most_common()
    ]
    pd.DataFrame(edge_rows, columns=edge_columns).to_csv(
        out / "actor_cooccurrence_edges.csv", index=False
    )
    pd.DataFrame(document_rows).fillna(0).to_csv(
        out / "rhetorical_markers_by_document.csv", index=False
    )

    if args.zero_shot:
        from transformers import pipeline

        classifier = pipeline(
            "zero-shot-classification",
            model=cfg["models"]["zero_shot_text"],
            device=args.device,
        )
        labels = list(political["zero_shot_frames"])
        batch_size = political["zero_shot_batch_size"]
        score_rows = []
        for start in range(0, len(zero_shot_sentences), batch_size):
            batch = zero_shot_sentences[start : start + batch_size]
            outputs = classifier(
                [item["sentence"] for item in batch],
                candidate_labels=labels,
                multi_label=True,
                hypothesis_template="This sentence uses a {} frame.",
            )
            if isinstance(outputs, dict):
                outputs = [outputs]
            for metadata, result in zip(batch, outputs):
                for label, score in zip(result["labels"], result["scores"]):
                    score_rows.append(
                        {
                            **metadata,
                            "frame": label,
                            "score": float(score),
                            "model": cfg["models"]["zero_shot_text"],
                            "validation_status": "model_assisted_unreviewed",
                        }
                    )
        pd.DataFrame(
            score_rows,
            columns=sentence_columns
            + ["frame", "score", "model", "validation_status"],
        ).to_csv(out / "zero_shot_frame_scores.csv", index=False)

    metadata = {
        "documents": len(articles),
        "frame_candidates": len(frame_rows),
        "legitimation_candidates": len(legitimation_rows),
        "actor_mentions": len(entity_rows),
        "reported_speech_handling": (
            "Candidate rows retain quotation and reporting-verb flags to reduce incorrect "
            "attribution of quoted language to the publisher."
        ),
        "interpretation": (
            "All outputs are candidate retrieval, syntactic descriptions or textual co-occurrence. "
            "Human coding is required before substantive claims."
        ),
    }
    (out / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
