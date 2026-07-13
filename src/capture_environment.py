#!/usr/bin/env python3
from __future__ import annotations
import json, os, platform, subprocess, sys
from pathlib import Path

def cmd(args):
 try:return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT).strip()
 except Exception as exc:return f'UNAVAILABLE: {exc}'
def main():
 out=Path('outputs/pa_news/manifests/execution_environment.json'); out.parent.mkdir(parents=True,exist_ok=True)
 safe_env={k:v for k,v in os.environ.items() if k in {'CONDA_DEFAULT_ENV','CUDA_VISIBLE_DEVICES','SLURM_JOB_ID','SLURM_JOB_NAME','SLURM_CLUSTER_NAME','HOSTNAME'}}
 data={'python':sys.version,'platform':platform.platform(),'machine':platform.machine(),'pip_freeze':cmd([sys.executable,'-m','pip','freeze']).splitlines(),'git_commit':cmd(['git','rev-parse','HEAD']),'nvidia_smi':cmd(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader']),'safe_environment':safe_env}
 out.write_text(json.dumps(data,indent=2)+'\n'); print(out)
if __name__=='__main__':main()
