#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score

from corpus_utils import load_articles, load_yaml


def main() -> int:
    ap=argparse.ArgumentParser(description='Multi-seed BERTopic analysis with saved embeddings and stability statistics.')
    ap.add_argument('--config',type=Path,default=Path('config/analysis.yml'))
    ap.add_argument('--device',default='auto')
    args=ap.parse_args(); root=Path.cwd(); cfg=load_yaml(args.config)
    articles=load_articles(cfg,root)
    if len(articles)<cfg['topics']['minimum_documents']:
        raise SystemExit(f"Topic modelling requires at least {cfg['topics']['minimum_documents']} documents; found {len(articles)}")
    from sentence_transformers import SentenceTransformer
    from bertopic import BERTopic
    from umap import UMAP
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    texts=[(a.get('title','')+'\n'+a.get('body','')).strip() for a in articles]
    ids=[a['document_id'] for a in articles]
    model_name=cfg['models']['text_embedding']
    device=None if args.device=='auto' else args.device
    encoder=SentenceTransformer(model_name,device=device)
    embeddings=encoder.encode(texts,batch_size=cfg['topics']['embedding_batch_size'],show_progress_bar=True,normalize_embeddings=True,convert_to_numpy=True)
    out=root/cfg['paths']['analysis_results']/ 'topics'; out.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(out/'document_embeddings.npz',embeddings=embeddings,document_ids=np.array(ids),model_name=np.array(model_name))
    assignments={}
    for seed in cfg['topics']['seeds']:
        umap_model=UMAP(n_neighbors=cfg['topics']['n_neighbors'],n_components=cfg['topics']['n_components'],min_dist=cfg['topics']['min_dist'],metric='cosine',random_state=seed)
        hdb=HDBSCAN(min_cluster_size=cfg['topics']['min_cluster_size'],metric='euclidean',cluster_selection_method='eom',prediction_data=True)
        vec=CountVectorizer(stop_words='english',ngram_range=(1,2),min_df=cfg['topics']['minimum_term_document_frequency'])
        topic_model=BERTopic(embedding_model=None,umap_model=umap_model,hdbscan_model=hdb,vectorizer_model=vec,calculate_probabilities=False,verbose=True)
        topics,_=topic_model.fit_transform(texts,embeddings)
        assignments[seed]=topics
        pd.DataFrame({'document_id':ids,'topic':topics}).to_csv(out/f'document_topics_seed_{seed}.csv',index=False)
        topic_model.get_topic_info().to_csv(out/f'topic_info_seed_{seed}.csv',index=False)
        topic_model.save(out/f'model_seed_{seed}',serialization='safetensors',save_ctfidf=True,save_embedding_model=False)
    stability=[]
    seeds=list(assignments)
    for i,s1 in enumerate(seeds):
        for s2 in seeds[i+1:]:
            stability.append({'seed_1':s1,'seed_2':s2,'adjusted_rand_index':adjusted_rand_score(assignments[s1],assignments[s2]),'outliers_seed_1':sum(x==-1 for x in assignments[s1]),'outliers_seed_2':sum(x==-1 for x in assignments[s2])})
    pd.DataFrame(stability).to_csv(out/'topic_stability.csv',index=False)
    (out/'topic_run_metadata.json').write_text(json.dumps({'model':model_name,'documents':len(ids),'seeds':seeds,'interpretation':'Topics are model-induced clusters and require human review.'},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'documents':len(ids),'seeds':seeds,'output':str(out)},indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
