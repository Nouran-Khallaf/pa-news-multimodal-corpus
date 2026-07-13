#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from collections import Counter
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker


def lines(path: Path):
    if not path.exists(): return
    with path.open(encoding='utf-8') as f:
        for n,line in enumerate(f,1):
            if line.strip(): yield n,json.loads(line)

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--root',type=Path,default=Path('outputs/pa_news')); ap.add_argument('--article-schema',type=Path,default=Path('schemas/article.schema.json')); ap.add_argument('--image-schema',type=Path,default=Path('schemas/image.schema.json')); args=ap.parse_args()
    av=Draft202012Validator(json.loads(args.article_schema.read_text()),format_checker=FormatChecker()); iv=Draft202012Validator(json.loads(args.image_schema.read_text()),format_checker=FormatChecker())
    articles_path=args.root/'data/processed/articles.jsonl'; images_path=args.root/'data/processed/images.jsonl'; errors=[]; urls=[]; doc_ids=[]; body_hashes=[]; image_hashes=[]; article_images=set(); image_ids=[]
    article_count=word_count=0
    for n,rec in lines(articles_path) or []:
        article_count+=1
        for error in av.iter_errors(rec):errors.append(f'articles.jsonl:{n}: {error.message}')
        urls.append(rec['final_url']); doc_ids.append(rec['document_id']); body_hashes.append(rec['derived_text_sha256']); word_count+=rec.get('word_count',0)
        for im in rec.get('images',[]): article_images.add(im.get('image_id'))
        raw=args.root/rec['raw_html_path']
        if not raw.exists():errors.append(f'articles.jsonl:{n}: missing raw HTML {raw}')
        elif hashlib.sha256(raw.read_bytes()).hexdigest()!=rec['raw_payload_sha256']:errors.append(f'articles.jsonl:{n}: raw hash mismatch')
        if hashlib.sha256(rec['body'].encode()).hexdigest()!=rec['derived_text_sha256']:errors.append(f'articles.jsonl:{n}: derived hash mismatch')
    image_count=0
    for n,rec in lines(images_path) or []:
        image_count+=1; image_hashes.append(rec['sha256']); image_ids.append(rec['image_id'])
        for error in iv.iter_errors(rec):errors.append(f'images.jsonl:{n}: {error.message}')
        p=args.root/rec['object_path']
        if not p.exists():errors.append(f'images.jsonl:{n}: missing image object {p}')
        elif hashlib.sha256(p.read_bytes()).hexdigest()!=rec['sha256']:errors.append(f'images.jsonl:{n}: image hash mismatch')
        if rec['document_id'] not in set(doc_ids):errors.append(f"images.jsonl:{n}: unknown document_id {rec['document_id']}")
    missing_rel=sorted(x for x in article_images if x and x not in set(image_ids)); orphan_rel=sorted(x for x in image_ids if x not in article_images)
    if missing_rel:errors.append(f'article image references missing from images.jsonl: {missing_rel[:10]}')
    if orphan_rel:errors.append(f'images.jsonl records not linked from article: {orphan_rel[:10]}')
    for label,values in (('URL',urls),('document ID',doc_ids),('image ID',image_ids)):
        dups=[k for k,v in Counter(values).items() if v>1]
        if dups:errors.append(f'duplicate {label}s: {dups[:10]}')
    summary={'articles':article_count,'words':word_count,'image_references':image_count,'unique_image_objects':len(set(image_hashes)),'duplicate_body_hashes':sum(v-1 for v in Counter(body_hashes).values() if v>1),'missing_article_image_relations':len(missing_rel),'orphan_image_relations':len(orphan_rel),'validation_errors':errors}
    path=args.root/'manifests/validation_summary.json'; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(summary,indent=2)+'\n'); print(json.dumps(summary,indent=2)); return 1 if errors else 0
if __name__=='__main__':raise SystemExit(main())
