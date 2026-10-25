"""Offline installer transaction checks using tiny executable fixtures, no tool downloads."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'NativeGameBuilder/Backend/install_bundled_tools.sh'
spec=importlib.util.spec_from_file_location('toolchain_pack',ROOT/'scripts/prepare-bundled-toolchain.py')
pack=importlib.util.module_from_spec(spec);spec.loader.exec_module(pack)

class OfflineToolsTests(unittest.TestCase):
    def test_fat_macho_headers_are_not_dependencies(self):
        output='/tmp/tool (architecture x86_64):\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n/tmp/tool (architecture arm64):\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n'
        with patch.object(pack,'run',return_value=output):
            self.assertEqual(pack.dependencies(Path('/tmp/tool')),['/usr/lib/libSystem.B.dylib'])

    def fixture(self, base):
        tools=base/'source';tools.mkdir()
        for name in ['python/bin/python3.13','dotnet/dotnet','bin/glslangValidator','bin/zstd','bin/spirv-cross','nxnative/dm/gfx/tools/dmsh_xlate_bin/dmsh_xlate']:
            p=tools/name;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text('#!/bin/sh\nexit 0\n');p.chmod(0o755)
        p=tools/'nxnative/scripts/build_ipa_from_nsp.py';p.parent.mkdir(parents=True);p.write_text('# fixture')
        resources=base/'bundle resources';resources.mkdir()
        archive=resources/'tools.tar.gz'
        with tarfile.open(archive,'w:gz') as t:t.add(tools,arcname='.')
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        manifest={'id':digest[:16],'sha256':digest,'entries':len(list(tools.rglob('*')))+1,'unpackedBytes':4096}
        (resources/'manifest.json').write_text(json.dumps(manifest))
        return resources,manifest

    def test_installs_offline_to_path_with_spaces_and_preserves_previous_version(self):
        with tempfile.TemporaryDirectory(prefix='offline installer ') as temp:
            base=Path(temp);resources,manifest=self.fixture(base)
            target=base/'Tools'/manifest['id'];target.mkdir(parents=True)
            (target/'local-edit').write_text('preserve this')
            result=subprocess.run(['bash',str(SCRIPT),str(target),str(resources)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(json.loads((target/'installed.json').read_text())['bundleID'],manifest['id'])
            backups=list(target.parent.glob(target.name+'.previous.*'))
            self.assertEqual(len(backups),1)
            self.assertEqual((backups[0]/'local-edit').read_text(),'preserve this')
            self.assertFalse(list(target.parent.glob('*.partial.*')))
            self.assertFalse(list(target.parent.glob('*.install-lock')))
            self.assertIn('Unpacking bundled tools',result.stdout)

    def test_corrupt_archive_does_not_replace_existing_tools(self):
        with tempfile.TemporaryDirectory(prefix='offline-checksum-') as temp:
            base=Path(temp);resources,manifest=self.fixture(base)
            (resources/'tools.tar.gz').write_bytes(b'corrupt')
            target=base/'Tools'/manifest['id'];target.mkdir(parents=True)
            (target/'keep').write_text('old tools')
            result=subprocess.run(['bash',str(SCRIPT),str(target),str(resources)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((target/'keep').read_text(),'old tools')
            self.assertFalse(list(target.parent.glob('*.install-lock')))

if __name__=='__main__':unittest.main()
