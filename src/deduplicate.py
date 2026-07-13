#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from collections import defaultdict
from pathlib import Path
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors
from corpus_utils import load_articles, load_yaml

def main():
    ap=argparse.ArgumentParser(description='Find exact and near-duplicate article text without deleting records.')
    ap.add_argument('--config',type=Path,default=Path('config/analysis.yml')); ap.add_argument('--threshold',type=float,default=0.92); ap.add_argument('--neighbours',type=int,default=6); args=ap.parse_args(); root=Path.cwd(); cfg=load_yaml(args.config)
    articles=load_articles(cfg,root); out=root/cfg['paths']['analysis_results']/'quality_control'; out.mkdir(parents=True,exist_ok=True)
    exact=defaultdict(list)
    for a in articles:exact[a.get('derived_text_sha256','')].append(a['document_id'])
    exact_rows=[{'derived_text_sha256':h,'document_ids':'|'.join(ids),'count':len(ids)} for h,ids in exact.items() if h and len(ids)>1]
    pd.DataFrame(exact_rows,columns=['derived_text_sha256','document_ids','count']).to_csv(out/'exact_duplicate_groups.csv',index=False)
    texts=[a.get('body','') for a in articles]
    if len(texts)>=2:
        vec=TfidfVectorizer(analyzer='char_wb',ngram_range=(4,6),min_df=1,max_features=150000); X=vec.fit_transform(texts)
        k=min(args.neighbours,len(texts)); nn=NearestNeighbors(n_neighbors=k,metric='cosine',n_jobs=-1).fit(X); distances,indices=nn.kneighbors(X)
        pairs={}
        for i,(ds,js) in enumerate(zip(distances,indices)):
            for d,j in zip(ds,js):
                if i==j:continue
                sim=1-float(d)
                if sim>=args.threshold:
                    a,b=sorted((i,int(j))); pairs[(a,b)]=max(sim,pairs.get((a,b),0))
        near=[{'document_id_1':articles[i]['document_id'],'document_id_2':articles[j]['document_id'],'cosine_similarity_char_ngrams':s,'url_1':articles[i].get('final_url'),'url_2':articles[j].get('final_url'),'review_status':'unreviewed_candidate'} for (i,j),s in sorted(pairs.items(),key=lambda x:-x[1])]
    else:near=[]
    pd.DataFrame(near,columns=['document_id_1','document_id_2','cosine_similarity_char_ngrams','url_1','url_2','review_status']).to_csv(out/'near_duplicate_candidates.csv',index=False)
    meta={'documents':len(articles),'exact_duplicate_groups':len(exact_rows),'near_duplicate_pairs':len(near),'threshold':args.threshold,'action':'No records were deleted automatically.'}; (out/'deduplication_summary.json').write_text(json.dumps(meta,indent=2)+'\n'); print(json.dumps(meta,indent=2))
if __name__=='__main__':main()
