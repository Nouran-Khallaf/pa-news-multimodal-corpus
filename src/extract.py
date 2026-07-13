#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from bs4 import BeautifulSoup
from collect_pa_news import parse_article
from corpus_utils import iter_jsonl, load_yaml

def main():
    ap=argparse.ArgumentParser(description='Re-extract saved raw HTML and compare it with the stored derived record.')
    ap.add_argument('--config',type=Path,default=Path('config/analysis.yml')); ap.add_argument('--limit',type=int); args=ap.parse_args(); root=Path.cwd(); cfg=load_yaml(args.config)
    collection=root/cfg['paths']['collection_root']; rows=[]
    for i,rec in enumerate(iter_jsonl(root/cfg['paths']['articles_jsonl']) or []):
        if args.limit is not None and i>=args.limit:break
        raw=collection/rec['raw_html_path']
        try:
            parsed=parse_article(BeautifulSoup(raw.read_bytes(),'html.parser'),rec['final_url'],minimum_words=1)
            new_body=parsed['body']; status='match' if new_body==rec.get('body') else 'different'
            rows.append({'document_id':rec['document_id'],'raw_html_path':rec['raw_html_path'],'status':status,'stored_words':len(rec.get('body','').split()),'reextracted_words':len(new_body.split()),'title_match':parsed['title']==rec.get('title'),'stored_image_count':len(rec.get('images') or []),'reextracted_image_candidates':len(parsed['image_candidates'])})
        except Exception as exc:rows.append({'document_id':rec['document_id'],'raw_html_path':rec['raw_html_path'],'status':'error','error':f'{type(exc).__name__}: {exc}'})
    out=collection/'manifests/reextraction_audit.json'; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(rows,indent=2)+'\n'); print(f'Wrote {len(rows)} audit rows to {out}')
if __name__=='__main__':main()
