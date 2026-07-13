#!/usr/bin/env python3
from __future__ import annotations

import argparse, math
from collections import Counter, defaultdict
from pathlib import Path
import pandas as pd

from corpus_utils import load_articles, load_yaml, tokenise


def main() -> int:
    ap=argparse.ArgumentParser(description='Window collocations with PMI, logDice, dispersion and concordance examples.')
    ap.add_argument('--config',type=Path,default=Path('config/analysis.yml'))
    ap.add_argument('--nodes',nargs='*')
    args=ap.parse_args(); root=Path.cwd(); cfg=load_yaml(args.config)
    nodes=[x.lower() for x in (args.nodes or cfg['political_analysis']['node_terms'])]
    if not nodes: raise SystemExit('No node terms configured. Add political_analysis.node_terms or pass --nodes.')
    articles=load_articles(cfg,root); window=int(cfg['collocations']['window']); min_freq=int(cfg['collocations']['minimum_collocate_frequency'])
    total=0; unigram=Counter(); pair=Counter(); pair_docs=defaultdict(set); examples=defaultdict(list); node_counts=Counter()
    for rec in articles:
        toks=tokenise(rec.get('body','')); total+=len(toks); unigram.update(toks)
        for i,t in enumerate(toks):
            if t not in nodes: continue
            node_counts[t]+=1
            for j in range(max(0,i-window),min(len(toks),i+window+1)):
                if j==i: continue
                c=toks[j]
                if len(c)<2: continue
                pair[(t,c)]+=1; pair_docs[(t,c)].add(rec['document_id'])
                if len(examples[(t,c)])<3:
                    examples[(t,c)].append(' '.join(toks[max(0,i-8):min(len(toks),i+9)]))
    rows=[]
    for (node,col),freq in pair.items():
        if freq<min_freq: continue
        pmi=math.log2((freq*max(1,total))/(max(1,node_counts[node])*max(1,unigram[col])))
        logdice=14+math.log2((2*freq)/(max(1,node_counts[node])+max(1,unigram[col])))
        rows.append({'node':node,'collocate':col,'cooccurrence_frequency':freq,'node_frequency':node_counts[node],'collocate_frequency':unigram[col],'document_frequency':len(pair_docs[(node,col)]),'pmi':pmi,'logdice':logdice,'examples':' || '.join(examples[(node,col)])})
    out=root/cfg['paths']['analysis_results']; out.mkdir(parents=True,exist_ok=True)
    columns=['node','collocate','cooccurrence_frequency','node_frequency','collocate_frequency','document_frequency','pmi','logdice','examples']
    pd.DataFrame(sorted(rows,key=lambda r:(r['node'],-r['logdice'],-r['cooccurrence_frequency'])), columns=columns).to_csv(out/'collocations.csv',index=False)
    print(f'Wrote {len(rows)} collocation rows for {len(nodes)} nodes to {out / "collocations.csv"}')
    return 0
if __name__=='__main__': raise SystemExit(main())
