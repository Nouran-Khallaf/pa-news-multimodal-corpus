#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from scipy.stats import chi2

from corpus_utils import (benjamini_hochberg, load_articles, load_yaml, log_likelihood,
                          log_ratio, stopwords_en, tokenise)


def ngrams(tokens, n):
    return [' '.join(tokens[i:i+n]) for i in range(len(tokens)-n+1)]


def load_comparator(path: Path) -> list[str]:
    if path.is_dir():
        return [p.read_text(encoding='utf-8',errors='replace') for p in sorted(path.rglob('*.txt'))]
    if path.suffix.lower()=='.jsonl':
        texts=[]
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                row=json.loads(line); texts.append(row.get('body') or row.get('text') or '')
        return texts
    if path.suffix.lower()=='.csv':
        df=pd.read_csv(path)
        col='body' if 'body' in df else 'text'
        return df[col].fillna('').astype(str).tolist()
    return [path.read_text(encoding='utf-8',errors='replace')]


def count_terms(texts: list[str], min_len=2):
    sw=stopwords_en(); tf=Counter(); df=Counter(); total=0
    for text in texts:
        toks=[t for t in tokenise(text) if t not in sw and len(t)>=min_len]
        total += len(toks); tf.update(toks); df.update(set(toks))
    return tf,df,total


def main() -> int:
    ap=argparse.ArgumentParser(description='Descriptive statistics, frequencies, n-grams and optional keyness.')
    ap.add_argument('--config', type=Path, default=Path('config/analysis.yml'))
    ap.add_argument('--comparator', type=Path)
    args=ap.parse_args(); root=Path.cwd(); cfg=load_yaml(args.config)
    articles=load_articles(cfg,root); texts=[x.get('body','') for x in articles]
    out=root/cfg['paths']['analysis_results']; out.mkdir(parents=True,exist_ok=True)
    tf,df,total=count_terms(texts)
    pd.DataFrame([{'term':t,'frequency':c,'per_million':c/total*1e6,'document_frequency':df[t],'document_proportion':df[t]/len(texts)} for t,c in tf.most_common()]).to_csv(out/'term_frequencies.csv',index=False)
    for n in (2,3):
        ntf=Counter(); ndf=Counter(); ntotal=0
        for text in texts:
            toks=[t for t in tokenise(text) if len(t)>1]
            vals=ngrams(toks,n); ntf.update(vals); ndf.update(set(vals)); ntotal+=len(vals)
        rows=[{'ngram':g,'n':n,'frequency':c,'per_million':c/max(1,ntotal)*1e6,'document_frequency':ndf[g]} for g,c in ntf.most_common() if c>=cfg['text']['minimum_ngram_frequency']]
        pd.DataFrame(rows).to_csv(out/f'{n}gram_frequencies.csv',index=False)
    dates=[]
    for a in articles:
        if a.get('published_at'):
            dates.append({'published_at':a['published_at'][:10],'month':a['published_at'][:7],'year':a['published_at'][:4],'word_count':a.get('word_count',len(tokenise(a.get('body','')))),'images':len(a.get('images') or [])})
    ddf=pd.DataFrame(dates)
    if not ddf.empty:
        ddf.groupby('month',dropna=False).agg(articles=('month','size'),words=('word_count','sum'),images=('images','sum')).reset_index().to_csv(out/'publication_by_month.csv',index=False)
        ddf.groupby('year',dropna=False).agg(articles=('year','size'),words=('word_count','sum'),images=('images','sum')).reset_index().to_csv(out/'publication_by_year.csv',index=False)
    if args.comparator:
        comp_texts=load_comparator(args.comparator); ctf,cdf,ctotal=count_terms(comp_texts)
        vocab=sorted(set(tf)|set(ctf)); rows=[]; pvals=[]
        for term in vocab:
            if tf[term] < cfg['keyness']['minimum_target_frequency']: continue
            ll=log_likelihood(tf[term],total,ctf[term],ctotal)
            p=float(chi2.sf(ll,1)); pvals.append(p)
            rows.append({'term':term,'target_frequency':tf[term],'target_document_frequency':df[term],'comparator_frequency':ctf[term],'comparator_document_frequency':cdf[term],'log_likelihood':ll,'p_value':p,'log_ratio':log_ratio(tf[term],total,ctf[term],ctotal)})
        q=benjamini_hochberg(pvals)
        for row,qq in zip(rows,q): row['q_value_bh']=qq
        pd.DataFrame(sorted(rows,key=lambda r:(-r['log_ratio'],-r['log_likelihood']))).to_csv(out/'keyness.csv',index=False)
    summary={'documents':len(articles),'tokens_after_filtering':total,'unique_terms':len(tf),'date_min':min((x.get('published_at') for x in articles if x.get('published_at')),default=None),'date_max':max((x.get('published_at') for x in articles if x.get('published_at')),default=None),'comparator_used':str(args.comparator) if args.comparator else None}
    (out/'corpus_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
