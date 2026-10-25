#!/usr/bin/env python3
"""Prepare the offline Apple-silicon toolchain. Does not build or run games."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/bundled-toolchain'


def run(args, **kw):
    return subprocess.check_output(list(map(str, args)), text=True, **kw).strip()


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        link = os.readlink(source)
        if os.path.isabs(link):
            raise ValueError(f'External symlink cannot be bundled: {source}')
        target.symlink_to(link)
    else:
        shutil.copyfile(source, target)
        target.chmod(source.stat().st_mode & 0o777)


def copy_tree(source, target):
    shutil.copytree(source.resolve(), target, symlinks=True, copy_function=lambda a,b: copy(Path(a),Path(b)),
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))


def dependencies(path):
    return list(dict.fromkeys(line.strip().split(' (',1)[0] for line in run(['otool','-L',path]).splitlines() if line.startswith('\t')))


def rpaths(path):
    return re.findall(r'cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (.+?) \(offset', run(['otool','-l',path]))


def bundle_binary(source, target, libdir, collected):
    source = source.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    copy(source, target)
    for dep in dependencies(source):
        if dep.startswith(('/usr/lib/', '/System/Library/')):
            continue
        # A dylib's own install ID is the first otool entry; it is not a dependency.
        if target.parent == libdir and Path(dep).name == target.name:
            continue
        if dep.startswith('@rpath/'):
            candidates = [Path(p.replace('@loader_path', str(source.parent))) / dep[7:] for p in rpaths(source)]
            resolved = next((p for p in candidates if p.is_file()), None)
        else:
            resolved = Path(dep.replace('@loader_path',str(source.parent)))
        if resolved is None or not resolved.is_file():
            raise ValueError(f'Cannot resolve {dep} used by {source}')
        name = Path(dep).name
        if name in collected:
            if collected[name] != resolved.resolve(): raise ValueError(f'Dylib name collision: {name}')
        else:
            collected[name] = resolved.resolve()
            bundle_binary(resolved, libdir / name, libdir, collected)
        new = ('@loader_path/' if target.parent == libdir else '@loader_path/../lib/') + name
        subprocess.run(['install_name_tool','-change',dep,new,target],check=True)
    if target.parent == libdir:
        subprocess.run(['install_name_tool','-id','@loader_path/'+target.name,target],check=True)
    for rp in rpaths(target):
        if rp.startswith('/') and not rp.startswith(('/usr/lib/', '/System/Library/')):
            subprocess.run(['install_name_tool','-delete_rpath',rp,target],check=True)
    subprocess.run(['codesign','--force','--sign','-',target],check=True,stderr=subprocess.DEVNULL)


def audit(root):
    count = 0
    for p in root.rglob('*'):
        if p.is_symlink():
            if not p.resolve().is_relative_to(root.resolve()): raise ValueError(f'External symlink: {p}')
        elif p.is_file():
            with p.open('rb') as f: magic=f.read(4)
            if magic in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'):
                # otool prints LC_ID_DYLIB as the first entry too; it is not a load dependency.
                own_ids = run(['otool', '-D', p]).splitlines()[1:]
                for dep in dependencies(p):
                    if dep in own_ids: continue
                    if dep.startswith('/') and not dep.startswith(('/usr/lib/', '/System/Library/')):
                        raise ValueError(f'Nonportable Mach-O dependency: {p}: {dep}')
                for rp in rpaths(p):
                    if rp.startswith('/') and not rp.startswith(('/usr/lib/', '/System/Library/')):
                        raise ValueError(f'Nonportable Mach-O rpath: {p}: {rp}')
                count += 1
    return count


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--python', type=Path, default=Path.home()/'.local/share/uv/python/cpython-3.13-macos-aarch64-none')
    parser.add_argument('--dotnet',type=Path,required=True)
    parser.add_argument('--repository',type=Path,default=ROOT/'.nxnative')
    args=parser.parse_args()
    sdks=[p for p in (args.dotnet/'sdk').iterdir() if p.is_dir()]
    if len(sdks) != 1 or not sdks[0].name.startswith('10.'):
        raise ValueError('Use an isolated .NET SDK 10 installation, not a machine-wide directory with multiple SDKs.')
    OUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='toolchain-',dir=OUT) as temp:
        stage=Path(temp)/'tools';stage.mkdir()
        print('Copying portable Python and .NET SDK…',flush=True)
        copy_tree(args.python,stage/'python')
        python_lib=stage/'python/lib/libpython3.13.dylib'
        subprocess.run(['install_name_tool','-id','@rpath/libpython3.13.dylib',python_lib],check=True,stderr=subprocess.DEVNULL)
        subprocess.run(['codesign','--force','--sign','-',python_lib],check=True,stderr=subprocess.DEVNULL)
        # Python modules are installed into the relocatable runtime, not a venv.
        subprocess.run(['uv','pip','install','--python',stage/'python/bin/python3.13','--target',stage/'python/lib/python3.13/site-packages',
                        '--only-binary=:all:','--requirements',ROOT/'requirements-toolchain.txt'],check=True)
        copy_tree(args.dotnet,stage/'dotnet')
        print('Bundling shader/compression tools and private dylibs…',flush=True)
        libs={}
        for name in ('spirv-cross','glslangValidator','zstd'):
            source=shutil.which(name)
            if not source: raise ValueError('Missing '+name)
            bundle_binary(Path(source),stage/'bin'/name,stage/'lib',libs)
        (stage/'bin/python3').symlink_to('../python/bin/python3.13')
        (stage/'bin/python').symlink_to('../python/bin/python3.13')
        print('Copying tracked nxnative sources and local game-profile fixes…',flush=True)
        repo=args.repository.resolve()
        files=subprocess.check_output(['git','-C',repo,'ls-files','-z']).decode().split('\0')
        # New container readers may be uncommitted during bring-up. Include the
        # Python tool modules the splitter imports, as its cache fingerprint does.
        files=sorted(set(filter(None,files)) | {str(p.relative_to(repo)) for p in (repo/'dm/gfx/tools').glob('*.py')})
        for name in filter(None,files): copy(repo/name,stage/'nxnative'/name)
        feed=stage/'nuget-feed';feed.mkdir()
        nupkg=Path.home()/'.nuget/packages/libhac/0.19.0/libhac.0.19.0.nupkg'
        if not nupkg.is_file():
            nupkg=OUT/'libhac.0.19.0.nupkg'
            if not nupkg.is_file():
                with urllib.request.urlopen('https://api.nuget.org/v3-flatcontainer/libhac/0.19.0/libhac.0.19.0.nupkg',timeout=60) as response, nupkg.open('wb') as output:
                    shutil.copyfileobj(response,output)
        copy(nupkg,feed/nupkg.name)
        (stage/'nxnative/NuGet.Config').write_text('<configuration><packageSources><clear/><add key="offline" value="../nuget-feed"/></packageSources><config><add key="globalPackagesFolder" value="../nuget-packages"/></config></configuration>')
        (stage/'nxnative/Directory.Build.props').write_text('<Project><PropertyGroup><NuGetAudit>false</NuGetAudit><RestoreIgnoreFailedSources>true</RestoreIgnoreFailedSources></PropertyGroup></Project>')
        licenses=stage/'Licenses';licenses.mkdir()
        subprocess.run([sys.executable,ROOT/'scripts/collect-notices.py','--repository',repo,'--output',licenses],check=True)
        (licenses/'README.txt').write_text('Bundled tools retain their upstream licenses. Python notices are in python/LICENSE*; .NET notices are in dotnet/LICENSE* and ThirdPartyNotices*; nxnative and vendored component licenses remain beside their sources. Python package notices remain in their .dist-info directories. LibHac NuGet metadata and MIT license expression remain in nuget-feed/libhac.0.19.0.nupkg. Native tool license copies follow. This distribution contains no game images, game keys or saves.\n')
        cellar=Path('/opt/homebrew/Cellar')
        for package in ('spirv-cross','glslang','spirv-tools','zstd','xz','lz4'):
            folder=cellar/package
            for version in folder.iterdir():
                for file in version.rglob('*'):
                    if file.is_file() and any(x in file.name.lower() for x in ('license','copying','copyright','authors')):
                        copy(file,licenses/package/version.name/file.relative_to(version))
        env=dict(os.environ,PATH=str(stage/'bin')+':/usr/bin:/bin:/usr/sbin:/sbin',DOTNET_ROOT=str(stage/'dotnet'),
                 PYTHONDONTWRITEBYTECODE='1',DOTNET_CLI_TELEMETRY_OPTOUT='1',DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1')
        print('Verifying private runtime and Mach-O dependencies…',flush=True)
        run([stage/'python/bin/python3.13','-c','import capstone,lz4.block,fontTools,backports.zstd,nsz; print("Python dependencies OK")'],env=env)
        run([stage/'dotnet/dotnet','--list-sdks'],env=env)
        run([stage/'bin/glslangValidator','--version'],env=env)
        run([stage/'bin/zstd','--version'],env=env)
        binaries=audit(stage)
        subprocess.run([stage/'python/bin/python3.13',ROOT/'scripts/prepare-release-fonts.py','--repository',repo],check=True,env=env)
        for dist in (stage/'python/lib/python3.13/site-packages').glob('*.dist-info'):
            for file in dist.rglob('*'):
                if file.is_file() and any(word in str(file.relative_to(dist)).lower() for word in ('license','copying','notice','authors')):
                    copy(file,licenses/'PythonPackages'/dist.name/file.relative_to(dist))
        for file in (stage/'dotnet').rglob('*'):
            if file.is_file() and file.name.lower() in ('license.txt','thirdpartynotices.txt','license','notice'):
                copy(file,licenses/'dotnet'/file.relative_to(stage/'dotnet'))
        # Preserve an exact dependency/version record for the shipped runtime.
        packages=run([stage/'python/bin/python3.13','-c','import importlib.metadata as m; print("\\n".join(sorted(d.metadata["Name"]+"=="+d.version for d in m.distributions())))'],env=env)
        snapshot={'nxnative':run(['git','-C',repo,'rev-parse','HEAD']),'localChanges':run(['git','-C',repo,'diff','--name-only']),
                  'python':run([stage/'python/bin/python3.13','--version']),'packages':packages,'machoFiles':binaries}
        (stage/'Licenses/toolchain-versions.json').write_text(json.dumps(snapshot,indent=2)+'\n')
        notices=ROOT/'build/third-party-notices'
        if notices.exists(): shutil.rmtree(notices)
        copy_tree(licenses,notices)
        paths=sorted(stage.rglob('*'))
        size=sum(p.stat().st_size for p in paths if p.is_file() and not p.is_symlink())
        archive=OUT/'tools.tar.gz'
        print(f'Packing {size/2**20:.0f} MiB, {len(paths)} entries…',flush=True)
        with tarfile.open(archive.with_suffix('.partial'),'w:gz',compresslevel=1) as tar:
            tar.add(stage,arcname='.',recursive=True)
        archive.with_suffix('.partial').replace(archive)
        digest=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
        manifest={'schema':1,'id':digest[:16],'sha256':digest,'archive':'tools.tar.gz','unpackedBytes':size,'entries':len(paths)+1,**snapshot}
        (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(f'Ready: {archive} ({archive.stat().st_size/2**20:.0f} MiB), bundle {manifest["id"]}',flush=True)

if __name__=='__main__':main()
