#!/usr/bin/env python3
"""Generate distributable OFL fonts; never read system fonts."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def renamed(font,family):
    for n in font['name'].names:
        values={1:family,2:'Regular',3:family.replace(' ','')+'-1.0',4:family,6:family.replace(' ',''),16:family,17:'Regular'}
        if n.nameID in values:
            n.string=values[n.nameID].encode(n.getEncoding())
    font['OS/2'].fsType=0
    return font

def main():
    p=argparse.ArgumentParser();p.add_argument('--repository',type=Path,default=ROOT/'.nxnative');args=p.parse_args()
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    from fontTools import subset
    source=ROOT/'NativeGameBuilder/Assets/Fonts/NotoSansCJKjp-VF.ttf'
    generator=args.repository/'dm/tools/make_ext_font.py'
    key=hashlib.sha256(source.read_bytes()+generator.read_bytes()+Path(__file__).read_bytes()).hexdigest()
    out=ROOT/'build/font-assets';out.mkdir(parents=True,exist_ok=True)
    marker=out/'manifest.json'
    if marker.exists() and json.loads(marker.read_text()).get('key')==key and all((out/n).is_file() for n in ['standard.ttf','nintendo_ext.ttf']):
        print('Redistributable fonts reused');return
    print('Preparing static Noto CJK regular font…',flush=True)
    f=instantiateVariableFont(TTFont(source),{'wght':400},inplace=True)
    renamed(f,'NX Game Sans').save(out/'standard.ttf')
    f=TTFont(source)
    options=subset.Options();options.name_IDs=['*'];options.name_legacy=True;options.name_languages=['*']
    sub=subset.Subsetter(options=options);sub.populate(text='ABXYLRZLSR');sub.subset(f)
    f=instantiateVariableFont(f,{'wght':700},inplace=True)
    renamed(f,'NX Game Letter Shapes').save(out/'letters.ttf')
    subprocess.run([sys.executable,generator,out/'nintendo_ext.ttf',out/'letters.ttf'],check=True)
    f=TTFont(out/'nintendo_ext.ttf');renamed(f,'NX Game Symbols')
    for nameid,value in [(0,'Glyph outlines derived from Noto CJK, Copyright 2014-2021 Adobe; generator Copyright 2026 seedds. Modified by prBigBrother.'),(13,'Licensed under the SIL Open Font License, Version 1.1. See OFL.txt.'),(14,'https://openfontlicense.org/')]:
        f['name'].setName(value,nameid,3,1,0x409)
    f.save(out/'nintendo_ext.ttf')
    marker.write_text(json.dumps({'key':key,'source':'notofonts/noto-cjk f8d157532fbfaeda587e826d4cd5b21a49186f7c','license':'OFL-1.1'}))
    print('Redistributable fonts ready',flush=True)

if __name__=='__main__':main()
