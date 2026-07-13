#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, re, unicodedata
from pathlib import Path
from corpus_utils import iter_jsonl, load_yaml, write_jsonl

EMAIL_RE=re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',re.I)

def normalise(text:str)->str:
    text=unicodedata.normalize('NFKC',text or '')
    text=text.replace('\r\n','\n').replace('\r','\n')
    text=EMAIL_RE.sub('[EMAIL_REDACTED]',text)
    paragraphs=[re.sub(r'[ \t]+',' ',p).strip() for p in re.split(r'\n\s*\n',text)]
    return '\n\n'.join(p for p in paragraphs if p)

def main():
    ap=argparse.ArgumentParser(description='Create a versioned, deterministic normalised analysis layer without altering source captures.')
    ap.add_argument('--config',type=Path,default=Path('config/analysis.yml')); args=ap.parse_args(); root=Path.cwd(); cfg=load_yaml(args.config)
    src=root/cfg['paths']['articles_jsonl']; dst=root/cfg['paths']['collection_root']/'data/analysis_ready/articles.normalised.jsonl'
    rows=[]
    for rec in iter_jsonl(src) or []:
        body=normalise(rec.get('body','')); row=dict(rec); row['body']=body; row['paragraphs']=[normalise(p) for p in rec.get('paragraphs',[]) if normalise(p)]
        row['normalisation_version']='nfkc-whitespace-email-redaction-v1'; row['normalised_text_sha256']=hashlib.sha256(body.encode()).hexdigest(); row['corpus_layer']='analysis_ready'
        rows.append(row)
    write_jsonl(dst,rows); print(f'Wrote {len(rows)} records to {dst}')
if __name__=='__main__':main()
