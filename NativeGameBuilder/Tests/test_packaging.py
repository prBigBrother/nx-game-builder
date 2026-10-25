"""Small packaging checks; no game extraction, shader build or game launch."""
import importlib.util
import json
import hashlib
from pathlib import Path
import plistlib
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent
spec = importlib.util.spec_from_file_location('portable', PROJECT / 'Backend/build_game.py')
portable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portable)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'build').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='packaging-test-', dir=ROOT / 'build')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def app(self, path, identifier, content):
        (path / 'Contents').mkdir(parents=True)
        with (path / 'Contents/Info.plist').open('wb') as stream:
            plistlib.dump({'CFBundleIdentifier': identifier}, stream)
        (path / 'Contents/payload').write_text(content)

    def test_nsz_uses_console_entrypoint_and_reuses_completed_decompression(self):
        image=self.root/'game.nsz'; image.write_bytes(b'compressed fixture')
        keys=self.root/'test.keys'; keys.write_text('fixture')
        helper=Mock()
        def decompress(command, log, env, cwd):
            self.assertEqual(Path(command[1]).name, 'nsz_cli.py')
            self.assertNotIn('-m', command)
            self.assertEqual(command[command.index('--keys') + 1], str(keys))
            self.assertEqual((cwd/'prod.keys').resolve(), keys)
            (Path(command[-2])/'game.nsp').write_bytes(b'decompressed fixture')
        helper.run.side_effect=decompress
        with patch.object(portable.importlib.util,'find_spec',return_value=object()):
            out=portable.unpack_input(image,self.root,helper,{'NX_KEYS':str(keys)},self.root)
            self.assertTrue(out.is_file())
            self.assertEqual(portable.unpack_input(image,self.root,helper,{'NX_KEYS':str(keys)},self.root),out)
            helper.run.assert_called_once()

    def test_mac_compiler_versions_can_differ_but_translator_must_match(self):
        logs = self.root / 'logs'
        logs.mkdir()
        prefix = '[RED] translation chain tools do not match the lock file: '
        helper = Mock()
        own = SimpleNamespace(returncode=1, stdout=prefix + 'spirv-cross: lock abc / actual def\n' + prefix + 'metal_macosx: lock A / actual B\n', stderr='')
        with patch.object(portable.subprocess, 'run', return_value=own):
            portable.check_mac_shader_tools(helper, ROOT / '.nxnative', logs, {})
        helper.say.assert_called_once()
        for error in ['dmsh_xlate.dll: lock abc / actual def', 'spirv-cross: lock abc / actual missing', 'the translator was not built from the in-repo source']:
            bad = SimpleNamespace(returncode=1, stdout=prefix + error + '\n', stderr='')
            with patch.object(portable.subprocess, 'run', return_value=bad):
                with self.assertRaises(ValueError):
                    portable.check_mac_shader_tools(helper, ROOT / '.nxnative', logs, {})

    def test_experimental_profile_is_reused_and_input_changes_get_new_profile(self):
        base, update = self.root / 'base.nsp', self.root / 'update.nsp'
        base.write_bytes(b'base fixture')
        update.write_bytes(b'update fixture')
        family = {'base': base, 'updates': [(65536, update)], 'dlc': []}
        helpers, games = Mock(), Mock()
        helpers.survey.return_value = {'version': 'v65536'}
        def write_profile(path, appid, facts):
            path.mkdir(parents=True)
            (path / 'game.tsv').write_text('fixture profile')
            self.assertTrue(facts['survey'].endswith('survey.md'))
        helpers.write_profile.side_effect = write_profile
        env = {}
        with patch.dict(os.environ), patch.object(portable, 'event'):
            portable.experimental_profile(helpers, games, ROOT / '.nxnative', self.root, 0x1000, family, self.root / 'keys', env)
            first = env['DM_GAMES_DIR']
            portable.experimental_profile(helpers, games, ROOT / '.nxnative', self.root, 0x1000, family, self.root / 'keys', env)
            self.assertEqual(helpers.survey.call_count, 1)
            update.write_bytes(b'different update fixture')
            portable.experimental_profile(helpers, games, ROOT / '.nxnative', self.root, 0x1000, family, self.root / 'keys', env)
            self.assertEqual(helpers.survey.call_count, 2)
            self.assertNotEqual(first, env['DM_GAMES_DIR'])
            self.assertTrue(env['DM_GAMES_DIR'].startswith(str(self.root / 'experimental')))

    def test_resources_are_independent_after_source_removal(self):
        source, destination = self.root / 'source', self.root / 'Game.app/Contents/Resources/Game'
        (source / 'shaders').mkdir(parents=True)
        (source / 'shaders/test.metallib').write_bytes(b'compiled-library')
        progress = []
        portable.copy_resources([(source, destination)], lambda *v: progress.append(v))
        (source / 'shaders/test.metallib').write_bytes(b'changed')
        shutil.rmtree(source)
        self.assertEqual((destination / 'shaders/test.metallib').read_bytes(), b'compiled-library')
        self.assertFalse(any(p.is_symlink() for p in destination.rglob('*')))
        self.assertEqual(progress[-1][0], progress[-1][1])

    def test_link_to_external_data_is_rejected(self):
        outside = self.root / 'outside'
        outside.write_text('must not be bundled by reference')
        source = self.root / 'resources'
        source.mkdir()
        (source / 'link').symlink_to(outside)
        with self.assertRaises(ValueError):
            portable.copy_resources([(source, self.root / 'dest')], lambda *_: None)

    def test_system_font_copies_without_protected_filesystem_flags(self):
        source = Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
        if not source.is_file():
            self.skipTest('macOS system font is unavailable')
        destination = self.root / 'Game.app/Contents/Resources/Game/font/standard.ttf'
        portable.clone_or_copy(source, destination)
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), hashlib.sha256(destination.read_bytes()).digest())
        self.assertEqual(destination.stat().st_flags, 0)

    def test_data_copy_fallback_preserves_executable_permission(self):
        source, destination = self.root / 'host', self.root / 'copied-host'
        source.write_bytes(b'executable fixture')
        source.chmod(0o755)
        with patch.object(portable, '_clone', None):
            portable.clone_or_copy(source, destination)
        self.assertTrue(os.access(destination, os.X_OK))

    def test_other_app_is_not_overwritten(self):
        staged, target = self.root / 'staged.app', self.root / 'existing.app'
        self.app(staged, 'game.new', 'new')
        self.app(target, 'other.app', 'old')
        with self.assertRaises(ValueError):
            portable.install_bundle(staged, target, 'game.new')
        self.assertEqual((target / 'Contents/payload').read_text(), 'old')

    def test_failed_install_restores_previous_app(self):
        staged, target = self.root / 'staged.app', self.root / 'existing.app'
        self.app(staged, 'game.same', 'new')
        self.app(target, 'game.same', 'old')
        rename = Path.rename
        def failing_rename(path, destination):
            if path == staged:
                raise OSError('injected installation failure')
            return rename(path, destination)
        with patch.object(Path, 'rename', failing_rename):
            with self.assertRaises(OSError):
                portable.install_bundle(staged, target, 'game.same')
        self.assertEqual((target / 'Contents/payload').read_text(), 'old')

    def test_launcher_resolves_moved_bundle_without_workspace(self):
        original = self.root / 'original.app'
        mac = original / 'Contents/MacOS'
        mac.mkdir(parents=True)
        (original / 'Contents/Resources/Game').mkdir(parents=True)
        with (original / 'Contents/Info.plist').open('wb') as stream:
            plistlib.dump({'CFBundleExecutable': 'GameLauncher', 'CFBundleIdentifier': 'test.nx.launcher',
                          'CFBundlePackageType': 'APPL', 'NXGameID': '010055D009F78000'}, stream)
        subprocess.run(['clang', '-O0', '-fobjc-arc', '-framework', 'Foundation',
                        str(PROJECT / 'Backend/GameLauncher.m'), '-o', str(mac / 'GameLauncher')], check=True)
        moved = self.root / 'another folder/Game with spaces.app'
        moved.parent.mkdir()
        original.rename(moved)
        result = subprocess.check_output([str(moved / 'Contents/MacOS/GameLauncher'), '--inspect'], text=True)
        paths = json.loads(result)
        for name in ('DM_ROMFS', 'DM_MSL_DIR', 'DM_AOC_DIR', 'DM_NVN_SHMAP', 'DM_FONT_DIR'):
            self.assertTrue(Path(paths[name]).is_relative_to(moved / 'Contents/Resources/Game'))
        self.assertIn('Application Support/NXNative/010055D009F78000/save', paths['DM_SAVE'])
        self.assertNotIn(str(ROOT / '.nxnative'), result)

    def test_save_import_never_overwrites_existing_state(self):
        work, support = self.root / 'work', self.root / 'Application Support'
        (work / 'run/save').mkdir(parents=True)
        (work / 'run/save/slot').write_text('legacy')
        self.assertTrue(portable.migrate_saves(work, 'game-id', support))
        (support / 'game-id/save/slot').write_text('new-progress')
        self.assertFalse(portable.migrate_saves(work, 'game-id', support))
        self.assertEqual((support / 'game-id/save/slot').read_text(), 'new-progress')

    def test_untagged_image_identification_stops_after_program_id(self):
        extractor = self.root / 'extractor'
        program = self.root / 'extractor_fixture.py'
        program.write_text('import time\nprint("title 010055d009f78000", flush=True)\ntime.sleep(60)\n')
        extractor.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(program)) + ' "$@"\n')
        extractor.chmod(0o755)
        progress = SimpleNamespace(stage=lambda *_: None, end=lambda *_: None)
        builder = SimpleNamespace(PROG=progress, build_nx_extract=lambda *_: extractor)
        result = portable.identify_untagged_base(self.root / 'Game.xci', self.root, builder,
                    dict(os.environ, NX_REPOSITORY=str(self.root)), self.root, self.root / 'prod.keys')
        self.assertEqual(result, int('010055D009F78000', 16))


if __name__ == '__main__':
    unittest.main()
