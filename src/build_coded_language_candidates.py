#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd
from corpus_utils import load_yaml

FIELDS=['surface_form','normalised_form','document_id','evidence_location','minimal_context','proposed_decoded_meaning','discursive_function','target_or_referent','ambiguity','alternative_interpretation','corpus_frequency','document_frequency','first_observed','last_observed','confidence','review_status','harm_or_amplification_note','candidate_basis']

def main():
    ap=argparse.ArgumentParser(description='Create a human-review queue; it does not automatically label terms as coded language.')
    ap.add_argument('--config',type=Path,default=Path('config/analysis.yml')); ap.add_argument('--top-k',type=int,default=100)
    args=ap.parse_args(); root=Path.cwd(); cfg=load_yaml(args.config); results=root/cfg['paths']['analysis_results']
    key=results/'keyness.csv'; coll=results/'collocations.csv'; rows=[]
    if key.exists() and key.stat().st_size > 0:
        try: df=pd.read_csv(key).query('log_ratio > 0').head(args.top_k)
        except pd.errors.EmptyDataError: df=pd.DataFrame()
        for _,r in df.iterrows(): rows.append({'surface_form':r.term,'normalised_form':r.term,'corpus_frequency':int(r.target_frequency),'document_frequency':int(r.target_document_frequency),'candidate_basis':f"positive keyness; log-ratio={r.log_ratio:.2f}; q={r.q_value_bh:.3g}",'review_status':'unreviewed_candidate'})
    if coll.exists() and coll.stat().st_size > 0:
        try: df=pd.read_csv(coll).sort_values(['logdice','cooccurrence_frequency'],ascending=False).head(args.top_k)
        except pd.errors.EmptyDataError: df=pd.DataFrame()
        for _,r in df.iterrows(): rows.append({'surface_form':f"{r.node} … {r.collocate}",'normalised_form':f"{r.node} {r.collocate}",'minimal_context':r.examples,'corpus_frequency':int(r.cooccurrence_frequency),'document_frequency':int(r.document_frequency),'candidate_basis':f"collocation candidate; logDice={r.logdice:.2f}",'review_status':'unreviewed_candidate'})
    out=results/'political_discourse'/'coded_language_candidate_review.csv'; out.parent.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(rows,columns=FIELDS).drop_duplicates(subset=['normalised_form']).to_csv(out,index=False)
    print(f'Wrote {len(rows)} unreviewed candidates to {out}. No decoded meanings were invented.')
if __name__=='__main__': main()
