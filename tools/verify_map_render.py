"""Render an existing test import through the product's real GPU command."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from core.ue_pipeline import render_step

parser=argparse.ArgumentParser()
parser.add_argument('--project',required=True)
parser.add_argument('--source',required=True)
parser.add_argument('--dest',required=True)
parser.add_argument('--scripts',default=str(BASE/'scripts/official'))
parser.add_argument('--ev',default='0')
args=parser.parse_args()
step=render_step({'engine':'E:/UE_5.4/Engine/Binaries/Win64/UnrealEditor.exe',
    'project':args.project,'root':args.source,'dest':args.dest,'scripts':args.scripts,'render_ev':args.ev})
env=os.environ.copy()
env.update(step.env)
started=time.time()
with open(step.log_path,'w',encoding='utf-8') as log:
    proc=subprocess.run(step.cmd,env=env,stdout=log,stderr=subprocess.STDOUT,
                         creationflags=0x08000000,timeout=900)
assert proc.returncode==0,proc.returncode
step.validate(started)
print(Path(args.source,'render_report.json').read_text())
print(Path(args.source,'lighting_report.json').read_text())
