#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd
from corpus_utils import load_yaml


def count_csv(path):
    try:return len(pd.read_csv(path))
    except Exception:return None

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',type=Path,default=Path('config/analysis.yml')); args=ap.parse_args()
    root=Path.cwd(); cfg=load_yaml(args.config); r=root/cfg['paths']['analysis_results']
    summary={
      'corpus_summary':json.loads((r/'corpus_summary.json').read_text()) if (r/'corpus_summary.json').exists() else None,
      'term_rows':count_csv(r/'term_frequencies.csv'),'keyness_rows':count_csv(r/'keyness.csv'),'collocation_rows':count_csv(r/'collocations.csv'),
      'frame_candidates':count_csv(r/'political_discourse/frame_candidates.csv'),'actor_mentions':count_csv(r/'political_discourse/actor_mentions.csv'),
      'image_rows':count_csv(r/'images/image_analysis.csv'),'image_clusters':count_csv(r/'images/image_clusters.csv'),'multimodal_pairs':count_csv(r/'multimodal/image_text_alignment.csv'),
    }
    lines=['# Analysis run summary','', '> Counts below describe pipeline outputs, not validated substantive findings.','']+[f'- **{k.replace("_"," ").title()}**: {v}' for k,v in summary.items()]
    (r/'analysis_summary.md').write_text('\n'.join(lines)+'\n',encoding='utf-8'); (r/'analysis_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
