#!/usr/bin/env python3
"""JSON event bridge to nxnative; creates portable macOS game bundles."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent


def event(kind, **fields):
    print(json.dumps(dict(ev=kind, **fields), ensure_ascii=False), flush=True)


def load_helpers(repo):
    sys.path.insert(0, str(repo / 'dm/games'))
    sys.path.insert(0, str(repo / 'dm/tools'))
    import game
    import nacp
    import profile_guess
    spec = importlib.util.spec_from_file_location('nx_portable_helpers', repo / 'scripts/build_ipa_from_nsp.py')
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    b.nacp, b.pg = nacp, profile_guess
    b.PROG = b.Progress('json')
    return b, game, nacp, profile_guess


def validated_file(value):
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f'File not found: {path}')
    return path


def prerequisites(config):
    repo = Path(config['repository']).expanduser().resolve()
    if not (repo / 'scripts/build_ipa_from_nsp.py').is_file():
        raise ValueError('Select the nxnative folder containing scripts/build_ipa_from_nsp.py.')
    dotnet = Path(config['dotnet']).expanduser().resolve()
    if not (dotnet / 'dotnet').is_file():
        raise ValueError('Select the installed .NET SDK 10 folder.')
    # Do not carry runtime experiments into extraction or shader capture.
    env = {k: v for k, v in os.environ.items() if not k.startswith('DM_')}
    env.pop('IOSOUT', None)
    env.pop('MSL_IOS', None)
    env['DOTNET_ROOT'] = str(dotnet)
    env['DOTNET_CLI_TELEMETRY_OPTOUT'] = '1'
    env['DOTNET_GENERATE_ASPNET_CERTIFICATE'] = 'false'
    env['DOTNET_SKIP_FIRST_TIME_EXPERIENCE'] = '1'
    env['PATH'] = os.pathsep.join([str(Path(config.get('toolsBin') or dotnet.parent / 'bin')), str(Path(config['python']).expanduser().parent), str(dotnet), '/opt/homebrew/bin', '/usr/local/bin', env.get('PATH', '/usr/bin:/bin')])
    for name in ('dotnet', 'make', 'clang', 'xcrun', 'spirv-cross', 'codesign', 'sips', 'iconutil'):
        if not shutil.which(name, path=env['PATH']):
            raise ValueError(f'Missing tool: {name}')
    for name in ('capstone', 'lz4.block', 'fontTools'):
        try:
            __import__(name)
        except ImportError:
            raise ValueError(f'The selected Python is missing module {name}.')
    sdk = subprocess.check_output([str(dotnet / 'dotnet'), '--list-sdks'], env=env, text=True)
    if not any(line.startswith('10.') for line in sdk.splitlines()):
        raise ValueError('.NET SDK 10 was not found in the selected folder.')
    if subprocess.check_output(['sysctl', '-n', 'hw.optional.arm64'], text=True).strip() != '1':
        raise ValueError('Running game code requires a Mac with Apple silicon.')
    return repo, env


def unpack_input(source, root, b, env, logs):
    if source.suffix.lower() in ('.nsp', '.xci'):
        return source
    if source.suffix.lower() not in ('.nsz', '.xcz'):
        raise ValueError(f'Supported formats are NSP, XCI, NSZ, and XCZ: {source.name}')
    if importlib.util.find_spec('nsz') is None:
        raise ValueError('NSZ/XCZ requires the nsz module in the selected Python. Alternatively, select a decompressed NSP/XCI.')
    key = hashlib.sha256(f'{source}:{source.stat().st_size}:{source.stat().st_mtime_ns}'.encode()).hexdigest()[:16]
    target = root / 'decompressed' / key
    expected = target / (source.stem + ('.nsp' if source.suffix.lower() == '.nsz' else '.xci'))
    marker = target / 'complete.json'
    if expected.is_file() and marker.is_file():
        return expected
    target.mkdir(parents=True, exist_ok=True)
    # nsz's key discovery uses prod.keys in its working directory.
    with tempfile.TemporaryDirectory(prefix='decompress-', dir=root) as temp:
        cwd = Path(temp)
        (cwd / 'prod.keys').symlink_to(env['NX_KEYS'])
        b.run([sys.executable, HERE / 'nsz_cli.py', '-D', '--keys', env['NX_KEYS'], '-o', target, source], logs / f'decompress-{key}.log', env=env, cwd=cwd)
    if not expected.is_file():
        raise ValueError(f'Decompression did not produce {expected.name}; see the decompression log.')
    marker.write_text(json.dumps({'source': str(source)}))
    return expected


def check_mac_shader_tools(b, repo, logs, env):
    # Match upstream own_compilers.py: translator stays strict; this Mac's
    # available Metal and SPIRV-Cross versions may differ from the maintainer's.
    result = subprocess.run([sys.executable, repo / 'dm/gfx/tools/dmsh_chain.py', '--check-tools'],
                            env=env, capture_output=True, text=True)
    output = result.stdout + result.stderr
    (logs / 'chain-check.log').write_text(output)
    lines = [line for line in output.splitlines() if line.strip()]
    allowed = re.compile(r'^\[RED\] translation chain tools do not match the lock file: (spirv-cross|metal_macosx|metal_iphoneos): lock .+ / actual (?!missing$).+')
    bad = [line for line in lines if not allowed.fullmatch(line)]
    if result.returncode and (bad or not lines):
        raise ValueError('Shader translator check failed. See chain-check.log: ' + '; '.join(bad))
    if result.returncode:
        b.say("Using this Mac's Metal and SPIRV-Cross compilers (upstream own_compilers mode).")


def experimental_profile(b, gamemod, repo, root, appid, family, keys, env):
    """Survey only selected inputs; keep profiles isolated by input fingerprint."""
    paths = [family['base'], *[p for _, p in family['updates']]]
    fingerprint = hashlib.sha256(json.dumps([
        [str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns] for p in paths
    ]).encode()).hexdigest()[:16]
    analysis = root / 'experimental' / f'{appid:016X}' / fingerprint
    analysis.mkdir(parents=True, exist_ok=True)
    profiles = analysis / 'profiles'
    profile = profiles / f'{appid:016X}'
    report = analysis / f'{appid:016X}_survey/survey.md'
    event('identified', title=f'{appid:016X} · experimental build',
          logs=str(analysis / f'{appid:016X}_survey/logs'))
    if not (profile / 'game.tsv').is_file():
        facts = b.survey(analysis, appid, family, keys, repo, Path(sys.executable), env)
        facts['survey'] = str(report)
        b.write_profile(profile, appid, facts)
    env['DM_GAMES_DIR'] = str(profiles)
    os.environ['DM_GAMES_DIR'] = str(profiles)
    event('survey', report=str(report), profile=str(profile))
    event('say', text='Provisional profile: parameters were inferred automatically; the game may not run.')
    return gamemod.load(f'{appid:016X}')


def identify_untagged_base(source, root, b, env, logs, keys):
    """Read the extractor's decrypted Program ID, stopping before RomFS traversal."""
    b.PROG.stage('Identifying game image')
    scratch_root = root / 'discovery'
    scratch_root.mkdir(exist_ok=True)
    nx = b.build_nx_extract(Path(env['NX_REPOSITORY']), scratch_root, logs, env)
    with tempfile.TemporaryDirectory(prefix='identify-', dir=scratch_root) as scratch:
        proc = subprocess.Popen([str(nx), str(keys), str(source), '-', scratch, '--manifest'],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace')
        found = None
        try:
            with (logs / 'identify.log').open('w') as output:
                for line in proc.stdout:
                    output.write(line)
                    match = re.match(r'title ([0-9a-fA-F]{16})', line)
                    if match:
                        found = int(match[1], 16)
                        break
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            proc.stdout.close()
        if found is None:
            raise ValueError(f'Could not identify the game. See {logs / "identify.log"}.')
    b.PROG.end(f'{found:016X}')
    return found


_libc = ctypes.CDLL(None, use_errno=True)
_clone = getattr(_libc, 'clonefile', None)
if _clone:
    _clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    _clone.restype = ctypes.c_int


def clone_or_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata = source.stat()
    # System fonts carry SF_RESTRICTED/UF_COMPRESSED. Copying their filesystem
    # flags with copy2/copystat fails even though their contents are readable.
    # Clone ordinary build files; copy flagged files as data, without attributes.
    if not getattr(metadata, 'st_flags', 0) and _clone and _clone(os.fsencode(source), os.fsencode(destination), 0) == 0:
        return
    shutil.copyfile(source, destination)
    os.chmod(destination, stat.S_IMODE(metadata.st_mode) & 0o777)


def copy_resources(items, progress):
    """Real files (APFS clones where possible), never links to the build workspace."""
    files = []
    for source, destination in items:
        if source.is_symlink():
            raise ValueError(f'Unexpected symlink in resources: {source}')
        if source.is_file():
            files.append((source, destination))
        elif source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            for base, dirs, names in os.walk(source):
                base = Path(base)
                relative = base.relative_to(source)
                for name in dirs:
                    if (base / name).is_symlink():
                        raise ValueError(f'Unexpected symlink in resources: {base / name}')
                    (destination / relative / name).mkdir(parents=True, exist_ok=True)
                for name in names:
                    path = base / name
                    if path.is_symlink():
                        raise ValueError(f'Unexpected symlink in resources: {path}')
                    files.append((path, destination / relative / name))
        else:
            raise FileNotFoundError(source)
    total = sum(p.stat().st_size for p, _ in files)
    done, last = 0, 0.0
    for index, (source, destination) in enumerate(files):
        clone_or_copy(source, destination)
        done += source.stat().st_size
        now = time.monotonic()
        if now - last > .2 or index + 1 == len(files):
            progress(done, total, f'{index + 1} / {len(files)} files')
            last = now


def safe_name(name):
    cleaned = re.sub(r'[/:\x00-\x1f]', ' ', name)
    return ' '.join(cleaned.split()).strip('.')[:100] or 'NXNative Game'


def install_bundle(staged, destination, identifier):
    if destination.exists():
        try:
            with (destination / 'Contents/Info.plist').open('rb') as stream:
                old = plistlib.load(stream)
        except Exception:
            raise ValueError(f'Another item already exists: {destination}')
        if old.get('CFBundleIdentifier') != identifier:
            raise ValueError(f'The folder already contains another app named {destination.name}. Select another install folder.')
    backup = destination.with_name(f'.{destination.name}.previous-{os.getpid()}')
    if destination.exists():
        destination.rename(backup)
    try:
        staged.rename(destination)
    except BaseException:
        if backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def migrate_saves(work, game_id, support=None):
    source = work / 'run/save'
    if not source.is_dir() or not any(source.iterdir()):
        return False
    support = support or Path.home() / 'Library/Application Support/NXNative'
    state = support / game_id
    target = state / 'save'
    # Never merge into or replace a user's existing save directory.
    if target.exists():
        return False
    state.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.save-import-', dir=state) as scratch:
        staged = Path(scratch) / 'save'
        copy_resources([(source, staged)], lambda *_: None)
        staged.rename(target)
    return True


def package(b, repo, g, work, game_dir, version, shaders, aoc, graphics, name, language, install, logs, env):
    b.PROG.stage('Preparing fonts')
    fonts = HERE.parent / 'Fonts'
    standard = fonts / 'standard.ttf'
    if not all((fonts / name).is_file() for name in ('standard.ttf', 'nintendo_ext.ttf', 'OFL.txt')):
        raise ValueError('Redistributable fonts are missing; rebuild NX Game Builder.')
    b.PROG.end()
    b.PROG.stage('Building macOS executable')
    host = b.build_mac_host(repo, work / 'tools/dmhost-portable', env, logs, g)
    b.PROG.end()
    # Stage on the installation volume; the final rename is atomic.
    with tempfile.TemporaryDirectory(prefix='.nxnative-build-', dir=install) as scratch:
        app = Path(scratch) / f'{safe_name(name)}.app'
        mac = app / 'Contents/MacOS'
        data = app / 'Contents/Resources/Game'
        mac.mkdir(parents=True)
        data.mkdir(parents=True)
        info = {
            'CFBundleExecutable': 'GameLauncher', 'CFBundlePackageType': 'APPL',
            'CFBundleIdentifier': f'org.nxnative.mac.{g.id.lower()}',
            'CFBundleName': safe_name(name), 'CFBundleDisplayName': name,
            'CFBundleShortVersionString': version, 'CFBundleVersion': str(int(time.time())),
            'LSApplicationCategoryType': g.get('app_category', 'public.app-category.games'),
            'NSHighResolutionCapable': True, 'NXGameID': g.id, 'NXLanguage': language,
        }
        with (app / 'Contents/Info.plist').open('wb') as stream:
            plistlib.dump(info, stream)
        items = [(host, mac / 'dmhost'), (game_dir / 'RomFS', data / 'romfs'),
                 (work / f'patched_{env["NX_VERSION"]}', data / 'modules'),
                 (fonts / 'nintendo_ext.ttf', data / 'font/nintendo_ext.ttf'),
                 (standard, data / 'font/standard.ttf'),
                 (fonts / 'OFL.txt', data / 'font/OFL.txt')]
        if graphics == 'nvn':
            items.append((shaders, data / 'shaders' / shaders.name))
            for entry in g.dir.glob('*.tsv'):
                items.append((entry, data / 'profile' / entry.name))
        else:
            items.append((shaders, data / 'shaders' / graphics))
        if aoc:
            items.append((aoc, data / 'aoc'))
        # Existing per-device warm-up lists contain only shader/pipeline keys.
        # Merge a copy into the seed; future discoveries are saved outside the bundle.
        b.PROG.stage('Bundling game resources', unit='B')
        copy_resources(items, lambda d, t, note: b.PROG.set(done=d, total=t, unit='B', note=note))
        if graphics == 'nvn':
            seed = data / 'profile/pso_manifest.tsv'
            seen = set(seed.read_text().splitlines()) if seed.exists() else set()
            user = work / 'run/pso_user.tsv'
            if user.is_file():
                extra = [line for line in user.read_text().splitlines() if line and not line.startswith('#') and line not in seen]
                with seed.open('a') as stream:
                    stream.write('\n' + '\n'.join(extra) + '\n')
        b.PROG.end()
        b.PROG.stage('App icon and code signing')
        from third_party_notices import install_game_notices
        install_game_notices(app, HERE.parent)
        from mac_app_icon import install_icon
        if (game_dir / 'icon.jpg').exists():
            install_icon(app, game_dir / 'icon.jpg')
        b.run(['clang', '-O2', '-fobjc-arc', '-framework', 'Foundation', HERE / 'GameLauncher.m',
               '-o', mac / 'GameLauncher'], logs / 'launcher.log', env=env)
        b.run(['codesign', '--force', '--deep', '--sign', '-', app], logs / 'codesign.log', env=env)
        b.run(['codesign', '--verify', '--deep', '--verbose', app], logs / 'codesign-verify.log', env=env)
        b.PROG.end()
        if env.get('NX_IMPORT_SAVES') == '1':
            b.PROG.stage('Checking existing saves')
            if migrate_saves(work, g.id):
                b.say('Existing saves copied to Application Support/NXNative.')
            b.PROG.end()
        b.PROG.stage('Installing app')
        destination = install / app.name
        install_bundle(app, destination, info['CFBundleIdentifier'])
        b.PROG.end(str(destination))
        return destination


def execute(config, inspect_only=False):
    repo, env = prerequisites(config)
    b, gamemod, nacp, pg = load_helpers(repo)
    if inspect_only:
        event('checked', message='Python, .NET 10, build tools, and nxnative are available.')
        return
    import fcntl
    with (repo / '.mac-builder.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another instance of NX Game Builder is already building.')
        return execute_inputs(config, repo, env, b, gamemod, nacp, pg)


def execute_inputs(config, repo, env, b, gamemod, nacp, pg):
    keys = validated_file(config['keys'])
    originals = [validated_file(config['base'])]
    if config.get('update'):
        originals.append(validated_file(config['update']))
    originals.extend(validated_file(p) for p in config.get('dlc', []))
    root = Path(config['work']).expanduser().resolve()
    install = Path(config['destination']).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    install.mkdir(parents=True, exist_ok=True)
    if not os.access(install, os.W_OK):
        raise ValueError('Cannot write to the install folder. Select ~/Applications or another writable folder.')
    logs0 = root / 'input-logs'
    logs0.mkdir(exist_ok=True)
    env.update(NX_KEYS=str(keys), NX_REPOSITORY=str(repo))
    os.environ.clear()
    os.environ.update(env)
    b.PROG.stage('Preparing game images')
    unpacked = [unpack_input(p, root, b, env, logs0) for p in originals]
    base_id = b.title_of(unpacked[0])
    if config.get('update'):
        update_id = b.title_of(unpacked[1])
        if update_id is None or update_id & 0xFFF != 0x800:
            raise ValueError('The selected update file is not an NSP update.')
    first_dlc = 2 if config.get('update') else 1
    for path in unpacked[first_dlc:]:
        tid = b.title_of(path)
        if tid is None or tid & 0xFFF in (0, 0x800):
            raise ValueError(f'The selected file is not DLC: {path.name}')
    b.PROG.end()
    if base_id is None:
        base_id = identify_untagged_base(unpacked[0], root, b, env, logs0, keys)
    # The original scanner reads NSP ticket names and tagged cartridge filenames.
    # Only selected inputs are visible in this temporary view.
    with tempfile.TemporaryDirectory(prefix='selected-', dir=root) as selected:
        selected = Path(selected)
        for index, path in enumerate(unpacked):
            tag = f'[{base_id:016X}]-' if index == 0 and b.title_of(path) is None else ''
            (selected / f'{index:03d}-{tag}{path.name}').symlink_to(path)
        appid, family = b.scan_nsps(selected)
        if base_id != appid:
            raise ValueError('The base game field contains an update or DLC.')
        profile_dir = gamemod.by_title(appid)
        provisional = not bool(profile_dir)
        if provisional and not config.get('experimental', False):
            raise ValueError(f'Game {appid:016X} has no registered nxnative profile. Enable Experimental games to analyze it and attempt a build.')
        g = experimental_profile(b, gamemod, repo, root, appid, family, keys, env) if provisional else gamemod.load(f'{appid:016X}')
        available = b.nsp_versions(family, g.builds())
        version = max(available, key=b.vnum)
        needed_versions = g.words('shader_versions')
        if version not in g.builds() or any(v not in available for v in needed_versions):
            raise ValueError(f'A profile version is required: {", ".join(g.builds())}. Select the matching update.')
        work = g.dir.parent.parent / 'build' if provisional else root / f'{g.id}_build'
        existing = originals[0].parent / f'build/{g.id}_build'
        if not provisional and config.get('reuseExisting', True) and (existing / f'extract/{version}/ExeFS/main').is_file():
            work = existing
        env.update(DM_GAME=g.id, DM_ROOT=str(work), WORK=str(work / 'tmp'), DM_RULESET='native', NX_VERSION=version,
                   NX_IMPORT_SAVES='1' if config.get('importSaves', True) else '0')
        os.environ.update(env)
        for folder in ('logs', 'tmp', 'extract', 'shader', 'run/save', 'run/temp'):
            (work / folder).mkdir(parents=True, exist_ok=True)
        logs = work / 'logs'
        event('identified', title=g.get('name'), gameID=g.id, work=str(work), logs=str(logs))
        event('say', text=f'Work folder: {work}')
        return pipeline(b, repo, g, nacp, pg, family, available, version, needed_versions,
                        work, install, logs, env, keys, config, provisional=provisional)


def pipeline(b, repo, g, nacp, pg, family, available, version, needed, work, install, logs, env, keys, config, provisional=False):
    versions = list(dict.fromkeys([*needed, version]))
    picks = b.pick_nsps(family, available, versions)
    estimate = sum({p.resolve(): p.stat().st_size for pair in picks.values() for p in pair if p}.values())
    if not (work / f'extract/{version}/ExeFS/main').is_file() and shutil.disk_usage(work).free < estimate + 6 * 2**30:
        raise ValueError('Not enough free space to extract the game and build files.')
    b.PROG.stage('Building extraction tool')
    nx = b.build_nx_extract(repo, work, logs, env)
    b.PROG.end()
    directories = {}
    for ver in versions:
        base, update = picks[ver]
        directory = b.extract(nx, keys, work / 'extract', ver, base, update, None, logs, g)
        mismatch = b.build_mismatch(directory, ver, g)
        if mismatch:
            raise ValueError('Game modules do not match the profile: ' + '; '.join(mismatch))
        directories[ver] = directory
    current = directories[version]
    # Preserve version metadata for human-readable macOS bundle versions.
    name = nacp.name(current / 'control.nacp') or g.get('name')
    display = nacp.version(current / 'control.nacp') or g.builds()[version]['display']
    languages = nacp.languages(current / 'control.nacp')
    wanted = config.get('language', 'en-US')
    language = b.game_language(wanted, True, languages) if languages else wanted
    aoc = b.extract_aoc(nx, keys, repo, work, int(g.id, 16), family, logs)
    patched = work / f'patched_{version}'
    b.rewrite(Path(sys.executable), repo, current / 'ExeFS', patched, env, logs, g)
    if provisional:
        b.PROG.stage('Refining provisional profile')
        b.provisional_prep(Path(sys.executable), repo, env, logs, g)
        g = b.refine_after_rewrite(g, current, patched)
        b.PROG.end()
        if not b.heap_checked(g) and pg.heap_check_needed(current / 'ExeFS'):
            g = b.heap_check(repo, current, patched, work, env, logs, g)
    sources = pg.build_sources(current / 'ExeFS' , current / 'RomFS', g.words('modules'))
    graphics = sources['graphics'][0]
    b.PROG.stage('Checking shader tools and chain')
    if graphics == 'nvn':
        check_mac_shader_tools(b, repo, logs, env)
        b.run([sys.executable, repo / 'dm/gfx/tools/dmsh_chain.py', '--header'], logs / 'chain-header.log', env=env)
    b.PROG.end()
    if graphics == 'nvn':
        if sources['glslc_capture'][0]:
            b.capture_glslc(repo, {v: directories[v] for v in needed}, version, patched, work, env, logs, g)
        if sources['ue_decode'][0]:
            b.decode_ue_shaders(repo, {v: directories[v] for v in needed}, version, patched, work, env, logs, g)
        oodle = (lambda: {'DM_OODLE_HOST': str(b.build_mac_host(repo, work / 'tools/dmhost-decode', env, logs, g)),
                          'DM_OODLE_MODULES': str(patched)}) if sources['oodle_packs'][0] or sources['ue_legacy'][0] else None
        b.split_shaders(Path(sys.executable), repo, [directories[v] / 'RomFS' for v in needed],
                        [directories[v] / 'ExeFS/main' for v in needed], work / 'shader/pkg', env, logs, g, provisional=provisional, oodle=oodle)
        if provisional:
            b.run([sys.executable, repo / 'dm/gfx/tools/dmsh_chain.py', '--header'], logs / 'chain-after-split.log', env=env)
        cache = work / 'build/cache/metal_shader_cache' 
        b.PROG.stage('Building Metal shaders')
        try:
            b.PROG.watch(b.ShaderWatch(g, cache, work / 'tmp'))
        except Exception:
            pass
        b.run([sys.executable, repo / 'dm/gfx/tools/own_compilers.py', work / 'shader/pkg', cache], logs / 'mac-shaders.log', env=env)
        b.PROG.end()
        chain = subprocess.check_output([sys.executable, repo / 'dm/gfx/tools/dmsh_chain.py'], env=env, text=True).strip()
        shaders = cache / f'b-{chain}'
        b.PROG.stage('Preparing shader tables')
        for tool, output in [('c1_guard.py', 'c1_full.tsv'), ('cb_extent.py', 'cb_extent.tsv')]:
            b.run([sys.executable, repo / 'dm/gfx/tools' / tool, shaders, g.table(output)], logs / f'{tool}.log', env=env)
        b.PROG.end()
    elif graphics in ('vulkan', 'gl'):
        kind = 'vk' if graphics == 'vulkan' else 'gl'
        roots = [current / 'RomFS']
        if graphics == 'vulkan' and sources['vk_capture'][0]:
            roots.append(b.capture_vk(repo, current, patched, work, env, logs, g))
        if graphics == 'gl':
            roots.append(current / 'ExeFS/main')
            if not shutil.which('glslangValidator', path=env['PATH']):
                raise ValueError('This game requires glslang: brew install glslang.')
        b.PROG.stage('Building Metal shaders')
        b.run([sys.executable, repo / f'dm/gfx/tools/{kind}_shaders.py', *roots, work / 'shader'],
              logs / f'{kind}-shaders.log', env=dict(env, TMPDIR=str(work / 'tmp')))
        b.PROG.end()
        shaders = work / 'shader' / kind
        graphics = kind
    else:
        raise ValueError(f'Unknown graphics backend: {graphics}')
    # Reserve logical space conservatively, even when APFS cloning is available.
    size = sum(p.stat().st_size for root in [current / 'RomFS', patched, shaders] for p in root.rglob('*') if p.is_file())
    if aoc:
        size += sum(p.stat().st_size for p in aoc.rglob('*') if p.is_file())
    if shutil.disk_usage(install).free < size + 512 * 2**20:
        raise ValueError(f'The app needs approximately {size / 2**30:.1f} GB of free space in the install folder.')
    result = package(b, repo, g, work, current, display, shaders, aoc, graphics, name, language, install, logs, env)
    event('complete', app=str(result), gameID=g.id, logs=str(logs))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--inspect', action='store_true')
    args = parser.parse_args()
    # All subprocesses inherit this group; the native Cancel button stops the tree.
    try:
        os.setpgid(0, 0)
    except PermissionError:
        pass
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        with args.config.open() as stream:
            config = json.load(stream)
        execute(config, args.inspect)
        return 0
    except KeyboardInterrupt:
        event('cancelled', message='Build cancelled. Completed steps can be reused on the next run.')
        return 130
    except Exception as error:
        event('error', message=str(error))
        return 1


if __name__ == '__main__':
    sys.exit(main())
