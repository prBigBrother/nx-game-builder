"""Release compliance regression checks; no game data needed."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('game_notices',ROOT/'NativeGameBuilder/Backend/third_party_notices.py')
notices=importlib.util.module_from_spec(spec);spec.loader.exec_module(notices)

class ReleaseAssetsTests(unittest.TestCase):
    def test_standalone_games_receive_license_notices(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);resources=base/'resources';source=resources/'Licenses'
            (source/'nxnative').mkdir(parents=True)
            (source/'THIRD_PARTY_NOTICES.md').write_text('fixture attribution')
            (source/'nxnative/LICENSE').write_text('fixture MIT license')
            app=base/'Game.app'
            notices.install_game_notices(app,resources)
            target=app/'Contents/Resources/Licenses'
            self.assertEqual((target/'nxnative/LICENSE').read_text(),'fixture MIT license')
            self.assertIn('grant no rights',(target/'GAME-CONTENT.txt').read_text())

    def test_missing_notices_stop_packaging(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):notices.install_game_notices(Path(temp)/'app',Path(temp))

    def test_generated_fonts_are_redistributable_and_cover_supported_scripts(self):
        from fontTools.ttLib import TTFont
        folder=ROOT/'build/font-assets'
        self.assertTrue((folder/'standard.ttf').is_file(),'Prepare release fonts before tests')
        standard=TTFont(folder/'standard.ttf')
        self.assertNotIn('fvar',standard)
        self.assertEqual(standard['OS/2'].fsType,0)
        for character in 'HelloЯ日中한':self.assertIn(ord(character),standard.getBestCmap())
        for name in ['standard.ttf','nintendo_ext.ttf']:
            font=TTFont(folder/name)
            self.assertTrue(font['name'].getDebugName(1).startswith('NX Game '))
            self.assertIn('Adobe',font['name'].getDebugName(0))
        self.assertIn('OPEN FONT LICENSE',(ROOT/'NativeGameBuilder/Assets/Fonts/OFL.txt').read_text())

    def test_game_packaging_does_not_use_system_fonts(self):
        code=(ROOT/'NativeGameBuilder/Backend/build_game.py').read_text()
        self.assertNotIn('/System/Library/Fonts',code)
        self.assertIn('install_game_notices(app, HERE.parent)',code)

if __name__=='__main__':unittest.main()
