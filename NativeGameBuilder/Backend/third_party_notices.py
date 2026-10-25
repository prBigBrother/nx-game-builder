"""License propagation for standalone game apps."""
from pathlib import Path
import shutil

def install_game_notices(app, resources):
    source=Path(resources)/'Licenses'
    if not (source/'THIRD_PARTY_NOTICES.md').is_file():
        raise ValueError('The builder license bundle is missing; rebuild NX Game Builder before packaging games.')
    target=Path(app)/'Contents/Resources/Licenses'
    shutil.copytree(source,target,dirs_exist_ok=True)
    (target/'GAME-CONTENT.txt').write_text('These notices cover NX Game Builder, nxnative, runtime components and included OFL fonts. They grant no rights to the original game, DLC, trademarks or other publisher content.\n')
