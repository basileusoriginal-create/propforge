"""Expand upstream's git archive version placeholder after checking HEAD.

A shallow checkout leaves $Format:%h$ unexpanded, whereas the installed
nightly archive contains the short commit. Dependencies stay byte-identical.
"""
import json
import subprocess
import sys
from pathlib import Path

repository=Path(__file__).resolve().parents[1]
pins=json.loads((repository/'toolchain.lock.json').read_text())
checkout=Path(sys.argv[1]).resolve()
head=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
if head!=pins['sollumz_commit']: raise SystemExit('Unexpected Sollumz HEAD: '+head)
path=checkout/'blender_manifest.toml'
text=path.read_text()
token='$Format:%h$'
if token in text:
    path.write_text(text.replace(token,head[:8]),encoding='utf-8')
import tomllib
if tomllib.loads(path.read_text())['version']!=pins['sollumz_manifest']:
    raise SystemExit('Unexpected Sollumz manifest version')
print('Pinned Sollumz checkout prepared: '+head)
