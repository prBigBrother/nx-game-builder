"""Convert an extracted game icon to the macOS bundle icon."""
from pathlib import Path
import os
import plistlib
import subprocess
import tempfile
import sys


def install_icon(bundle, source):
    bundle, source = Path(bundle), Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    resources = bundle / 'Contents/Resources'
    resources.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mac-icon-', dir=source.parent) as scratch:
        iconset = Path(scratch) / 'GameIcon.iconset'
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                suffix = '@2x' if scale == 2 else ''
                output = iconset / f'icon_{size}x{size}{suffix}.png'
                subprocess.run(['sips', '-s', 'format', 'png', '-z', str(size * scale),
                                str(size * scale), str(source), '--out', str(output)],
                               check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(resources / 'GameIcon.icns')], check=True)
    info_path = bundle / 'Contents/Info.plist'
    with info_path.open('rb') as stream:
        info = plistlib.load(stream)
    info['CFBundleIconFile'] = 'GameIcon.icns'
    with info_path.open('wb') as stream:
        plistlib.dump(info, stream)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('Usage: python3 mac_app_icon.py <app bundle> <extracted icon.jpg>')
    app = Path(sys.argv[1])
    install_icon(app, Path(sys.argv[2]))
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--verbose', str(app)], check=True)
    os.utime(app, None)
    print(f'Installed original game icon: {app}')
