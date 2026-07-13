#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd
from corpus_utils import load_yaml

def aggregate_candidates(path,category,outpath):
 if not path.exists() or path.stat().st_size==0:return
 df=pd.read_csv(path); docs=pd.read_csv(DOCS)[['document_id','month','year','word_count']]; df=df.merge(docs,on='document_id',how='left')
 rows=[]
 for period in ('month','year'):
  agg=df.groupby([period,category],dropna=False).size().rename('candidate_sentences').reset_index(); den=docs.groupby(period,dropna=False).agg(documents=('document_id','nunique'),words=('word_count','sum')).reset_index(); agg=agg.merge(den,on=period,how='left'); agg['candidates_per_100_articles']=agg['candidate_sentences']/agg['documents']*100; agg['candidates_per_10000_words']=agg['candidate_sentences']/agg['words']*10000; agg['period_type']=period; rows.append(agg.rename(columns={period:'period'}))
 pd.concat(rows,ignore_index=True).to_csv(outpath,index=False)

def main():
 global DOCS
 ap=argparse.ArgumentParser(description='Aggregate validated or candidate text/visual categories by month and year with normalised rates.'); ap.add_argument('--config',type=Path,default=Path('config/analysis.yml')); args=ap.parse_args(); root=Path.cwd(); cfg=load_yaml(args.config); r=root/cfg['paths']['analysis_results']; DOCS=root/cfg['paths']['analysis_interim']/'documents.csv'; out=r/'temporal'; out.mkdir(parents=True,exist_ok=True)
 aggregate_candidates(r/'political_discourse/frame_candidates.csv','frame',out/'frame_candidates_over_time.csv'); aggregate_candidates(r/'political_discourse/legitimation_candidates.csv','strategy',out/'legitimation_candidates_over_time.csv')
 img=r/'images/image_analysis.csv'
 if img.exists() and img.stat().st_size>0:
  df=pd.read_csv(img); docs=pd.read_csv(DOCS)[['document_id','month','year']]; df=df.merge(docs,on='document_id',how='left')
  if 'visual_category_top1' in df:
   rows=[]
   for period in ('month','year'):
    x=df.groupby([period,'visual_category_top1'],dropna=False).size().rename('images').reset_index(); x['period_type']=period; rows.append(x.rename(columns={period:'period'}))
   pd.concat(rows,ignore_index=True).to_csv(out/'visual_categories_over_time.csv',index=False)
 print(out)
if __name__=='__main__':main()
