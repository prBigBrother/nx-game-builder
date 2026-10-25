#!/usr/bin/env python3
"""Collect runtime/source notices without game data or credentials."""
import argparse
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1]

def collect(repo,out):
    out.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'LICENSE',out/'NX-Game-Builder-MIT.txt')
    shutil.copyfile(ROOT/'THIRD_PARTY_NOTICES.md',out/'THIRD_PARTY_NOTICES.md')
    shutil.copytree(ROOT/'NativeGameBuilder/Assets/ToolchainLicenses',out/'RuntimeLicenses',dirs_exist_ok=True)
    shutil.copytree(ROOT/'NativeGameBuilder/Assets/Fonts',out/'FontNotices',dirs_exist_ok=True,ignore=shutil.ignore_patterns('*.ttf'))
    for name in ['LICENSE','README.md','dm/third_party/README.md','dm/gfx/nvn/include/nvn.h','dm/gfx/nvn/nvn_tex.c']:
        target=out/'nxnative'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/name,target)
    for p in (repo/'dm/third_party').rglob('*'):
        if p.is_file() and any(w in p.name.lower() for w in ('license','copying','notice','patents')):
            target=out/'nxnative'/p.relative_to(repo);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repository',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();collect(args.repository,args.output)
