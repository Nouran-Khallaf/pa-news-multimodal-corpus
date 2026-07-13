#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np, pandas as pd
from PIL import Image
from corpus_utils import load_images, load_yaml


def main():
    ap=argparse.ArgumentParser(description='SigLIP image embeddings, UMAP and HDBSCAN clusters for visual-theme discovery.')
    ap.add_argument('--config',type=Path,default=Path('config/analysis.yml')); ap.add_argument('--device',default='cuda'); ap.add_argument('--limit',type=int)
    args=ap.parse_args(); root=Path.cwd(); cfg=load_yaml(args.config); rows=load_images(cfg,root)
    if args.limit: rows=rows[:args.limit]
    import torch
    from transformers import AutoModel, AutoProcessor
    from umap import UMAP
    from hdbscan import HDBSCAN
    model_name=cfg['models']['image_text']; processor=AutoProcessor.from_pretrained(model_name); model=AutoModel.from_pretrained(model_name).to(args.device).eval()
    embeddings=[]; kept=[]; batch=[]; metas=[]; bs=cfg['image_analysis']['embedding_batch_size']
    def flush():
        nonlocal batch,metas
        if not batch:return
        inputs=processor(images=batch,return_tensors='pt').to(args.device)
        with torch.inference_mode(): emb=model.get_image_features(**inputs)
        emb=torch.nn.functional.normalize(emb,dim=-1).cpu().numpy(); embeddings.extend(emb); kept.extend(metas); batch=[]; metas=[]
    for rec in rows:
        p=root/cfg['paths']['collection_root']/rec['object_path']
        try: batch.append(Image.open(p).convert('RGB')); metas.append(rec)
        except Exception: continue
        if len(batch)>=bs: flush()
    flush()
    if len(embeddings)<cfg['image_analysis']['minimum_cluster_images']: raise SystemExit('Too few valid images for clustering.')
    arr=np.asarray(embeddings,dtype=np.float32)
    reducer=UMAP(n_neighbors=min(cfg['image_analysis']['cluster_n_neighbors'],len(arr)-1),n_components=2,min_dist=0.05,metric='cosine',random_state=cfg['image_analysis']['cluster_seed'])
    xy=reducer.fit_transform(arr)
    labels=HDBSCAN(min_cluster_size=cfg['image_analysis']['minimum_cluster_size']).fit_predict(xy)
    out=root/cfg['paths']['analysis_results']/'images'; out.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(out/'image_embeddings.npz',embeddings=arr,image_ids=np.array([r['image_id'] for r in kept]),model_name=np.array(model_name))
    pd.DataFrame([{'image_id':r['image_id'],'document_id':r['document_id'],'cluster':int(l),'umap_x':float(x),'umap_y':float(y)} for r,l,(x,y) in zip(kept,labels,xy)]).to_csv(out/'image_clusters.csv',index=False)
    (out/'embedding_metadata.json').write_text(json.dumps({'model':model_name,'images':len(kept),'clusters':len(set(labels)-{-1}),'outliers':int(sum(labels==-1)),'interpretation':'Clusters are similarity-based visual groupings and require human inspection.'},indent=2)+'\n')
    print(f'Embedded {len(kept)} images; wrote {out}')
if __name__=='__main__': main()
