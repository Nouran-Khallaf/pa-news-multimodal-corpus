#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from corpus_utils import load_yaml, load_articles, parse_date, readability, sentence_split, tokenise, write_jsonl


def load_nlp(model_name: str, allow_fallback: bool):
    try:
        import spacy
        return spacy.load(model_name), 'spacy'
    except Exception as exc:
        if not allow_fallback:
            raise RuntimeError(
                f'Could not load spaCy model {model_name!r}. Install it with: '
                f'python -m spacy download {model_name}. Use --allow-fallback only for a basic smoke run.'
            ) from exc
        return None, 'regex_fallback'


def main() -> int:
    ap=argparse.ArgumentParser(description='Create document, sentence, entity and token analysis tables.')
    ap.add_argument('--config', type=Path, default=Path('config/analysis.yml'))
    ap.add_argument('--allow-fallback', action='store_true')
    args=ap.parse_args()
    cfg=load_yaml(args.config); root=Path.cwd()
    articles=load_articles(cfg, root)
    nlp, mode=load_nlp(cfg['text']['spacy_model'], args.allow_fallback)
    doc_rows=[]; sent_rows=[]; ent_rows=[]; token_rows=[]
    for rec in articles:
        text=rec.get('body','')
        dt=parse_date(rec.get('published_at'))
        if nlp is not None:
            doc=nlp(text)
            sentences=[s.text.strip() for s in doc.sents if s.text.strip()]
            for si,s in enumerate(doc.sents):
                stext=s.text.strip()
                if not stext: continue
                sent_rows.append({'document_id':rec['document_id'],'sentence_id':f"{rec['document_id']}-s{si:04d}",'sentence_index':si,'text':stext,'token_count':len([t for t in s if not t.is_space])})
            for ei,e in enumerate(doc.ents):
                ent_rows.append({'document_id':rec['document_id'],'entity_id':f"{rec['document_id']}-e{ei:04d}",'text':e.text,'normalised':e.text.strip().lower(),'label':e.label_,'start_char':e.start_char,'end_char':e.end_char,'sentence':e.sent.text.strip()})
            for ti,t in enumerate(doc):
                if t.is_space: continue
                token_rows.append({'document_id':rec['document_id'],'token_index':ti,'text':t.text,'lower':t.lower_,'lemma':t.lemma_,'pos':t.pos_,'tag':t.tag_,'dep':t.dep_,'head_index':t.head.i,'is_stop':bool(t.is_stop),'is_alpha':bool(t.is_alpha),'sentence_index':next((i for i,s in enumerate(doc.sents) if s.start <= t.i < s.end),None)})
        else:
            sentences=sentence_split(text)
            for si,stext in enumerate(sentences):
                sent_rows.append({'document_id':rec['document_id'],'sentence_id':f"{rec['document_id']}-s{si:04d}",'sentence_index':si,'text':stext,'token_count':len(tokenise(stext))})
            for ti,t in enumerate(tokenise(text)):
                token_rows.append({'document_id':rec['document_id'],'token_index':ti,'text':t,'lower':t,'lemma':t,'pos':None,'tag':None,'dep':None,'head_index':None,'is_stop':None,'is_alpha':True,'sentence_index':None})
        metrics=readability(text, sentences)
        doc_rows.append({
            'document_id':rec['document_id'],'final_url':rec.get('final_url'),'title':rec.get('title'),
            'published_at':rec.get('published_at'),'year':dt.year if dt else None,'month':dt.strftime('%Y-%m') if dt else None,
            'author':rec.get('author'),'tags':'|'.join(rec.get('tags') or []),'image_count':len(rec.get('images') or []),
            'paragraph_count':len(rec.get('paragraphs') or []),**metrics,
        })
    out=root/cfg['paths']['analysis_interim']
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(doc_rows).to_csv(out/'documents.csv', index=False)
    pd.DataFrame(ent_rows).to_csv(out/'entities.csv', index=False)
    pd.DataFrame(token_rows).to_csv(out/'tokens.csv.gz', index=False, compression='gzip')
    write_jsonl(out/'sentences.jsonl', sent_rows)
    (out/'preprocessing_metadata.json').write_text(json.dumps({'documents':len(doc_rows),'sentences':len(sent_rows),'entities':len(ent_rows),'tokens':len(token_rows),'mode':mode,'spacy_model':cfg['text']['spacy_model']},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'ok','documents':len(doc_rows),'sentences':len(sent_rows),'entities':len(ent_rows),'tokens':len(token_rows),'mode':mode},indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
