#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from PIL import Image

from corpus_utils import load_articles, load_images, load_yaml, tokenise


def jaccard(a: str, b: str) -> float:
    left = set(tokenise(a or ""))
    right = set(tokenise(b or ""))
    return len(left & right) / len(left | right) if left | right else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Image–article alignment using SigLIP plus lexical/OCR/caption overlap."
    )
    ap.add_argument("--config", type=Path, default=Path("config/analysis.yml"))
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    root = Path.cwd()
    cfg = load_yaml(args.config)
    articles = {row["document_id"]: row for row in load_articles(cfg, root)}
    images = load_images(cfg, root)
    if args.limit:
        images = images[: args.limit]

    image_analysis_path = root / cfg["paths"]["analysis_results"] / "images" / "image_analysis.csv"
    if image_analysis_path.exists() and image_analysis_path.stat().st_size:
        try:
            image_analysis = pd.read_csv(image_analysis_path).fillna("")
        except pd.errors.EmptyDataError:
            image_analysis = pd.DataFrame()
    else:
        image_analysis = pd.DataFrame()
    extra = (
        {row.image_id: row.to_dict() for _, row in image_analysis.iterrows()}
        if not image_analysis.empty and "image_id" in image_analysis
        else {}
    )

    import torch
    from transformers import AutoModel, AutoProcessor

    model_name = cfg["models"]["image_text"]
    processor = AutoProcessor.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name).to(args.device).eval()

    rows: list[dict] = []
    for index, image_record in enumerate(images, 1):
        article = articles.get(image_record["document_id"])
        if not article:
            continue
        image_path = root / cfg["paths"]["collection_root"] / image_record["object_path"]
        try:
            texts = {
                "title": article.get("title", ""),
                "lead": " ".join((article.get("paragraphs") or [])[:2]),
                "explicit_caption": image_record.get("figcaption")
                or image_record.get("alt_text")
                or "",
            }
            with Image.open(image_path) as image:
                pil = image.convert("RGB")
            labels = [texts["title"], texts["lead"][:1200], texts["explicit_caption"] or ""]
            inputs = processor(
                text=labels, images=pil, padding="max_length", return_tensors="pt"
            ).to(args.device)
            with torch.inference_mode():
                image_embedding = model.get_image_features(pixel_values=inputs["pixel_values"])
                text_embedding = model.get_text_features(
                    input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"]
                )
            image_embedding = torch.nn.functional.normalize(image_embedding, dim=-1)
            text_embedding = torch.nn.functional.normalize(text_embedding, dim=-1)
            scores = (image_embedding @ text_embedding.T).squeeze(0).cpu().tolist()
            score_title, score_lead, score_caption = map(float, scores)
            extra_row = extra.get(image_record["image_id"], {})
            generated = extra_row.get("generated_caption", "")
            ocr = extra_row.get("ocr_text", "")
            relation = "review_required"
            if ocr and jaccard(ocr, article.get("body", "")) >= cfg["multimodal"][
                "ocr_redundancy_threshold"
            ]:
                relation = "text_bearing_redundant_or_evidential"
            elif (
                score_caption >= cfg["multimodal"]["high_similarity_threshold"]
                and texts["explicit_caption"]
            ):
                relation = "caption_aligned"
            elif max(score_title, score_lead) >= cfg["multimodal"][
                "high_similarity_threshold"
            ]:
                relation = "article_aligned_illustrative_or_complementary"
            elif max(score_title, score_lead) < cfg["multimodal"]["low_similarity_threshold"]:
                relation = "weak_alignment_review"
            rows.append(
                {
                    "image_id": image_record["image_id"],
                    "document_id": image_record["document_id"],
                    "title": article.get("title"),
                    "published_at": article.get("published_at"),
                    "explicit_caption": texts["explicit_caption"],
                    "generated_caption": generated,
                    "ocr_text": ocr,
                    "siglip_title_similarity": score_title,
                    "siglip_lead_similarity": score_lead,
                    "siglip_caption_similarity": score_caption,
                    "ocr_article_jaccard": jaccard(ocr, article.get("body", "")),
                    "generated_caption_title_jaccard": jaccard(
                        generated, article.get("title", "")
                    ),
                    "provisional_relation": relation,
                    "threshold_status": "uncalibrated_review_sampling_thresholds",
                    "validation_status": "model_assisted_unreviewed",
                    "model": model_name,
                    "analysis_error": None,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "image_id": image_record.get("image_id"),
                    "document_id": image_record.get("document_id"),
                    "title": article.get("title"),
                    "published_at": article.get("published_at"),
                    "validation_status": "analysis_error",
                    "model": model_name,
                    "analysis_error": f"{type(exc).__name__}: {exc}",
                }
            )
        if index % 25 == 0:
            print(f"processed {index}/{len(images)} image–article pairs", flush=True)

    out = root / cfg["paths"]["analysis_results"] / "multimodal"
    out.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(out / "image_text_alignment.csv", index=False)
    valid = frame[frame.get("analysis_error", "").fillna("") == ""] if not frame.empty else frame
    if not valid.empty and {"provisional_relation", "siglip_lead_similarity"}.issubset(valid.columns):
        review = (
            valid.sort_values(["provisional_relation", "siglip_lead_similarity"])
            .groupby("provisional_relation", group_keys=False)
            .head(cfg["multimodal"]["review_examples_per_relation"])
        )
    else:
        review = valid
    review.to_csv(out / "stratified_human_review_sample.csv", index=False)
    print(
        json.dumps(
            {
                "pairs": len(frame),
                "errors": int(frame["analysis_error"].notna().sum()) if "analysis_error" in frame else 0,
                "output": str(out),
                "warning": (
                    "Similarity does not establish agreement, truthfulness or political meaning. "
                    "Thresholds are uncalibrated and only support review sampling."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
