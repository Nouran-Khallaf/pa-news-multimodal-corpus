#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path

def run(cmd):
    print('+',' '.join(map(str,cmd)),flush=True); subprocess.run(list(map(str,cmd)),check=True)
def main():
    ap=argparse.ArgumentParser(description='Run CPU analysis stages. GPU stages remain separate Slurm jobs.')
    ap.add_argument('--config',default='config/analysis.yml'); ap.add_argument('--comparator'); ap.add_argument('--allow-fallback',action='store_true')
    args=ap.parse_args(); py=sys.executable
    cmd=[py,'src/preprocess_text.py','--config',args.config]+(['--allow-fallback'] if args.allow_fallback else []); run(cmd)
    cmd=[py,'src/analyse_corpus.py','--config',args.config]+(['--comparator',args.comparator] if args.comparator else []); run(cmd)
    run([py,'src/analyse_collocations.py','--config',args.config]); run([py,'src/analyse_political_discourse.py','--config',args.config])
    run([py,'src/build_coded_language_candidates.py','--config',args.config]); run([py,'src/build_analysis_summary.py','--config',args.config])
if __name__=='__main__': main()
