#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pandas as pd
from PIL import Image, ImageStat

from corpus_utils import load_images, load_yaml


def basic_features(path: Path) -> dict:
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        stat = ImageStat.Stat(rgb)
        return {
            "width_observed": rgb.width,
            "height_observed": rgb.height,
            "aspect_ratio": rgb.width / max(1, rgb.height),
            "mean_red": stat.mean[0],
            "mean_green": stat.mean[1],
            "mean_blue": stat.mean[2],
            "mean_luminance": sum(stat.mean) / 3,
        }


def merge_analysis(existing: Path, new_rows: list[dict]) -> pd.DataFrame:
    new = pd.DataFrame(new_rows)
    if not existing.exists() or existing.stat().st_size == 0 or new.empty:
        return new
    try:
        old = pd.read_csv(existing)
    except pd.errors.EmptyDataError:
        return new
    if "image_id" not in old or "image_id" not in new:
        return new
    old = old.set_index("image_id")
    new = new.set_index("image_id")
    combined = old.combine_first(new)
    combined.update(new)
    return combined.reset_index()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Image metadata, perceptual duplicates, OCR, captions and provisional visual categories."
    )
    ap.add_argument("--config", type=Path, default=Path("config/analysis.yml"))
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--ocr", action="store_true")
    ap.add_argument("--caption", action="store_true")
    ap.add_argument("--classify", action="store_true")
    ap.add_argument("--detect", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    root = Path.cwd()
    cfg = load_yaml(args.config)
    images = load_images(cfg, root)
    if args.limit:
        images = images[: args.limit]

    try:
        import imagehash
    except ImportError as exc:
        raise RuntimeError("Install imagehash from requirements-core.txt") from exc

    captioner = classifier = detector = None
    if args.caption or args.classify or args.detect:
        from transformers import pipeline

        if args.caption:
            captioner = pipeline(
                "image-to-text", model=cfg["models"]["image_captioning"], device=args.device
            )
        if args.classify:
            classifier = pipeline(
                "zero-shot-image-classification",
                model=cfg["models"]["image_text"],
                device=args.device,
            )
        if args.detect:
            detector = pipeline(
                "zero-shot-object-detection",
                model=cfg["models"]["object_detection"],
                device=args.device,
            )

    if args.ocr:
        try:
            import pytesseract
        except ImportError as exc:
            raise RuntimeError("Install pytesseract and the system tesseract executable.") from exc
        if shutil.which("tesseract") is None:
            raise RuntimeError("tesseract executable is not on PATH.")

    rows: list[dict] = []
    detections: list[dict] = []
    for idx, rec in enumerate(images, 1):
        path = root / cfg["paths"]["collection_root"] / rec["object_path"]
        if not path.exists():
            rows.append({**rec, "analysis_error": f"missing file: {path}"})
            continue
        try:
            feat = basic_features(path)
            with Image.open(path) as im:
                phash = str(imagehash.phash(im.convert("RGB")))
            row = {**rec, **feat, "perceptual_hash": phash, "analysis_error": None}
            if args.ocr:
                import pytesseract

                with Image.open(path) as im:
                    row["ocr_text"] = pytesseract.image_to_string(im).strip()
            if captioner:
                result = captioner(str(path), max_new_tokens=60)
                row["generated_caption"] = result[0].get("generated_text", "").strip()
            if classifier:
                result = classifier(
                    str(path), candidate_labels=cfg["image_analysis"]["visual_categories"]
                )
                row["visual_category_top1"] = result[0]["label"]
                row["visual_category_top1_score"] = float(result[0]["score"])
                row["visual_category_scores_json"] = json.dumps(
                    {x["label"]: float(x["score"]) for x in result}, ensure_ascii=False
                )
            if detector:
                result = detector(
                    str(path),
                    candidate_labels=cfg["image_analysis"]["object_queries"],
                    threshold=cfg["image_analysis"]["object_threshold"],
                )
                for detection in result:
                    detections.append(
                        {
                            "image_id": rec["image_id"],
                            "document_id": rec["document_id"],
                            "label": detection["label"],
                            "score": float(detection["score"]),
                            "xmin": detection["box"]["xmin"],
                            "ymin": detection["box"]["ymin"],
                            "xmax": detection["box"]["xmax"],
                            "ymax": detection["box"]["ymax"],
                            "validation_status": "model_assisted_unreviewed",
                        }
                    )
            rows.append(row)
        except Exception as exc:
            rows.append({**rec, "analysis_error": f"{type(exc).__name__}: {exc}"})
        if idx % 25 == 0:
            print(f"processed {idx}/{len(images)} images", flush=True)

    out = root / cfg["paths"]["analysis_results"] / "images"
    out.mkdir(parents=True, exist_ok=True)
    analysis_path = out / "image_analysis.csv"
    combined = merge_analysis(analysis_path, rows)
    combined.to_csv(analysis_path, index=False)

    detection_columns = [
        "image_id",
        "document_id",
        "label",
        "score",
        "xmin",
        "ymin",
        "xmax",
        "ymax",
        "validation_status",
    ]
    if args.detect:
        pd.DataFrame(detections, columns=detection_columns).to_csv(
            out / "object_detections.csv", index=False
        )

    if not combined.empty and "perceptual_hash" in combined:
        duplicates = combined.groupby("perceptual_hash", dropna=False).filter(
            lambda group: len(group) > 1
        )
        duplicates.to_csv(out / "perceptual_duplicate_groups.csv", index=False)

    meta = {
        "images_attempted": len(images),
        "ocr": args.ocr,
        "captioning": args.caption,
        "classification": args.classify,
        "object_detection": args.detect,
        "warning": (
            "Generated captions, OCR, visual classes and objects are provisional model outputs "
            "requiring manual validation. No face recognition or demographic inference is performed."
        ),
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
